# syntax=docker/dockerfile:1.4
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    WHISPER_CACHE_DIR=/models \
    STORAGE_ROOT=/storage \
    TEMP_DIR=/tmp/transcribe

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ffmpeg \
    libsndfile1 \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create application directories
RUN mkdir -p /app /models /storage/uploads /storage/results /data/postgresql && \
    groupadd -r app && useradd -r -g app app && \
    chown -R app:app /app /models /storage /data

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Pre-download whisper models (medium + small)
RUN python - <<'PY'
from faster_whisper import WhisperModel
for model_name in ["medium", "small"]:
    try:
        WhisperModel(model_name, device="cpu", compute_type="int8", download_root="/models")
    except Exception as exc:  # pragma: no cover
        print(f"Failed to pre-download {model_name}: {exc}")
PY

COPY . .

# Switch to non-root user
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD bash /app/health_check_script.sh --host http://127.0.0.1:8000 --timeout 5 || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
