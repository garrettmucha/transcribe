"""
OpenTelemetry tracing configuration.
"""

import os
from contextlib import contextmanager
from typing import Dict, Any, Optional

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor

from app.observability.logging import get_logger

logger = get_logger(__name__)

# Global tracer
tracer = None


def setup_tracing(app=None):
    """Setup OpenTelemetry tracing."""
    global tracer
    
    try:
        # Check if tracing is enabled
        if not os.getenv("TRACING_ENABLED", "false").lower() == "true":
            logger.info("Tracing disabled")
            return
        
        # Configure tracer provider
        trace.set_tracer_provider(TracerProvider())
        tracer = trace.get_tracer(__name__)
        
        # Setup exporters
        _setup_exporters()
        
        # Setup instrumentations
        if app:
            _setup_instrumentations(app)
        
        logger.info("Tracing configured successfully")
        
    except Exception as e:
        logger.error(f"Failed to setup tracing: {e}")


def _setup_exporters():
    """Setup trace exporters."""
    try:
        tracer_provider = trace.get_tracer_provider()
        
        # Console exporter for development
        if os.getenv("ENVIRONMENT", "development") == "development":
            console_exporter = ConsoleSpanExporter()
            span_processor = BatchSpanProcessor(console_exporter)
            tracer_provider.add_span_processor(span_processor)
        
        # Jaeger exporter for production
        jaeger_endpoint = os.getenv("JAEGER_ENDPOINT")
        if jaeger_endpoint:
            jaeger_exporter = JaegerExporter(
                agent_host_name=os.getenv("JAEGER_AGENT_HOST", "localhost"),
                agent_port=int(os.getenv("JAEGER_AGENT_PORT", "6831")),
                collector_endpoint=jaeger_endpoint,
            )
            span_processor = BatchSpanProcessor(jaeger_exporter)
            tracer_provider.add_span_processor(span_processor)
            
            logger.info(f"Jaeger tracing configured: {jaeger_endpoint}")
        
    except Exception as e:
        logger.error(f"Failed to setup trace exporters: {e}")


def _setup_instrumentations(app):
    """Setup automatic instrumentations."""
    try:
        # FastAPI instrumentation
        FastAPIInstrumentor.instrument_app(app)
        
        # HTTP requests instrumentation
        RequestsInstrumentor().instrument()
        
        # SQLAlchemy instrumentation
        SQLAlchemyInstrumentor().instrument()
        
        # Redis instrumentation
        RedisInstrumentor().instrument()
        
        logger.info("Automatic instrumentations configured")
        
    except Exception as e:
        logger.error(f"Failed to setup instrumentations: {e}")


@contextmanager
def trace_span(name: str, attributes: Optional[Dict[str, Any]] = None):
    """Context manager for creating traced spans."""
    if not tracer:
        yield None
        return
    
    try:
        with tracer.start_as_current_span(name) as span:
            if attributes:
                for key, value in attributes.items():
                    span.set_attribute(key, str(value))
            yield span
    except Exception as e:
        logger.error(f"Tracing span error: {e}")
        yield None


def trace_job_processing(job_id: str):
    """Decorator for tracing job processing."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            with trace_span(
                f"job.process",
                attributes={
                    "job.id": job_id,
                    "job.function": func.__name__
                }
            ) as span:
                try:
                    result = func(*args, **kwargs)
                    if span:
                        span.set_attribute("job.status", "success")
                    return result
                except Exception as e:
                    if span:
                        span.set_attribute("job.status", "error")
                        span.set_attribute("job.error", str(e))
                    raise
        return wrapper
    return decorator


def trace_storage_operation(operation: str, key: str):
    """Decorator for tracing storage operations."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            with trace_span(
                f"storage.{operation}",
                attributes={
                    "storage.operation": operation,
                    "storage.key": key
                }
            ) as span:
                try:
                    result = await func(*args, **kwargs)
                    if span:
                        span.set_attribute("storage.status", "success")
                        if hasattr(result, '__len__'):
                            span.set_attribute("storage.size", len(result))
                    return result
                except Exception as e:
                    if span:
                        span.set_attribute("storage.status", "error")
                        span.set_attribute("storage.error", str(e))
                    raise
        return wrapper
    return decorator


def trace_audio_processing(filename: str):
    """Decorator for tracing audio processing."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            with trace_span(
                "audio.process",
                attributes={
                    "audio.filename": filename,
                    "audio.function": func.__name__
                }
            ) as span:
                try:
                    result = await func(*args, **kwargs)
                    if span:
                        span.set_attribute("audio.status", "success")
                        if isinstance(result, tuple) and len(result) >= 3:
                            # Assume result is (transcript, vtt, duration, ...)
                            span.set_attribute("audio.duration", str(result[2]))
                            span.set_attribute("audio.transcript_length", len(result[0]))
                    return result
                except Exception as e:
                    if span:
                        span.set_attribute("audio.status", "error")
                        span.set_attribute("audio.error", str(e))
                    raise
        return wrapper
    return decorator


def trace_database_operation(table: str, operation: str):
    """Decorator for tracing database operations."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            with trace_span(
                f"db.{operation}",
                attributes={
                    "db.table": table,
                    "db.operation": operation
                }
            ) as span:
                try:
                    result = await func(*args, **kwargs)
                    if span:
                        span.set_attribute("db.status", "success")
                    return result
                except Exception as e:
                    if span:
                        span.set_attribute("db.status", "error")
                        span.set_attribute("db.error", str(e))
                    raise
        return wrapper
    return decorator


def add_trace_attributes(**attributes):
    """Add attributes to the current span."""
    try:
        current_span = trace.get_current_span()
        if current_span and current_span.is_recording():
            for key, value in attributes.items():
                current_span.set_attribute(key, str(value))
    except Exception as e:
        logger.debug(f"Failed to add trace attributes: {e}")


def get_trace_id() -> Optional[str]:
    """Get the current trace ID."""
    try:
        current_span = trace.get_current_span()
        if current_span and current_span.is_recording():
            trace_id = current_span.get_span_context().trace_id
            return f"{trace_id:032x}"
        return None
    except Exception:
        return None


def get_span_id() -> Optional[str]:
    """Get the current span ID."""
    try:
        current_span = trace.get_current_span()
        if current_span and current_span.is_recording():
            span_id = current_span.get_span_context().span_id
            return f"{span_id:016x}"
        return None
    except Exception:
        return None