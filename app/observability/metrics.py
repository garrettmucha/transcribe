"""
Prometheus metrics for observability.
"""

import os
from prometheus_client import Counter, Histogram, Gauge, Info

# Application info
APP_INFO = Info('app_info', 'Application information')

# Request metrics
REQUEST_COUNT = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status_code']
)

REQUEST_DURATION = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint']
)

# Job metrics
JOBS_TOTAL = Counter(
    'jobs_total',
    'Total jobs processed',
    ['status']
)

JOBS_ACTIVE = Gauge(
    'jobs_active',
    'Currently active jobs'
)

QUEUE_SIZE = Gauge(
    'queue_size',
    'Current queue size',
    ['queue_name']
)

QUEUE_WAIT_TIME = Histogram(
    'queue_wait_seconds',
    'Time jobs spend waiting in queue'
)

PROCESSING_TIME = Histogram(
    'processing_seconds',
    'Job processing time in seconds'
)

# Usage metrics
MINUTES_PROCESSED = Counter(
    'minutes_processed_total',
    'Total audio minutes processed'
)

BYTES_PROCESSED = Counter(
    'bytes_processed_total',
    'Total bytes processed'
)

FILES_PROCESSED = Counter(
    'files_processed_total',
    'Total files processed'
)

# Rate limiting metrics
RATELIMIT_REJECTIONS = Counter(
    'ratelimit_rejections_total',
    'Total rate limit rejections',
    ['limit_type']
)

ACTIVE_IDENTITIES = Gauge(
    'active_identities',
    'Number of active user identities'
)

# Storage metrics
STORAGE_OPERATIONS = Counter(
    'storage_operations_total',
    'Total storage operations',
    ['operation', 'status']
)

STORAGE_BYTES = Counter(
    'storage_bytes_total',
    'Total storage bytes transferred',
    ['direction']  # upload/download
)

# Audio processing metrics
AUDIO_DURATION_PROCESSED = Counter(
    'audio_duration_processed_seconds',
    'Total audio duration processed in seconds'
)

TRANSCRIPTION_ACCURACY = Histogram(
    'transcription_confidence',
    'Whisper transcription confidence scores'
)

MODEL_LOAD_TIME = Histogram(
    'model_load_seconds',
    'Time to load ML models'
)

# Error metrics
ERRORS_TOTAL = Counter(
    'errors_total',
    'Total errors',
    ['error_type', 'component']
)

# System metrics
MEMORY_USAGE = Gauge(
    'memory_usage_bytes',
    'Memory usage in bytes',
    ['type']  # resident, virtual
)

CPU_USAGE = Gauge(
    'cpu_usage_percent',
    'CPU usage percentage'
)

DISK_USAGE = Gauge(
    'disk_usage_bytes',
    'Disk usage in bytes',
    ['mount_point']
)

# Redis metrics
REDIS_CONNECTIONS = Gauge(
    'redis_connections',
    'Number of Redis connections'
)

REDIS_OPERATIONS = Counter(
    'redis_operations_total',
    'Total Redis operations',
    ['operation', 'status']
)

# Database metrics
DB_CONNECTIONS = Gauge(
    'database_connections',
    'Number of database connections'
)

DB_OPERATIONS = Counter(
    'database_operations_total',
    'Total database operations',
    ['operation', 'table', 'status']
)

DB_QUERY_DURATION = Histogram(
    'database_query_duration_seconds',
    'Database query duration',
    ['operation', 'table']
)


def setup_metrics():
    """Initialize metrics with application information."""
    APP_INFO.info({
        'version': '1.0.0',
        'service': 'transcribe-api',
        'environment': os.getenv('ENVIRONMENT', 'development')
    })


def record_request_metrics(method: str, endpoint: str, status_code: int, duration: float):
    """Record HTTP request metrics."""
    REQUEST_COUNT.labels(
        method=method,
        endpoint=endpoint,
        status_code=str(status_code)
    ).inc()
    
    REQUEST_DURATION.labels(
        method=method,
        endpoint=endpoint
    ).observe(duration)


