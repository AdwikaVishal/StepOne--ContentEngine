"""
Celery tasks — long-running ML jobs offloaded from the API.

Each task:
  - Updates its own Celery state so the frontend can poll for progress
  - Uses retry with exponential backoff for transient failures
  - Cleans up temp files in a finally block
  - Returns a fully serialisable dict (no Python objects)
  - Also stores job data in Redis for shared access across backends

Task names are stable strings (not auto-generated) so they survive refactors.
"""

import sys
import shutil
import tempfile
import traceback
import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

# Ensure project root is on sys.path for content_engine imports
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from celery.exceptions import SoftTimeLimitExceeded

from api.worker import celery_app
from api.logger import get_logger
from config import settings

logger = get_logger(__name__)

# ── Redis helpers (reuse the same as scheduler.py) ───────────────────────────
def _get_redis_client():
    """Get Redis client if available, else None."""
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


# ── JSON helper ───────────────────────────────────────────────────────────────

def _json_safe(value: Any) -> Any:
    """Convert numpy/torch scalar containers to Celery JSON-safe values."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            pass
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


# ── Progress helper ───────────────────────────────────────────────────────────

def _update(task, step: str, pct: int, job_data: Optional[Dict[str, Any]] = None) -> None:
    """
    Push a PROGRESS state update to the Celery result backend and also save to Redis.
    Safe to call at any point — swallows all exceptions.
    """
    try:
        task.update_state(
            state="PROGRESS",
            meta={"step": step, "pct": pct},
        )
        if job_data:
            job_data.update({
                "status": "PROGRESS",
                "progress": {"step": step, "pct": pct},
                "updated_at": datetime.utcnow().isoformat() if 'datetime' in globals() else None
            })
            _save_job_to_redis(task.request.id, job_data)
    except Exception:
        pass


def _output_payload(out_dir: Path) -> Dict[str, Any]:
    from config import settings

    output_files: Dict[str, str] = {}
    captions: Dict[str, str] = {}
    root = settings.output_dir.resolve()

    for f in sorted(out_dir.rglob("*")):
        if not f.is_file():
            continue
        rel_to_out = f.relative_to(out_dir)
        try:
            rel = f.resolve().relative_to(root)
            web_url = f"/output/{rel.as_posix()}"
        except Exception:
            web_url = str(f.resolve())

        file_key = rel_to_out.as_posix() if rel_to_out.parent != Path(".") else f.name
        output_files[file_key] = web_url
        if f.suffix in (".txt", ".md", ".json"):
            try:
                caption_key = (
                    rel_to_out.with_suffix("").as_posix().replace("/", "__")
                    if rel_to_out.parent != Path(".")
                    else f.stem
                )
                captions[caption_key] = f.read_text(encoding="utf-8").strip()
            except Exception:
                pass

    return {
        "output_dir": str(out_dir.resolve()),
        "files": output_files,
        "captions": captions,
    }


def _safe_id(value: str) -> str:
    return re.sub(r"[^\w\-]", "_", value).strip("_")


def _get_brand_counts_from_disk(out_dir: Path):
    brand_counts = {}
    for folder in out_dir.iterdir():
        if folder.is_dir() and folder.name != "unmatched":
            imgs = [f for f in folder.glob("*.*")
                    if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp')]
            if imgs:
                brand_counts[folder.name] = len(imgs)
    unmatched_dir = out_dir / "unmatched"
    unmatched = len(list(unmatched_dir.glob("*.*"))) if unmatched_dir.exists() else 0
    return brand_counts, unmatched


# ── Task 1: Full pipeline (ML selection only) ─────────────────────────────────

@celery_app.task(
    bind=True,
    name="api.tasks.run_pipeline_task",
    max_retries=0,          # ML failures are deterministic — don't retry
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_pipeline_task(
    self,
    asset_paths: List[str],
    event_description: str = "Event",
) -> Dict[str, Any]:
    """
    Run ML selection pipeline on a list of already-saved asset paths.

    Args:
        asset_paths:       Absolute paths to uploaded files.
        event_description: Human-readable event description for concept matching.

    Returns:
        Serialisable dict with selection results.
    """
    from datetime import datetime

    _update(self, "loading_models", 5)


    logger.info("pipeline_task_start", job_id=self.request.id, assets=len(asset_paths))

    # Initialize job data for Redis
    job_data = {
        "job_id": self.request.id,
        "type": "pipeline",
        "status": "PROGRESS",
        "progress": {"step": "loading_models", "pct": 5},
        "assets": [],
        "event_name": "",
        "event_description": event_description,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    _save_job_to_redis(self.request.id, job_data)

    try:
        from content_engine import ContentEngine
        from content_engine.orchestrator import ContentOrchestrator

        _update(self, "processing_assets", 20, job_data)
        engine = ContentEngine(event_description=event_description)

        # Process all assets in parallel for 3-4x speedup
        all_processed_assets = []
        raw_metadata = engine.process_assets_parallel(asset_paths)
        for idx, path in enumerate(asset_paths):
            metadata = next((m for m in raw_metadata if m.path == path), None)
            if metadata:
                all_processed_assets.append({
                    "id": f"asset-{idx}",
                    "path": path,
                    "filename": Path(path).name,
                    "final_score": metadata.final_score,
                    "scene_concepts": metadata.scene_concepts,
                    "face_count": metadata.face_count,
                })
            else:
                all_processed_assets.append({
                    "id": f"asset-{idx}",
                    "path": path,
                    "filename": Path(path).name,
                    "final_score": 0.0,
                    "scene_concepts": [],
                    "face_count": 0,
                })
        job_data["assets"] = all_processed_assets
        _save_job_to_redis(self.request.id, job_data)

        selections = engine.select_assets(asset_paths)

        _update(self, "serialising", 90, job_data)

        results = []
        for s in selections:
            file_name = Path(s.asset.path).name
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
            })

        logger.info("pipeline_task_done", job_id=self.request.id, selected=len(results))
        final_result = _json_safe({
            "status":     "completed",
            "event":      event_description,
            "total":      len(results),
            "selections": results,
        })

        # Update job data in Redis with final state
        job_data.update({
            "status": "SUCCESS",
            "progress": {"step": "done", "pct": 100},
            "result": final_result,
            "updated_at": datetime.utcnow().isoformat(),
        })
        _save_job_to_redis(self.request.id, job_data)

        return final_result

    except SoftTimeLimitExceeded as exc:
        logger.error("pipeline_task_timeout", job_id=self.request.id)
        job_data.update({
            "status": "failed",
            "error": "Job exceeded time limit",
            "traceback": traceback.format_exc(),
            "updated_at": datetime.utcnow().isoformat(),
        })
        _save_job_to_redis(self.request.id, job_data)
        raise

    except Exception as exc:
        logger.error(
            "pipeline_task_failed",
            job_id=self.request.id,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        job_data.update({
            "status": "failed",
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "updated_at": datetime.utcnow().isoformat(),
        })
        _save_job_to_redis(self.request.id, job_data)
        raise  # Celery marks task as FAILURE


# ── Task 2: Full generation (pipeline + layout + copy + case study) ───────────

@celery_app.task(
    bind=True,
    name="api.tasks.run_generate_task",
    max_retries=0,
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_generate_task(
    self,
    asset_paths: List[str],
    event_name: str = "Event",
    event_description: str = "Event",
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Run the complete content generation pipeline.

    Args:
        asset_paths:       Absolute paths to uploaded files.
        event_name:        Display name for the event (used in filenames).
        event_description: Longer description for ML concept matching.
        options:           Optional dict with mode, generate_reel, generate_linkedin, etc.

    Returns:
        Serialisable dict with web-accessible URLs for all generated files.
    """
    options = options or {}
    from datetime import datetime
    _update(self, "loading_models", 5)

    logger.info("generate_task_start", job_id=self.request.id, assets=len(asset_paths))

    # Initialize job data for Redis
    job_data = {
        "job_id": self.request.id,
        "type": "generate",
        "status": "PROGRESS",
        "progress": {"step": "loading_models", "pct": 5},
        "assets": [],
        "event_name": event_name,
        "event_description": event_description,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    _save_job_to_redis(self.request.id, job_data)

    tmp_dir = Path(tempfile.mkdtemp(prefix="ce_gen_"))
    try:
        # Copy assets to temp dir so orchestrator can work on them
        for p in asset_paths:
            shutil.copy(p, tmp_dir / Path(p).name)

        _update(self, "ml_selection", 20, job_data)

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
                    "filename": Path(path).name,
                    "final_score": metadata.final_score,
                    "scene_concepts": metadata.scene_concepts,
                    "face_count": metadata.face_count,
                })
            else:
                all_processed_assets.append({
                    "id": f"asset-{idx}",
                    "path": path,
                    "filename": Path(path).name,
                    "final_score": 0.0,
                    "scene_concepts": [],
                    "face_count": 0,
                })
        job_data["assets"] = all_processed_assets
        _save_job_to_redis(self.request.id, job_data)

        _update(self, "ml_selection", 20, job_data)

        from content_engine.orchestrator import ContentOrchestrator
        from config import settings

        _update(self, "processing_assets", 20, job_data)
        engine = ContentEngine(event_description=event_description)

        # Process all assets to get real metadata
        all_processed_assets = []
        for idx, path in enumerate(asset_paths):
            metadata = engine.process_asset(path)
            if metadata:
                all_processed_assets.append({
                    "id": f"asset-{idx}",
                    "path": path,
                    "filename": Path(path).name,
                    "final_score": metadata.final_score,
                    "scene_concepts": metadata.scene_concepts,
                    "face_count": metadata.face_count,
                })
            else:
                all_processed_assets.append({
                    "id": f"asset-{idx}",
                    "path": path,
                    "filename": Path(path).name,
                    "final_score": 0.0,
                    "scene_concepts": [],
                    "face_count": 0,
                })
        job_data["assets"] = all_processed_assets
        _save_job_to_redis(self.request.id, job_data)

        selections = engine.select_assets(asset_paths)

        _update(self, "ml_selection", 60, job_data)
        selections = sorted(selections, key=lambda s: s.confidence, reverse=True)[:10]

        _update(self, "layout_assembly", 75, job_data)
        orchestrator = ContentOrchestrator(event_name, event_description)
        out_dir = orchestrator.generate_from_selections(
            selections,
            output_root=str(settings.output_dir),
            total_assets_processed=len(asset_paths),
            generate_carousel=True,
            generate_stories=True,
            generate_reel=bool(options.get("generate_reel", False)),
            generate_linkedin=bool(options.get("generate_linkedin", True)),
        )

        _update(self, "finalising", 95, job_data)
        payload = _output_payload(out_dir)
        payload.update({
            "status": "completed",
            "event": event_name,
            "mode": options.get("mode", "standard"),
            "selections": len(selections),
        })
        logger.info("generate_fast_task_done", job_id=self.request.id, files=len(payload["files"]))

        # Update job data in Redis with final state
        job_data.update({
            "status": "SUCCESS",
            "progress": {"step": "done", "pct": 100},
            "result": payload,
            "updated_at": datetime.utcnow().isoformat(),
        })
        _save_job_to_redis(self.request.id, job_data)

        return _json_safe(payload)

    except Exception as exc:
        logger.error(
            "generate_fast_task_failed",
            job_id=self.request.id,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        job_data.update({
            "status": "FAILURE",
            "error": str(exc),
            "updated_at": datetime.utcnow().isoformat() if 'datetime' in globals() else None,
        })
        _save_job_to_redis(self.request.id, job_data)
        raise


@celery_app.task(
    bind=True,
    name="api.tasks.run_gff_generate_task",
    max_retries=0,
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_gff_generate_task(
    self,
    asset_paths: List[str],
    event_name: str = "GFF 2025",
    brands: Optional[List[str]] = None,
    selected_brand: str = "",
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run GFF brand segregation and brand-specific content generation as a job."""
    from datetime import datetime
    from config import settings

    options = options or {}
    brands = [b for b in (brands or []) if str(b).strip()]
    source_root_raw = str(options.get("source_root") or "")
    source_root = Path(source_root_raw).expanduser() if source_root_raw else None
    owns_source_root = bool(source_root is not None and source_root.exists())
    tmp_dir = source_root if owns_source_root else Path(tempfile.mkdtemp(prefix="gff_gen_"))
    _update(self, "loading_models", 5)
    logger.info("gff_generate_task_start", job_id=self.request.id, assets=len(asset_paths), brands=len(brands))

    # Initialize job data for Redis
    job_data = {
        "job_id": self.request.id,
        "type": "gff_generate",
        "status": "PROGRESS",
        "progress": {"step": "loading_models", "pct": 5},
        "assets": [],
        "event_name": event_name,
        "event_description": "",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    _save_job_to_redis(self.request.id, job_data)

    try:
        if not owns_source_root:
            for p in asset_paths:
                src = Path(p)
                shutil.copy(src, tmp_dir / src.name)

        _update(self, "processing_assets", 20, job_data)
        brand_defs = [
            (_safe_id(name), name, [])
            for name in brands
        ]

        _update(self, "brand_matching", 45, job_data)
        from api.gff_routes import BrandDef, _normalise_brands
        from content_engine.gff.orchestrator_gff import GFFOrchestrator

        normalised = _normalise_brands(
            str(tmp_dir),
            [BrandDef(brand_id=bid, brand_name=name, render_paths=paths) for bid, name, paths in brand_defs],
        )
        
        # Get job-specific threshold if available, fall back to config
        from api.scheduler import get_job_threshold
        from config import settings
        job_threshold = get_job_threshold(self.request.id, default=settings.brand_similarity_threshold)
        orch = GFFOrchestrator(
            event_name=event_name,
            brands=[(b.brand_id, b.brand_name, b.render_paths) for b in normalised],
            similarity_threshold=job_threshold,
            use_llm=bool(options.get("use_llm", False)),
        )

        _update(self, "ml_selection", 65, job_data)
        out_dir = orch.run(
            asset_folder=str(tmp_dir),
            output_root=str(settings.output_dir),
            event_date=str(options.get("event_date", "")),
        )

        _update(self, "finalising", 95, job_data)
        report_path = out_dir / "selection_report.json"
        brand_counts = {}
        unmatched_count = 0
        brand_results = {}

        if report_path.exists():
            report = json.loads(report_path.read_text())
            
            if isinstance(report, dict) and "brands" in report:
                for bid, info in report["brands"].items():
                    if bid != "unmatched":
                        brand_counts[bid] = info.get("photo_count", info.get("count", 0))
                        brand_results[bid] = info.get("result", {})
                unmatched_count = report["brands"].get("unmatched", {}).get("photo_count", 0)
            else:
                brand_counts, unmatched_count = _get_brand_counts_from_disk(out_dir)
        else:
            brand_counts, unmatched_count = _get_brand_counts_from_disk(out_dir)

        payload = _output_payload(out_dir)
        payload.update({
            "status": "completed",
            "mode": "gff",
            "event": event_name,
            "selected_brand": _safe_id(selected_brand) if selected_brand else "",
            "brand_counts": brand_counts,
            "brand_results": brand_results,
            "unmatched_count": unmatched_count,
        })
        logger.info("gff_generate_task_done", job_id=self.request.id, brands=len(brand_counts))

        # Update job data in Redis with final state
        job_data.update({
            "status": "SUCCESS",
            "progress": {"step": "done", "pct": 100},
            "result": payload,
            "updated_at": datetime.utcnow().isoformat(),
        })
        _save_job_to_redis(self.request.id, job_data)

        return _json_safe(payload)

    except Exception as exc:
        logger.error(
            "gff_generate_task_failed",
            job_id=self.request.id,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        job_data.update({
            "status": "failed",
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "updated_at": datetime.utcnow().isoformat(),
        })
        _save_job_to_redis(self.request.id, job_data)
        raise
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

