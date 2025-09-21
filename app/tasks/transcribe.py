"""
Celery task for audio transcription processing.
"""

import os
import time
import json
import asyncio
from datetime import datetime
from typing import Dict, Any

from celery import Celery
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, JobStatus, AsyncSessionLocal
from app.services.storage import StorageService
from app.services.audio import AudioProcessor, TextProcessor
from app.security.ratelimit import record_usage, release_concurrent_limit
from app.observability.logging import get_logger
from app.observability.metrics import JOBS_TOTAL, MINUTES_PROCESSED, PROCESSING_TIME

logger = get_logger(__name__)

# Celery configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

celery_app = Celery(
    'transcribe_worker',
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=['app.tasks.transcribe']
)

# Celery settings
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    worker_disable_rate_limits=False,
    task_routes={
        'app.tasks.transcribe.transcribe_audio_task': {'queue': 'free'},
    }
)


@celery_app.task(bind=True, name='app.tasks.transcribe.transcribe_audio_task')
def transcribe_audio_task(self, task_args: Dict[str, Any]):
    """
    Process audio transcription task.
    """
    job_id = task_args.get('job_id')
    input_uri = task_args.get('input_uri')
    output_prefix = task_args.get('output_prefix')
    language = task_args.get('language')
    diarize = task_args.get('diarize', False)
    topics = task_args.get('topics', True)
    
    logger.info(f"Starting transcription job {job_id}")
    
    # Track timing
    start_time = time.time()
    diagnostics = {
        'queue_wait_seconds': 0,
        'download_seconds': 0,
        'audio_processing_seconds': 0,
        'transcription_seconds': 0,
        'summarization_seconds': 0,
        'upload_seconds': 0,
        'total_processing_seconds': 0,
        'cpu_seconds_used': 0,
        'peak_memory_mb': 0,
        'whisper_model_used': os.getenv("WHISPER_MODEL", "small"),
        'cost_estimate_cents': 0
    }
    
    try:
        # Run async processing in sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(
                _process_transcription_async(
                    job_id, input_uri, output_prefix, 
                    language, diarize, topics, diagnostics
                )
            )
            
            # Calculate final timing
            total_time = time.time() - start_time
            diagnostics['total_processing_seconds'] = total_time
            
            # Estimate cost (CPU seconds * rate)
            cpu_cost_per_hour = float(os.getenv("CPU_COST_PER_HOUR", "0.10"))
            diagnostics['cost_estimate_cents'] = (
                diagnostics['cpu_seconds_used'] / 3600 * cpu_cost_per_hour * 100
            )
            
            # Update metrics
            JOBS_TOTAL.labels(status="succeeded").inc()
            PROCESSING_TIME.observe(total_time)
            
            if result.get('duration_seconds'):
                MINUTES_PROCESSED.inc(result['duration_seconds'] / 60.0)
            
            logger.info(f"Job {job_id} completed successfully in {total_time:.2f}s")
            return result
            
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        
        # Update job status to failed
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(_mark_job_failed(job_id, str(e), diagnostics))
        finally:
            loop.close()
        
        # Update metrics
        JOBS_TOTAL.labels(status="failed").inc()
        
        # Re-raise for Celery
        raise


