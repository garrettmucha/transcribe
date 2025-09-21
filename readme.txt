# 🎵 Audio Transcription Service

A production-ready, **CPU-only** audio transcription and summarization service built with FastAPI, Celery, and faster-whisper. Features a **Free plan only** at launch with **strict guardrails** and **usage tracking**.

## ✨ Features

- **🎯 CPU-Only Processing**: Uses faster-whisper with CTranslate2 for efficient CPU-based transcription
- **🗣️ Speaker Attribution**: Full speaker diarization with pyannote.audio for multi-speaker identification
- **📝 Complete Audio Processing**: Transcription, speaker-labeled VTT captions, summarization, and topic extraction
- **🌍 99-Language Support**: Auto-detection or manual selection from Whisper's full language set
- **🔒 Built-in Security**: Rate limiting, IP blocking, device fingerprinting without accounts
- **📊 Usage Tracking**: Daily limits, file counting, and comprehensive metrics
- **🚀 Production Ready**: Docker deployment, observability, and horizontal scaling
- **💾 Pluggable Storage**: Local files for dev, Cloudflare R2/S3 for production
- **🔍 Observability**: Prometheus metrics, structured logging, OpenTelemetry tracing

## 🏗️ Architecture

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│   Traefik   │───▶│   FastAPI    │───▶│   Celery    │
│  (Reverse   │    │     API      │    │   Worker    │
│   Proxy)    │    │              │    │             │
└─────────────┘    └──────────────┘    └─────────────┘
                           │                    │
                           ▼                    ▼
                   ┌──────────────┐    ┌─────────────┐
                   │ PostgreSQL   │    │    Redis    │
                   │ (Database)   │    │ (Queue/Cache)│
                   └──────────────┘    └─────────────┘
                           │
                           ▼
                   ┌──────────────┐
                   │ Cloudflare R2│
                   │  (Storage)   │
                   └──────────────┘
```

## 🚀 Quick Start

### Local Development (Docker Compose)

```bash
# 1. Setup
git clone <repository>
cd transcribe-service
cp .env.example .env
# Edit .env with your Cloudflare R2 credentials

# 2. Start everything  
make dev
# or: docker-compose up -d && make db-migrate

# 3. Test the service
make test-upload
# or: open http://localhost
```

### Akash Network Deployment (Decentralized Cloud)

```bash
# 1. Build for Akash
./scripts/build-for-akash.sh --username your-github-username

# 2. Configure deployment
# Edit akash/deploy.yaml with your S3/R2 credentials

# 3. Deploy to Akash
./scripts/deploy-to-akash.sh

# 4. Access your service
# URL provided after deployment
```

**💡 See [AKASH-DEPLOYMENT.md](AKASH-DEPLOYMENT.md) for detailed Akash deployment guide**

### Monitoring

```bash
# Local
open http://localhost/metrics      # Prometheus metrics
open http://localhost:8080         # Traefik dashboard

# Akash  
curl https://your-akash-url/healthz    # Health check
curl https://your-akash-url/metrics    # Metrics
```

## 📋 Configuration

### Environment Variables

Create a `.env` file with the following configuration:

```bash
# Database
DATABASE_URL=postgresql://transcribe_user:transcribe_pass@postgres:5432/transcribe_db

# Redis
REDIS_URL=redis://redis:6379

# Storage (Cloudflare R2)
S3_ENDPOINT=https://your-account.r2.cloudflarestorage.com
S3_REGION=auto
S3_BUCKET=transcribe-storage
S3_ACCESS_KEY=your-r2-access-key
S3_SECRET_KEY=your-r2-secret-key

# Security
COOKIE_SIGNING_KEY=your-secret-signing-key-change-in-production
PUBLIC_BASE_URL=https://your-domain.com

# Audio Processing
WHISPER_MODEL=medium                   # medium, small, large (medium default with small fallback)
WHISPER_BEAM_SIZE=5
ENABLE_DIARIZATION=true               # Enable speaker identification
MAX_SPEAKERS=10                       # Maximum speakers to detect
HUGGINGFACE_TOKEN=your-hf-token      # Optional: for gated models
MAX_DURATION_MIN=15
DAILY_CAP_MIN=10

# Rate Limiting
RATE_LIMIT_BURST=15
RATE_LIMIT_RATE=1                      # tokens per minute
CONCURRENT_JOB_LIMIT=1

# File Management
MAX_FILE_SIZE_MB=50
FILE_RETENTION_DAYS=7

