"""
Rate limiting using Redis token bucket and semaphores.
"""

import os
import time
from datetime import date, datetime
from typing import Tuple

import redis.asyncio as redis
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, JobStatus, UsageMonthly
from app.observability.logging import get_logger

logger = get_logger(__name__)

# Redis connection
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Rate limit configuration
TOKEN_BUCKET_SIZE = int(os.getenv("RATE_LIMIT_BURST", "10"))
TOKEN_REFILL_RATE = int(os.getenv("RATE_LIMIT_RATE", "10"))  # tokens per minute
CONCURRENT_JOB_LIMIT = int(os.getenv("CONCURRENT_JOB_LIMIT", "1"))


async def check_rate_limit(identity_id: str) -> Tuple[bool, int]:
    """
    Check token bucket rate limit for identity.
    Returns (allowed, remaining_tokens).
    """
    try:
        token_key = f"rate:{identity_id}:tokens"
        timestamp_key = f"rate:{identity_id}:timestamp"
        
        current_time = time.time()
        
        # Get current state
        pipe = redis_client.pipeline()
        pipe.get(token_key)
        pipe.get(timestamp_key)
        results = await pipe.execute()
        
        current_tokens = int(results[0] or TOKEN_BUCKET_SIZE)
        last_refill = float(results[1] or current_time)

        # Calculate tokens to add based on time elapsed
        time_elapsed = current_time - last_refill
        tokens_to_add = int(time_elapsed / 60.0 * TOKEN_REFILL_RATE)  # Rate per minute

        # Update token count
        bucket_capacity = max(TOKEN_BUCKET_SIZE, current_tokens)
        new_tokens = min(bucket_capacity, current_tokens + tokens_to_add)

        if new_tokens >= 1:
            # Allow request, consume token
            new_tokens -= 1

            # Update Redis
            pipe = redis_client.pipeline()
            pipe.set(token_key, new_tokens, ex=3600)  # 1 hour expiry
            pipe.set(timestamp_key, current_time, ex=3600)
            await pipe.execute()

            return True, new_tokens
        else:
            # Rate limited
            return False, 0
            
    except Exception as e:
        logger.error(f"Rate limit check failed for {identity_id}: {e}")
        # Fail open for service availability
        return True, TOKEN_BUCKET_SIZE


async def check_concurrent_limit(identity_id: str) -> Tuple[bool, int]:
    """
    Check concurrent job limit using a Redis-backed semaphore.

    Returns a tuple of (allowed: bool, remaining_slots: int).
    The remaining slot count reflects how many jobs the identity can
    still enqueue after the current request is admitted.
    """
    try:
        semaphore_key = f"concurrent:{identity_id}"

        # Try to acquire semaphore
        current_count_raw = await redis_client.get(semaphore_key)
        current_count = int(current_count_raw or 0)

        if current_count >= CONCURRENT_JOB_LIMIT:
            return False, 0

        # Increment semaphore
        updated = await redis_client.incr(semaphore_key)
        await redis_client.expire(semaphore_key, 1800)  # 30 minute expiry

        remaining_slots = max(CONCURRENT_JOB_LIMIT - updated, 0)
        return True, remaining_slots

    except Exception as e:
        logger.error(f"Concurrent limit check failed for {identity_id}: {e}")
        # Fail open
        return True, CONCURRENT_JOB_LIMIT


async def release_concurrent_limit(identity_id: str):
    """
    Release concurrent job semaphore.
    """
    try:
        semaphore_key = f"concurrent:{identity_id}"
        
        # Decrement semaphore
        current = await redis_client.get(semaphore_key)
        if current and int(current) > 0:
            updated = await redis_client.decr(semaphore_key)
            if updated <= 0:
                await redis_client.delete(semaphore_key)

    except Exception as e:
        logger.error(f"Failed to release concurrent limit for {identity_id}: {e}")


async def check_monthly_usage_limit(
    identity_id: str,
    duration_minutes: float,
    monthly_limit_minutes: int,
    db: AsyncSession,
) -> Tuple[bool, float]:
    """Check monthly usage limit and return allowance status."""

    try:
        month_start = date.today().replace(day=1)
        stmt = select(UsageMonthly).where(
            UsageMonthly.identity_id == identity_id,
            UsageMonthly.month == month_start,
        )
        result = await db.execute(stmt)
        record = result.scalar_one_or_none()

        current_minutes = record.minutes_used if record else 0.0
        remaining = monthly_limit_minutes - current_minutes
        if current_minutes + duration_minutes > monthly_limit_minutes:
            return False, remaining
        return True, remaining
    except Exception as exc:
        logger.error("Monthly usage lookup failed", error=str(exc))
        return True, monthly_limit_minutes / 2


