"""Database models for the transcription service."""

from __future__ import annotations

import os
from datetime import date, datetime
from enum import Enum
from typing import AsyncGenerator

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base, relationship

from app.observability.logging import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://transcribe_user:transcribe_pass@localhost:5432/transcribe_db",
)
ASYNC_DATABASE_URL = (
    DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
    if DATABASE_URL.startswith("postgresql://")
    else DATABASE_URL
)

engine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=os.getenv("SQL_ECHO", "false").lower() == "true",
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

Base = declarative_base()


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class UserIdentity(Base):
    __tablename__ = "user_identities"

    id = Column(String, primary_key=True)
    first_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ip_first = Column(String, nullable=False)
    ip_last = Column(String, nullable=False)
    ua_first = Column(String, nullable=True)
    ua_last = Column(String, nullable=True)
    blocked = Column(Boolean, nullable=False, default=False)

    jobs = relationship("Job", back_populates="identity")
    usage_monthly = relationship("UsageMonthly", back_populates="identity")

    __table_args__ = (
        Index("idx_user_identity_ip_first", "ip_first"),
        Index("idx_user_identity_blocked", "blocked"),
        Index("idx_user_identity_last_seen", "last_seen_at"),
    )


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True)
    identity_id = Column(String, ForeignKey("user_identities.id"), nullable=False)
    status = Column(String, nullable=False, default=JobStatus.QUEUED)
    input_uri = Column(String, nullable=False)
    output_uri_prefix = Column(String, nullable=True)
    duration_seconds = Column(Float, nullable=False)
    bytes_in = Column(Integer, nullable=False)
    bytes_out = Column(Integer, nullable=True)
    language = Column(String, nullable=True)
    diarize = Column(Boolean, default=False)
    topics = Column(Boolean, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    error_msg = Column(Text, nullable=True)
    diag_json = Column(JSON, nullable=True)

    identity = relationship("UserIdentity", back_populates="jobs")

    __table_args__ = (
        Index("idx_job_identity_status", "identity_id", "status"),
        Index("idx_job_status_created", "status", "created_at"),
        Index("idx_job_created_at", "created_at"),
    )


class UsageMonthly(Base):
    __tablename__ = "usage_monthly"

    identity_id = Column(String, ForeignKey("user_identities.id"), primary_key=True)
    month = Column(Date, primary_key=True)
    minutes_used = Column(Float, nullable=False, default=0.0)
    files = Column(Integer, nullable=False, default=0)
    bytes_in = Column(Integer, nullable=False, default=0)
    bytes_out = Column(Integer, nullable=False, default=0)
    last_updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    identity = relationship("UserIdentity", back_populates="usage_monthly")

    __table_args__ = (
        Index("idx_usage_month_identity", "identity_id"),
        Index("idx_usage_month", "month"),
    )


class IpBlocklist(Base):
    __tablename__ = "ip_blocklist"

    ip = Column(String, primary_key=True)
    reason = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_by = Column(String, nullable=True)

    __table_args__ = (
        Index("idx_ip_blocklist_ip", "ip"),
        Index("idx_ip_blocklist_created", "created_at"),
    )


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as exc:
            await session.rollback()
            logger.error("Database session error", error=str(exc))
            raise


async def create_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured")
