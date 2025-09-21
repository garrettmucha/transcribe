# Audio Transcription Service Configuration
# Copy this file to .env and update the values

# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================
DATABASE_URL=postgresql://transcribe_user:transcribe_pass@postgres:5432/transcribe_db

# =============================================================================
# REDIS CONFIGURATION
# =============================================================================
REDIS_URL=redis://redis:6379

# =============================================================================
# STORAGE CONFIGURATION (Cloudflare R2 / S3)
# =============================================================================
# For production, use Cloudflare R2 or AWS S3
# For development, leave empty to use local storage
S3_ENDPOINT=https://your-account.r2.cloudflarestorage.com
S3_REGION=auto
S3_BUCKET=transcribe-storage
S3_ACCESS_KEY=your-r2-access-key
S3_SECRET_KEY=your-r2-secret-key

# Local storage path (used when S3 not configured)
LOCAL_STORAGE_PATH=/tmp/transcribe/storage

# =============================================================================
# APPLICATION CONFIGURATION
# =============================================================================
PUBLIC_BASE_URL=http://localhost
ENVIRONMENT=development

# Security - CHANGE IN PRODUCTION!
COOKIE_SIGNING_KEY=your-secret-signing-key-change-in-production-must-be-random
COOKIE_SECURE=false

# CORS and allowed hosts
ALLOWED_HOSTS=localhost,127.0.0.1,your-domain.com

# =============================================================================
# AUDIO PROCESSING CONFIGURATION
# =============================================================================
# Whisper model: tiny, small, medium, large
# medium = default (good balance), small = fallback, large = max quality
WHISPER_MODEL=medium
WHISPER_BEAM_SIZE=5

# Model caching (faster-whisper downloads from Hugging Face Hub)
# Models: guillaumekln/faster-whisper-{tiny,small,medium,large}
WHISPER_CACHE_DIR=/models              # Custom model cache location
HF_HOME=/models                        # Hugging Face cache directory
HF_HUB_OFFLINE=false                   # Set true for offline mode

# Speaker diarization settings
ENABLE_DIARIZATION=true
MAX_SPEAKERS=10
HUGGINGFACE_TOKEN=your-huggingface-token-for-gated-models

# File and duration limits
MAX_FILE_SIZE_MB=50
MAX_DURATION_MIN=15
DAILY_CAP_MIN=10

# Supported MIME types (comma-separated)
ALLOWED_MIME_LIST=audio/mpeg,audio/wav,audio/x-wav,audio/flac,audio/mp4,audio/aac,audio/ogg,audio/webm,video/mp4

# =============================================================================
# RATE LIMITING CONFIGURATION
# =============================================================================
# Token bucket rate limiting
RATE_LIMIT_BURST=15
RATE_LIMIT_RATE=1

# Concurrent jobs per identity
CONCURRENT_JOB_LIMIT=1

# =============================================================================
# FILE RETENTION CONFIGURATION
# =============================================================================
FILE_RETENTION_DAYS=7

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================
LOG_LEVEL=INFO
LOG_FORMAT=json

# =============================================================================
# OBSERVABILITY CONFIGURATION
# =============================================================================
# Prometheus metrics
PROMETHEUS_ENABLE=true

# OpenTelemetry tracing
TRACING_ENABLED=false
JAEGER_ENDPOINT=
JAEGER_AGENT_HOST=localhost
JAEGER_AGENT_PORT=6831

# =============================================================================
# HUMAN VERIFICATION (Optional)
# =============================================================================
# Options: off, hcaptcha
HUMAN_VERIFICATION=off
HCAPTCHA_SECRET=your-hcaptcha-secret-key

# =============================================================================
# CELERY WORKER CONFIGURATION
# =============================================================================
# Worker concurrency (number of parallel jobs)
CELERY_CONCURRENCY=2

# Task time limits (seconds)
CELERY_TASK_TIME_LIMIT=1800
CELERY_TASK_SOFT_TIME_LIMIT=1500

# =============================================================================
# PERFORMANCE TUNING
# =============================================================================
# Database connection pool
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=30

# CPU optimization
OMP_NUM_THREADS=1

# Cost estimation (for metrics)
CPU_COST_PER_HOUR=0.10

# =============================================================================
# DEVELOPMENT / TESTING
# =============================================================================
# Set to true when running tests
TESTING=false

# SQL query echoing (development only)
SQL_ECHO=false

# =============================================================================
# FUTURE FEATURES (Not yet implemented)
# =============================================================================
# Webhook configuration
WEBHOOK_SECRET=your-webhook-secret
WEBHOOK_TIMEOUT=30

# Email notifications
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=noreply@your-domain.com

# =============================================================================
# DOCKER COMPOSE OVERRIDES
# =============================================================================
# These can be overridden in docker-compose.override.yml

# API port mapping
API_PORT=8000

# Traefik dashboard port
TRAEFIK_DASHBOARD_PORT=8080

# Database port mapping (for external access)
DB_PORT=5432

# Redis port mapping (for external access)
REDIS_PORT=6379