def record_job_metrics(status: str, duration: float = None, queue_wait: float = None):
    """Record job processing metrics."""
    JOBS_TOTAL.labels(status=status).inc()
    
    if duration is not None:
        PROCESSING_TIME.observe(duration)
    
    if queue_wait is not None:
        QUEUE_WAIT_TIME.observe(queue_wait)


def record_usage_metrics(minutes: float, bytes_processed: int, files: int = 1):
    """Record usage metrics."""
    MINUTES_PROCESSED.inc(minutes)
    BYTES_PROCESSED.inc(bytes_processed)
    FILES_PROCESSED.inc(files)


def record_rate_limit_rejection(limit_type: str):
    """Record rate limit rejection."""
    RATELIMIT_REJECTIONS.labels(limit_type=limit_type).inc()


def record_storage_metrics(operation: str, status: str, bytes_transferred: int, direction: str):
    """Record storage operation metrics."""
    STORAGE_OPERATIONS.labels(operation=operation, status=status).inc()
    STORAGE_BYTES.labels(direction=direction).inc(bytes_transferred)


def record_audio_metrics(duration_seconds: float, confidence: float = None):
    """Record audio processing metrics."""
    AUDIO_DURATION_PROCESSED.inc(duration_seconds)
    
    if confidence is not None:
        TRANSCRIPTION_ACCURACY.observe(confidence)


def record_error_metrics(error_type: str, component: str):
    """Record error metrics."""
    ERRORS_TOTAL.labels(error_type=error_type, component=component).inc()


def record_model_load_time(duration: float):
    """Record ML model loading time."""
    MODEL_LOAD_TIME.observe(duration)


def update_system_metrics():
    """Update system resource metrics (call periodically)."""
    try:
        import psutil
        
        # Memory usage
        memory = psutil.virtual_memory()
        MEMORY_USAGE.labels(type='used').set(memory.used)
        MEMORY_USAGE.labels(type='available').set(memory.available)
        
        # CPU usage
        cpu_percent = psutil.cpu_percent(interval=1)
        CPU_USAGE.set(cpu_percent)
        
        # Disk usage
        disk = psutil.disk_usage('/')
        DISK_USAGE.labels(mount_point='/').set(disk.used)
        
    except ImportError:
        # psutil not available
        pass
    except Exception as e:
        record_error_metrics('system_metrics_update', 'metrics')


def update_redis_metrics():
    """Update Redis metrics (call periodically)."""
    try:
        import redis
        from app.security.ratelimit import redis_client
        
        # Get Redis info
        info = redis_client.info()
        
        REDIS_CONNECTIONS.set(info.get('connected_clients', 0))
        
    except Exception as e:
        record_error_metrics('redis_metrics_update', 'metrics')


def update_database_metrics():
    """Update database metrics (call periodically)."""
    try:
        # This would require database-specific monitoring
        # For now, we'll rely on application-level metrics
        pass
    except Exception as e:
        record_error_metrics('database_metrics_update', 'metrics')


def get_metrics_summary() -> dict:
    """Get a summary of key metrics for health checks."""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from prometheus_client.parser import text_string_to_metric_families
    
    try:
        # Generate metrics
        metrics_text = generate_latest().decode('utf-8')
        
        # Parse key metrics
        summary = {
            'total_requests': 0,
            'total_jobs': 0,
            'active_jobs': 0,
            'total_minutes_processed': 0,
            'total_errors': 0
        }
        
        for family in text_string_to_metric_families(metrics_text):
            if family.name == 'http_requests_total':
                summary['total_requests'] += sum(sample.value for sample in family.samples)
            elif family.name == 'jobs_total':
                summary['total_jobs'] += sum(sample.value for sample in family.samples)
            elif family.name == 'jobs_active':
                summary['active_jobs'] = sum(sample.value for sample in family.samples)
            elif family.name == 'minutes_processed_total':
                summary['total_minutes_processed'] = sum(sample.value for sample in family.samples)
            elif family.name == 'errors_total':
                summary['total_errors'] += sum(sample.value for sample in family.samples)
        
        return summary
        
    except Exception as e:
        record_error_metrics('metrics_summary', 'metrics')
        return {'error': str(e)}