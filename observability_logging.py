"""
Structured logging configuration.
"""

import os
import sys
import logging
import json
from datetime import datetime
from typing import Dict, Any

import structlog


class JSONFormatter(logging.Formatter):
    """Custom JSON formatter for structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_entry = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)
        
        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in {
                'name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
                'filename', 'module', 'exc_info', 'exc_text', 'stack_info',
                'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
                'thread', 'threadName', 'processName', 'process', 'getMessage'
            }:
                log_entry[key] = value
        
        return json.dumps(log_entry, default=str)


def setup_logging():
    """Setup structured logging configuration."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    use_json = os.getenv("LOG_FORMAT", "json").lower() == "json"
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer() if not use_json else structlog.processors.JSONRenderer()
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level)
        ),
        logger_factory=structlog.WriteLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level))
    
    # Remove default handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Add custom handler
    handler = logging.StreamHandler(sys.stdout)
    
    if use_json:
        handler.setFormatter(JSONFormatter())
    else:
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
    
    root_logger.addHandler(handler)
    
    # Configure specific loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    
    # Celery logging
    if use_json:
        from celery.signals import setup_logging as celery_setup_logging
        
        @celery_setup_logging.connect
        def config_loggers(*args, **kwargs):
            """Configure Celery logging to use our JSON formatter."""
            celery_logger = logging.getLogger('celery')
            celery_logger.setLevel(getattr(logging, log_level))
            
            # Remove existing handlers
            for handler in celery_logger.handlers[:]:
                celery_logger.removeHandler(handler)
            
            # Add JSON handler
            celery_handler = logging.StreamHandler(sys.stdout)
            celery_handler.setFormatter(JSONFormatter())
            celery_logger.addHandler(celery_handler)


def get_logger(name: str = None) -> structlog.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name)


class LogContext:
    """Context manager for adding structured logging context."""
    
    def __init__(self, **kwargs):
        self.context = kwargs
    
    def __enter__(self):
        structlog.contextvars.clear_contextvars()
        for key, value in self.context.items():
            structlog.contextvars.bind_contextvars(**{key: value})
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        structlog.contextvars.clear_contextvars()


def log_request(request_id: str, method: str, path: str, **kwargs):
    """Log HTTP request with context."""
    logger = get_logger("http")
    with LogContext(request_id=request_id):
        logger.info(
            "HTTP request",
            method=method,
            path=path,
            **kwargs
        )


def log_job_event(job_id: str, event: str, **kwargs):
    """Log job processing event with context."""
    logger = get_logger("jobs")
    with LogContext(job_id=job_id):
        logger.info(
            f"Job {event}",
            event=event,
            **kwargs
        )


def log_error(error: Exception, context: Dict[str, Any] = None):
    """Log error with context and stack trace."""
    logger = get_logger("errors")
    
    error_context = {
        'error_type': type(error).__name__,
        'error_message': str(error)
    }
    
    if context:
        error_context.update(context)
    
    logger.error(
        "Error occurred",
        **error_context,
        exc_info=True
    )


def log_performance(operation: str, duration: float, **kwargs):
    """Log performance metrics."""
    logger = get_logger("performance")
    logger.info(
        f"Performance: {operation}",
        operation=operation,
        duration_seconds=duration,
        **kwargs
    )


def log_security_event(event_type: str, **kwargs):
    """Log security-related events."""
    logger = get_logger("security")
    logger.warning(
        f"Security event: {event_type}",
        event_type=event_type,
        **kwargs
    )