# Observability
LOG_LEVEL=INFO
LOG_FORMAT=json
PROMETHEUS_ENABLE=true
TRACING_ENABLED=false

# Optional: Human Verification
HUMAN_VERIFICATION=off                 # off, hcaptcha
HCAPTCHA_SECRET=your-hcaptcha-secret
```

### Free Plan Limits

| Limit | Value | Description |
|-------|-------|-------------|
| **Daily Audio** | 10 minutes | Total audio processing per day |
| **File Size** | 50 MB | Maximum file size |
| **File Duration** | 15 minutes | Maximum audio length |
| **Concurrent Jobs** | 1 | Active jobs per identity |
| **Daily Jobs** | 10 | Total jobs per day |
| **File Retention** | 7 days | Auto-delete after period |

## 🎤 Whisper Models & Sources

### **Model Download Source**
Models are automatically downloaded from **Hugging Face Hub**:

| Model | Repository | Size | Accuracy | Use Case |
|-------|------------|------|----------|----------|
| `tiny` | `guillaumekln/faster-whisper-tiny` | 39MB | Basic | Development |
| `small` | `guillaumekln/faster-whisper-small` | 244MB | Good | Fallback |
| `medium` | `guillaumekln/faster-whisper-medium` | **769MB** | **Better** | **Default** |
| `large` | `guillaumekln/faster-whisper-large` | 1550MB | Best | Max quality |

### **Caching Strategy**
- **Local Development**: Models cached in `~/.cache/huggingface/hub/`
- **Docker/Akash**: Pre-downloaded during container build to `/models/`
- **First Run**: ~3-7 minute delay for medium model download
- **Subsequent Runs**: Instant loading from cache

### **Network Requirements**
- **Internet required**: For initial model download
- **Bandwidth**: 769MB for medium model (one-time)
- **Offline mode**: Available after first download

**💡 See [WHISPER-MODELS.md](WHISPER-MODELS.md) for detailed model management guide**

### Upload Audio for Transcription

```bash
curl -X POST http://localhost/api/v1/transcribe \
  -F "file=@audio.wav" \
  -F "lang=en" \
  -F "diarize=true" \
  -F "topics=true"
```

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "remaining_day_minutes": 8.5
}
```

### Check Job Status

```bash
curl http://localhost/api/v1/jobs/{job_id}
```

**Response (Completed):**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "succeeded",
  "created_at": "2024-12-19T12:00:00Z",
  "finished_at": "2024-12-19T12:02:30Z",
  "outputs": {
    "transcript": "https://signed-url-to-transcript.txt",
    "captions": "https://signed-url-to-captions.vtt", 
    "summary": "https://signed-url-to-summary.txt",
    "topics": "https://signed-url-to-topics.json",
    "diagnostics": "https://signed-url-to-diagnostics.json"
  }
}
```

### Get Usage Statistics

```bash
curl http://localhost/api/v1/usage
```

**Response:**
```json
{
  "identity_id": "abc123...",
  "daily_limit_minutes": 10,
  "today": {
    "minutes_used": 6.5,
    "files": 4,
    "bytes": 15000000
  },
  "last_7_days": {
    "minutes_used": 28.2,
    "files": 18,
    "bytes": 75000000
  },
  "server_time": "2024-12-19T12:00:00Z",
  "reset_time": "2024-12-20T00:00:00Z"
}
```

## 🎯 Supported Audio Formats

- **Audio**: MP3, WAV, FLAC, AAC, OGG, WebM
- **Video**: MP4 (audio extraction)
- **Sample Rates**: Any (converted to 16kHz mono)
- **Channels**: Mono/Stereo (converted to mono)

## 🔍 Monitoring & Observability

### Prometheus Metrics

Available at `http://localhost/metrics`:

- `http_requests_total` - HTTP request count by endpoint/status
- `jobs_total` - Job count by status
- `minutes_processed_total` - Total audio minutes processed
- `queue_wait_seconds` - Time jobs spend in queue
- `processing_seconds` - Job processing duration
- `ratelimit_rejections_total` - Rate limit rejections

### Admin Dashboard

Basic admin overview at `/admin/overview` (add authentication in production):

```json
{
  "total_jobs": 1234,
  "jobs_last_24h": 89,
  "total_minutes_processed": 456.7,
  "top_ips": [
    {"ip": "192.168.1.100", "jobs": 45},
    {"ip": "10.0.0.5", "jobs": 23}
  ]
}
```

### Structured Logs

JSON-formatted logs with correlation IDs:

