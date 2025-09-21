"""Identity management and device fingerprinting."""

import asyncio
import os
import uuid
import hashlib
import hmac
from datetime import datetime
from typing import Optional

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AsyncSessionLocal, IpBlocklist, UserIdentity
from app.observability.logging import get_logger

logger = get_logger(__name__)

# Configuration
COOKIE_SIGNING_KEY = os.getenv("COOKIE_SIGNING_KEY", "default-dev-key-change-in-prod").encode()
COOKIE_NAME = "dev_id"
COOKIE_MAX_AGE = 365 * 24 * 3600  # 1 year


def generate_device_id() -> str:
    """Generate a new device ID."""
    return str(uuid.uuid4())


def sign_device_id(device_id: str) -> str:
    """Sign device ID with HMAC."""
    signature = hmac.new(
        COOKIE_SIGNING_KEY,
        device_id.encode(),
        hashlib.sha256
    ).hexdigest()
    return f"{device_id}.{signature}"


def verify_device_id(signed_device_id: str) -> Optional[str]:
    """Verify and extract device ID from signed cookie."""
    try:
        device_id, signature = signed_device_id.rsplit(".", 1)
        expected_signature = hmac.new(
            COOKIE_SIGNING_KEY,
            device_id.encode(),
            hashlib.sha256
        ).hexdigest()
        
        if hmac.compare_digest(signature, expected_signature):
            return device_id
        return None
    except ValueError:
        return None


def hash_user_agent(user_agent: Optional[str]) -> str:
    """Hash user agent for fingerprinting."""
    if not user_agent:
        return "unknown"
    
    return hashlib.sha256(user_agent.encode()).hexdigest()[:16]


def compute_identity_key(ip: str, device_id: str, ua_hash: str) -> str:
    """Compute identity key from IP, device ID, and user agent hash."""
    identity_data = f"{ip}:{device_id}:{ua_hash}"
    return hashlib.sha256(identity_data.encode()).hexdigest()


async def _maybe_await(value):
    """Return awaited value if coroutine, otherwise the original value."""

    if asyncio.iscoroutine(value):
        return await value
    return value


async def get_or_create_identity(request: Request) -> str:
    """
    Get or create user identity based on IP + device cookie + UA.
    Sets device cookie if not present.
    """
    # Get client information
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent")
    ua_hash = hash_user_agent(user_agent)
    
    # Get or create device ID from cookie
    device_cookie = request.cookies.get(COOKIE_NAME)
    device_id = None
    
    if device_cookie:
        device_id = verify_device_id(device_cookie)
    
    if not device_id:
        # Generate new device ID
        device_id = generate_device_id()
        signed_cookie = sign_device_id(device_id)
        
        # Note: We can't set the cookie here directly since we're in middleware
        # The cookie will be set in the response via a custom header
        request.state.set_device_cookie = signed_cookie
    
    # Compute identity key
    identity_key = compute_identity_key(client_ip, device_id, ua_hash)
    
    # Get or create identity record
    async with AsyncSessionLocal() as db:
        try:
            # Check if identity exists
            stmt = select(UserIdentity).where(UserIdentity.id == identity_key)
            result = await db.execute(stmt)
            identity = await _maybe_await(result.scalar_one_or_none())
            
            if identity:
                # Update last seen
                identity.last_seen_at = datetime.utcnow()
                identity.ip_last = client_ip
                identity.ua_last = user_agent
            else:
                # Create new identity
                identity = UserIdentity(
                    id=identity_key,
                    first_seen_at=datetime.utcnow(),
                    last_seen_at=datetime.utcnow(),
                    ip_first=client_ip,
                    ip_last=client_ip,
                    ua_first=user_agent,
                    ua_last=user_agent,
                    blocked=False
                )
                await _maybe_await(db.add(identity))
            
            await db.commit()
            logger.debug(f"Identity resolved: {identity_key[:8]}... (IP: {client_ip})")
            
            return identity_key
            
        except Exception as e:
            await db.rollback()
            logger.error(f"Identity resolution failed: {e}")
            # Return a fallback identity based on IP only
            return hashlib.sha256(f"fallback:{client_ip}".encode()).hexdigest()


async def is_ip_blocked(ip: str) -> bool:
    """Check if IP is in blocklist."""
    try:
        async with AsyncSessionLocal() as db:
            stmt = select(IpBlocklist).where(IpBlocklist.ip == ip)
            result = await db.execute(stmt)
            blocked_entry = await _maybe_await(result.scalar_one_or_none())
            return blocked_entry is not None
    except Exception as e:
        logger.error(f"IP blocklist check failed: {e}")
        return False


async def block_ip(ip: str, reason: str, admin_user: Optional[str] = None) -> bool:
    """Add IP to blocklist."""
    try:
        async with AsyncSessionLocal() as db:
            # Check if already blocked
            stmt = select(IpBlocklist).where(IpBlocklist.ip == ip)
            result = await db.execute(stmt)
            existing = await _maybe_await(result.scalar_one_or_none())
            if existing:
                return True  # Already blocked
            
            # Add to blocklist
            block_entry = IpBlocklist(
                ip=ip,
                reason=reason,
                created_by=admin_user,
                created_at=datetime.utcnow()
            )
            await _maybe_await(db.add(block_entry))
            await db.commit()
            
            logger.info(f"IP {ip} blocked: {reason}")
            return True
            
    except Exception as e:
        logger.error(f"Failed to block IP {ip}: {e}")
        return False


async def unblock_ip(ip: str) -> bool:
    """Remove IP from blocklist."""
    try:
        async with AsyncSessionLocal() as db:
            stmt = select(IpBlocklist).where(IpBlocklist.ip == ip)
            result = await db.execute(stmt)
            block_entry = await _maybe_await(result.scalar_one_or_none())
            
            if block_entry:
                await _maybe_await(db.delete(block_entry))
                await db.commit()
                logger.info(f"IP {ip} unblocked")
                return True
            
            return False  # Not blocked
            
    except Exception as e:
        logger.error(f"Failed to unblock IP {ip}: {e}")
        return False


def set_device_cookie_middleware(response: Response, request: Request):
    """Set device cookie if requested by identity resolution."""
    if hasattr(request.state, 'set_device_cookie'):
        response.set_cookie(
            key=COOKIE_NAME,
            value=request.state.set_device_cookie,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=os.getenv("COOKIE_SECURE", "false").lower() == "true"
        )
        logger.debug("Device cookie set for new identity")