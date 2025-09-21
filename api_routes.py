"""
API routes for the transcription service.
"""

import os
import uuid
from typing import Optional, Dict, Any
from datetime import datetime, date

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import get_db_session, Job, UsageDaily
from app.schemas import JobResponse, UsageResponse, JobStatus
from app.services.storage import StorageService
from app.services.audio import AudioProcessor
from app.security.ratelimit import check_concurrent_limit, check_daily_usage_limit
from app.tasks.transcribe import transcribe_audio_task
from app.observability.logging import get_logger
from app.observability.metrics import JOBS_TOTAL, BYTES_PROCESSED, MINUTES_PROCESSED

logger = get_logger(__name__)
router = APIRouter()

# Allowed MIME types
ALLOWED_MIME_TYPES = {
    "audio/mpeg", "audio/wav", "audio/x-wav", "audio/flac", 
    "audio/mp4", "audio/aac", "audio/ogg", "audio/webm", "video/mp4"
}

# Configuration
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE_MB", "50")) * 1024 * 1024  # 50MB
MAX_DURATION_MIN = int(os.getenv("MAX_DURATION_MIN", "15"))
DAILY_CAP_MIN = int(os.getenv("DAILY_CAP_MIN", "10"))


def get_identity_id(request: Request) -> str:
    """Get identity ID from request state."""
    if not hasattr(request.state, 'identity_id'):
        raise HTTPException(status_code=400, detail="Identity not found")
    return request.state.identity_id


