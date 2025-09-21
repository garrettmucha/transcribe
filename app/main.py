"""Main FastAPI application for the Akash-native transcription service."""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.routes import router
from app.models import create_tables
from app.observability.logging import get_logger, setup_logging
from app.observability.metrics import REQUEST_COUNT, REQUEST_DURATION, setup_metrics
from app.observability.tracing import setup_tracing
from app.security import identity as identity_service
from app.security import ratelimit as ratelimit_service
from app.services import storage as storage_service

# Backwards-compatible aliases for test patches and dependency overrides
get_or_create_identity = identity_service.get_or_create_identity
is_ip_blocked = identity_service.is_ip_blocked

# Initialise logging and metrics as early as possible
setup_logging()
setup_metrics()

logger = get_logger(__name__)

STORAGE_ROOT = Path(os.getenv("STORAGE_ROOT", "/storage"))
UPLOAD_ROOT = STORAGE_ROOT / "uploads"
RESULT_ROOT = STORAGE_ROOT / "results"

# Ensure base directory exists prior to mounting static files
STORAGE_ROOT.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """FastAPI lifespan manager used by Akash deployments."""

    logger.info("Starting transcription service")

    # Ensure local storage directories exist
    for folder in (STORAGE_ROOT, UPLOAD_ROOT, RESULT_ROOT):
        folder.mkdir(parents=True, exist_ok=True)
        logger.debug("Ensured storage directory exists", directory=str(folder))

    # Initialise database schema
    await create_tables()

    # Pre-load spaCy model if available (best effort only)
    try:
        import spacy  # type: ignore

        try:
            spacy.load("en_core_web_sm")
        except OSError:
            logger.info("Downloading spaCy model en_core_web_sm for text processing")
            os.system("python -m spacy download en_core_web_sm")
    except Exception as exc:  # pragma: no cover - advisory only
        logger.warning("Unable to prepare spaCy model", error=str(exc))

    # Configure tracing after application and dependencies exist
    setup_tracing(app=application)

    logger.info("Service initialised successfully")
    yield
    logger.info("Transcription service shutting down")


app = FastAPI(
    title="Akash Whisper Transcription",
    description="CPU-only transcription, diarisation, and summarisation platform",
    version="1.0.0",
    lifespan=lifespan,
)

# Allow browser clients while keeping configuration simple for Akash
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve output files directly from persistent storage
if STORAGE_ROOT.exists():
    app.mount("/storage", StaticFiles(directory=STORAGE_ROOT), name="storage")


async def _maybe_await(value):
    """Await value if it is a coroutine, otherwise return it directly."""

    if asyncio.iscoroutine(value):
        return await value
    return value


