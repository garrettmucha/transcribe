"""
Main FastAPI application for the transcription service.
"""

import os
import time
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app.routes import router
from app.models import create_tables
from app.security.identity import get_or_create_identity, is_ip_blocked
from app.security.ratelimit import check_rate_limit
from app.observability.logging import setup_logging, get_logger
from app.observability.metrics import setup_metrics, REQUEST_COUNT, REQUEST_DURATION

# Setup logging
setup_logging()
logger = get_logger(__name__)

# Setup Prometheus metrics
setup_metrics()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting transcription service...")
    
    # Create database tables
    await create_tables()
    
    # Download spaCy model if needed
    try:
        import spacy
        try:
            spacy.load("en_core_web_sm")
        except OSError:
            logger.info("Downloading spaCy model...")
            os.system("python -m spacy download en_core_web_sm")
    except Exception as e:
        logger.warning(f"Could not setup spaCy model: {e}")
    
    logger.info("Service started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down transcription service...")


app = FastAPI(
    title="Audio Transcription Service",
    description="CPU-only audio transcription and summarization service",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    """Global request middleware for identity, rate limiting, and metrics."""
    start_time = time.time()
    
    # Skip middleware for certain paths
    if request.url.path in ["/healthz", "/metrics", "/docs", "/openapi.json"]:
        response = await call_next(request)
        return response
    
    try:
        # Check IP blocklist
        client_ip = request.client.host
        if await is_ip_blocked(client_ip):
            REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path, status_code="403").inc()
            raise HTTPException(status_code=403, detail="IP address is blocked")
        
        # Get or create identity
        identity_id = await get_or_create_identity(request)
        
        # Check rate limits for API endpoints
        if request.url.path.startswith("/api/"):
            rate_limit_ok, remaining = await check_rate_limit(identity_id)
            if not rate_limit_ok:
                REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path, status_code="429").inc()
                raise HTTPException(
                    status_code=429, 
                    detail="Rate limit exceeded",
                    headers={"X-RateLimit-Remaining": str(remaining)}
                )
        
        # Add identity to request state
        request.state.identity_id = identity_id
        
        # Process request
        response = await call_next(request)
        
        # Record metrics
        duration = time.time() - start_time
        REQUEST_DURATION.labels(method=request.method, endpoint=request.url.path).observe(duration)
        REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path, status_code=str(response.status_code)).inc()
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Request middleware error: {e}")
        duration = time.time() - start_time
        REQUEST_DURATION.labels(method=request.method, endpoint=request.url.path).observe(duration)
        REQUEST_COUNT.labels(method=request.method, endpoint=request.url.path, status_code="500").inc()
        raise HTTPException(status_code=500, detail="Internal server error")


# Include API routes
app.include_router(router, prefix="/api/v1")


