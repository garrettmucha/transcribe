"""Pydantic schemas used by the API responses."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class JobStatusEnum(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobResponse(BaseModel):
    job_id: str
    status: JobStatusEnum
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    error: Optional[str] = None
    outputs: Optional[Dict[str, str]] = None
    diagnostics: Optional[Dict[str, Any]] = None
    remaining_month_minutes: Optional[float] = Field(None, description="Minutes remaining in current month")
    remaining_day_minutes: Optional[float] = Field(None, description="Minutes remaining in current day")

    class Config:
        use_enum_values = True


class UsageSummary(BaseModel):
    minutes_used: float
    files: int
    bytes: int


class UsageResponse(BaseModel):
    identity_id: str
    monthly_limit_minutes: int
    this_month: UsageSummary
    last_month: UsageSummary
    server_time: datetime
    reset_time: datetime