@app.middleware("http")
async def identity_and_metrics_middleware(request: Request, call_next):
    """Resolve user identity, enforce rate limits, and capture metrics."""

    start_time = time.time()

    # Skip instrumentation for health/metrics endpoints
    if request.url.path in {"/healthz", "/metrics"}:
        return await call_next(request)

    try:
        client_ip = request.client.host if request.client else "unknown"

        if await _maybe_await(is_ip_blocked(client_ip)):
            REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path, status_code="403").inc()
            raise HTTPException(status_code=403, detail="IP address is blocked")

        identity_id = await _maybe_await(get_or_create_identity(request))
        request.state.identity_id = identity_id

        if request.url.path.startswith("/api/"):
            allowed, remaining = await _maybe_await(
                ratelimit_service.check_rate_limit(identity_id)
            )
            if not allowed:
                REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path, status_code="429").inc()
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded",
                    headers={"X-RateLimit-Remaining": str(remaining)},
                )
            request.state.rate_limit_remaining = remaining

        response = await call_next(request)

        # Persist identity cookie if one was generated during the request
        cookie_value = getattr(request.state, "set_device_cookie", None)
        if cookie_value:
            response.set_cookie(
                identity_service.COOKIE_NAME,
                cookie_value,
                max_age=identity_service.COOKIE_MAX_AGE,
                httponly=True,
                secure=os.getenv("COOKIE_SECURE", "true").lower() == "true",
                samesite=os.getenv("COOKIE_SAMESITE", "lax"),
            )

        remaining_header = getattr(request.state, "rate_limit_remaining", None)
        if remaining_header is not None and request.url.path.startswith("/api/"):
            response.headers["X-RateLimit-Remaining"] = str(remaining_header)

        duration = time.time() - start_time
        REQUEST_DURATION.labels(method=request.method, endpoint=request.url.path).observe(duration)
        REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path, status_code=str(response.status_code)).inc()
        return response

    except HTTPException as exc:
        duration = time.time() - start_time
        REQUEST_DURATION.labels(method=request.method, endpoint=request.url.path).observe(duration)

        status_code = exc.status_code
        REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path, status_code=str(status_code)).inc()

        if isinstance(exc.detail, dict):
            content = exc.detail
        else:
            content = {"detail": exc.detail}

        response = JSONResponse(status_code=status_code, content=content)

        if exc.headers:
            for header, value in exc.headers.items():
                response.headers[header] = value

        cookie_value = getattr(request.state, "set_device_cookie", None)
        if cookie_value:
            response.set_cookie(
                identity_service.COOKIE_NAME,
                cookie_value,
                max_age=identity_service.COOKIE_MAX_AGE,
                httponly=True,
                secure=os.getenv("COOKIE_SECURE", "true").lower() == "true",
                samesite=os.getenv("COOKIE_SAMESITE", "lax"),
            )

        remaining_header = getattr(request.state, "rate_limit_remaining", None)
        if remaining_header is not None and request.url.path.startswith("/api/"):
            response.headers["X-RateLimit-Remaining"] = str(remaining_header)

        return response
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Unhandled request error", error=str(exc))
        duration = time.time() - start_time
        REQUEST_DURATION.labels(method=request.method, endpoint=request.url.path).observe(duration)
        REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path, status_code="500").inc()

        response = JSONResponse(status_code=500, content={"detail": "Internal server error"})

        cookie_value = getattr(request.state, "set_device_cookie", None)
        if cookie_value:
            response.set_cookie(
                identity_service.COOKIE_NAME,
                cookie_value,
                max_age=identity_service.COOKIE_MAX_AGE,
                httponly=True,
                secure=os.getenv("COOKIE_SECURE", "true").lower() == "true",
                samesite=os.getenv("COOKIE_SAMESITE", "lax"),
            )

        return response


# Register API routes under /api/v1
app.include_router(router, prefix="/api/v1")