@app.get("/healthz")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": time.time()}


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    if not os.getenv("PROMETHEUS_ENABLE", "true").lower() == "true":
        raise HTTPException(status_code=404, detail="Metrics disabled")
    
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/", response_class=HTMLResponse)
async def landing_page():
    """Simple landing page with upload form."""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Audio Transcription Service</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
            .container { background: #f5f5f5; padding: 20px; border-radius: 8px; margin: 20px 0; }
            .upload-form { background: white; padding: 20px; border-radius: 8px; }
            .form-group { margin: 15px 0; }
            label { display: block; margin-bottom: 5px; font-weight: bold; }
            input, select, button { padding: 10px; margin: 5px 0; border: 1px solid #ddd; border-radius: 4px; }
            input[type="file"] { width: 100%; }
            button { background: #007bff; color: white; border: none; cursor: pointer; padding: 12px 24px; }
            button:hover { background: #0056b3; }
            .info-box { background: #e7f3ff; padding: 15px; border-left: 4px solid #007bff; margin: 20px 0; }
            .limits { background: #fff3cd; padding: 15px; border-left: 4px solid #ffc107; margin: 20px 0; }
            #usage-info { margin: 10px 0; padding: 10px; background: #f8f9fa; border-radius: 4px; }
            #progress { display: none; margin: 20px 0; }
            #results { display: none; margin: 20px 0; }
        </style>
    </head>
    <body>
        <h1>🎵 Audio Transcription Service</h1>
        
        <div class="info-box">
            <h3>Free CPU-Only Transcription</h3>
            <p>Upload audio files to get accurate transcriptions, captions, summaries, and topic extraction. 
            Processing is done entirely on our servers with no third-party AI APIs.</p>
        </div>
        
        <div class="limits">
            <h3>Free Plan Limits</h3>
            <ul>
                <li><strong>10 minutes per day</strong> total audio processing</li>
                <li><strong>15 minutes maximum</strong> per file</li>
                <li><strong>50 MB maximum</strong> file size</li>
                <li><strong>1 concurrent job</strong> at a time</li>
                <li><strong>Files auto-delete</strong> after 7 days</li>
            </ul>
        </div>
        
        <div id="usage-info">
            <strong>Today's Usage:</strong> <span id="usage-text">Loading...</span>
        </div>
        
        <div class="upload-form">
            <h3>Upload Audio File</h3>
            <form id="uploadForm" enctype="multipart/form-data">
                <div class="form-group">
                    <label for="file">Audio File:</label>
                    <input type="file" id="file" name="file" required accept="audio/*,video/mp4">
                    <small>Supported: MP3, WAV, FLAC, AAC, OGG, WebM, MP4</small>
                </div>
                
                <div class="form-group">
                    <label for="lang">Language (optional):</label>
                    <select id="lang" name="lang">
                        <option value="">Auto-detect</option>
                        <option value="en">English</option>
                        <option value="es">Spanish</option>
                        <option value="fr">French</option>
                        <option value="de">German</option>
                        <option value="it">Italian</option>
                        <option value="pt">Portuguese</option>
                        <option value="ru">Russian</option>
                        <option value="ja">Japanese</option>
                        <option value="ko">Korean</option>
                        <option value="zh">Chinese</option>
                    </select>
                </div>
                
                <div class="form-group">
                    <label>
                        <input type="checkbox" id="diarize" name="diarize" checked> 
                        <strong>Speaker identification</strong> (identify and label different speakers)
                    </label>
                </div>
                
                <div class="form-group">
                    <label>
                        <input type="checkbox" id="topics" name="topics" checked> 
                        Extract topics and generate summary
                    </label>
                </div>
                
                <button type="submit">Start Transcription</button>
            </form>
        </div>
        
        <div id="progress">
            <h3>Processing...</h3>
            <p>Status: <span id="status">Queued</span></p>
            <p>Job ID: <span id="jobId"></span></p>
            <button onclick="checkStatus()">Refresh Status</button>
        </div>
        
        <div id="results">
            <h3>Results Ready!</h3>
            <div id="download-links"></div>
        </div>

        <script>
            let currentJobId = null;
            let statusInterval = null;
            
            // Load usage on page load
            window.onload = function() {
                loadUsage();
            };
            
            async function loadUsage() {
                try {
                    const response = await fetch('/api/v1/usage');
                    const data = await response.json();
                    const remaining = data.daily_limit_minutes - data.today.minutes_used;
                    document.getElementById('usage-text').textContent = 
                        `${data.today.minutes_used}/${data.daily_limit_minutes} minutes used (${remaining} remaining)`;
                } catch (error) {
                    document.getElementById('usage-text').textContent = 'Unable to load usage data';
                }
            }
            
            document.getElementById('uploadForm').addEventListener('submit', async function(e) {
                e.preventDefault();
                
                const formData = new FormData();
                const fileInput = document.getElementById('file');
                const file = fileInput.files[0];
                
                if (!file) {
                    alert('Please select a file');
                    return;
                }
                
                formData.append('file', file);
                formData.append('lang', document.getElementById('lang').value);
                formData.append('diarize', document.getElementById('diarize').checked);
                formData.append('topics', document.getElementById('topics').checked);
                
                try {
                    const response = await fetch('/api/v1/transcribe', {
                        method: 'POST',
                        body: formData
                    });
                    
                    const data = await response.json();
                    
                    if (!response.ok) {
                        alert(`Error: ${data.detail}`);
                        return;
                    }
                    
                    currentJobId = data.job_id;
                    document.getElementById('jobId').textContent = currentJobId;
                    document.getElementById('status').textContent = data.status;
                    
                    document.querySelector('.upload-form').style.display = 'none';
                    document.getElementById('progress').style.display = 'block';
                    
                    // Start polling for status
                    statusInterval = setInterval(checkStatus, 2000);
                    
                } catch (error) {
                    alert(`Upload failed: ${error.message}`);
                }
            });
            
            async function checkStatus() {
                if (!currentJobId) return;
                
                try {
                    const response = await fetch(`/api/v1/jobs/${currentJobId}`);
                    const data = await response.json();
                    
                    document.getElementById('status').textContent = data.status;
                    
                    if (data.status === 'succeeded') {
                        clearInterval(statusInterval);
                        showResults(data);
                    } else if (data.status === 'failed') {
                        clearInterval(statusInterval);
                        alert(`Job failed: ${data.error || 'Unknown error'}`);
                        resetForm();
                    }
                } catch (error) {
                    console.error('Status check failed:', error);
                }
            }
            
            function showResults(data) {
                document.getElementById('progress').style.display = 'none';
                document.getElementById('results').style.display = 'block';
                
                const linksDiv = document.getElementById('download-links');
                linksDiv.innerHTML = '';
                
                if (data.outputs) {
                    Object.entries(data.outputs).forEach(([key, url]) => {
                        const link = document.createElement('a');
                        link.href = url;
                        link.textContent = `Download ${key}`;
                        link.style.display = 'block';
                        link.style.margin = '10px 0';
                        link.style.padding = '10px';
                        link.style.background = '#007bff';
                        link.style.color = 'white';
                        link.style.textDecoration = 'none';
                        link.style.borderRadius = '4px';
                        linksDiv.appendChild(link);
                    });
                }
                
                // Refresh usage
                loadUsage();
                
                // Add reset button
                const resetBtn = document.createElement('button');
                resetBtn.textContent = 'Process Another File';
                resetBtn.onclick = resetForm;
                linksDiv.appendChild(resetBtn);
            }
            
            function resetForm() {
                currentJobId = null;
                if (statusInterval) {
                    clearInterval(statusInterval);
                    statusInterval = null;
                }
                document.querySelector('.upload-form').style.display = 'block';
                document.getElementById('progress').style.display = 'none';
                document.getElementById('results').style.display = 'none';
                document.getElementById('uploadForm').reset();
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)