```json
{
  "timestamp": "2024-12-19T12:00:00Z",
  "level": "INFO", 
  "logger": "jobs",
  "message": "Job completed",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "duration_seconds": 45.2,
  "identity_id": "abc123..."
}
```

## 🧪 Testing

### Run Tests

```bash
# Unit tests
docker-compose exec api pytest tests/ -v

# With coverage
docker-compose exec api pytest tests/ --cov=app --cov-report=html

# Specific test file
docker-compose exec api pytest tests/test_api.py -v
```

### Load Testing

```bash
# Install dependencies
pip install locust

# Run load test
locust -f tests/load_test.py --host=http://localhost
```

## 🔒 Security Features

### Identity Tracking
- **IP Address**: Client IP tracking
- **Device Fingerprint**: Signed HMAC cookies
- **User Agent**: Hashed browser fingerprint
- **No Accounts**: Frictionless free tier

### Rate Limiting
- **Token Bucket**: 15 burst, 1 token/minute refill
- **Concurrent Jobs**: 1 active job per identity
- **Daily Limits**: 10 minutes, 10 files per day
- **IP Blocking**: Manual blocklist for abuse

### File Security
- **MIME Validation**: Strict content-type checking
- **Magic Bytes**: File header verification
- **Size Limits**: 50MB maximum file size
- **Signed URLs**: Time-limited download links
- **Auto-Cleanup**: 7-day file retention

## 🏭 Production Deployment

### Option 1: Traditional VPS/Cloud (Docker Compose)

### 1. Cloudflare R2 Setup

```bash
# Create R2 bucket
wrangler r2 bucket create transcribe-storage

# Get credentials
wrangler r2 bucket list
```

### 2. Database Migration

```bash
# Run migrations
docker-compose exec api alembic upgrade head

# Create new migration
docker-compose exec api alembic revision --autogenerate -m "description"
```

### 3. Environment Configuration

```bash
# Production environment
export ENVIRONMENT=production
export LOG_LEVEL=WARNING
export COOKIE_SECURE=true
export ALLOWED_HOSTS=your-domain.com
```

### 4. SSL/TLS Setup

Update `infra/local/traefik.toml` for production:

```toml
[http.routers.api-secure]
  rule = "Host(`your-domain.com`)"
  service = "transcribe-api"
  tls.certResolver = "letsencrypt"
```

### 5. Scaling Workers

```bash
# Scale Celery workers
docker-compose up -d --scale worker=3

# Monitor queue
docker-compose exec worker celery -A app.tasks.main inspect active
```

---

### Option 2: Akash Network (Decentralized Cloud)

**Cost-effective, censorship-resistant deployment**

### 1. Build Container Images

```bash
# Build and push to registry
./scripts/build-for-akash.sh --username your-github-username

# Or use custom registry
./scripts/build-for-akash.sh --registry docker.io --username your-dockerhub-username
```

### 2. Configure for Akash

```bash
# Edit deployment configuration
vim akash/deploy.yaml

# Add your S3/R2 credentials:
env:
  - S3_ENDPOINT=https://your-account.r2.cloudflarestorage.com
  - S3_ACCESS_KEY=your-access-key
  - S3_SECRET_KEY=your-secret-key
```

### 3. Deploy to Akash

```bash
# Prerequisites: Install Akash CLI, create wallet, fund with AKT
# See AKASH-DEPLOYMENT.md for detailed setup

# Deploy
./scripts/deploy-to-akash.sh

# Monitor deployment
akash provider lease-status --dseq YOUR_DSEQ --provider PROVIDER --from default
```

### 4. Cost Comparison

| Deployment | Monthly Cost | Resources | Pros | Cons |
|------------|--------------|-----------|------|------|
| **Akash Standard** | $30-50 | 6 CPU, 14GB RAM | Decentralized, cheap | Learning curve |
| **Akash Small** | $10-20 | 2 CPU, 4GB RAM | Very cheap | Limited features |
| **AWS/GCP** | $100-200 | Similar specs | Familiar | Expensive |
| **VPS** | $50-80 | Similar specs | Simple | Single provider |

**💡 Detailed Akash guide: [AKASH-DEPLOYMENT.md](AKASH-DEPLOYMENT.md)**

## 🛠️ Development

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Start services (PostgreSQL + Redis)
docker-compose up postgres redis

# First run downloads models (~769MB for medium)
# Set smaller model for faster development:
export WHISPER_MODEL=small

