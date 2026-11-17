"""
api/scheduler.py — In-memory async job store using APScheduler with Redis fallback.

This is the fallback when Celery + Redis are not available.
Jobs run in a background thread pool managed by APScheduler.
Results are stored in memory (lost on restart — acceptable for dev/demo),
but if Redis is available, we use it for shared job data across backends.

For production with persistence, the Celery path in api/tasks.py is preferred.
The API automatically uses whichever is available:
  - Redis reachable → Celery tasks (persistent, distributed)
  - Redis unavailable → this module (in-process, ephemeral)

Job lifecycle:
  pending → running → completed | failed
"""

import uuid
import traceback
import json
import time
import threading
from datetime import datetime
from typing import Dict, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor

from apscheduler.schedulers.background import BackgroundScheduler
from api.logger import get_logger
from config import settings

logger = get_logger(__name__)

# ── Redis availability cache ──────────────────────────────────────────────────
# Redis is unavailable in local dev. Caching the result avoids paying a ~2 s
# connection timeout on every job update / status read when Redis is down.
_redis_available_cache = {"value": None, "checked_at": 0.0}


def _redis_available() -> bool:
    """Cached Redis availability.

    Populated by the startup background probe. The request path never performs a
    synchronous Redis probe, so /health, /submit and job updates never block on
    a dead Redis connection.
    """
    return _redis_available_cache["value"]


# ── Redis helpers ──────────────────────────────────────────────────────────────
def _get_redis_client():
    """Get Redis client if available, else None. Never blocks on a dead Redis."""
    if not _redis_available():
        return None
    try:
        import redis
        r = redis.from_url(settings.redis_url, socket_connect_timeout=1)
        r.ping()
        return r
    except Exception:
        return None

def _redis_job_key(job_id: str) -> str:
    return f"job:{job_id}"

def _save_job_to_redis(job_id: str, job_data: Dict[str, Any]) -> None:
    """Save job data to Redis with 24h TTL."""
    r = _get_redis_client()
    if r:
        try:
            r.setex(_redis_job_key(job_id), 86400, json.dumps(job_data))
        except Exception as e:
            logger.warning("redis_save_failed", job_id=job_id, error=str(e))

def _load_job_from_redis(job_id: str) -> Optional[Dict[str, Any]]:
    """Load job data from Redis if available."""
    r = _get_redis_client()
    if r:
        try:
            data = r.get(_redis_job_key(job_id))
            if data:
                return json.loads(data)
        except Exception as e:
            logger.warning("redis_load_failed", job_id=job_id, error=str(e))
    return None

# ── In-memory store ───────────────────────────────────────────────────────────
# {job_id: {status, type, result, error, created_at, updated_at, progress, assets, event_name, event_description}}
# This dict is the single authoritative job registry for the APScheduler backend.
# It is guarded by _jobs_lock so status reads (async event loop) and job updates
# (background executor threads) never corrupt each other. Locks are held only for
# dict operations (microseconds) — never during model inference or file I/O.
_jobs: Dict[str, Dict[str, Any]] = {}
_jobs_lock = threading.Lock()

# Thread pool — concurrency=1 keeps ML memory usage bounded. Jobs run here, off
# the FastAPI event loop, so generation can never block health/status requests.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ce_job")

# APScheduler instance (also used for cleanup scheduling in main.py).
# Started exactly once per process; guarded against duplicate starts on reload.
_scheduler: Optional[BackgroundScheduler] = None
_scheduler_started = False


def get_scheduler() -> BackgroundScheduler:
    """Return the shared APScheduler instance, starting it exactly once."""
    global _scheduler, _scheduler_started
    with _jobs_lock:
        if not _scheduler_started:
            _scheduler = BackgroundScheduler(daemon=True)
            _scheduler.start()
            _scheduler_started = True
        return _scheduler

# ── Public API ────────────────────────────────────────────────────────────────

