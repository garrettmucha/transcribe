"""API routes for the transcription service."""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional
import inspect

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, JobStatus, UsageMonthly, get_db_session
from app.observability.logging import get_logger
from app.observability.metrics import BYTES_PROCESSED, JOBS_TOTAL
from app.schemas import JobResponse, JobStatusEnum, UsageResponse
from app.security import ratelimit as ratelimit_service
from app.services import audio as audio_service
from app.services import storage as storage_service
from app.tasks.transcribe import transcribe_audio_task

logger = get_logger(__name__)
router = APIRouter()

# Limits for free tier. Environment variables allow runtime tuning for premium plans.
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE_MB", "25")) * 1024 * 1024
MAX_DURATION_MIN = int(os.getenv("MAX_DURATION_MIN", "20"))
MONTHLY_CAP_MIN = int(os.getenv("MONTHLY_CAP_MIN", "100"))
ALLOWED_MIME_TYPES = {
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/flac",
    "audio/mp4",
    "audio/aac",
    "audio/ogg",
    "audio/webm",
    "video/mp4",
}


def get_identity_id(request: Request) -> str:
    if not hasattr(request.state, "identity_id"):
        raise HTTPException(status_code=400, detail="Identity not resolved")
    return request.state.identity_id


@router.post("/transcribe", response_model=JobResponse)
async def transcribe_audio(
    request: Request,
    file: UploadFile,
    lang: Optional[str] = Form(None),
    diarize: bool = Form(False),
    topics: bool = Form(True),
    db: AsyncSession = Depends(get_db_session),
) -> JobResponse:
    """Upload an audio file and enqueue a transcription job."""

    identity_id = get_identity_id(request)
    if not file:
        raise HTTPException(status_code=400, detail="Audio file missing")

    # Validate MIME type and size based on free tier limits
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED_MIME_TYPES))}",
        )

    file_bytes = await file.read()
    size = len(file_bytes)
    if size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"File size exceeds {MAX_FILE_SIZE // (1024 * 1024)}MB limit")

    processor = audio_service.AudioProcessor()
    try:
        duration_seconds = await processor.probe_duration(file_bytes, file.filename)
    except Exception as exc:  # pragma: no cover - ffprobe failure details vary
        logger.error("ffprobe failed", error=str(exc))
        raise HTTPException(status_code=400, detail="Invalid or unsupported audio container")

    duration_minutes = duration_seconds / 60.0
    if duration_minutes > MAX_DURATION_MIN:
        raise HTTPException(status_code=413, detail=f"Audio duration exceeds {MAX_DURATION_MIN} minute limit")

    limit_ok, _remaining_slots = await ratelimit_service.check_concurrent_limit(identity_id)
    if not limit_ok:
        raise HTTPException(status_code=429, detail="Only one active job per identity is allowed")

    try:
        usage_ok, remaining_month_minutes = await ratelimit_service.check_monthly_usage_limit(
            identity_id, duration_minutes, MONTHLY_CAP_MIN, db
        )
    except Exception as exc:
        logger.error("Monthly usage check failed", error=str(exc))
        await ratelimit_service.release_concurrent_limit(identity_id)
        raise HTTPException(status_code=500, detail="Usage check failed")

    if not usage_ok:
        await ratelimit_service.release_concurrent_limit(identity_id)
        raise HTTPException(
            status_code=429,
            detail=f"Monthly quota exceeded. Remaining: {remaining_month_minutes:.1f} minutes",
        )

    job_id = str(uuid.uuid4())
    storage = storage_service.StorageService()
    input_key = f"uploads/{job_id}/{file.filename}"
    input_uri = await storage.upload_file(file_bytes, input_key, file.content_type)

    job = Job(
        id=job_id,
        identity_id=identity_id,
        status=JobStatus.QUEUED,
        input_uri=input_uri,
        output_uri_prefix=f"results/{job_id}/",
        duration_seconds=duration_seconds,
        bytes_in=size,
        language=lang,
        diarize=diarize,
        topics=topics,
        created_at=datetime.utcnow(),
    )
    db.add(job)
    await db.commit()

    task_args = {
        "job_id": job_id,
        "input_uri": input_uri,
        "output_prefix": job.output_uri_prefix,
        "language": lang,
        "diarize": diarize,
        "topics": topics,
    }
    transcribe_audio_task.apply_async(args=[task_args], queue="free")

    JOBS_TOTAL.labels(status="queued").inc()
    BYTES_PROCESSED.inc(size)

    logger.info("Job queued", job_id=job_id, identity=identity_id, duration_minutes=duration_minutes)
    return JobResponse(
        job_id=job_id,
        status=JobStatusEnum.QUEUED,
        remaining_month_minutes=max(0.0, remaining_month_minutes - duration_minutes),
        remaining_day_minutes=max(0.0, remaining_month_minutes - duration_minutes),
    )


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, request: Request, db: AsyncSession = Depends(get_db_session)) -> JobResponse:
    identity_id = get_identity_id(request)
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.identity_id != identity_id:
        raise HTTPException(status_code=403, detail="Access denied")

    response: Dict[str, Any] = {
        "job_id": job_id,
        "status": JobStatusEnum(job.status),
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }

    if job.status == JobStatus.FAILED and job.error_msg:
        response["error"] = job.error_msg

    if job.status == JobStatus.SUCCEEDED and job.output_uri_prefix:
        storage = storage_service.StorageService()
        outputs: Dict[str, str] = {}
        for filename in [
            "transcript.txt",
            "captions.vtt",
            "summary.txt",
            "topics.json",
            "diagnostics.json",
        ]:
            key = f"{job.output_uri_prefix}{filename}"
            try:
                outputs[filename.split(".")[0]] = await storage.get_signed_url(key, expires_in=3600)
            except FileNotFoundError:
                continue
        response["outputs"] = outputs

    if job.diag_json:
        response["diagnostics"] = job.diag_json

    return JobResponse(**response)