# Run API locally
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run worker locally  
celery -A app.tasks.main worker --loglevel=info
```

### Code Quality

```bash
# Format code
black app/ tests/

# Lint code
ruff app/ tests/

# Type checking
mypy app/
```

### Database Management

```bash
# Connect to database
docker-compose exec postgres psql -U transcribe_user -d transcribe_db

# Backup database
docker-compose exec postgres pg_dump -U transcribe_user transcribe_db > backup.sql

# Reset database
docker-compose down -v && docker-compose up -d
```

## 📈 Performance Tuning

### Whisper Model Selection

| Model | Speed | Accuracy | Memory | Use Case |
|-------|-------|----------|---------|----------|
| `tiny` | Fastest | Lower | ~1GB | Development |
| `small` | Fast | Good | ~2GB | **Recommended** |
| `medium` | Medium | Better | ~5GB | High accuracy |
| `large` | Slow | Best | ~10GB | Maximum quality |

### Worker Optimization

```bash
# CPU-optimized settings for medium model + speaker diarization
export WHISPER_MODEL=medium
export ENABLE_DIARIZATION=true
export CELERY_CONCURRENCY=1  # Reduce for memory-intensive processing
export OMP_NUM_THREADS=1      # Prevent thread oversubscription

# For high-volume deployments, consider:
export WHISPER_MODEL=small    # Faster processing, less memory
export ENABLE_DIARIZATION=false  # Disable for speed
export CELERY_CONCURRENCY=2  # More parallel workers
```

### Memory Requirements

| Configuration | Memory Usage | Recommended RAM |
|---------------|--------------|-----------------|
| `small` + no diarization | ~2GB | 4GB+ |
| `medium` + no diarization | ~5GB | 8GB+ |
| `medium` + diarization | ~7GB | 12GB+ |
| `large` + diarization | ~12GB | 16GB+ |

### Redis Configuration

```redis
# Persistence for queue durability
appendonly yes
save 900 1

# Memory optimization
maxmemory-policy allkeys-lru
```

## 🔮 Future Enhancements

This service is designed to easily evolve from free-only to paid plans:

### Planned Features
- **User Accounts**: OAuth login (GitHub/Google)
- **Paid Plans**: Stripe integration ready
- **Premium Features**: Larger files, faster queue, longer retention
- **API Keys**: Machine-to-machine access
- **Webhooks**: Job completion notifications
- **Batch Processing**: Multiple file uploads

### Plan Structure (Future)
```python
# Already implemented interfaces:
class PlanProvider:
    def get_limits(self, plan: str) -> PlanLimits:
        # Returns daily minutes, file size, etc.

class QuotaService:
    def check_quota(self, identity: str, usage: Usage) -> bool:
        # Unified quota checking
```

## 🐛 Troubleshooting

### Common Issues

**"Job stuck in queue"**
```bash
# Check worker status
docker-compose logs worker

# Restart workers
docker-compose restart worker

# Check Redis queue
docker-compose exec redis redis-cli llen celery
```

**"Whisper model download failed"**
```bash
# Check internet connectivity
curl -I https://huggingface.co/guillaumekln/faster-whisper-medium

# Check disk space
df -h

# Clear model cache and retry
rm -rf ~/.cache/huggingface/hub/
docker-compose restart worker
```

**"Audio processing failed"**
```bash
# Check ffmpeg installation
docker-compose exec worker ffmpeg -version

# Check model loading
docker-compose exec worker python -c "
from faster_whisper import WhisperModel
model = WhisperModel('small', device='cpu', compute_type='int8')
print('Model loaded successfully')
"
```

**"Out of memory errors"**
```bash
# Use smaller model
export WHISPER_MODEL=small
export ENABLE_DIARIZATION=false

# Check available memory
docker stats

# Reduce worker concurrency
export CELERY_CONCURRENCY=1
```

**"Storage errors"**
```bash
# Check R2 credentials
docker-compose exec api python -c "from app.services.storage import StorageService; print(StorageService().health_check())"

# Check local storage permissions
docker-compose exec api ls -la /tmp/transcribe/
```

### Debug Mode

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG

# Enable SQL echo
export SQL_ECHO=true

# Disable rate limiting
export RATE_LIMIT_RATE=1000
```

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📧 Support

- **Documentation**: Check this README and inline code comments
- **Issues**: Open a GitHub issue for bugs or feature requests
- **Monitoring**: Check `/healthz` and `/metrics` endpoints
- **Logs**: Use `docker-compose logs` for debugging

---

**Built with ❤️ for the open source community**