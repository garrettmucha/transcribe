"""
Celery application main module.
"""

from app.tasks.transcribe import celery_app

# Export for worker discovery
__all__ = ['celery_app']