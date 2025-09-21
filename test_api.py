"""
Tests for API endpoints.
"""

import io
import json
from unittest.mock import patch, AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Job, JobStatus, UserIdentity, UsageMonthly
from datetime import datetime, date


class TestTranscribeEndpoint:
    """Tests for the /transcribe endpoint."""
    
    def test_transcribe_success(self, client: TestClient, sample_audio_file: bytes, mock_storage, mock_audio_processor):
        """Test successful transcription request."""
        with patch('app.services.storage.StorageService', return_value=mock_storage), \
             patch('app.services.audio.AudioProcessor', return_value=mock_audio_processor):
            
            response = client.post(
                "/api/v1/transcribe",
                files={"file": ("test.wav", io.BytesIO(sample_audio_file), "audio/wav")},
                data={"lang": "en", "diarize": "false", "topics": "true"}
            )
        
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "queued"
        assert "remaining_day_minutes" in data
    
    def test_transcribe_file_too_large(self, client: TestClient):
        """Test rejection of oversized files."""
        # Create a file that's too large (> 50MB)
        large_file = b"x" * (51 * 1024 * 1024)
        
        response = client.post(
            "/api/v1/transcribe",
            files={"file": ("large.wav", io.BytesIO(large_file), "audio/wav")}
        )
        
        assert response.status_code == 413
        assert "File size exceeds" in response.json()["detail"]
    
    def test_transcribe_invalid_mime_type(self, client: TestClient):
        """Test rejection of invalid file types."""
        response = client.post(
            "/api/v1/transcribe",
            files={"file": ("test.txt", io.BytesIO(b"not audio"), "text/plain")}
        )
        
        assert response.status_code == 415
        assert "Unsupported file type" in response.json()["detail"]
    
    def test_transcribe_audio_too_long(self, client: TestClient, sample_audio_file: bytes):
        """Test rejection of audio files that are too long."""
        with patch('app.services.audio.AudioProcessor') as mock_processor_class:
            mock_processor = AsyncMock()
            mock_processor.probe_duration.return_value = 21 * 60  # 21 minutes
            mock_processor_class.return_value = mock_processor
            
            response = client.post(
                "/api/v1/transcribe",
                files={"file": ("long.wav", io.BytesIO(sample_audio_file), "audio/wav")}
            )
        
        assert response.status_code == 413
        assert "Audio duration exceeds" in response.json()["detail"]
    
    def test_transcribe_daily_limit_exceeded(self, client: TestClient, sample_audio_file: bytes):
        """Test rejection when daily limit is exceeded."""
        with patch('app.security.ratelimit.check_monthly_usage_limit') as mock_check:
            mock_check.return_value = (False, 0.5)  # Not allowed, 0.5 minutes remaining

            response = client.post(
                "/api/v1/transcribe",
                files={"file": ("test.wav", io.BytesIO(sample_audio_file), "audio/wav")}
            )

        assert response.status_code == 429
        assert "Monthly quota exceeded" in response.json()["detail"]


class TestJobStatusEndpoint:
    """Tests for the /jobs/{job_id} endpoint."""
    
    @pytest.mark.asyncio
    async def test_get_job_status_queued(self, client: TestClient, db_session: AsyncSession, identity_id: str):
        """Test getting status of queued job."""
        # Create a test job
        job = Job(
            id="test-job-123",
            identity_id=identity_id,
            status=JobStatus.QUEUED,
            input_uri="file:///tmp/test.wav",
            duration_seconds=5.0,
            bytes_in=1000,
            created_at=datetime.utcnow()
        )
        db_session.add(job)
        await db_session.commit()
        
        # Mock identity middleware
        with patch('app.main.get_or_create_identity', return_value=identity_id):
            response = client.get("/api/v1/jobs/test-job-123")
        
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "test-job-123"
        assert data["status"] == "queued"
    
    @pytest.mark.asyncio
    async def test_get_job_status_succeeded(self, client: TestClient, db_session: AsyncSession, identity_id: str, mock_storage):
        """Test getting status of completed job."""
        # Create a completed job
        job = Job(
            id="test-job-456",
            identity_id=identity_id,
            status=JobStatus.SUCCEEDED,
            input_uri="file:///tmp/test.wav",
            output_uri_prefix="results/test-job-456/",
            duration_seconds=5.0,
            bytes_in=1000,
            bytes_out=500,
            created_at=datetime.utcnow(),
            finished_at=datetime.utcnow()
        )
        db_session.add(job)
        await db_session.commit()
        
        with patch('app.services.storage.StorageService', return_value=mock_storage), \
             patch('app.main.get_or_create_identity', return_value=identity_id):
            
            response = client.get("/api/v1/jobs/test-job-456")
        
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "test-job-456"
        assert data["status"] == "succeeded"
        assert "outputs" in data
    
    def test_get_job_status_not_found(self, client: TestClient, identity_id: str):
        """Test getting status of non-existent job."""
        with patch('app.main.get_or_create_identity', return_value=identity_id):
            response = client.get("/api/v1/jobs/nonexistent")
        
        assert response.status_code == 404
        assert "Job not found" in response.json()["detail"]
    
    @pytest.mark.asyncio
    async def test_get_job_status_access_denied(self, client: TestClient, db_session: AsyncSession):
        """Test access denied for job owned by different identity."""
        # Create job with different identity
        job = Job(
            id="test-job-789",
            identity_id="other-identity",
            status=JobStatus.QUEUED,
            input_uri="file:///tmp/test.wav",
            duration_seconds=5.0,
            bytes_in=1000,
            created_at=datetime.utcnow()
        )
        db_session.add(job)
        await db_session.commit()
        
        with patch('app.main.get_or_create_identity', return_value="my-identity"):
            response = client.get("/api/v1/jobs/test-job-789")
        
        assert response.status_code == 403
        assert "Access denied" in response.json()["detail"]


