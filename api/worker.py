"""
Celery worker — background job processing.

Start with:
    celery -A api.worker worker --loglevel=info

Monitor with Flower:
    celery -A api.worker flower --port=5555

The worker is configured for ML workloads:
  - concurrency=1 (one task at a time — ML models are memory-heavy)
  - acks_late=True (re-queue on worker crash)
  - prefetch_multiplier=1 (fair distribution)
  - result_expires=86400 (results kept 24 h in Redis)
"""

import sys
from pathlib import Path

# Ensure the project root is on sys.path so `content_engine` and `config`
# are importable regardless of the working directory Celery starts from.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from celery import Celery
from kombu import Exchange, Queue
from config import settings

celery_app = Celery(
    "content_engine",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Reliability
    task_track_started=True,
    task_acks_late=True,                  # Re-queue on worker crash
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,         # One task at a time

    # Pool — solo avoids forking, which prevents MPS/torch SIGABRT on Apple Silicon
    worker_pool="solo",
    # Time limits
    task_time_limit=settings.celery_task_time_limit,
    task_soft_time_limit=settings.celery_task_soft_time_limit,

    # Worker lifecycle
    worker_concurrency=settings.celery_worker_concurrency,
    worker_max_tasks_per_child=settings.celery_worker_max_tasks_per_child,

    # Results
    result_expires=86400,                 # 24 hours

    # Timezone
    timezone="UTC",
    enable_utc=True,

    # Queues — default queue for all tasks
    task_default_queue="content_engine",
    task_queues=(
        Queue("content_engine", Exchange("content_engine"), routing_key="content_engine"),
    ),

    # Logging — don't hijack root logger
    worker_hijack_root_logger=False,
    worker_redirect_stdouts_level="WARNING",
)

# Auto-discover tasks in api/tasks.py
celery_app.autodiscover_tasks(["api"])

# Optional: Sentry integration
if settings.sentry_dsn:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.celery import CeleryIntegration
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            integrations=[CeleryIntegration()],
            traces_sample_rate=0.1,
        )
    except ImportError:
        pass

# Preload ML models when Celery worker starts (eliminates cold start)
@celery_app.on_after_finalize.connect
def preload_models_on_worker_start(sender, **kwargs):
    from api.logger import get_logger
    _wlog = get_logger("api.worker")
    _wlog.info("worker_preloading_models_start")
    import time
    start = time.perf_counter()
    try:
        from content_engine.models.quality import QualityAssessor
        from content_engine.models.face_detection import FaceDetector
        from content_engine.models.content_understanding import ContentUnderstander
        from content_engine.models.video_processing import VideoProcessor
        qa = QualityAssessor()
        _ = qa.clip_model
        fd = FaceDetector()
        _ = fd.model
        cu = ContentUnderstander()
        _ = cu.clip_model
        vp = VideoProcessor()
        _ = vp.clip_model
        elapsed = time.perf_counter() - start
        _wlog.info("worker_preloading_models_done", elapsed_seconds=round(elapsed, 2))
    except Exception as e:
        _wlog.warning("worker_preloading_models_failed", error=str(e))
