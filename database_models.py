"""
Database models for the transcription service.
"""

import os
from datetime import datetime, date
from typing import Optional, AsyncGenerator
from enum import Enum

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Date, 
    Text, JSON, Index, ForeignKey, create_engine
)
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

from app.observability.logging import get_logger

logger = get_logger(__name__)

# Database configuration
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://transcribe_user:transcribe_pass@localhost:5432/transcribe_db"
)

# Convert sync URL to async for SQLAlchemy 2.0
if DATABASE_URL.startswith("postgresql://"):
    ASYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
else:
    ASYNC_DATABASE_URL = DATABASE_URL

# Create async engine
engine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=os.getenv("SQL_ECHO", "false").lower() == "true",
    pool_size=20,
    max_overflow=30,
    pool_pre_ping=True
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()


class JobStatus(str, Enum):
    """Job status enumeration."""
    QUEUED = "queued"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class UserIdentity(Base):
    """User identity tracking via IP + device fingerprint."""
    __tablename__ = "user_identities"
    
    id = Column(String, primary_key=True)
    first_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    ip_first = Column(String, nullable=False)
    ip_last = Column(String, nullable=False)
    ua_first = Column(String, nullable=True)
    ua_last = Column(String, nullable=True)
    blocked = Column(Boolean, default=False, nullable=False)
    
    # Relationships
    jobs = relationship("Job", back_populates="identity")
    usage_records = relationship("UsageDaily", back_populates="identity")
    
    # Indexes
    __table_args__ = (
        Index("idx_user_identity_ip_first", "ip_first"),
        Index("idx_user_identity_blocked", "blocked"),
        Index("idx_user_identity_last_seen", "last_seen_at"),
    )


class Job(Base):
    """Audio transcription job."""
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
    
    # Relationships
    identity = relationship("UserIdentity", back_populates="jobs")
    
    # Indexes
    __table_args__ = (
        Index("idx_job_identity_status", "identity_id", "status"),
        Index("idx_job_status_created", "status", "created_at"),
        Index("idx_job_created_at", "created_at"),
    )


class UsageDaily(Base):
    """Daily usage tracking per identity."""
    __tablename__ = "usage_daily"
    
    identity_id = Column(String, ForeignKey("user_identities.id"), primary_key=True)
    date = Column(Date, primary_key=True)
    minutes_used = Column(Float, default=0.0, nullable=False)
    files = Column(Integer, default=0, nullable=False)
    bytes_in = Column(Integer, default=0, nullable=False)
    bytes_out = Column(Integer, default=0, nullable=False)
    last_updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationships
    identity = relationship("UserIdentity", back_populates="usage_records")
    
    # Indexes
    __table_args__ = (
        Index("idx_usage_daily_date", "date"),
        Index("idx_usage_daily_identity_date", "identity_id", "date"),
    )


class IpBlocklist(Base):
    """IP address blocklist."""
    __tablename__ = "ip_blocklist"
    
    ip = Column(String, primary_key=True)
    reason = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_by = Column(String, nullable=True)  # Admin user who added the block
    
    # Indexes
    __table_args__ = (
        Index("idx_ip_blocklist_ip", "ip"),
        Index("idx_ip_blocklist_created", "created_at"),
    )


class BillingEvent(Base):
    """Future billing events (not used yet, but ready for paid plans)."""
    __tablename__ = "billing_events"
    
    id = Column(String, primary_key=True)
    identity_id = Column(String, ForeignKey("user_identities.id"), nullable=False)
    event_type = Column(String, nullable=False)  # "usage", "subscription", etc.
    amount_cents = Column(Integer, nullable=False)
    currency = Column(String, default="USD", nullable=False)
    description = Column(String, nullable=False)
    metadata = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)
    
    # Indexes
    __table_args__ = (
        Index("idx_billing_event_identity", "identity_id"),
        Index("idx_billing_event_created", "created_at"),
        Index("idx_billing_event_type", "event_type"),
    )


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Database session dependency for FastAPI.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            logger.error(f"Database session error: {e}")
            raise
        finally:
            await session.close()


async def create_tables():
    """
    Create database tables.
    """
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Failed to create database tables: {e}")
        raise


async def drop_tables():
    """
    Drop all database tables (for testing).
    """
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        logger.info("Database tables dropped successfully")
    except Exception as e:
        logger.error(f"Failed to drop database tables: {e}")
        raise