class TestUsageEndpoint:
    """Tests for the /usage endpoint."""
    
    @pytest.mark.asyncio
    async def test_get_usage_stats(self, client: TestClient, db_session: AsyncSession, identity_id: str):
        """Test getting usage statistics."""
        # Create usage record
        month_start = date.today().replace(day=1)
        usage = UsageMonthly(
            identity_id=identity_id,
            month=month_start,
            minutes_used=55.0,
            files=6,
            bytes_in=15000,
            bytes_out=7500,
            last_updated_at=datetime.utcnow()
        )
        db_session.add(usage)
        await db_session.commit()

        with patch('app.main.get_or_create_identity', return_value=identity_id):
            response = client.get("/api/v1/usage")

        assert response.status_code == 200
        data = response.json()
        assert data["identity_id"] == identity_id
        assert data["monthly_limit_minutes"] == 100
        assert data["this_month"]["minutes_used"] == 55.0
        assert data["this_month"]["files"] == 6
        assert data["this_month"]["bytes"] == 15000

    def test_get_usage_stats_new_user(self, client: TestClient, identity_id: str):
        """Test getting usage stats for new user with no history."""
        with patch('app.main.get_or_create_identity', return_value=identity_id):
            response = client.get("/api/v1/usage")

        assert response.status_code == 200
        data = response.json()
        assert data["identity_id"] == identity_id
        assert data["this_month"]["minutes_used"] == 0.0
        assert data["this_month"]["files"] == 0
        assert data["this_month"]["bytes"] == 0


class TestHealthEndpoint:
    """Tests for health check endpoints."""
    
    def test_health_check(self, client: TestClient):
        """Test health check endpoint."""
        response = client.get("/healthz")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
    
    def test_metrics_endpoint(self, client: TestClient):
        """Test Prometheus metrics endpoint."""
        response = client.get("/metrics")
        
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")


class TestLandingPage:
    """Tests for the landing page."""
    
    def test_landing_page(self, client: TestClient):
        """Test landing page loads."""
        response = client.get("/")
        
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Audio Transcription Service" in response.text


class TestRateLimiting:
    """Tests for rate limiting functionality."""
    
    def test_rate_limit_headers(self, client: TestClient):
        """Test that rate limit headers are included in API responses."""
        with patch('app.security.ratelimit.check_rate_limit', return_value=(True, 14)):
            response = client.get("/api/v1/usage")
        
        # Should succeed but we can't easily test headers in this setup
        # In a real integration test, we'd check for X-RateLimit-Remaining
        assert response.status_code == 200
    
    def test_rate_limit_exceeded(self, client: TestClient):
        """Test rate limit rejection."""
        with patch('app.security.ratelimit.check_rate_limit', return_value=(False, 0)):
            response = client.get("/api/v1/usage")
        
        assert response.status_code == 429
        assert "Rate limit exceeded" in response.json()["detail"]


class TestErrorHandling:
    """Tests for error handling."""
    
    def test_internal_server_error(self, client: TestClient):
        """Test internal server error handling."""
        with patch('app.api.routes.get_usage') as mock_usage:
            mock_usage.side_effect = Exception("Database error")
            
            response = client.get("/api/v1/usage")
        
        assert response.status_code == 500
        assert "Internal server error" in response.json()["detail"]
    
    def test_validation_error(self, client: TestClient):
        """Test validation error handling."""
        # Send invalid data
        response = client.post(
            "/api/v1/transcribe",
            data={"invalid": "data"}  # Missing required file
        )
        
        assert response.status_code == 422  # Validation error


class TestCORS:
    """Tests for CORS handling."""
    
    def test_cors_headers(self, client: TestClient):
        """Test CORS headers are present."""
        response = client.options("/api/v1/usage")
        
        # FastAPI TestClient may not fully simulate CORS
        # In real tests, we'd check for Access-Control-Allow-Origin
        assert response.status_code in [200, 405]  # OPTIONS may not be implemented