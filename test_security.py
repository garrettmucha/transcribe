"""
Tests for security modules.
"""

import os
import time
from datetime import datetime, date
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.security.identity import (
    generate_device_id, sign_device_id, verify_device_id, 
    hash_user_agent, compute_identity_key, get_or_create_identity,
    is_ip_blocked, block_ip, unblock_ip
)
from app.security.ratelimit import (
    check_rate_limit,
    check_concurrent_limit,
    release_concurrent_limit,
    check_monthly_usage_limit,
    record_usage,
    get_rate_limit_status,
)
from app.models import UserIdentity, UsageMonthly, IpBlocklist


class TestIdentityManagement:
    """Tests for identity management functions."""
    
    def test_generate_device_id(self):
        """Test device ID generation."""
        device_id1 = generate_device_id()
        device_id2 = generate_device_id()
        
        assert device_id1 != device_id2
        assert len(device_id1) == 36  # UUID4 format
        assert "-" in device_id1
    
    def test_sign_device_id(self):
        """Test device ID signing."""
        device_id = "test-device-123"
        signed = sign_device_id(device_id)
        
        assert "." in signed
        assert signed.startswith(device_id)
        
        # Should be deterministic
        signed2 = sign_device_id(device_id)
        assert signed == signed2
    
    def test_verify_device_id_valid(self):
        """Test device ID verification with valid signature."""
        device_id = "test-device-456"
        signed = sign_device_id(device_id)
        
        verified = verify_device_id(signed)
        assert verified == device_id
    
    def test_verify_device_id_invalid(self):
        """Test device ID verification with invalid signature."""
        # Tampered signature
        invalid_signed = "test-device-789.invalid_signature"
        
        verified = verify_device_id(invalid_signed)
        assert verified is None
    
    def test_verify_device_id_malformed(self):
        """Test device ID verification with malformed input."""
        malformed = "no_dot_separator"
        
        verified = verify_device_id(malformed)
        assert verified is None
    
    def test_hash_user_agent(self):
        """Test user agent hashing."""
        ua1 = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        ua2 = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        
        hash1 = hash_user_agent(ua1)
        hash2 = hash_user_agent(ua2)
        hash3 = hash_user_agent(ua1)  # Same as first
        
        assert hash1 != hash2
        assert hash1 == hash3
        assert len(hash1) == 16  # Truncated SHA256
        
        # Test with None
        hash_none = hash_user_agent(None)
        assert hash_none == "unknown"
    
    def test_compute_identity_key(self):
        """Test identity key computation."""
        ip = "192.168.1.1"
        device_id = "device-123"
        ua_hash = "ua_hash_456"
        
        key1 = compute_identity_key(ip, device_id, ua_hash)
        key2 = compute_identity_key(ip, device_id, ua_hash)  # Same inputs
        key3 = compute_identity_key(ip, "different-device", ua_hash)  # Different device
        
        assert key1 == key2  # Deterministic
        assert key1 != key3  # Different inputs produce different keys
        assert len(key1) == 64  # SHA256 hex
    
    @pytest.mark.asyncio
    async def test_get_or_create_identity_new(self):
        """Test creating new identity."""
        # Mock request
        mock_request = MagicMock()
        mock_request.client.host = "192.168.1.1"
        mock_request.headers.get.return_value = "Mozilla/5.0 Test Browser"
        mock_request.cookies.get.return_value = None
        mock_request.state = MagicMock()
        
        with patch('app.security.identity.AsyncSessionLocal') as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value.__aenter__.return_value = mock_session
            
            # Mock database operations
            mock_session.execute.return_value.scalar_one_or_none.return_value = None
            
            identity_id = await get_or_create_identity(mock_request)
            
            assert identity_id is not None
            assert len(identity_id) == 64  # SHA256 hex
            
            # Should have set cookie
            assert hasattr(mock_request.state, 'set_device_cookie')
    
    @pytest.mark.asyncio
    async def test_get_or_create_identity_existing(self):
        """Test retrieving existing identity."""
        # Mock request with valid cookie
        device_id = "existing-device-123"
        signed_cookie = sign_device_id(device_id)
        
        mock_request = MagicMock()
        mock_request.client.host = "192.168.1.1"
        mock_request.headers.get.return_value = "Mozilla/5.0 Test Browser"
        mock_request.cookies.get.return_value = signed_cookie
        
        # Mock existing identity
        mock_identity = MagicMock()
        mock_identity.id = "existing-identity-key"
        
        with patch('app.security.identity.AsyncSessionLocal') as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value.__aenter__.return_value = mock_session
            
            mock_session.execute.return_value.scalar_one_or_none.return_value = mock_identity
            
            identity_id = await get_or_create_identity(mock_request)
            
            assert identity_id is not None
            # Should have updated last_seen_at
            mock_session.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_is_ip_blocked_true(self):
        """Test IP blocklist check for blocked IP."""
        with patch('app.security.identity.AsyncSessionLocal') as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value.__aenter__.return_value = mock_session
            
            # Mock blocked IP exists
            mock_blocked_entry = MagicMock()
            mock_session.execute.return_value.scalar_one_or_none.return_value = mock_blocked_entry
            
            is_blocked = await is_ip_blocked("192.168.1.100")
            assert is_blocked is True
    
    @pytest.mark.asyncio
    async def test_is_ip_blocked_false(self):
        """Test IP blocklist check for non-blocked IP."""
        with patch('app.security.identity.AsyncSessionLocal') as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value.__aenter__.return_value = mock_session
            
            # Mock no blocked entry
            mock_session.execute.return_value.scalar_one_or_none.return_value = None
            
            is_blocked = await is_ip_blocked("192.168.1.1")
            assert is_blocked is False
    
    @pytest.mark.asyncio
    async def test_block_ip(self):
        """Test blocking an IP address."""
        with patch('app.security.identity.AsyncSessionLocal') as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value.__aenter__.return_value = mock_session
            
            # Mock IP not already blocked
            mock_session.execute.return_value.scalar_one_or_none.return_value = None
            
            success = await block_ip("192.168.1.100", "Abuse detected", "admin@example.com")
            
            assert success is True
            mock_session.add.assert_called_once()
            mock_session.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_unblock_ip(self):
        """Test unblocking an IP address."""
        with patch('app.security.identity.AsyncSessionLocal') as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value.__aenter__.return_value = mock_session
            
            # Mock blocked entry exists
            mock_blocked_entry = MagicMock()
            mock_session.execute.return_value.scalar_one_or_none.return_value = mock_blocked_entry
            
            success = await unblock_ip("192.168.1.100")
            
            assert success is True
            mock_session.delete.assert_called_once_with(mock_blocked_entry)
            mock_session.commit.assert_called_once()


