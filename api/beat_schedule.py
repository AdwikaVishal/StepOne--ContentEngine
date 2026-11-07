"""
Celery Beat periodic task schedule.

Run the beat scheduler with:
    celery -A api.worker beat --loglevel=info --schedule=celerybeat-schedule

Or combined with a worker (single-process, dev only):
    celery -A api.worker worker --beat --loglevel=info

In production, run beat as a separate process:
    celery -A api.worker beat --loglevel=info &
    celery -A api.worker worker --loglevel=info &
"""

from celery.schedules import crontab
from api.worker import celery_app


@celery_app.task(name="api.beat_schedule.cleanup_uploads_task")
def cleanup_uploads_task():
    """Celery-managed cleanup of old uploads."""
    from cleanup import run_cleanup
    from config import settings
    return run_cleanup(
        upload_days=settings.upload_retention_days,
        output_days=settings.output_retention_days,
    )


# Register periodic tasks
celery_app.conf.beat_schedule = {
    # Delete old uploads daily at 03:00 UTC
    "cleanup-uploads-daily": {
        "task":    "api.beat_schedule.cleanup_uploads_task",
        "schedule": crontab(hour=3, minute=0),
        "options": {"expires": 3600},  # Don't run if missed by >1 hour
    },
}

celery_app.conf.timezone = "UTC"