@router.post("/transcribe", response_model=JobResponse)
async def transcribe_audio(
    request: Request,
    file: UploadFile = File(...),
    lang: Optional[str] = Form(None),
    diarize: bool = Form(False),
    topics: bool = Form(True),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Upload and transcribe an audio file.
    """
    identity_id = get_identity_id(request)
    
    try:
        # Validate file size
        if file.size and file.size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413, 
                detail=f"File size exceeds {MAX_FILE_SIZE // (1024*1024)}MB limit"
            )
        
        # Validate MIME type
        if file.content_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported file type. Allowed: {', '.join(ALLOWED_MIME_TYPES)}"
            )
        
        # Check concurrent job limit
        concurrent_ok = await check_concurrent_limit(identity_id)
        if not concurrent_ok:
            raise HTTPException(
                status_code=429,
                detail="One active job allowed at a time"
            )
        
        # Read file content
        file_content = await file.read()
        actual_size = len(file_content)
        
        if actual_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413, 
                detail=f"File size exceeds {MAX_FILE_SIZE // (1024*1024)}MB limit"
            )
        
        # Probe audio duration
        audio_processor = AudioProcessor()
        try:
            duration_seconds = await audio_processor.probe_duration(file_content, file.filename)
            duration_minutes = duration_seconds / 60.0
        except Exception as e:
            logger.error(f"Audio probing failed: {e}")
            raise HTTPException(status_code=400, detail="Invalid audio file or unsupported format")
        
        # Check duration limit
        if duration_minutes > MAX_DURATION_MIN:
            raise HTTPException(
                status_code=413,
                detail=f"Audio duration exceeds {MAX_DURATION_MIN} minute limit"
            )
        
        # Check daily usage limit
        usage_ok, remaining_minutes = await check_daily_usage_limit(
            identity_id, duration_minutes, DAILY_CAP_MIN, db
        )
        if not usage_ok:
            raise HTTPException(
                status_code=429,
                detail=f"Daily limit exceeded. Remaining: {remaining_minutes:.1f} minutes"
            )
        
        # Generate job ID and upload file
        job_id = str(uuid.uuid4())
        storage = StorageService()
        
        # Upload original file
        input_key = f"uploads/{job_id}/{file.filename}"
        input_uri = await storage.upload_file(file_content, input_key, file.content_type)
        
        # Create job record
        job = Job(
            id=job_id,
            identity_id=identity_id,
            status=JobStatus.QUEUED,
            input_uri=input_uri,
            output_uri_prefix=f"results/{job_id}/",
            duration_seconds=duration_seconds,
            bytes_in=actual_size,
            language=lang,
            diarize=diarize,
            topics=topics,
            created_at=datetime.utcnow()
        )
        
        db.add(job)
        await db.commit()
        
        # Enqueue task
        task_args = {
            "job_id": job_id,
            "input_uri": input_uri,
            "output_prefix": job.output_uri_prefix,
            "language": lang,
            "diarize": diarize,
            "topics": topics
        }
        
        transcribe_audio_task.apply_async(
            args=[task_args],
            queue="free"
        )
        
        # Update metrics
        JOBS_TOTAL.labels(status="queued").inc()
        BYTES_PROCESSED.inc(actual_size)
        
        logger.info(f"Job {job_id} queued for identity {identity_id}")
        
        return JobResponse(
            job_id=job_id,
            status=JobStatus.QUEUED,
            remaining_day_minutes=remaining_minutes - duration_minutes
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Transcription request failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job_status(
    job_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Get job status and results.
    """
    identity_id = get_identity_id(request)
    
    try:
        # Find job
        job = await db.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        # Check ownership
        if job.identity_id != identity_id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        response_data = {
            "job_id": job_id,
            "status": job.status,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at
        }
        
        # Add error if failed
        if job.status == JobStatus.FAILED and job.error_msg:
            response_data["error"] = job.error_msg
        
        # Add output URLs if succeeded
        if job.status == JobStatus.SUCCEEDED and job.output_uri_prefix:
            storage = StorageService()
            outputs = {}
            
            # Generate signed URLs for outputs
            output_files = ["transcript.txt", "captions.vtt", "summary.txt", "topics.json", "diagnostics.json"]
            
            for filename in output_files:
                try:
                    key = f"{job.output_uri_prefix}{filename}"
                    signed_url = await storage.get_signed_url(key, expires_in=3600)  # 1 hour
                    outputs[filename.split('.')[0]] = signed_url
                except Exception as e:
                    logger.warning(f"Could not generate signed URL for {filename}: {e}")
            
            response_data["outputs"] = outputs
        
        # Add diagnostics if available
        if job.diag_json:
            response_data["diagnostics"] = job.diag_json
        
        return JobResponse(**response_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Job status request failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/usage", response_model=UsageResponse)
async def get_usage_stats(
    request: Request,
    db: AsyncSession = Depends(get_db_session)
):
    """
    Get usage statistics for the current identity.
    """
    identity_id = get_identity_id(request)
    
    try:
        from sqlalchemy import func, select
        from datetime import datetime, timedelta
        
        today = date.today()
        week_ago = today - timedelta(days=7)
        
        # Get today's usage
        today_stmt = select(UsageDaily).where(
            UsageDaily.identity_id == identity_id,
            UsageDaily.date == today
        )
        today_result = await db.execute(today_stmt)
        today_usage = today_result.scalar_one_or_none()
        
        # Get last 7 days usage
        week_stmt = select(
            func.sum(UsageDaily.minutes_used).label('total_minutes'),
            func.sum(UsageDaily.files).label('total_files'),
            func.sum(UsageDaily.bytes_in).label('total_bytes')
        ).where(
            UsageDaily.identity_id == identity_id,
            UsageDaily.date >= week_ago
        )
        week_result = await db.execute(week_stmt)
        week_usage = week_result.first()
        
        # Build response
        response_data = {
            "identity_id": identity_id,
            "daily_limit_minutes": DAILY_CAP_MIN,
            "today": {
                "minutes_used": today_usage.minutes_used if today_usage else 0.0,
                "files": today_usage.files if today_usage else 0,
                "bytes": today_usage.bytes_in if today_usage else 0
            },
            "last_7_days": {
                "minutes_used": float(week_usage.total_minutes or 0),
                "files": int(week_usage.total_files or 0),
                "bytes": int(week_usage.total_bytes or 0)
            },
            "server_time": datetime.utcnow(),
            "reset_time": datetime.combine(today + timedelta(days=1), datetime.min.time())
        }
        
        return UsageResponse(**response_data)
        
    except Exception as e:
        logger.error(f"Usage request failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/admin/overview")
async def admin_overview(db: AsyncSession = Depends(get_db_session)):
    """
    Admin overview dashboard (basic auth required).
    TODO: Add proper admin authentication
    """
    try:
        from sqlalchemy import func, select, desc
        from datetime import datetime, timedelta
        
        # Basic stats
        total_jobs_stmt = select(func.count(Job.id))
        total_jobs_result = await db.execute(total_jobs_stmt)
        total_jobs = total_jobs_result.scalar()
        
        # Recent activity (last 24h)
        yesterday = datetime.utcnow() - timedelta(days=1)
        recent_jobs_stmt = select(func.count(Job.id)).where(Job.created_at >= yesterday)
        recent_jobs_result = await db.execute(recent_jobs_stmt)
        recent_jobs = recent_jobs_result.scalar()
        
        # Total processing time
        total_minutes_stmt = select(func.sum(Job.duration_seconds)).where(Job.status == JobStatus.SUCCEEDED)
        total_minutes_result = await db.execute(total_minutes_stmt)
        total_seconds = total_minutes_result.scalar() or 0
        total_minutes = total_seconds / 60.0
        
        # Most active IPs (approximation via identity)
        from app.models import UserIdentity
        active_ips_stmt = select(
            UserIdentity.ip_first,
            func.count(Job.id).label('job_count')
        ).join(Job, UserIdentity.id == Job.identity_id).group_by(
            UserIdentity.ip_first
        ).order_by(desc('job_count')).limit(10)
        
        active_ips_result = await db.execute(active_ips_stmt)
        top_ips = [{"ip": row.ip_first, "jobs": row.job_count} for row in active_ips_result]
        
        return {
            "total_jobs": total_jobs,
            "jobs_last_24h": recent_jobs,
            "total_minutes_processed": round(total_minutes, 2),
            "top_ips": top_ips,
            "timestamp": datetime.utcnow()
        }
        
    except Exception as e:
        logger.error(f"Admin overview failed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")