"""
Pytest configuration and fixtures.
"""

import asyncio
import os
import asyncio
import tempfile
from typing import AsyncGenerator, Generator
import os
import tempfile
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Set test environment
os.environ["TESTING"] = "true"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379"
os.environ["LOG_LEVEL"] = "ERROR"
os.environ["STORAGE_ROOT"] = os.path.join(tempfile.gettempdir(), "transcribe-tests")
os.environ["STORAGE_PUBLIC_PREFIX"] = "/storage"

from app.main import app
from app.models import Base, get_db_session
from app.security.ratelimit import redis_client


# Test database setup
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False
)

TestSessionLocal = async_sessionmaker(
    test_engine,
    class_=AsyncSession,
    expire_on_commit=False
)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session."""
    # Create tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Create session
    async with TestSessionLocal() as session:
        yield session
    
    # Clean up
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def client(db_session: AsyncSession) -> Generator[TestClient, None, None]:
    """Create a test client with mocked dependencies."""
    
    # Mock database dependency
    async def get_test_db_session():
        yield db_session
    
    app.dependency_overrides[get_db_session] = get_test_db_session
    
    # Mock Redis
    fake_redis = fakeredis.aioredis.FakeRedis()
    import app.security.ratelimit as ratelimit_module

    original_redis = ratelimit_module.redis_client
    ratelimit_module.redis_client = fake_redis

    try:
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client
    finally:
        ratelimit_module.redis_client = original_redis
        app.dependency_overrides.clear()


@pytest.fixture
def mock_storage():
    """Mock storage service."""
    from app.services.storage import StorageService
    
    mock = MagicMock(spec=StorageService)
    mock.use_local = True
    
    # Mock methods
    mock.upload_file = AsyncMock(return_value="file:///tmp/test.wav")
    mock.download_file = AsyncMock(return_value=b"fake audio data")
    mock.get_signed_url = AsyncMock(return_value="http://localhost/test.wav")
    mock.delete_file = AsyncMock(return_value=True)
    mock.list_files = AsyncMock(return_value=[])
    mock.health_check = AsyncMock(return_value={"status": "healthy", "type": "local"})
    
    return mock


@pytest.fixture
def mock_audio_processor():
    """Mock audio processor."""
    from app.services.audio import AudioProcessor
    
    mock = MagicMock(spec=AudioProcessor)
    
    # Mock methods
    mock.probe_duration = AsyncMock(return_value=5.0)  # 5 seconds
    mock.process_audio_file = AsyncMock(return_value=(
        "This is a test transcript.",
        "WEBVTT\n\n00:00:00.000 --> 00:00:05.000\nThis is a test transcript.\n",
        5.0,
        {"processing": {"transcription": {"language": "en"}}}
    ))
    
    return mock


@pytest.fixture
def mock_text_processor():
    """Mock text processor."""
    from app.services.audio import TextProcessor
    
    mock = MagicMock(spec=TextProcessor)
    
    # Mock methods
    mock.summarize_text = AsyncMock(return_value="This is a summary.")
    mock.extract_topics = AsyncMock(return_value={
        "topics": [{"keyword": "test", "score": 0.9}],
        "extraction_method": "basic"
    })
    
    return mock


@pytest.fixture
def sample_audio_file():
    """Create a sample audio file for testing."""
    # Create a minimal WAV file (44 bytes header + 1 second of silence)
    wav_header = b'RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00'
    wav_data = b'\x00' * 1000  # 1000 bytes of silence
    
    return wav_header + wav_data


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture(autouse=True)
def mock_celery():
    """Mock Celery tasks for testing."""
    from app.tasks.transcribe import transcribe_audio_task
    
    # Mock the task
    original_apply_async = transcribe_audio_task.apply_async
    
    def mock_apply_async(*args, **kwargs):
        # Return a mock result
        result = MagicMock()
        result.id = "test-task-id"
        result.status = "PENDING"
        return result
    
    transcribe_audio_task.apply_async = mock_apply_async
    
    yield
    
    # Restore original
    transcribe_audio_task.apply_async = original_apply_async


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    fake_redis = fakeredis.aioredis.FakeRedis()
    
    # Patch the redis client
    original_redis = redis_client
    
    # Replace with fake redis
    import app.security.ratelimit
    app.security.ratelimit.redis_client = fake_redis
    
    yield fake_redis
    
    # Restore original
    app.security.ratelimit.redis_client = original_redis


@pytest.fixture
def identity_id():
    """Standard test identity ID."""
    return "test-identity-12345"


@pytest.fixture
def job_data():
    """Standard test job data."""
    return {
        "job_id": "test-job-12345",
        "input_uri": "file:///tmp/test-input.wav",
        "output_prefix": "results/test-job-12345/",
        "language": "en",
        "diarize": False,
        "topics": True
    }


# Configure asyncio for tests
@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


# Test configuration
pytest_plugins = ["pytest_asyncio"]