async def _process_transcription_async(
    job_id: str,
    input_uri: str,
    output_prefix: str,
    language: str,
    diarize: bool,
    topics: bool,
    diagnostics: Dict[str, Any]
) -> Dict[str, Any]:
    """Async transcription processing logic."""
    
    async with AsyncSessionLocal() as db:
        try:
            # Update job status to processing
            job = await db.get(Job, job_id)
            if not job:
                raise ValueError(f"Job {job_id} not found")
            
            job.status = JobStatus.PROCESSING
            job.started_at = datetime.utcnow()
            await db.commit()
            
            # Calculate queue wait time
            if job.created_at:
                diagnostics['queue_wait_seconds'] = (
                    job.started_at - job.created_at
                ).total_seconds()
            
            # Initialize services
            storage = StorageService()
            audio_processor = AudioProcessor()
            text_processor = TextProcessor()
            
            # Download input file
            download_start = time.time()
            file_content = await storage.download_file(input_uri)
            diagnostics['download_seconds'] = time.time() - download_start
            
            logger.info(f"Downloaded input file: {len(file_content)} bytes")
            
            # Process audio
            processing_start = time.time()
            
            # Extract filename from input URI for processing
            filename = input_uri.split('/')[-1] if '/' in input_uri else 'audio.wav'
            
            transcript, vtt_captions, duration, audio_metadata = await audio_processor.process_audio_file(
                file_content=file_content,
                filename=filename,
                language=language,
                diarize=diarize
            )
            
            diagnostics['audio_processing_seconds'] = time.time() - processing_start
            diagnostics['transcription_seconds'] = audio_metadata.get('processing', {}).get(
                'transcription', {}
            ).get('transcription_time', 0)
            
            logger.info(f"Audio processed: {duration:.2f}s, {len(transcript)} chars")
            
            # Generate summary and topics if requested
            summary_text = ""
            topics_data = {}
            
            if topics and len(transcript) > 50:
                summarization_start = time.time()
                
                # Generate summary
                summary_text = await text_processor.summarize_text(transcript)
                
                # Extract topics
                topics_data = await text_processor.extract_topics(transcript)
                
                diagnostics['summarization_seconds'] = time.time() - summarization_start
                
                logger.info(f"Generated summary: {len(summary_text)} chars, {len(topics_data.get('topics', []))} topics")
            
            # Upload results
            upload_start = time.time()
            output_files = {}
            
            # Upload transcript
            transcript_key = f"{output_prefix}transcript.txt"
            await storage.upload_file(
                transcript.encode('utf-8'), 
                transcript_key, 
                'text/plain'
            )
            output_files['transcript'] = transcript_key
            
            # Upload VTT captions
            vtt_key = f"{output_prefix}captions.vtt"
            await storage.upload_file(
                vtt_captions.encode('utf-8'), 
                vtt_key, 
                'text/vtt'
            )
            output_files['captions'] = vtt_key
            
            # Upload summary if generated
            if summary_text:
                summary_key = f"{output_prefix}summary.txt"
                await storage.upload_file(
                    summary_text.encode('utf-8'), 
                    summary_key, 
                    'text/plain'
                )
                output_files['summary'] = summary_key
            
            # Upload topics if generated
            if topics_data:
                topics_key = f"{output_prefix}topics.json"
                topics_json = json.dumps(topics_data, indent=2)
                await storage.upload_file(
                    topics_json.encode('utf-8'), 
                    topics_key, 
                    'application/json'
                )
                output_files['topics'] = topics_key
            
            # Upload diagnostics
            diagnostics_key = f"{output_prefix}diagnostics.json"
            diagnostics_copy = diagnostics.copy()
            diagnostics_copy.update({
                'audio_metadata': audio_metadata,
                'output_files': list(output_files.keys()),
                'job_id': job_id,
                'completed_at': datetime.utcnow().isoformat()
            })
            
            diagnostics_json = json.dumps(diagnostics_copy, indent=2, default=str)
            await storage.upload_file(
                diagnostics_json.encode('utf-8'), 
                diagnostics_key, 
                'application/json'
            )
            output_files['diagnostics'] = diagnostics_key
            
            diagnostics['upload_seconds'] = time.time() - upload_start
            
            # Calculate output size
            total_output_size = sum(len(content.encode('utf-8')) for content in [
                transcript, vtt_captions, summary_text, 
                json.dumps(topics_data), diagnostics_json
            ])
            
            # Update job record
            job.status = JobStatus.SUCCEEDED
            job.finished_at = datetime.utcnow()
            job.bytes_out = total_output_size
            job.diag_json = diagnostics_copy
            await db.commit()
            
            # Record usage
            await record_usage(
                identity_id=job.identity_id,
                duration_minutes=duration / 60.0,
                bytes_in=len(file_content),
                bytes_out=total_output_size,
                db=db
            )
            
            # Release concurrent limit
            await release_concurrent_limit(job.identity_id)
            
            logger.info(f"Job {job_id} completed: {len(output_files)} files uploaded")
            
            return {
                'job_id': job_id,
                'status': 'succeeded',
                'duration_seconds': duration,
                'output_files': output_files,
                'diagnostics': diagnostics_copy
            }
            
        except Exception as e:
            await db.rollback()
            logger.error(f"Transcription processing failed for job {job_id}: {e}")
            raise


async def _mark_job_failed(job_id: str, error_msg: str, diagnostics: Dict[str, Any]):
    """Mark job as failed in database."""
    try:
        async with AsyncSessionLocal() as db:
            job = await db.get(Job, job_id)
            if job:
                job.status = JobStatus.FAILED
                job.finished_at = datetime.utcnow()
                job.error_msg = error_msg
                job.diag_json = diagnostics
                await db.commit()
                
                # Release concurrent limit
                await release_concurrent_limit(job.identity_id)
                
                logger.info(f"Job {job_id} marked as failed")
                
    except Exception as e:
        logger.error(f"Failed to mark job {job_id} as failed: {e}")


# Health check task
@celery_app.task(name='app.tasks.transcribe.health_check')
def health_check():
    """Worker health check task."""
    return {
        'status': 'healthy',
        'timestamp': time.time(),
        'worker_id': os.getpid()
    }


# Cleanup task
@celery_app.task(name='app.tasks.transcribe.cleanup_expired_files')
def cleanup_expired_files():
    """Clean up expired files (run periodically)."""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(_cleanup_expired_files_async())
            return result
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"File cleanup failed: {e}")
        return {'status': 'error', 'message': str(e)}


async def _cleanup_expired_files_async() -> Dict[str, Any]:
    """Async file cleanup logic."""
    from datetime import timedelta
    from sqlalchemy import select
    
    try:
        retention_days = int(os.getenv("FILE_RETENTION_DAYS", "30"))
        cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
        
        storage = StorageService()
        cleaned_count = 0
        
        async with AsyncSessionLocal() as db:
            # Find expired jobs
            stmt = select(Job).where(
                Job.finished_at < cutoff_date,
                Job.status.in_([JobStatus.SUCCEEDED, JobStatus.FAILED])
            )
            result = await db.execute(stmt)
            expired_jobs = result.scalars().all()
            
            for job in expired_jobs:
                try:
                    # Delete input file
                    if job.input_uri:
                        await storage.delete_file(job.input_uri)
                    
                    # Delete output files
                    if job.output_uri_prefix:
                        output_files = await storage.list_files(job.output_uri_prefix)
                        for file_key in output_files:
                            await storage.delete_file(file_key)
                    
                    # Mark job as cleaned (or delete record)
                    job.input_uri = None
                    job.output_uri_prefix = None
                    
                    cleaned_count += 1
                    
                except Exception as e:
                    logger.warning(f"Failed to cleanup job {job.id}: {e}")
            
            await db.commit()
        
        logger.info(f"Cleaned up {cleaned_count} expired jobs")
        
        return {
            'status': 'success',
            'cleaned_jobs': cleaned_count,
            'cutoff_date': cutoff_date.isoformat()
        }
        
    except Exception as e:
        logger.error(f"Cleanup process failed: {e}")
        raise


if __name__ == '__main__':
    # Run worker
    celery_app.start()