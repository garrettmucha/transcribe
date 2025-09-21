"""
Pydantic schemas for request/response models.
"""

from datetime import datetime, date
from typing import Optional, Dict, Any, List
from enum import Enum

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Job status enumeration."""
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class TranscribeRequest(BaseModel):
    """Request model for transcription."""
    lang: Optional[str] = Field(None, description="Language code (e.g., 'en', 'es')")
    diarize: bool = Field(False, description="Enable speaker diarization")
    topics: bool = Field(True, description="Extract topics and generate summary")


class JobResponse(BaseModel):
    """Response model for job status."""
    job_id: str
    status: JobStatus
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    outputs: Optional[Dict[str, str]] = None  # filename -> signed URL
    diagnostics: Optional[Dict[str, Any]] = None
    remaining_day_minutes: Optional[float] = None
    
    class Config:
        use_enum_values = True


class UsageStats(BaseModel):
    """Usage statistics for a time period."""
    minutes_used: float
    files: int
    bytes: int


class UsageResponse(BaseModel):
    """Response model for usage statistics."""
    identity_id: str
    daily_limit_minutes: int
    today: UsageStats
    last_7_days: UsageStats
    server_time: datetime
    reset_time: datetime


class AdminOverviewResponse(BaseModel):
    """Response model for admin overview."""
    total_jobs: int
    jobs_last_24h: int
    total_minutes_processed: float
    active_identities_last_24h: int
    top_ips: List[Dict[str, Any]]
    avg_processing_time_seconds: Optional[float]
    p95_queue_time_seconds: Optional[float]
    timestamp: datetime


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    timestamp: float
    version: str = "1.0.0"
    services: Optional[Dict[str, str]] = None


class ErrorResponse(BaseModel):
    """Error response model."""
    detail: str
    code: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class FileUploadLimits(BaseModel):
    """File upload limits response."""
    max_file_size_mb: int
    max_duration_minutes: int
    daily_limit_minutes: int
    allowed_mime_types: List[str]
    max_concurrent_jobs: int


class AdminJobFilter(BaseModel):
    """Admin job filtering parameters."""
    status: Optional[JobStatus] = None
    since: Optional[datetime] = None
    ip: Optional[str] = None
    limit: int = Field(50, ge=1, le=1000)
    offset: int = Field(0, ge=0)


class AdminBlocklistRequest(BaseModel):
    """Admin blocklist operation request."""
    action: str = Field(..., regex="^(add|remove)$")
    ip: str = Field(..., description="IP address to block/unblock")
    reason: Optional[str] = Field(None, description="Reason for blocking")


class JobDiagnostics(BaseModel):
    """Job processing diagnostics."""
    queue_wait_seconds: float
    download_seconds: float
    audio_processing_seconds: float
    transcription_seconds: float
    summarization_seconds: float
    upload_seconds: float
    total_processing_seconds: float
    cpu_seconds_used: float
    peak_memory_mb: float
    whisper_model_used: str
    cost_estimate_cents: float


class TranscriptionOutput(BaseModel):
    """Transcription output files."""
    transcript: Optional[str] = Field(None, description="Plain text transcript")
    captions: Optional[str] = Field(None, description="VTT captions file")
    summary: Optional[str] = Field(None, description="Text summary")
    topics: Optional[str] = Field(None, description="JSON topics file")
    diagnostics: Optional[str] = Field(None, description="JSON diagnostics file")


class PlanLimits(BaseModel):
    """Plan limits and quotas."""
    name: str
    daily_minutes: int
    max_file_size_mb: int
    max_duration_minutes: int
    concurrent_jobs: int
    retention_days: int
    queue_priority: str
    features: List[str]


class IdentityInfo(BaseModel):
    """Identity information."""
    id: str
    first_seen: datetime
    last_seen: datetime
    total_jobs: int
    total_minutes: float
    blocked: bool


class RateLimitInfo(BaseModel):
    """Rate limit information."""
    tokens_remaining: int
    tokens_max: int
    reset_at: datetime
    concurrent_jobs: int
    concurrent_max: int