async def get_usage(request: Request, db: AsyncSession = Depends(get_db_session)) -> UsageResponse:
    identity_id = get_identity_id(request)
    today = date.today()
    month_start = today.replace(day=1)
    previous_month_end = month_start - timedelta(days=1)
    prev_month_start = previous_month_end.replace(day=1)

    current_stmt = select(UsageMonthly).where(
        UsageMonthly.identity_id == identity_id,
        UsageMonthly.month == month_start,
    )
    previous_stmt = select(UsageMonthly).where(
        UsageMonthly.identity_id == identity_id,
        UsageMonthly.month == prev_month_start,
    )

    current_usage = (await db.execute(current_stmt)).scalar_one_or_none()
    previous_usage = (await db.execute(previous_stmt)).scalar_one_or_none()

    response = UsageResponse(
        identity_id=identity_id,
        monthly_limit_minutes=MONTHLY_CAP_MIN,
        this_month={
            "minutes_used": float(current_usage.minutes_used) if current_usage else 0.0,
            "files": int(current_usage.files if current_usage else 0),
            "bytes": int(current_usage.bytes_in if current_usage else 0),
        },
        last_month={
            "minutes_used": float(previous_usage.minutes_used) if previous_usage else 0.0,
            "files": int(previous_usage.files if previous_usage else 0),
            "bytes": int(previous_usage.bytes_in if previous_usage else 0),
        },
        server_time=datetime.utcnow(),
        reset_time=(month_start + timedelta(days=32)).replace(day=1),
    )
    return response


@router.get("/usage", response_model=UsageResponse)
async def usage_endpoint(request: Request, db: AsyncSession = Depends(get_db_session)) -> UsageResponse:
    """Wrapper endpoint to allow tests to patch get_usage dynamically."""

    handler = globals().get("get_usage")
    if handler is None or handler is usage_endpoint:
        handler = get_usage

    result = handler(request, db)
    if inspect.isawaitable(result):
        return await result
    return result


@router.get("/limits")
async def get_limits() -> Dict[str, Any]:
    return {
        "max_file_size_mb": MAX_FILE_SIZE // (1024 * 1024),
        "max_duration_minutes": MAX_DURATION_MIN,
        "monthly_limit_minutes": MONTHLY_CAP_MIN,
        "allowed_mime_types": sorted(ALLOWED_MIME_TYPES),
    }
