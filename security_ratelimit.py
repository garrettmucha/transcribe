"""
Rate limiting using Redis token bucket and semaphores.
"""

import os
import time
from datetime import date, datetime, timedelta
from typing import Tuple

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models import UsageDaily, Job, JobStatus
from app.observability.logging import get_logger

logger = get_logger(__name__)

# Redis connection
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# Rate limit configuration
TOKEN_BUCKET_SIZE = int(os.getenv("RATE_LIMIT_BURST", "15"))
TOKEN_REFILL_RATE = int(os.getenv("RATE_LIMIT_RATE", "1"))  # tokens per minute
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
        new_tokens = min(TOKEN_BUCKET_SIZE, current_tokens + tokens_to_add)
        
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


async def check_concurrent_limit(identity_id: str) -> bool:
    """
    Check concurrent job limit using Redis semaphore.
    """
    try:
        semaphore_key = f"concurrent:{identity_id}"
        
        # Try to acquire semaphore
        current_count = await redis_client.get(semaphore_key)
        current_count = int(current_count or 0)
        
        if current_count >= CONCURRENT_JOB_LIMIT:
            return False
        
        # Increment semaphore
        await redis_client.incr(semaphore_key)
        await redis_client.expire(semaphore_key, 1800)  # 30 minute expiry
        
        return True
        
    except Exception as e:
        logger.error(f"Concurrent limit check failed for {identity_id}: {e}")
        # Fail open
        return True


async def release_concurrent_limit(identity_id: str):
    """
    Release concurrent job semaphore.
    """
    try:
        semaphore_key = f"concurrent:{identity_id}"
        
        # Decrement semaphore
        current = await redis_client.get(semaphore_key)
        if current and int(current) > 0:
            await redis_client.decr(semaphore_key)
            
    except Exception as e:
        logger.error(f"Failed to release concurrent limit for {identity_id}: {e}")


async def check_daily_usage_limit(
    identity_id: str, 
    duration_minutes: float, 
    daily_limit_minutes: int,
    db: AsyncSession
) -> Tuple[bool, float]:
    """
    Check daily usage limit against database records.
    Returns (allowed, remaining_minutes).
    """
    try:
        today = date.today()
        
        # Get today's usage
        stmt = select(UsageDaily).where(
            UsageDaily.identity_id == identity_id,
            UsageDaily.date == today
        )
        result = await db.execute(stmt)
        usage_record = result.scalar_one_or_none()
        
        current_usage = usage_record.minutes_used if usage_record else 0.0
        remaining_minutes = daily_limit_minutes - current_usage
        
        # Check if new request would exceed limit
        if current_usage + duration_minutes > daily_limit_minutes:
            return False, remaining_minutes
        
        return True, remaining_minutes
        
    except Exception as e:
        logger.error(f"Daily usage check failed for {identity_id}: {e}")
        # Fail open with conservative remaining estimate
        return True, daily_limit_minutes / 2


async def record_usage(
    identity_id: str,
    duration_minutes: float,
    bytes_in: int,
    bytes_out: int,
    db: AsyncSession
):
    """
    Record usage in daily tracking table.
    """
    try:
        today = date.today()
        
        # Get or create usage record
        stmt = select(UsageDaily).where(
            UsageDaily.identity_id == identity_id,
            UsageDaily.date == today
        )
        result = await db.execute(stmt)
        usage_record = result.scalar_one_or_none()
        
        if usage_record:
            # Update existing record
            usage_record.minutes_used += duration_minutes
            usage_record.files += 1
            usage_record.bytes_in += bytes_in
            usage_record.bytes_out += bytes_out
            usage_record.last_updated_at = datetime.utcnow()
        else:
            # Create new record
            usage_record = UsageDaily(
                identity_id=identity_id,
                date=today,
                minutes_used=duration_minutes,
                files=1,
                bytes_in=bytes_in,
                bytes_out=bytes_out,
                last_updated_at=datetime.utcnow()
            )
            db.add(usage_record)
        
        await db.commit()
        
        # Also update Redis cache for faster lookups
        cache_key = f"usage:{identity_id}:{today.isoformat()}"
        await redis_client.set(
            cache_key, 
            usage_record.minutes_used, 
            ex=86400  # 24 hours
        )
        
        logger.debug(f"Usage recorded for {identity_id}: +{duration_minutes:.2f} minutes")
        
    except Exception as e:
        logger.error(f"Failed to record usage for {identity_id}: {e}")
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