@app.get("/healthz")
async def health_check() -> dict[str, Any]:
    """Simple health check used by Akash and Traefik."""

    storage = storage_service.StorageService()
    storage_health = await storage.health_check()
    return {
        "status": "healthy" if storage_health.get("status") == "healthy" else "degraded",
        "storage": storage_health,
        "version": app.version,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/metrics")
async def metrics() -> Response:
    """Expose Prometheus metrics."""

    if os.getenv("PROMETHEUS_ENABLE", "true").lower() != "true":
        raise HTTPException(status_code=404, detail="Metrics disabled")

    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/", response_class=HTMLResponse)
async def web_landing() -> HTMLResponse:
    """Minimal web UI for uploading audio files."""

    html_content = """
    <!DOCTYPE html>
    <html lang=\"en\">
    <head>
        <meta charset=\"utf-8\">
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
        <title>Akash CPU Transcription</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 0 auto; max-width: 880px; padding: 24px; background: #f6f7fb; }}
            h1 {{ margin-bottom: 0.4rem; }}
            .card {{ background: white; border-radius: 10px; padding: 24px; box-shadow: 0 10px 30px rgba(0,0,0,0.05); margin-top: 18px; }}
            label {{ font-weight: 600; display: block; margin-bottom: 8px; }}
            input[type=\"file\"], select {{ width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 6px; }}
            button {{ background: #0066ff; color: white; padding: 12px 28px; border: 0; border-radius: 6px; font-size: 16px; cursor: pointer; }}
            button:disabled {{ background: #9ab6ff; cursor: not-allowed; }}
            .usage {{ margin-top: 12px; font-size: 14px; color: #555; }}
            .results a {{ display: block; margin: 10px 0; color: white; background: #1f8b4c; padding: 10px; border-radius: 6px; text-decoration: none; }}
            .limits ul {{ padding-left: 20px; }}
            .limits li {{ margin-bottom: 6px; }}
        </style>
    </head>
    <body>
        <h1>Audio Transcription Service on Akash ⚡️</h1>
        <p>Transcribe audio in 99 languages with diarisation and summaries. No account or API key required.</p>
        <div class=\"card limits\">
            <h2>Free Tier Guardrails</h2>
            <ul>
                <li><strong>100 minutes</strong> of audio transcription each month</li>
                <li><strong>25&nbsp;MB</strong> maximum upload size per file</li>
                <li><strong>20 minutes</strong> maximum duration per upload</li>
                <li><strong>1 concurrent job</strong> per device/IP identity</li>
                <li>Files stored locally for <strong>30 days</strong> then purged</li>
            </ul>
        </div>
        <div class=\"card\">
            <form id=\"uploadForm\" enctype=\"multipart/form-data\">
                <label for=\"file\">Select audio file</label>
                <input id=\"file\" name=\"file\" type=\"file\" accept=\"audio/*,video/mp4\" required>
                <label for=\"lang\">Language (optional)</label>
                <select id=\"lang\" name=\"lang\">
                    <option value=\"\">Auto detect</option>
                    <option value=\"en\">English</option>
                    <option value=\"es\">Spanish</option>
                    <option value=\"fr\">French</option>
                    <option value=\"de\">German</option>
                    <option value=\"pt\">Portuguese</option>
                    <option value=\"hi\">Hindi</option>
                    <option value=\"zh\">Chinese</option>
                    <option value=\"ar\">Arabic</option>
                    <option value=\"ru\">Russian</option>
                </select>
                <label><input type=\"checkbox\" id=\"diarize\" name=\"diarize\" checked> Speaker diarisation</label>
                <label><input type=\"checkbox\" id=\"topics\" name=\"topics\" checked> Summaries &amp; topics</label>
                <div class=\"usage\" id=\"usage-info\">Loading usage…</div>
                <button type=\"submit\">Start transcription</button>
            </form>
            <div class=\"usage\" id=\"status-box\" style=\"display:none\"></div>
            <div class=\"results\" id=\"results\" style=\"display:none\"></div>
        </div>
        <script>
        const form = document.getElementById('uploadForm');
        const statusBox = document.getElementById('status-box');
        const resultsBox = document.getElementById('results');
        const usageInfo = document.getElementById('usage-info');
        let currentJob = null;
        let pollTimer = null;

        async function refreshUsage() {{
            try {{
                const response = await fetch('/api/v1/usage');
                const usage = await response.json();
                usageInfo.textContent = `Month usage: ${usage.this_month.minutes_used.toFixed(1)} / ${usage.monthly_limit_minutes} minutes`;
            }} catch (err) {{
                usageInfo.textContent = 'Unable to load usage data';
            }}
        }}

        form.addEventListener('submit', async (event) => {{
            event.preventDefault();
            if (pollTimer) {{ clearInterval(pollTimer); pollTimer = null; }}
            statusBox.style.display = 'block';
            statusBox.textContent = 'Uploading…';
            resultsBox.style.display = 'none';
            resultsBox.innerHTML = '';

            const formData = new FormData();
            const file = document.getElementById('file').files[0];
            if (!file) {{ alert('Please choose a file.'); return; }}
            formData.append('file', file);
            formData.append('lang', document.getElementById('lang').value);
            formData.append('diarize', document.getElementById('diarize').checked);
            formData.append('topics', document.getElementById('topics').checked);

            const response = await fetch('/api/v1/transcribe', {{ method: 'POST', body: formData }});
            const payload = await response.json();
            if (!response.ok) {{
                statusBox.textContent = payload.detail || 'Request rejected';
                return;
            }}
            currentJob = payload.job_id;
            statusBox.textContent = `Queued: ${currentJob}`;
            pollTimer = setInterval(checkStatus, 2500);
        }});

        async function checkStatus() {{
            if (!currentJob) return;
            const response = await fetch(`/api/v1/jobs/${currentJob}`);
            const payload = await response.json();
            if (payload.status === 'succeeded') {{
                clearInterval(pollTimer);
                pollTimer = null;
                statusBox.textContent = 'Finished!';
                resultsBox.style.display = 'block';
                resultsBox.innerHTML = '';
                Object.entries(payload.outputs || {{}}).forEach(([label, url]) => {{
                    const link = document.createElement('a');
                    link.href = url;
                    link.textContent = `Download ${label}`;
                    link.target = '_blank';
                    resultsBox.appendChild(link);
                }});
                refreshUsage();
            }} else if (payload.status === 'failed') {{
                clearInterval(pollTimer);
                pollTimer = null;
                statusBox.textContent = payload.error || 'Processing failed';
            }} else {{
                statusBox.textContent = `Status: ${payload.status}`;
            }}
        }}

        refreshUsage();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


if __name__ == "__main__":  # pragma: no cover - manual start helper
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