class TestRateLimiting:
    """Tests for rate limiting functions."""
    
    @pytest.mark.asyncio
    async def test_check_rate_limit_allowed(self, mock_redis):
        """Test rate limit check when request is allowed."""
        identity_id = "test-identity"
        
        # Set up Redis state - fresh bucket
        await mock_redis.set(f"rate:{identity_id}:tokens", 15)
        await mock_redis.set(f"rate:{identity_id}:timestamp", time.time())
        
        allowed, remaining = await check_rate_limit(identity_id)
        
        assert allowed is True
        assert remaining == 14  # Should have consumed one token
    
    @pytest.mark.asyncio
    async def test_check_rate_limit_denied(self, mock_redis):
        """Test rate limit check when request is denied."""
        identity_id = "test-identity"
        
        # Set up Redis state - empty bucket
        await mock_redis.set(f"rate:{identity_id}:tokens", 0)
        await mock_redis.set(f"rate:{identity_id}:timestamp", time.time())
        
        allowed, remaining = await check_rate_limit(identity_id)
        
        assert allowed is False
        assert remaining == 0
    
    @pytest.mark.asyncio
    async def test_check_rate_limit_refill(self, mock_redis):
        """Test rate limit token refill over time."""
        identity_id = "test-identity"
        
        # Set up Redis state - old timestamp to trigger refill
        old_timestamp = time.time() - 120  # 2 minutes ago
        await mock_redis.set(f"rate:{identity_id}:tokens", 5)
        await mock_redis.set(f"rate:{identity_id}:timestamp", old_timestamp)
        
        allowed, remaining = await check_rate_limit(identity_id)
        
        assert allowed is True
        # Should have refilled some tokens (2 minutes * 1 token/minute = 2 tokens)
        # 5 + 2 = 7, minus 1 consumed = 6 remaining
        assert remaining >= 6
    
    @pytest.mark.asyncio
    async def test_check_concurrent_limit_allowed(self, mock_redis):
        """Test concurrent limit check when allowed."""
        identity_id = "test-identity"
        
        # No existing concurrent jobs
        allowed, remaining = await check_concurrent_limit(identity_id)

        assert allowed is True
        assert remaining >= 0
        
        # Should have incremented semaphore
        count = await mock_redis.get(f"concurrent:{identity_id}")
        assert int(count) == 1
    
    @pytest.mark.asyncio
    async def test_check_concurrent_limit_denied(self, mock_redis):
        """Test concurrent limit check when denied."""
        identity_id = "test-identity"
        
        # Set up existing concurrent job
        await mock_redis.set(f"concurrent:{identity_id}", 1)
        
        allowed, remaining = await check_concurrent_limit(identity_id)

        assert allowed is False
        assert remaining == 0
    
    @pytest.mark.asyncio
    async def test_release_concurrent_limit(self, mock_redis):
        """Test releasing concurrent limit."""
        identity_id = "test-identity"
        
        # Set up existing concurrent job
        await mock_redis.set(f"concurrent:{identity_id}", 1)
        
        await release_concurrent_limit(identity_id)
        
        # Should have decremented
        count = await mock_redis.get(f"concurrent:{identity_id}")
        assert count in (None, "0")
    
    @pytest.mark.asyncio
    async def test_check_monthly_usage_limit_allowed(self, db_session: AsyncSession):
        """Test monthly usage limit check when allowed."""
        identity_id = "usage-test-identity"
        
        # Create identity
        identity = UserIdentity(
            id=identity_id,
            ip_first="192.168.1.1",
            ip_last="192.168.1.1"
        )
        db_session.add(identity)
        
        # Create usage record with some usage
        usage = UsageMonthly(
            identity_id=identity_id,
            month=date.today().replace(day=1),
            minutes_used=50.0,
            files=2,
            bytes_in=1000000,
            bytes_out=500000
        )
        db_session.add(usage)
        await db_session.commit()
        
        # Test adding 20 more minutes (should be allowed)
        allowed, remaining = await check_monthly_usage_limit(
            identity_id, 20.0, 100, db_session
        )

        assert allowed is True
        assert remaining == 50.0  # 100 - 50

    @pytest.mark.asyncio
    async def test_check_monthly_usage_limit_exceeded(self, db_session: AsyncSession):
        """Test monthly usage limit check when exceeded."""
        identity_id = "usage-exceeded-identity"
        
        # Create identity
        identity = UserIdentity(
            id=identity_id,
            ip_first="192.168.1.1",
            ip_last="192.168.1.1"
        )
        db_session.add(identity)
        
        # Create usage record near limit
        usage = UsageMonthly(
            identity_id=identity_id,
            month=date.today().replace(day=1),
            minutes_used=90.0,
            files=5,
            bytes_in=5000000,
            bytes_out=2500000
        )
        db_session.add(usage)
        await db_session.commit()
        
        # Test adding 20 more minutes (should exceed 100 minute limit)
        allowed, remaining = await check_monthly_usage_limit(
            identity_id, 20.0, 100, db_session
        )

        assert allowed is False
        assert remaining == 10.0  # 100 - 90
    
    @pytest.mark.asyncio
    async def test_record_usage_new_record(self, db_session: AsyncSession, mock_redis):
        """Test recording usage for new daily record."""
        identity_id = "record-usage-identity"
        
        # Create identity
        identity = UserIdentity(
            id=identity_id,
            ip_first="192.168.1.1",
            ip_last="192.168.1.1"
        )
        db_session.add(identity)
        await db_session.commit()
        
        # Record usage
        await record_usage(
            identity_id, 3.5, 2000000, 1000000, db_session
        )
        
        # Verify record was created
        usage = await db_session.get(UsageMonthly, (identity_id, date.today().replace(day=1)))
        assert usage is not None
        assert usage.minutes_used == 3.5
        assert usage.files == 1
        assert usage.bytes_in == 2000000
        assert usage.bytes_out == 1000000
    
    @pytest.mark.asyncio
    async def test_record_usage_existing_record(self, db_session: AsyncSession, mock_redis):
        """Test recording usage for existing daily record."""
        identity_id = "record-existing-identity"
        
        # Create identity
        identity = UserIdentity(
            id=identity_id,
            ip_first="192.168.1.1",
            ip_last="192.168.1.1"
        )
        db_session.add(identity)
        
        # Create existing usage record
        usage = UsageMonthly(
            identity_id=identity_id,
            month=date.today().replace(day=1),
            minutes_used=2.0,
            files=1,
            bytes_in=1000000,
            bytes_out=500000
        )
        db_session.add(usage)
        await db_session.commit()
        
        # Record additional usage
        await record_usage(
            identity_id, 1.5, 500000, 250000, db_session
        )
        
        # Verify record was updated
        updated_usage = await db_session.get(UsageMonthly, (identity_id, date.today().replace(day=1)))
        assert updated_usage.minutes_used == 3.5  # 2.0 + 1.5
        assert updated_usage.files == 2  # 1 + 1
        assert updated_usage.bytes_in == 1500000  # 1000000 + 500000
        assert updated_usage.bytes_out == 750000  # 500000 + 250000
    
    @pytest.mark.asyncio
    async def test_get_rate_limit_status(self, mock_redis):
        """Test getting rate limit status."""
        identity_id = "status-test-identity"
        
        # Set up Redis state
        await mock_redis.set(f"rate:{identity_id}:tokens", 5)
        await mock_redis.set(f"rate:{identity_id}:timestamp", time.time())
        await mock_redis.set(f"concurrent:{identity_id}", 1)
        
        status = await get_rate_limit_status(identity_id)
        
        assert status['tokens_remaining'] == 5
        assert status['tokens_max'] == 10
        assert status['concurrent_jobs'] == 1
        assert status['concurrent_max'] == 1
        assert 'reset_at' in status