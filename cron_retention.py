"""
File retention and cleanup cron jobs.
"""

import os
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, JobStatus, AsyncSessionLocal
from app.services.storage import StorageService
from app.observability.logging import get_logger
from app.observability.metrics import record_error_metrics

logger = get_logger(__name__)


class RetentionManager:
    """Manages file retention and cleanup operations."""
    
    def __init__(self):
        self.retention_days = int(os.getenv("FILE_RETENTION_DAYS", "7"))
        self.storage = StorageService()
    
    async def cleanup_expired_files(self) -> Dict[str, Any]:
        """
        Clean up files that have exceeded retention period.
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=self.retention_days)
            
            logger.info(f"Starting file cleanup for files older than {cutoff_date}")
            
            cleanup_stats = {
                'jobs_processed': 0,
                'files_deleted': 0,
                'bytes_freed': 0,
                'errors': 0,
                'cutoff_date': cutoff_date.isoformat()
            }
            
            async with AsyncSessionLocal() as db:
                # Find expired jobs
                stmt = select(Job).where(
                    Job.finished_at < cutoff_date,
                    Job.status.in_([JobStatus.SUCCEEDED, JobStatus.FAILED])
                ).order_by(Job.finished_at.asc())
                
                result = await db.execute(stmt)
                expired_jobs = result.scalars().all()
                
                logger.info(f"Found {len(expired_jobs)} expired jobs to clean up")
                
                for job in expired_jobs:
                    try:
                        job_cleanup_stats = await self._cleanup_job_files(job)
                        
                        # Update aggregate stats
                        cleanup_stats['files_deleted'] += job_cleanup_stats['files_deleted']
                        cleanup_stats['bytes_freed'] += job_cleanup_stats['bytes_freed']
                        cleanup_stats['jobs_processed'] += 1
                        
                        # Clear file references in database
                        job.input_uri = None
                        job.output_uri_prefix = None
                        
                        # Add cleanup metadata
                        if not job.diag_json:
                            job.diag_json = {}
                        job.diag_json['cleanup'] = {
                            'cleaned_at': datetime.utcnow().isoformat(),
                            'files_deleted': job_cleanup_stats['files_deleted'],
                            'bytes_freed': job_cleanup_stats['bytes_freed']
                        }
                        
                    except Exception as e:
                        logger.error(f"Failed to cleanup job {job.id}: {e}")
                        cleanup_stats['errors'] += 1
                        record_error_metrics('job_cleanup', 'retention')
                
                # Commit database changes
                await db.commit()
            
            logger.info(
                f"Cleanup completed: {cleanup_stats['jobs_processed']} jobs, "
                f"{cleanup_stats['files_deleted']} files, "
                f"{cleanup_stats['bytes_freed']} bytes freed"
            )
            
            return cleanup_stats
            
        except Exception as e:
            logger.error(f"File cleanup failed: {e}")
            record_error_metrics('cleanup_process', 'retention')
            raise
    
    async def _cleanup_job_files(self, job: Job) -> Dict[str, int]:
        """
        Clean up files for a specific job.
        """
        cleanup_stats = {
            'files_deleted': 0,
            'bytes_freed': 0
        }
        
        try:
            # Delete input file
            if job.input_uri:
                try:
                    file_size = await self._get_file_size(job.input_uri)
                    success = await self.storage.delete_file(job.input_uri)
                    if success:
                        cleanup_stats['files_deleted'] += 1
                        cleanup_stats['bytes_freed'] += file_size
                        logger.debug(f"Deleted input file: {job.input_uri}")
                except Exception as e:
                    logger.warning(f"Failed to delete input file {job.input_uri}: {e}")
            
            # Delete output files
            if job.output_uri_prefix:
                try:
                    output_files = await self._list_output_files(job.output_uri_prefix)
                    
                    for file_key in output_files:
                        try:
                            # Construct full URI
                            if self.storage.use_local:
                                file_uri = f"file://{os.path.join(self.storage.local_storage_path, file_key)}"
                            else:
                                file_uri = f"s3://{self.storage.bucket_name}/{file_key}"
                            
                            file_size = await self._get_file_size(file_uri)
                            success = await self.storage.delete_file(file_uri)
                            if success:
                                cleanup_stats['files_deleted'] += 1
                                cleanup_stats['bytes_freed'] += file_size
                                logger.debug(f"Deleted output file: {file_uri}")
                        except Exception as e:
                            logger.warning(f"Failed to delete output file {file_key}: {e}")
                            
                except Exception as e:
                    logger.warning(f"Failed to list output files for {job.output_uri_prefix}: {e}")
            
            return cleanup_stats
            
        except Exception as e:
            logger.error(f"Job file cleanup failed for {job.id}: {e}")
            raise
    
    async def _list_output_files(self, prefix: str) -> list:
        """List output files for a job."""
        try:
            return await self.storage.list_files(prefix)
        except Exception as e:
            logger.warning(f"Failed to list files for prefix {prefix}: {e}")
            return []
    
    async def _get_file_size(self, uri: str) -> int:
        """Get file size for a URI (best effort)."""
        try:
            if uri.startswith("file://"):
                file_path = uri[7:]
                if os.path.exists(file_path):
                    return os.path.getsize(file_path)
            elif uri.startswith("s3://"):
                # For S3, we'd need to make a HEAD request
                # For now, return 0 as we can't easily get size without downloading
                pass
            return 0
        except Exception:
            return 0
    
    async def cleanup_orphaned_files(self) -> Dict[str, Any]:
        """
        Clean up orphaned files that don't have corresponding database records.
        """
        try:
            logger.info("Starting orphaned file cleanup")
            
            cleanup_stats = {
                'orphaned_files': 0,
                'bytes_freed': 0,
                'errors': 0
            }
            
            # List all files in storage
            all_files = []
            try:
                # List uploads
                uploads = await self.storage.list_files("uploads/")
                all_files.extend([(f, "uploads") for f in uploads])
                
                # List results
                results = await self.storage.list_files("results/")
                all_files.extend([(f, "results") for f in results])
                
            except Exception as e:
                logger.error(f"Failed to list storage files: {e}")
                return cleanup_stats
            
            logger.info(f"Found {len(all_files)} files in storage")
            
            # Check each file against database
            async with AsyncSessionLocal() as db:
                for file_path, file_type in all_files:
                    try:
                        # Extract job ID from file path
                        job_id = self._extract_job_id_from_path(file_path)
                        if not job_id:
                            continue
                        
                        # Check if job exists
                        job = await db.get(Job, job_id)
                        if not job:
                            # Orphaned file - delete it
                            if self.storage.use_local:
                                file_uri = f"file://{os.path.join(self.storage.local_storage_path, file_path)}"
                            else:
                                file_uri = f"s3://{self.storage.bucket_name}/{file_path}"
                            
                            file_size = await self._get_file_size(file_uri)
                            success = await self.storage.delete_file(file_uri)
                            if success:
                                cleanup_stats['orphaned_files'] += 1
                                cleanup_stats['bytes_freed'] += file_size
                                logger.debug(f"Deleted orphaned file: {file_uri}")
                        
                    except Exception as e:
                        logger.warning(f"Failed to process file {file_path}: {e}")
                        cleanup_stats['errors'] += 1
            
            logger.info(
                f"Orphaned file cleanup completed: {cleanup_stats['orphaned_files']} files deleted, "
                f"{cleanup_stats['bytes_freed']} bytes freed"
            )
            
            return cleanup_stats
            
        except Exception as e:
            logger.error(f"Orphaned file cleanup failed: {e}")
            record_error_metrics('orphaned_cleanup', 'retention')
            raise
    
    def _extract_job_id_from_path(self, file_path: str) -> str:
        """Extract job ID from file path."""
        try:
            # File paths are like "uploads/{job_id}/..." or "results/{job_id}/..."
            parts = file_path.split('/')
            if len(parts) >= 2:
                return parts[1]
            return None
        except Exception:
            return None
    
    async def get_retention_stats(self) -> Dict[str, Any]:
        """
        Get statistics about files and retention.
        """
        try:
            stats = {
                'total_jobs': 0,
                'active_jobs': 0,
                'succeeded_jobs': 0,
                'failed_jobs': 0,
                'jobs_with_files': 0,
                'jobs_cleaned': 0,
                'oldest_job': None,
                'newest_job': None
            }
            
            async with AsyncSessionLocal() as db:
                # Count jobs by status
                stmt = select(Job)
                result = await db.execute(stmt)
                jobs = result.scalars().all()
                
                stats['total_jobs'] = len(jobs)
                
                oldest_job = None
                newest_job = None
                
                for job in jobs:
                    # Count by status
                    if job.status == JobStatus.QUEUED or job.status == JobStatus.PROCESSING:
                        stats['active_jobs'] += 1
                    elif job.status == JobStatus.SUCCEEDED:
                        stats['succeeded_jobs'] += 1
                    elif job.status == JobStatus.FAILED:
                        stats['failed_jobs'] += 1
                    
                    # Check if job has files
                    if job.input_uri or job.output_uri_prefix:
                        stats['jobs_with_files'] += 1
                    else:
                        stats['jobs_cleaned'] += 1
                    
                    # Track oldest/newest
                    if job.created_at:
                        if not oldest_job or job.created_at < oldest_job:
                            oldest_job = job.created_at
                        if not newest_job or job.created_at > newest_job:
                            newest_job = job.created_at
                
                stats['oldest_job'] = oldest_job.isoformat() if oldest_job else None
                stats['newest_job'] = newest_job.isoformat() if newest_job else None
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get retention stats: {e}")
            record_error_metrics('retention_stats', 'retention')
            return {}


async def run_retention_cleanup():
    """
    Main function to run retention cleanup.
    Can be called from cron or Celery task.
    """
    manager = RetentionManager()
    
    try:
        # Clean up expired files
        expired_stats = await manager.cleanup_expired_files()
        logger.info(f"Expired file cleanup: {expired_stats}")
        
        # Clean up orphaned files
        orphaned_stats = await manager.cleanup_orphaned_files()
        logger.info(f"Orphaned file cleanup: {orphaned_stats}")
        
        # Get retention statistics
        retention_stats = await manager.get_retention_stats()
        logger.info(f"Retention stats: {retention_stats}")
        
        return {
            'expired_cleanup': expired_stats,
            'orphaned_cleanup': orphaned_stats,
            'retention_stats': retention_stats
        }
        
    except Exception as e:
        logger.error(f"Retention cleanup failed: {e}")
        raise


if __name__ == "__main__":
    # Run retention cleanup directly
    asyncio.run(run_retention_cleanup())