async def record_usage(
    identity_id: str,
    duration_minutes: float,
    bytes_in: int,
    bytes_out: int,
    db: AsyncSession,
):
    """Record usage into the monthly quota table."""
    try:
        month_start = date.today().replace(day=1)
        stmt = select(UsageMonthly).where(
            UsageMonthly.identity_id == identity_id,
            UsageMonthly.month == month_start,
        )
        result = await db.execute(stmt)
        usage_record = result.scalar_one_or_none()

        if usage_record:
            usage_record.minutes_used += duration_minutes
            usage_record.files += 1
            usage_record.bytes_in += bytes_in
            usage_record.bytes_out += bytes_out
            usage_record.last_updated_at = datetime.utcnow()
        else:
            usage_record = UsageMonthly(
                identity_id=identity_id,
                month=month_start,
                minutes_used=duration_minutes,
                files=1,
                bytes_in=bytes_in,
                bytes_out=bytes_out,
                last_updated_at=datetime.utcnow(),
            )
            db.add(usage_record)

        await db.commit()
        cache_key = f"usage:{identity_id}:{month_start.isoformat()}"
        await redis_client.set(cache_key, usage_record.minutes_used, ex=31 * 24 * 3600)
        logger.debug("Usage recorded", identity=identity_id, minutes=duration_minutes)

    except Exception as exc:
        logger.error("Failed to record usage", error=str(exc), identity=identity_id)
        await db.rollback()


async def get_active_jobs_count(identity_id: str, db: AsyncSession) -> int:
    """
    Get count of active jobs for identity.
    """
    try:
        stmt = select(func.count(Job.id)).where(
            Job.identity_id == identity_id,
            Job.status.in_([JobStatus.QUEUED, JobStatus.PROCESSING])
        )
        result = await db.execute(stmt)
        count = result.scalar()
        return count or 0
        
    except Exception as e:
        logger.error(f"Failed to get active jobs count for {identity_id}: {e}")
        return 0


async def cleanup_expired_semaphores():
    """
    Cleanup expired semaphore keys (run periodically).
    """
    try:
        # Find all concurrent semaphore keys
        pattern = "concurrent:*"
        keys = await redis_client.keys(pattern)
        
        if keys:
            # Check TTL and remove expired ones
            pipe = redis_client.pipeline()
            for key in keys:
                pipe.ttl(key)
            ttls = await pipe.execute()
            
            expired_keys = [key for key, ttl in zip(keys, ttls) if ttl == -1]
            if expired_keys:
                await redis_client.delete(*expired_keys)
                logger.info(f"Cleaned up {len(expired_keys)} expired semaphore keys")
                
    except Exception as e:
        logger.error(f"Semaphore cleanup failed: {e}")


async def get_rate_limit_status(identity_id: str) -> dict:
    """
    Get current rate limit status for identity.
    """
    try:
        token_key = f"rate:{identity_id}:tokens"
        timestamp_key = f"rate:{identity_id}:timestamp"
        concurrent_key = f"concurrent:{identity_id}"
        
        pipe = redis_client.pipeline()
        pipe.get(token_key)
        pipe.get(timestamp_key)
        pipe.get(concurrent_key)
        results = await pipe.execute()
        
        current_time = time.time()
        current_tokens = int(results[0] or TOKEN_BUCKET_SIZE)
        last_refill = float(results[1] or current_time)
        concurrent_count = int(results[2] or 0)
        
        # Calculate when tokens will be fully replenished
        tokens_needed = TOKEN_BUCKET_SIZE - current_tokens
        seconds_to_full = tokens_needed * 60 / TOKEN_REFILL_RATE
        reset_at = datetime.fromtimestamp(current_time + seconds_to_full)
        
        return {
            "tokens_remaining": current_tokens,
            "tokens_max": TOKEN_BUCKET_SIZE,
            "reset_at": reset_at,
            "concurrent_jobs": concurrent_count,
            "concurrent_max": CONCURRENT_JOB_LIMIT
        }
        
    except Exception as e:
        logger.error(f"Failed to get rate limit status for {identity_id}: {e}")
        return {
            "tokens_remaining": TOKEN_BUCKET_SIZE,
            "tokens_max": TOKEN_BUCKET_SIZE,
            "reset_at": datetime.utcnow(),
            "concurrent_jobs": 0,
            "concurrent_max": CONCURRENT_JOB_LIMIT
        }