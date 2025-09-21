# Akash CPU Transcription Service

A production-ready, CPU-only speech transcription SaaS designed to run natively on the [Akash Network](https://akash.network/).
The service exposes a FastAPI application and Celery worker in a single container image, supports speaker diarisation, topic
extraction and TextRank summaries, and enforces a free tier of **100 minutes per month** without requiring user accounts.

## Features

- ✅ **CPU-only Whisper** using `faster-whisper` with the `medium` model (automatic fallback to `small`).
- 🗣️ **Speaker diarisation** powered by `pyannote.audio` with WebVTT speaker labels.
- 🌍 **99 Whisper languages** with automatic detection or manual override.
- 📄 **Outputs per job**: transcript text, speaker-labelled VTT captions, TextRank summary, KeyBERT topics, diagnostics JSON.
- 🧮 **Usage enforcement**: 25 MB uploads, 20 minute duration limit, one concurrent job, 100 minutes/month identity quota.
- 🛡️ **Anonymous identities** built from IP + signed device cookie (HMAC) with Redis token bucket rate limiting.
- 📦 **Local storage only** – audio lives in `/storage`, models cached in `/models`, PostgreSQL data in `/data` persistent volume.
- 🔭 **Observability**: Prometheus metrics, structured JSON logging, optional OpenTelemetry tracing.
- 📈 **Scripts & tooling**: Makefile, Akash deployment manifest, build/deploy helper scripts.

## Architecture

```
Traefik (Ingress) ─────┐
                       │          ┌────────────┐        ┌─────────────┐
                       └────────▶ │ FastAPI API│ ─────▶ │  Celery     │
                                  │  (uvicorn) │        │   Worker    │
                                  └────────────┘        └─────────────┘
                                          │                    │
                                          ▼                    ▼
                                  ┌────────────┐        ┌─────────────┐
                                  │ PostgreSQL │        │   Redis     │
                                  └────────────┘        └─────────────┘
                                          │
                                          ▼
                                  ┌────────────┐
                                  │  /storage  │ (uploads & results)
                                  └────────────┘
```

Both API and worker run from the same container image. Persistent volumes mounted on Akash:

- `/storage` (100 GiB) – uploaded audio, generated results, diagnostics.
- `/models` (20 GiB) – cached Whisper models downloaded during image build.
- `/data` (50 GiB) – PostgreSQL database data directory.

## Free Tier Guardrails

| Limit | Value |
| ----- | ----- |
| Monthly quota | 100 audio minutes per IP/device identity |
| File size | 25 MB max |
| Duration per file | 20 minutes |
| Concurrent jobs | 1 |
| File retention | 30 days (cron cleanup) |
| Rate limit | 10 requests/minute burst (Redis token bucket) |

## Local Development

```bash
python -m venv .venv && source .venv/bin/activate
make install
cp .env.example .env  # adjust values as needed

# Start API
make api
# In another terminal start Celery worker
make worker

# Run the test-suite
make test
```

The API serves a browser UI at `http://localhost:8000/` with drag-and-drop upload, progress polling, and download links for
result artefacts.

## Celery Worker Commands

The same container image can be used for both API and worker:

```bash
# API
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Worker
celery -A celery_main:celery_app worker --loglevel=info
```

## Building for Akash

```bash
# Build image and render akash/deploy.yaml
PUSH_IMAGE=true ./scripts/build-for-akash.sh ghcr.io/<user>/transcribe-akash:latest

# Deploy (requires akash CLI configuration)
PROVIDER=<provider-address> ./scripts/deploy-to-akash.sh
```

The generated manifest provisions PostgreSQL, Redis, the API container, a Celery worker, and a Traefik ingress with public
port 80. Update environment variables in `deploy.yaml` or the rendered manifest as needed (e.g. `HUGGINGFACE_TOKEN`).

## REST API

- `POST /api/v1/transcribe` – upload audio file (`multipart/form-data`), optional `lang`, `diarize`, `topics` fields.
- `GET /api/v1/jobs/{job_id}` – job status plus signed URLs (served locally via `/storage/...`).
- `GET /api/v1/usage` – monthly usage summary for current identity.
- `GET /metrics` – Prometheus metrics (enabled by default).
- `GET /healthz` – readiness probe for Akash/Traefik.

## Storage Layout

```
/storage
├── uploads/<job_id>/<original_file>
└── results/<job_id>/
    ├── transcript.txt
    ├── captions.vtt
    ├── summary.txt
    ├── topics.json
    └── diagnostics.json
```

Signed URLs returned by the API map to `/storage/...` and are served directly by FastAPI's static file mount.

## Security & Identity

- Identity = IP address + signed device cookie (HMAC). Cookie secret configurable via `COOKIE_SIGNING_KEY`.
- Redis token bucket provides 10 req/min burst throttling; single active job enforced with Redis semaphore.
- Monthly usage stored in PostgreSQL (`usage_monthly` table) to enforce 100 minute quota.
- IP blocklist supported via database table (`ip_blocklist`).

## Monitoring

- `GET /metrics` – Prometheus scraping endpoint.
- Structured logging via `structlog` (JSON by default) ready for shipping to Loki/ELK.
- Optional OpenTelemetry tracing (Jaeger exporter) configurable with environment variables.
- Health checks executed by the bundled `health_check_script.sh` and Traefik router.

## Scripts

- `scripts/build-for-akash.sh [IMAGE]` – build/push container and generate `akash/deploy.yaml` manifest.
- `scripts/deploy-to-akash.sh [MANIFEST]` – helper shell for Akash CLI deployment & lease creation.
- `health_check_script.sh` – curl-based multi-endpoint health probe used by container `HEALTHCHECK`.

## License

This project is provided as-is for Akash Network deployments. Review and harden before production use (e.g. add TLS, backup
strategies, observability exporters, and paywall integration for usage beyond the free tier).