def submit_pipeline_job(asset_paths: list, event_description: str = "Event") -> str:
    """
    Submit an ML selection pipeline job.
    Returns job_id immediately; job runs in background thread.
    """
    job_id = _new_job("pipeline", asset_paths, event_description=event_description)
    _executor.submit(_run_pipeline, job_id, asset_paths, event_description)
    logger.info("job_submitted", job_id=job_id, type="pipeline", assets=len(asset_paths))
    return job_id


def submit_generate_job(
    asset_paths: list,
    event_name: str = "Event",
    event_description: str = "Event",
    generate_reel: bool = False,
) -> str:
    """
    Submit a full content generation job.
    Returns job_id immediately; job runs in background thread.
    """
    job_id = _new_job("generate", asset_paths, event_name=event_name, event_description=event_description, generate_reel=generate_reel)
    _executor.submit(_run_generate, job_id, asset_paths, event_name, event_description, generate_reel)
    logger.info("job_submitted", job_id=job_id, type="generate", assets=len(asset_paths), generate_reel=generate_reel)
    return job_id


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Return a *copy* of the job dict from the in-memory store.

    In-memory is the authoritative source for the APScheduler backend. Redis is
    written to (best-effort, fire-and-forget) for cross-process visibility when
    it is available, but status/result reads never block on Redis — that is what
    made /api/jobs/{id}/status take seconds when Redis was down.

    The returned dict is a shallow copy so callers cannot mutate shared state.
    Lock is held only for the dict lookup (microseconds).
    """
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        return None
    return dict(job)


def set_job_data(job_id: str, **kwargs) -> None:
    """Set or update job data in memory (authoritative), then mirror to Redis best-effort."""
    with _jobs_lock:
        if job_id not in _jobs:
            _jobs[job_id] = {
                "job_id": job_id,
                "type": "generate",
                "status": "pending",
                "progress": {"step": "queued", "pct": 0},
                "result": None,
                "error": None,
                "assets": [],
                "event_name": "",
                "event_description": "",
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }
        _jobs[job_id].update(kwargs)
        _jobs[job_id]["updated_at"] = datetime.utcnow().isoformat()
        snapshot = dict(_jobs[job_id])
    # Redis mirror is best-effort and never blocks status reads or the lock.
    _save_job_to_redis(job_id, snapshot)


# ── Per-job threshold storage ──────────────────────────────────────────────────
_job_thresholds: Dict[str, float] = {}

def set_job_threshold(job_id: str, threshold: float) -> None:
    """Set a custom brand similarity threshold for a specific job."""
    _job_thresholds[job_id] = threshold
    # Also save to Redis if available
    r = _get_redis_client()
    if r:
        try:
            r.setex(f"job:threshold:{job_id}", 86400, json.dumps(threshold))
        except Exception as e:
            logger.warning("redis_threshold_save_failed", job_id=job_id, error=str(e))

def get_job_threshold(job_id: str, default: float = 0.60) -> float:
    """Get the brand similarity threshold for a job, falling back to default."""
    if job_id in _job_thresholds:
        return _job_thresholds[job_id]
    # Check Redis
    r = _get_redis_client()
    if r:
        try:
            data = r.get(f"job:threshold:{job_id}")
            if data:
                threshold = json.loads(data)
                _job_thresholds[job_id] = threshold
                return threshold
        except Exception as e:
            logger.warning("redis_threshold_load_failed", job_id=job_id, error=str(e))
    return default


# ── Internal helpers ──────────────────────────────────────────────────────────

def _new_job(job_type: str, asset_paths: list = None, event_name: str = "", event_description: str = "", generate_reel: bool = False) -> str:
    job_id = uuid.uuid4().hex
    from pathlib import Path
    initial_assets = []
    if asset_paths:
        for idx, path in enumerate(asset_paths):
            initial_assets.append({
                "id": f"asset-{idx}",
                "path": path,
                "filename": Path(path).name,
                "final_score": 0.0,
                "scene_concepts": [],
                "face_count": 0,
            })
    video_count = sum(1 for p in (asset_paths or []) if Path(p).suffix.lower() in {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".qt", ".wmv", ".flv", ".f4v", ".mpg", ".mpeg", ".mpe", ".m2v", ".m2ts", ".mts", ".ts", ".3gp", ".3g2", ".ogv", ".asf", ".divx", ".dv", ".vob"})
    job_data = {
        "job_id":     job_id,
        "type":       job_type,
        "status":     "pending",
        "progress":   {"step": "queued", "pct": 0},
        "result":     None,
        "error":      None,
        "assets":     initial_assets,
        "event_name": event_name,
        "event_description": event_description,
        "generate_reel": generate_reel,
        "video_count": video_count,
        "reel_status": "not_requested" if not generate_reel else "pending",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    with _jobs_lock:
        _jobs[job_id] = job_data
    # Redis mirror is best-effort and never blocks status reads or the lock.
    _save_job_to_redis(job_id, job_data)
    return job_id


def _update(job_id: str, **kwargs) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)
            _jobs[job_id]["updated_at"] = datetime.utcnow().isoformat()
            snapshot = dict(_jobs[job_id])
        else:
            snapshot = None
    # Redis mirror is best-effort and never blocks status reads or the lock.
    if snapshot is not None:
        _save_job_to_redis(job_id, snapshot)


def _run_pipeline(job_id: str, asset_paths: list, event_description: str) -> None:
    """Background thread: run ML selection pipeline."""
    try:
        _update(job_id, status="running", progress={"step": "loading_models", "pct": 10})

        from content_engine import ContentEngine
        engine = ContentEngine(event_description=event_description)

        _update(job_id, progress={"step": "processing_assets", "pct": 30})
        
        # Process ALL assets in parallel for 3-4x speedup
        all_processed_assets = []
        raw_metadata = engine.process_assets_parallel(asset_paths)
        for idx, path in enumerate(asset_paths):
            metadata = next((m for m in raw_metadata if m.path == path), None)
            if metadata:
                all_processed_assets.append({
                    "id": f"asset-{idx}",
                    "path": path,
                    "filename": metadata.path.split("/")[-1],
                    "final_score": metadata.final_score,
                    "quality_score": metadata.quality_score,
                    "aesthetic_score": metadata.aesthetic_score,
                    "scene_concepts": metadata.scene_concepts,
                    "face_count": metadata.face_count,
                    # Score provenance (availability-aware scoring)
                    "score_available_signals": getattr(metadata, "score_available_signals", []),
                    "score_missing_signals": getattr(metadata, "score_missing_signals", []),
                    "score_effective_weights": getattr(metadata, "score_effective_weights", {}),
                    "score_is_partial": getattr(metadata, "score_is_partial", False),
                    "score_valid": getattr(metadata, "score_valid", False),
                    # Classification diagnostics
                    "classification_explanation": getattr(metadata, "classification_explanation", None),
                })
            else:
                from pathlib import Path
                all_processed_assets.append({
                    "id": f"asset-{idx}",
                    "path": path,
                    "filename": Path(path).name,
                    "final_score": 0.0,
                    "quality_score": 0.0,
                    "aesthetic_score": 0.0,
                    "scene_concepts": [],
                    "face_count": 0,
                    # Score provenance (availability-aware scoring)
                    "score_available_signals": [],
                    "score_missing_signals": ["quality", "aesthetic", "faces", "concepts"],
                    "score_effective_weights": {
                        "quality": 0.0,
                        "aesthetic": 0.0,
                        "faces": 0.0,
                        "concepts": 0.0,
                    },
                    "score_is_partial": True,
                })
        
        _update(job_id, assets=all_processed_assets)
        
        selections = engine.select_assets(asset_paths)

        _update(job_id, progress={"step": "serialising", "pct": 90})

        results = []
        for s in selections:
            file_name = s.asset.path.split("/")[-1]
            results.append({
                "filename":         file_name,
                "file_url":         f"/uploads/{file_name}",
                "intended_use":     s.intended_use,
                "confidence":       round(s.confidence, 4),
                "low_confidence":   s.confidence < 0.5,
                "selection_reason": s.selection_reason,
                "scores": {
                    "quality":   round(s.asset.quality_score, 4),
                    "aesthetic": round(s.asset.aesthetic_score, 4),
                    "final":     round(s.asset.final_score, 4),
                },
                "face_count":      s.asset.face_count,
                "bboxes":          [],
                "scene_concepts":  s.asset.scene_concepts[:8],
                "asset_type":      s.asset.asset_type,
                "duration":        s.asset.duration,
                "highlight_clips": s.asset.highlight_clips or [],
                # Score provenance (availability-aware scoring)
                "score_available_signals": getattr(s.asset, "score_available_signals", []),
                "score_missing_signals": getattr(s.asset, "score_missing_signals", []),
                "score_effective_weights": getattr(s.asset, "score_effective_weights", {}),
                "score_is_partial": getattr(s.asset, "score_is_partial", False),
                "score_valid": getattr(s.asset, "score_valid", False),
                # Classification diagnostics
                "classification_explanation": getattr(s.asset, "classification_explanation", None),
            })

        _update(
            job_id,
            status="completed",
            progress={"step": "done", "pct": 100},
            result={
                "status":     "completed",
                "event":      event_description,
                "total":      len(results),
                "selections": results,
            },
        )
        logger.info("job_completed", job_id=job_id, type="pipeline", selected=len(results))

    except Exception as exc:
        _update(job_id, status="failed", error=str(exc))
        logger.error("job_failed", job_id=job_id, type="pipeline", error=str(exc),
                     traceback=traceback.format_exc())


def _run_generate(
    job_id: str,
    asset_paths: list,
    event_name: str,
    event_description: str,
    generate_reel: bool = False,
) -> None:
    """Background thread: run full content generation."""
    import shutil
    import tempfile
    from pathlib import Path

    tmp_dir = Path(tempfile.mkdtemp(prefix="ce_gen_"))
    try:
        _update(job_id, status="running", progress={"step": "loading_models", "pct": 5})

        for p in asset_paths:
            shutil.copy(p, tmp_dir / Path(p).name)

        _update(job_id, progress={"step": "ml_selection", "pct": 20})

        from content_engine.orchestrator import ContentOrchestrator
        from config import settings
        from content_engine import ContentEngine

        # Process all assets in parallel for 3-4x speedup
        engine = ContentEngine(event_description=event_description)
        all_processed_assets = []
        raw_metadata = engine.process_assets_parallel(asset_paths)
        for idx, path in enumerate(asset_paths):
            metadata = next((m for m in raw_metadata if m.path == path), None)
            if metadata:
                all_processed_assets.append({
                    "id": f"asset-{idx}",
                    "path": path,
                    "filename": metadata.path.split("/")[-1],
                    "final_score": metadata.final_score,
                    "quality_score": metadata.quality_score,
                    "aesthetic_score": metadata.aesthetic_score,
                    "scene_concepts": metadata.scene_concepts,
                    "face_count": metadata.face_count,
                    "asset_type": metadata.asset_type,
                    "duration": metadata.duration,
                    "highlight_clips": metadata.highlight_clips or [],
                    # Score provenance (availability-aware scoring)
                    "score_available_signals": getattr(metadata, "score_available_signals", []),
                    "score_missing_signals": getattr(metadata, "score_missing_signals", []),
                    "score_effective_weights": getattr(metadata, "score_effective_weights", {}),
                    "score_is_partial": getattr(metadata, "score_is_partial", False),
                    "score_valid": getattr(metadata, "score_valid", False),
                    # Classification diagnostics
                    "classification_explanation": getattr(metadata, "classification_explanation", None),
                })
            else:
            all_processed_assets.append({
                "id": f"asset-{idx}",
                "path": path,
                "filename": Path(path).name,
                "final_score": 0.0,
                "quality_score": 0.0,
                "aesthetic_score": 0.0,
                "scene_concepts": [],
                "face_count": 0,
                "asset_type": "image",
                "duration": 0.0,
                "highlight_clips": [],
                # Score provenance (availability-aware scoring)
                "score_available_signals": [],
                "score_missing_signals": ["quality", "aesthetic", "faces", "concepts"],
                "score_effective_weights": {
                    "quality": 0.0,
                    "aesthetic": 0.0,
                    "faces": 0.0,
                    "concepts": 0.0,
                },
                "score_is_partial": True,
                "score_valid": False,
                # Classification diagnostics
                "classification_explanation": None,
            })
        
        _update(job_id, assets=all_processed_assets)

        video_count = sum(1 for a in all_processed_assets if a.get("asset_type") == "video")

        orch = ContentOrchestrator(
            event_name=event_name,
            event_description=event_description,
        )

        _update(job_id, progress={"step": "layout_assembly", "pct": 50})
        out_dir = orch.run(
            str(tmp_dir),
            output_root=str(settings.output_dir),
            generate_reel=generate_reel,
        )

        _update(job_id, progress={"step": "finalising", "pct": 90})

        event_slug = out_dir.name  # e.g. "Tech_Summit_2024"
        output_files = {}
        captions = {}

        for f in sorted(out_dir.iterdir()):
            if not f.is_file():
                continue
            web_url = f"/output/{event_slug}/{f.name}"
            output_files[f.name] = web_url

            # Read text files so frontend gets captions without disk access
            if f.suffix in (".txt", ".md"):
                try:
                    key = f.stem  # e.g. "linkedin_caption", "case_study"
                    captions[key] = f.read_text(encoding="utf-8").strip()
                except Exception:
                    pass

        # Determine reel status for the frontend.
        # Prefer the reel_status.json sidecar written by the orchestrator, which
        # carries precise error info (ffmpeg_unavailable, no_highlight_clips,
        # no_video_assets). Fall back to checking for the reel output file.
        reel_url = output_files.get("instagram_reel.mp4")
        reel_status = "not_requested"
        reel_error = None
        try:
            import json as _json
            rs_path = Path(out_dir) / "reel_status.json"
            if rs_path.is_file():
                rs = _json.loads(rs_path.read_text(encoding="utf-8"))
                reel_status = rs.get("reel_status", "not_requested")
                reel_error = rs.get("reel_error")
                sidecar_url = rs.get("reel_url")
                if sidecar_url:
                    reel_url = sidecar_url
        except Exception:
            pass
        if generate_reel and reel_status == "not_requested":
            reel_status = "generated" if reel_url else "failed"

        # Aggregate scene concepts and face count for caption regeneration context
        all_concepts: List[str] = []
        total_faces = 0
        for a in all_processed_assets:
            for c in (a.get("scene_concepts") or []):
                if c not in all_concepts:
                    all_concepts.append(c)
            total_faces += int(a.get("face_count") or 0)

        _update(
            job_id,
            status="completed",
            progress={"step": "done", "pct": 100},
            result={
                "status":     "completed",
                "event":      event_name,
                "event_description": event_description,
                "scene_concepts": all_concepts,
                "face_count": total_faces,
                "output_dir": str(out_dir.resolve()),
                "files":      output_files,
                "captions":   captions,
                "generate_reel": generate_reel,
                "reel_status": reel_status,
                "reel_url": reel_url,
                "reel_error": reel_error,
                "video_count": video_count,
                "video_assets": [
                    {
                        "filename": a.get("filename", ""),
                        "path": a.get("path", ""),
                        "duration": a.get("duration", 0.0),
                        "highlight_clips": a.get("highlight_clips", []),
                        "asset_type": a.get("asset_type", "image"),
                    }
                    for a in all_processed_assets
                    if a.get("asset_type") == "video"
                ],
            },
            event_name=event_name,
            event_description=event_description,
        )
        logger.info("job_completed", job_id=job_id, type="generate", files=len(output_files))

    except Exception as exc:
        if generate_reel:
            _update(job_id, status="failed", error=str(exc), reel_status="failed")
        else:
            _update(job_id, status="failed", error=str(exc))
        logger.error("job_failed", job_id=job_id, type="generate", error=str(exc),
                     traceback=traceback.format_exc())
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
