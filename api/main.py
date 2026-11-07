"""
FastAPI backend — Content & Design Engine
All configuration read from .env via config.py

Async job processing:
  - Redis available → Celery (persistent, distributed, retryable)
  - Redis unavailable → APScheduler in-process (dev/demo fallback)

Both backends expose the same /api/jobs/{id}/status and /api/jobs/{id}/result
endpoints, so the frontend doesn't need to know which backend is active.
"""

import uuid
import shutil
import time
import subprocess
import tempfile
import mimetypes
import io
import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Request, Form, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import asyncio
import uvicorn

from config import settings
from api.logger import get_logger, request_id_var, setup_logging
from api.utils import safe_jsonify


# Initialise structured logging before any logger.* calls
setup_logging(
    log_level=settings.log_level,
    json_output=(settings.log_level.upper() != "DEBUG"),
)

logger = get_logger(__name__)

# Preview cache for layout previews (size-limited to prevent memory bloat)
_preview_cache = {}
_MAX_CACHE_SIZE = 50


def _safe_id(value: str) -> str:
    return re.sub(r"[^\w\-]", "_", value).strip("_")

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Content & Design Engine",
    version="2.0.0",
    description="AI-powered social media content generator from event photos/videos",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    """
    On startup:
    1. Schedule daily cleanup via APScheduler (no cron/Docker needed)
    2. Log which job backend is active
    3. Preload ML models in background (eliminate cold start)
    """
    # Daily cleanup at 03:00 UTC
    try:
        from api.scheduler import get_scheduler
        from cleanup import run_cleanup

        sched = get_scheduler()
        sched.add_job(
            lambda: run_cleanup(
                upload_days=settings.upload_retention_days,
                output_days=settings.output_retention_days,
            ),
            trigger="cron",
            hour=3, minute=0,
            id="daily_cleanup",
            replace_existing=True,
        )
        logger.info("cleanup_scheduler_started", schedule="daily at 03:00 UTC")
    except Exception as e:
        logger.warning("cleanup_scheduler_failed", error=str(e))

    # Log active job backend
    try:
        import redis as redis_lib
        r = redis_lib.from_url(settings.redis_url, socket_connect_timeout=1)
        r.ping()
        logger.info("job_backend", backend="celery+redis", url=settings.redis_url)
    except Exception:
        logger.info(
            "job_backend",
            backend="apscheduler_in_memory",
            note="Redis unavailable — async jobs run in-process (dev mode)",
        )

    # Background model preloading — eliminates 15-20s cold start on first request
    def preload_models():
        logger.info("preloading_models_start")
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
            _ = cu.clip
            vp = VideoProcessor()
            _ = vp.clip_model
            elapsed = time.perf_counter() - start
            logger.info("preloading_models_done", elapsed_seconds=round(elapsed, 2))
        except Exception as e:
            logger.warning("preloading_models_failed", error=str(e))

    threading.Thread(target=preload_models, daemon=True).start()

# ── Request ID + timing middleware ────────────────────────────────────────────

@app.middleware("http")
async def request_middleware(request: Request, call_next):
    rid = str(uuid.uuid4())[:8]
    request_id_var.set(rid)
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = round((time.perf_counter() - start) * 1000)
    logger.info(f"[{rid}] {request.method} {request.url.path} → {response.status_code} ({elapsed}ms)")
    response.headers["X-Request-ID"] = rid
    return response

# ── Static files ──────────────────────────────────────────────────────────────

import os
os.makedirs(str(settings.output_dir), exist_ok=True)

app.mount("/uploads", StaticFiles(directory=str(settings.upload_dir)), name="uploads")
app.mount("/output",  StaticFiles(directory=str(settings.output_dir)), name="output")

# ── Lazy model singletons ─────────────────────────────────────────────────────

_quality_assessor    = None
_face_detector       = None
_content_understander = None
_video_processor     = None
_engine              = None


def get_quality_assessor():
    global _quality_assessor
    if _quality_assessor is None:
        from content_engine.models.quality import QualityAssessor
        _quality_assessor = QualityAssessor()
    return _quality_assessor


def get_face_detector():
    global _face_detector
    if _face_detector is None:
        from content_engine.models.face_detection import FaceDetector
        _face_detector = FaceDetector()
    return _face_detector


def get_content_understander():
    global _content_understander
    if _content_understander is None:
        from content_engine.models.content_understanding import ContentUnderstander
        _content_understander = ContentUnderstander()
    return _content_understander


def get_video_processor():
    global _video_processor
    if _video_processor is None:
        from content_engine.models.video_processing import VideoProcessor
        _video_processor = VideoProcessor()
    return _video_processor


# ── File validation ───────────────────────────────────────────────────────────

_VIDEO_EXTENSION_MIME_MAP = {
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".f4v": "video/mp4",
    ".mov": "video/quicktime",
    ".qt": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".wmv": "video/x-ms-wmv",
    ".flv": "video/x-flv",
    ".mpg": "video/mpeg",
    ".mpeg": "video/mpeg",
    ".mpe": "video/mpeg",
    ".m2v": "video/mpeg",
    ".m2ts": "video/mp2t",
    ".mts": "video/mp2t",
    ".ts": "video/mp2t",
    ".3gp": "video/3gpp",
    ".3g2": "video/3gpp2",
    ".ogv": "video/ogg",
    ".asf": "video/x-ms-asf",
    ".divx": "video/x-msvideo",
    ".dv": "video/dv",
    ".vob": "video/mpeg",
}

_ISO_BMFF_VIDEO_BRANDS = {
    b"isom", b"iso2", b"mp41", b"mp42", b"avc1", b"dash", b"qt  ",
    b"m4v ", b"3gp4", b"3gp5", b"3g2a", b"3g2b",
}
_ISO_BMFF_IMAGE_BRANDS = {
    b"heic", b"heix", b"hevc", b"hevx", b"heif", b"mif1", b"msf1",
    b"avif", b"avis",
}


def _is_valid_video_file(file_path: Path) -> bool:
    """
    Validate video container with ffprobe (preferred) and OpenCV fallback.
    Returns True when a playable video stream is detected.
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_type",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0 and "video" in (result.stdout or "").lower():
            return True
    except FileNotFoundError:
        pass
    except Exception:
        pass

    # Some containers don't report stream metadata cleanly; duration probe is a
    # secondary ffprobe check.
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file_path),
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        duration_raw = (result.stdout or "").strip()
        if result.returncode == 0 and duration_raw and duration_raw.lower() != "n/a":
            return float(duration_raw) > 0
    except FileNotFoundError:
        pass
    except Exception:
        pass

    # Final fallback: OpenCV decode sanity check.
    try:
        import cv2

        cap = cv2.VideoCapture(str(file_path))
        if not cap.isOpened():
            cap.release()
            return False

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames > 0:
            cap.release()
            return True

        ok, _ = cap.read()
        cap.release()
        return bool(ok)
    except Exception:
        return False


def _is_valid_video_bytes(data: bytes, suffix: str) -> bool:
    """
    Write bytes to a temp file and run video validation.
    """
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix or ".mp4") as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        return _is_valid_video_file(tmp_path)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def _is_valid_image_bytes(data: bytes) -> bool:
    """
    Validate image bytes with Pillow and OpenCV fallback.
    """
    try:
        from PIL import Image as PILImage

        with PILImage.open(io.BytesIO(data)) as img:
            img.verify()
        return True
    except Exception:
        pass

    try:
        import cv2
        import numpy as np

        decoded = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        return decoded is not None
    except Exception:
        return False

def _is_likely_video_signature(data: bytes, ext: str) -> bool:
    """
    Lightweight container signature checks for common video formats.
    Useful when ffprobe/OpenCV can't parse codec/container variants.
    """
    head = data[:64]
    ext = (ext or "").lower()

    # ISO BMFF family (mp4/mov/m4v/3gp/3g2)
    if len(head) >= 12 and head[4:8] == b"ftyp":
        major_brand = head[8:12].lower()
        if major_brand in _ISO_BMFF_VIDEO_BRANDS:
            return True
        if ext in {".mp4", ".mov", ".m4v", ".3gp", ".3g2"}:
            return True

    # AVI
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return True

    # Matroska / WebM
    if head.startswith(b"\x1A\x45\xDF\xA3"):
        return True

    # FLV
    if head.startswith(b"FLV"):
        return True

    # Ogg container (used by .ogv)
    if head.startswith(b"OggS"):
        return True

    # MPEG Program Stream / Sequence header
    if head.startswith(b"\x00\x00\x01\xBA") or head.startswith(b"\x00\x00\x01\xB3"):
        return True

    # MPEG-TS packets usually start with sync byte 0x47
    if ext in {".ts", ".m2ts", ".mts"} and head[:1] == b"\x47":
        return True

    return False


def _is_likely_image_signature(data: bytes, ext: str) -> bool:
    """
    Lightweight signature checks for common image formats.
    Useful when Pillow/OpenCV plugins are missing (e.g. HEIC/HEIF).
    """
    head = data[:64]
    ext = (ext or "").lower()

    if head.startswith(b"\xFF\xD8\xFF"):  # JPEG/JFIF/EXIF
        return True
    if head.startswith(b"\x89PNG\r\n\x1A\n"):  # PNG
        return True
    if head.startswith((b"GIF87a", b"GIF89a")):  # GIF
        return True
    if head.startswith(b"BM"):  # BMP
        return True
    if head.startswith((b"II*\x00", b"MM\x00*")):  # TIFF (little/big endian)
        return True
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return True

    # ISO BMFF image family (HEIC/HEIF/AVIF)
    if len(head) >= 12 and head[4:8] == b"ftyp":
        major_brand = head[8:12].lower()
        if major_brand in _ISO_BMFF_IMAGE_BRANDS:
            return True
        if ext in {".heic", ".heif"}:
            return True

    return False


def _guess_mime_from_extension(ext: str, fallback: str) -> str:
    guessed = mimetypes.guess_type(f"upload{ext}")[0]
    return guessed or fallback

async def validate_upload(file: UploadFile) -> Path:
    """
    Validate file size, detect MIME type for logging, then save to uploads/
    with a UUID filename.
    Raises HTTP 413 for oversized files.
    """
    data = await file.read()

    # Size check
    if len(data) > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File '{file.filename}' is {len(data) // (1024*1024)}MB. "
                f"Maximum allowed: {settings.max_file_size_mb}MB."
            ),
        )

    ext = Path(file.filename or "upload").suffix.lower() or ".bin"
    allowed_mimes = settings.allowed_mime_types
    is_video_ext = ext in settings.allowed_video_extensions
    is_image_ext = ext in settings.allowed_image_extensions

    # Real MIME type from file bytes
    try:
        import magic as libmagic
        detected_mime = libmagic.from_buffer(data[:2048], mime=True)
    except Exception:
        detected_mime = file.content_type or "application/octet-stream"
    declared_mime = file.content_type or "application/octet-stream"

    resolved_kind: Optional[str] = None
    resolved_mime: Optional[str] = None

    # Fast-path: explicitly allowed MIME list.
    if detected_mime in allowed_mimes:
        resolved_mime = detected_mime
        resolved_kind = "video" if detected_mime.startswith("video/") else "image"
    elif detected_mime in {"application/x-matroska", "audio/ogg"} and is_video_ext:
        resolved_mime = _VIDEO_EXTENSION_MIME_MAP.get(ext, "video/mp4")
        resolved_kind = "video"

    # Fallback path: handle non-standard or octet-stream media types.
    if resolved_mime is None:
        video_signature_ok = _is_likely_video_signature(data, ext)
        image_signature_ok = _is_likely_image_signature(data, ext)
        looks_like_video = (
            detected_mime.startswith("video/")
            or declared_mime.startswith("video/")
            or is_video_ext
            or video_signature_ok
        )
        looks_like_image = (
            detected_mime.startswith("image/")
            or declared_mime.startswith("image/")
            or is_image_ext
            or image_signature_ok
        )
        video_probe_ok = _is_valid_video_bytes(data, ext if ext != ".bin" else ".mp4")
        image_probe_ok = _is_valid_image_bytes(data)
        if looks_like_video and (video_probe_ok or video_signature_ok):
            resolved_kind = "video"
            resolved_mime = _VIDEO_EXTENSION_MIME_MAP.get(
                ext,
                _guess_mime_from_extension(
                    ext,
                    declared_mime if declared_mime.startswith("video/") else "video/mp4",
                ),
            )
        elif looks_like_image and (image_probe_ok or image_signature_ok):
            resolved_kind = "image"
            resolved_mime = _guess_mime_from_extension(
                ext,
                declared_mime if declared_mime.startswith("image/") else "image/jpeg",
            )

    if resolved_mime is None or resolved_kind is None:
        allowed = ", ".join(allowed_mimes)
        allowed_exts = ", ".join(settings.allowed_upload_extensions)
        raise HTTPException(
            status_code=400,
            detail=(
                f"File '{file.filename}' has unsupported type '{detected_mime}'. "
                f"Allowed MIME types: {allowed}. Allowed extensions: {allowed_exts}"
            ),
        )

    if detected_mime not in allowed_mimes:
        logger.info(
            "upload_media_fallback_accepted",
            filename=file.filename,
            extension=ext,
            detected_mime=detected_mime,
            declared_mime=declared_mime,
            resolved_mime=resolved_mime,
            resolved_kind=resolved_kind,
        )

    # Normalise extension so downstream routing remains consistent.
    saved_ext = ext
    if saved_ext == ".bin":
        if resolved_kind == "video":
            saved_ext = mimetypes.guess_extension(resolved_mime) or ".mp4"
        else:
            saved_ext = mimetypes.guess_extension(resolved_mime) or ".jpg"

    dest = settings.upload_dir / f"{uuid.uuid4().hex}{saved_ext}"
    dest.write_bytes(data)

    logger.info(
        "upload_saved",
        filename=file.filename,
        dest=dest.name,
        size_kb=len(data) // 1024,
        mime=resolved_mime,
    )
    return dest


async def validate_uploads(files: List[UploadFile]) -> List[Path]:
    return [await validate_upload(f) for f in files]


# ── Health & status ───────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Health check — also reports Redis/Celery availability."""
    redis_ok = False
    try:
        import redis as redis_lib
        redis_lib.from_url(settings.redis_url, socket_connect_timeout=1).ping()
        redis_ok = True
    except Exception:
        pass

    return {
        "status":  "ok",
        "version": "2.0.0",
        "redis":   redis_ok,
        "backend": "celery" if redis_ok else "apscheduler",
    }


@app.get("/api/model-status")
def model_status():
    """Check which ML packages are installed."""
    status = {}
    for pkg in ["torch", "transformers", "ultralytics", "sentence_transformers",
                "cv2", "librosa", "scenedetect", "celery", "redis", "flower", "groq"]:
        try:
            __import__(pkg)
            status[pkg] = "available"
        except ImportError:
            status[pkg] = "not installed"

    # Check Groq key configured
    status["groq_configured"] = "yes" if settings.groq_api_key else "no"
    status["groq_model"]      = settings.groq_model if settings.groq_api_key else "—"
    return status


# ── Individual ML model endpoints ─────────────────────────────────────────────

@app.post("/api/quality")
async def assess_quality(file: UploadFile = File(...)):
    path = await validate_upload(file)
    try:
        result = get_quality_assessor().assess(str(path))
        return {"filename": file.filename, "file_url": f"/uploads/{path.name}", "scores": result}
    except Exception as e:
        logger.error(f"Quality assessment failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/faces")
async def detect_faces(file: UploadFile = File(...)):
    """Returns face count, per-face confidences, and normalised bounding boxes."""
    path = await validate_upload(file)
    try:
        detector = get_face_detector()
        results  = detector.model.predict(
            str(path), conf=settings.face_confidence_threshold, verbose=False
        )

        face_count  = 0
        confidences = []
        bboxes      = []
        w = h = 0

        if results and results[0].boxes is not None:
            boxes      = results[0].boxes
            face_count = len(boxes)
            confidences = [round(c, 3) for c in boxes.conf.cpu().tolist()]

            from PIL import Image as PILImage
            img = PILImage.open(str(path))
            w, h = img.size
            for box in boxes.xyxy.cpu().tolist():
                bboxes.append({
                    "x1": round(box[0] / w, 4),
                    "y1": round(box[1] / h, 4),
                    "x2": round(box[2] / w, 4),
                    "y2": round(box[3] / h, 4),
                })

        return {
            "filename":     file.filename,
            "file_url":     f"/uploads/{path.name}",
            "face_count":   face_count,
            "confidences":  confidences,
            "bboxes":       bboxes,
            "image_width":  w,
            "image_height": h,
        }
    except Exception as e:
        logger.error(f"Face detection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/content")
async def understand_content(file: UploadFile = File(...)):
    path = await validate_upload(file)
    try:
        result = get_content_understander().understand_image(str(path))
        return {"filename": file.filename, "file_url": f"/uploads/{path.name}", **result}
    except Exception as e:
        logger.error(f"Content understanding failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/highlights")
async def extract_highlights(file: UploadFile = File(...), target_duration: int = 45):
    path = await validate_upload(file)
    try:
        highlights = get_video_processor().extract_highlights(str(path), target_duration=target_duration)
        return {
            "filename":               file.filename,
            "file_url":               f"/uploads/{path.name}",
            "highlights":             highlights,
            "total_selected_seconds": round(sum(h["end"] - h["start"] for h in highlights), 2),
        }
    except Exception as e:
        logger.error(f"Highlight extraction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Synchronous pipeline (small batches / testing) ────────────────────────────

@app.post("/api/pipeline")
async def run_pipeline(
    files: List[UploadFile] = File(...),
    event_description: str = Form("Event"),
):
    paths = [str(p) for p in await validate_uploads(files)]
    try:
        from content_engine import ContentEngine
        engine     = ContentEngine(event_description=event_description)
        selections = engine.select_assets(paths)
        return safe_jsonify({"event": event_description, "total": len(selections), "selections": _serialise_selections(selections)})

    except Exception as e:
        logger.error(f"Pipeline failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Async pipeline via Celery (with APScheduler fallback) ─────────────────────

@app.post("/api/pipeline/async")
async def run_pipeline_async(
    files: List[UploadFile] = File(...),
    event_description: str = Form("Event"),
):
    """
    Submit pipeline job. Returns job_id immediately (<500ms).
    Uses APScheduler in-process by default (more stable for ML workloads).
    Poll /api/jobs/{job_id}/status for progress.
    """
    paths = [str(p) for p in await validate_uploads(files)]

    # Use APScheduler in-memory by default
    from api.scheduler import submit_pipeline_job
    job_id = submit_pipeline_job(paths, event_description)
    return {"job_id": job_id, "status": "pending", "backend": "apscheduler"}


@app.post("/api/generate/async")
async def run_generate_async(
    files: List[UploadFile] = File(...),
    event_name: str = Form("Event"),
    event_description: str = Form("Event"),
):
    """
    Submit full generation job. Returns job_id immediately (<500ms).
    Uses APScheduler in-process by default (more stable for ML workloads).
    """
    paths = [str(p) for p in await validate_uploads(files)]

    # Use APScheduler in-memory by default
    from api.scheduler import submit_generate_job
    job_id = submit_generate_job(paths, event_name, event_description)
    return {"job_id": job_id, "status": "pending", "backend": "apscheduler"}


@app.post("/api/generate/fast")
async def run_generate_fast(
    files: List[UploadFile] = File(...),
    render_files: Optional[List[UploadFile]] = File(None),
    event_name: str = Form("Event"),
    event_description: str = Form("Event"),
    mode: str = Form("standard"),
    brands: Optional[str] = Form(None),
    selected_brand: Optional[str] = Form(None),
    render_brand_ids: Optional[str] = Form(None),
    generate_reel: bool = Form(False),
):
    """
    Submit an optimized generation job for the unified Studio page.

    standard mode: ML selects the strongest assets, caps to top 10, then writes
    normal ResultsPage-compatible outputs.

    gff mode: runs brand segregation and brand-specific GFF outputs.
    """
    mode = (mode or "standard").lower()

    paths: List[str]
    source_root: Optional[Path] = None
    parsed_brands: List[str] = []

    if mode == "gff":
        parsed_brands = json.loads(brands or "[]")
        if not isinstance(parsed_brands, list):
            raise HTTPException(400, "brands must be a JSON list")
        parsed_brands = [str(b).strip() for b in parsed_brands if str(b).strip()]
        if len(parsed_brands) != 4:
            raise HTTPException(400, "GFF mode requires exactly 4 brand names")
        if not selected_brand:
            raise HTTPException(400, "GFF mode requires selected_brand")

        source_root = settings.upload_dir / f"gff_{uuid.uuid4().hex}"
        source_root.mkdir(parents=True, exist_ok=True)
        paths = []
        for file in files:
            filename = (file.filename or "upload").strip().replace("\\", "/")
            ext = Path(filename).suffix.lower()
            if ext not in settings.allowed_upload_extensions:
                raise HTTPException(
                    400,
                    (
                        f"File '{file.filename}' has unsupported extension '{ext or '(none)'}'. "
                        f"Allowed extensions: {', '.join(settings.allowed_upload_extensions)}"
                    ),
                )
            data = await file.read()
            if len(data) > settings.max_file_size_bytes:
                raise HTTPException(
                    413,
                    (
                        f"File '{file.filename}' is {len(data) // (1024 * 1024)}MB. "
                        f"Maximum allowed: {settings.max_file_size_mb}MB."
                    ),
                )
            rel = Path(filename)
            safe_parts = [part for part in rel.parts if part not in ("", ".", "..")]
            if not safe_parts:
                safe_parts = [f"{uuid.uuid4().hex}{ext}"]
            dest = source_root.joinpath(*safe_parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            paths.append(str(dest))

        if render_files:
            try:
                render_ids = json.loads(render_brand_ids or "[]")
            except Exception as e:
                raise HTTPException(400, f"Invalid render_brand_ids: {e}") from e
            if not isinstance(render_ids, list) or len(render_ids) != len(render_files):
                raise HTTPException(400, "render_brand_ids must match render_files")

            render_counts = {_safe_id(name): 0 for name in parsed_brands}
            for idx, render in enumerate(render_files):
                brand_id = _safe_id(str(render_ids[idx]).strip())
                if brand_id not in render_counts:
                    raise HTTPException(400, f"Render file references unknown brand '{render_ids[idx]}'")

                ext = Path(render.filename or "render").suffix.lower()
                if ext not in settings.allowed_image_extensions:
                    raise HTTPException(
                        400,
                        f"Render file '{render.filename}' must be an image. Allowed: {', '.join(settings.allowed_image_extensions)}",
                    )
                data = await render.read()
                if len(data) > settings.max_file_size_bytes:
                    raise HTTPException(
                        413,
                        (
                            f"Render file '{render.filename}' is {len(data) // (1024 * 1024)}MB. "
                            f"Maximum allowed: {settings.max_file_size_mb}MB."
                        ),
                    )
                render_counts[brand_id] += 1
                safe_name = Path(render.filename or f"render_{render_counts[brand_id]}{ext}").name
                dest = source_root / "render_images" / brand_id / f"{render_counts[brand_id]}_{safe_name}"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)

            missing_renders = [name for name in parsed_brands if render_counts.get(_safe_id(name), 0) == 0]
            if missing_renders:
                raise HTTPException(400, f"Missing render images for: {', '.join(missing_renders)}")
    else:
        paths = [str(p) for p in await validate_uploads(files)]

    try:
        import redis as redis_lib
        redis_lib.from_url(settings.redis_url, socket_connect_timeout=1).ping()

        if mode == "gff":
            from api.tasks import run_gff_generate_task
            task = run_gff_generate_task.delay(
                paths,
                event_name,
                parsed_brands,
                selected_brand,
                {
                    "similarity_threshold": 0.45,
                    "use_llm": False,
                    "source_root": str(source_root) if source_root else "",
                },
            )
        else:
            from api.tasks import run_generate_task
            task = run_generate_task.delay(
                paths,
                event_name,
                event_description,
                {
                    "mode": "standard",
                    "generate_reel": generate_reel,
                    "generate_linkedin": True,
                },
            )

        logger.info("job_submitted", backend="celery", job_id=task.id, mode=mode)
        return {"job_id": task.id, "status": "queued", "backend": "celery"}

    except HTTPException:
        raise
    except Exception as e:
        if mode == "standard":
            from api.scheduler import submit_generate_job
            job_id = submit_generate_job(paths, event_name, event_description)
            return {"job_id": job_id, "status": "pending", "backend": "apscheduler"}
        if source_root is not None:
            shutil.rmtree(source_root, ignore_errors=True)
        raise HTTPException(status_code=503, detail=f"Fast {mode} generation requires Celery/Redis: {e}")


# ── Job status & result ───────────────────────────────────────────────────────

def _try_load_job_from_redis(job_id: str) -> Optional[dict]:
    """Read job status/progress from Redis written by Celery tasks."""
    try:
        import redis
        import json as _json
        from config import settings as _settings

        r = redis.from_url(_settings.redis_url, socket_connect_timeout=1)
        data = r.get(f"job:{job_id}")
        if not data:
            return None
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="ignore")
        payload = _json.loads(data)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


@app.get("/api/jobs/{job_id}/status")
async def job_status(job_id: str):
    """
    Poll job status. Works for both Celery and APScheduler jobs.
    Returns: {job_id, status, progress: {step, pct}, backend, error?}
    """
    # 1) Redis — most up-to-date, written by Celery tasks
    redis_job = _try_load_job_from_redis(job_id)
    if redis_job and redis_job.get("status"):
        return safe_jsonify({
            "job_id": job_id,
            "status": redis_job.get("status"),
            "progress": redis_job.get("progress", {}) or {},
            "backend": "redis",
            "error": redis_job.get("error"),
            "result": redis_job.get("result"),
        })

    # 2) Celery AsyncResult state (fallback)
    try:
        from celery.result import AsyncResult
        from api.worker import celery_app
        result = AsyncResult(job_id, app=celery_app)
        info   = result.info or {}
        return safe_jsonify({
            "job_id":   job_id,
            "status":   result.state,
            "progress": info if isinstance(info, dict) else {},
            "backend":  "celery",
            "error":    str(info) if result.state == "FAILURE" else None,
        })
    except Exception as e:
        # 3) APScheduler in-memory store (fallback for scheduler jobs)
        from api.scheduler import get_job
        job = get_job(job_id)
        if job:
            return safe_jsonify({
                "job_id":   job_id,
                "status":   job["status"],
                "progress": job.get("progress", {}),
                "backend":  "apscheduler",
                "error":    job.get("error"),
            })
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found: {e}")


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancel a stuck job (Celery revoke + mark Redis)."""
    # Cancel Celery job (best-effort)
    try:
        from celery.result import AsyncResult
        from api.worker import celery_app
        result = AsyncResult(job_id, app=celery_app)
        result.revoke(terminate=True)
    except Exception:
        pass

    # Mark Redis job state for UI
    try:
        import redis
        import json
        from config import settings as _settings
        r = redis.from_url(_settings.redis_url, socket_connect_timeout=1)
        payload = {"status": "cancelled", "error": "Cancelled by user"}
        r.setex(f"job:{job_id}", 86400, json.dumps(payload))
    except Exception:
        pass

    return safe_jsonify({"job_id": job_id, "status": "cancelled"})


@app.get("/api/jobs/{job_id}/result")
async def job_result(job_id: str):
    """Retrieve completed job result (both backends).

    Priority order:
      1) Redis payload written by workers (CELERY) — if status=SUCCESS and result exists.
      2) APScheduler in-memory store.
      3) Celery AsyncResult.
    """

    # 1) Redis (most reliable if job:{job_id} exists)
    redis_job = _try_load_job_from_redis(job_id)
    if redis_job:
        if redis_job.get("status") in ("SUCCESS", "completed"):
            # Redis payloads may store the full output under `result`.
            redis_result = redis_job.get("result")
            if redis_result is not None:
                return safe_jsonify(redis_result)

            # If status is SUCCESS but result is missing, do not lie to the frontend.
            # Return a consistent terminal error.
            raise HTTPException(
                status_code=500,
                detail="Job marked SUCCESS but no result payload found in Redis.",
            )
        elif redis_job.get("status") in ("PROGRESS", "pending", "queued", "STARTED", "running"):
            return {"job_id": job_id, "status": redis_job.get("status"), "message": "Job not yet complete"}

    # 2) APScheduler store
    from api.scheduler import get_job
    job = get_job(job_id)
    if job:
        if job["status"] == "completed":
            return safe_jsonify(job["result"])

        elif job["status"] == "failed":
            raise HTTPException(status_code=500, detail=job.get("error", "Job failed"))
        else:
            return {"job_id": job_id, "status": job["status"], "message": "Job not yet complete"}

    # 3) Celery
    try:
        from celery.result import AsyncResult
        from api.worker import celery_app
        result = AsyncResult(job_id, app=celery_app)
        if result.state == "SUCCESS":
            return safe_jsonify(result.result)

        elif result.state == "FAILURE":
            raise HTTPException(status_code=500, detail=str(result.info))
        else:
            return {"job_id": job_id, "status": result.state, "message": "Job not yet complete"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))



# ── WebSocket — real-time job updates ─────────────────────────────────────────

@app.get("/api/ml/status")
async def get_ml_status():
    """Check if ML models are loaded and working"""
    status = {
        'models_loaded': False,
        'quality_assessor': False,
        'face_detector': False,
        'content_understander': False,
        'errors': []
    }

    try:
        from content_engine.models.quality import QualityAssessor
        qa = QualityAssessor()
        status['quality_assessor'] = True

        from content_engine.models.face_detection import FaceDetector
        fd = FaceDetector()
        status['face_detector'] = True

        from content_engine.models.content_understanding import ContentUnderstander
        cu = ContentUnderstander()
        status['content_understander'] = True

        status['models_loaded'] = True

    except Exception as e:
        status['errors'].append(str(e))

    return status


@app.websocket("/ws/jobs/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """
    Push job status updates over WebSocket every second.
    Closes automatically when the job reaches a terminal state.
    """
    await websocket.accept()
    try:
        while True:
            status_data = await job_status(job_id)
            await websocket.send_json(safe_jsonify(status_data))
            if status_data.get("status") in ("completed", "SUCCESS", "failed", "FAILURE"):
                break
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ── Asset categorization & generation from selected assets ────────────────────

@app.get("/api/assets/enhanced/{job_id}")
async def get_enhanced_assets(
    job_id: str,
    top_n_overall: int = 10,
    top_n_per_category: int = 3
):
    """Returns deduplicated top assets + per-category with layout metadata."""
    from pathlib import Path
    from PIL import Image
    import imagehash

    # Get full job data first
    job_data = None
    assets = None
    redis_job = _try_load_job_from_redis(job_id)
    if redis_job:
        # Check both top-level job and result for assets
        job_data = redis_job
        assets = job_data.get('assets') or (job_data.get('result') or {}).get('assets')
        if not assets:
            # If job is still processing, return pending
            if redis_job.get("status") not in ("SUCCESS", "completed"):
                return {
                    'job_id': job_id,
                    'top_overall': [],
                    'per_category': {},
                    'stats': {
                        'total': 0,
                        'unique': 0,
                        'deduped': 0,
                        'duplicates_removed': 0,
                        'pending_processing': True
                    }
                }

    # 2) APScheduler fallback
    if not assets:
        from api.scheduler import get_job
        scheduler_job = get_job(job_id)
        if scheduler_job:
            job_data = scheduler_job
            assets = job_data.get('assets') or (job_data.get('result') or {}).get('assets')
            if scheduler_job.get("status") == "failed":
                raise HTTPException(status_code=500, detail=scheduler_job.get("error", "Job failed"))
            elif scheduler_job.get("status") not in ("completed", "SUCCESS") or not assets:
                return {
                    'job_id': job_id,
                    'top_overall': [],
                    'per_category': {},
                    'stats': {
                        'total': 0,
                        'unique': 0,
                        'deduped': 0,
                        'duplicates_removed': 0,
                        'pending_processing': True
                    }
                }

    # 3) Celery AsyncResult fallback
    if not assets:
        try:
            from celery.result import AsyncResult
            from api.worker import celery_app
            result = AsyncResult(job_id, app=celery_app)
            if result.ready():
                job_data = result.result
                assets = (job_data or {}).get('assets')
            else:
                raise HTTPException(400, "Job not completed yet")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(404, "Job not found") from e

    # Normalize assets list
    all_assets = list(assets or [])

    has_real_scores = any(a.get('final_score', 0) > 0.0 and a.get('final_score', 0) != 0.7 for a in all_assets[:5])
    if not has_real_scores:
        return {
            'job_id': job_id,
            'top_overall': [],
            'per_category': {},
            'stats': {
                'total': len(all_assets),
                'unique': 0,
                'deduped': 0,
                'duplicates_removed': 0,
                'pending_processing': True
            }
        }


    all_assets.sort(key=lambda x: x.get('final_score', 0), reverse=True)

    def get_image_hash(path):
        try:
            img = Image.open(path)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            img = img.resize((128, 128))
            return str(imagehash.phash(img, hash_size=8))
        except Exception:
            return None

    unique_assets = []
    seen_hashes = set()
    duplicate_count = 0

    for asset in all_assets:
        asset_path = asset.get('path')
        if not asset_path:
            continue

        asset_hash = get_image_hash(asset_path)
        if asset_hash:
            hash_prefix = asset_hash[:8]
            if hash_prefix not in seen_hashes:
                seen_hashes.add(hash_prefix)
                unique_assets.append(asset)
            else:
                duplicate_count += 1
        else:
            unique_assets.append(asset)

    top_overall = []
    for asset in unique_assets[:top_n_overall]:
        top_overall.append({
            'id': asset.get('id', ''),
            'url': f"/uploads/{Path(asset.get('path', '')).name}",
            'score': asset.get('final_score', 0),
            'faces': asset.get('face_count', 0),
            'concepts': asset.get('scene_concepts', [])[:3]
        })

    category_keywords = {
        'stage': {'keywords': ['stage', 'presentation', 'podium', 'speaker', 'keynote', 'talk', 'lecture', 'platform'], 'icon': '🎤'},
        'booth': {'keywords': ['booth', 'exhibit', 'display', 'stand', 'kiosk', 'table', 'setup', 'counter'], 'icon': '🏪'},
        'crowd': {'keywords': ['crowd', 'audience', 'people', 'attendees', 'mass', 'gathering', 'spectators', 'viewers'], 'icon': '👥'},
        'speakers': {'keywords': ['speaker', 'presenter', 'host', 'moderator', 'panel', 'lecturer', 'guest'], 'icon': '🎙️'},
        'networking': {'keywords': ['networking', 'conversation', 'handshake', 'meeting', 'chat', 'discussion', 'interaction'], 'icon': '🤝'},
        'awards': {'keywords': ['award', 'trophy', 'winner', 'prize', 'ceremony', 'medal', 'recognition'], 'icon': '🏆'},
    }

    per_category = {}
    for cat_id, cat_info in category_keywords.items():
        cat_assets = []
        for asset in unique_assets[:30]:
            concepts = ' '.join(asset.get('scene_concepts', [])).lower()
            if any(kw in concepts for kw in cat_info['keywords']):
                cat_assets.append({
                    'id': asset.get('id', ''),
                    'url': f"/uploads/{Path(asset.get('path', '')).name}",
                    'score': asset.get('final_score', 0),
                    'faces': asset.get('face_count', 0),
                    'concepts': asset.get('scene_concepts', [])[:3]
                })
        cat_assets.sort(key=lambda x: x['score'], reverse=True)
        per_category[cat_id] = {
            'name': cat_id.capitalize(),
            'icon': cat_info['icon'],
            'color': '#e8f5e9' if cat_id == 'booth' else '#e3f2fd',
            'assets': cat_assets[:top_n_per_category]
        }

    return {
        'job_id': job_id,
        'top_overall': top_overall,
        'per_category': per_category,
        'stats': {
            'total': len(all_assets),
            'unique': len(unique_assets),
            'deduped': duplicate_count,
            'duplicates_removed': duplicate_count,
            'has_real_scores': has_real_scores
        }
    }

@app.get("/api/assets/categorized/{job_id}")
async def get_categorized_assets(job_id: str):
    """Get AI-categorized assets from completed job."""
    from collections import defaultdict
    from pathlib import Path

    from api.scheduler import get_job
    job_data = get_job(job_id)
    if not job_data:
        try:
            from celery.result import AsyncResult
            from api.worker import celery_app
            result = AsyncResult(job_id, app=celery_app)
            if result.ready():
                job_data = {"status": "completed", "result": result.result, "assets": []}
            else:
                raise HTTPException(400, "Job not completed yet")
        except Exception as e:
            raise HTTPException(404, "Job not found") from e

    if job_data.get('status') not in ('completed', 'SUCCESS'):
        raise HTTPException(400, "Job not completed yet")

    assets = list(job_data.get('assets') or [])

    # Check if assets have real scores
    has_real_scores = any(a.get('final_score', 0) > 0.0 and a.get('final_score', 0) != 0.7 for a in assets[:5])
    if not has_real_scores:
        return {
            'job_id': job_id,
            'categories': {},
            'category_counts': {},
            'top_assets': [],
            'total_assets': len(assets),
            'pending_processing': True
        }

    # Define category keywords for scene matching (expanded for better matching)
    category_keywords = {
        'stage': ['stage', 'presentation', 'podium', 'speaker', 'keynote', 'talk', 'lecture', 'platform'],
        'booth': ['booth', 'exhibit', 'display', 'stand', 'kiosk', 'table', 'setup', 'counter'],
        'crowd': ['crowd', 'audience', 'people', 'attendees', 'mass', 'gathering', 'spectators', 'viewers'],
        'speakers': ['speaker', 'presenter', 'host', 'moderator', 'panel', 'lecturer', 'guest'],
        'networking': ['networking', 'conversation', 'group', 'meeting', 'handshake', 'chat', 'discussion', 'interaction'],
        'awards': ['award', 'trophy', 'winner', 'prize', 'ceremony', 'medal', 'recognition'],
        'product': ['product', 'launch', 'demo', 'showcase', 'display']
    }

    # Categorize each asset
    categorized = defaultdict(list)
    top_assets = []

    for asset in assets:
        asset_score = asset.get('final_score', 0.5)
        scene_concepts = asset.get('scene_concepts', [])
        asset_path = asset.get('path', '')
        asset_id = asset.get('id', '')

        if not asset_path or not asset_id:
            continue

        # Determine category
        assigned_category = 'other'
        concepts_str = ' '.join(scene_concepts).lower()
        for category, keywords in category_keywords.items():
            if any(kw in concepts_str for kw in keywords):
                assigned_category = category
                break

        asset_info = {
            'id': asset_id,
            'url': f"/uploads/{Path(asset_path).name}",
            'score': asset_score,
            'face_count': asset.get('face_count', 0),
            'concepts': scene_concepts[:3],
            'category': assigned_category
        }

        categorized[assigned_category].append(asset_info)
        top_assets.append(asset_info)

    # Sort top assets by score
    top_assets.sort(key=lambda x: x['score'], reverse=True)
    top_assets = top_assets[:10]

    # Get category counts
    category_counts = {cat: len(cat_assets) for cat, cat_assets in categorized.items()}

    return {
        'job_id': job_id,
        'categories': dict(categorized),
        'category_counts': category_counts,
        'top_assets': top_assets,
        'total_assets': len(assets)
    }


@app.post("/api/generate/from-selected")
async def generate_from_selected(request: Request):
    """Generate content using only user-selected assets."""
    from content_engine.orchestrator import ContentOrchestrator
    import tempfile
    import shutil
    from datetime import datetime
    
    body = await request.json()
    job_id = body.get('job_id')
    selected_asset_ids = body.get('selected_asset_ids', [])
    
    # Get job data from APScheduler or Redis
    from api.scheduler import get_job
    job_data = get_job(job_id)
    if not job_data:
        raise HTTPException(404, "Job not found")
    
    # Find selected asset paths
    all_assets = list(job_data.get('assets') or [])
    selected_paths = []
    for asset in all_assets:
        asset_id = asset.get('id')
        asset_path = asset.get('path')
        if asset_id and asset_path and asset_id in selected_asset_ids:
            selected_paths.append(asset_path)
    
    if not selected_paths:
        raise HTTPException(400, "No assets selected")
    
    # Create temp directory with selected assets
    temp_dir = tempfile.mkdtemp()
    temp_asset_paths = []
    try:
        for src_path in selected_paths:
            src_p = Path(src_path)
            if src_p.exists():
                dst_path = Path(temp_dir) / src_p.name
                shutil.copy(src_p, dst_path)
                temp_asset_paths.append(str(dst_path))
        
        if not temp_asset_paths:
            raise HTTPException(400, "No valid assets found")
        
        # Run orchestrator on selected assets only
        orchestrator = ContentOrchestrator(
            event_name=job_data.get('event_name', 'Event'),
            event_description=job_data.get('event_description', '')
        )
        
        output_dir = orchestrator.run(
            temp_dir,
            output_root="output"
        )
        
        # Prepare output payload
        from config import settings
        event_slug = output_dir.name
        output_files = {}
        captions = {}
        root = settings.output_dir.resolve()
        
        for f in sorted(output_dir.rglob("*")):
            if not f.is_file():
                continue
            try:
                rel = f.resolve().relative_to(root)
                web_url = f"/output/{rel.as_posix()}"
            except Exception:
                web_url = str(f.resolve())
            
            output_files[f.name] = web_url
            if f.suffix in (".txt", ".md", ".json"):
                try:
                    captions[f.stem] = f.read_text(encoding="utf-8").strip()
                except Exception:
                    pass
        
        return {
            'job_id': job_id,
            'output_dir': str(output_dir),
            'selected_count': len(selected_paths),
            'status': 'completed',
            'event': job_data.get('event_name', 'Event'),
            'files': output_files,
            'captions': captions
        }
    finally:
        # Cleanup temp dir
        shutil.rmtree(temp_dir, ignore_errors=True)


from pydantic import BaseModel


class CustomGenerateRequest(BaseModel):
    job_id: str
    asset_ids: list[str]
    linkedin_layout: str = "hero_right"
    story_layout: str = "single"
    reel_layout: str = "standard"


@app.post("/api/generate/custom")
async def generate_custom(request: CustomGenerateRequest):
    """Generate with selected layout and selected assets"""
    from content_engine.orchestrator import ContentOrchestrator
    
    # Get job data from APScheduler or Redis
    from api.scheduler import get_job
    job_data = get_job(request.job_id)
    if not job_data:
        raise HTTPException(404, "Job not found")
    
    # Find selected asset paths
    all_assets = list(job_data.get('assets') or [])
    selected_paths = []
    for asset in all_assets:
        asset_id = asset.get('id')
        asset_path = asset.get('path')
        if asset_id and asset_path and asset_id in request.asset_ids:
            selected_paths.append(asset_path)
    
    if not selected_paths:
        raise HTTPException(400, "No assets selected")
    
    # Validate that all selected paths exist
    valid_paths = []
    for path in selected_paths:
        if Path(path).exists():
            valid_paths.append(path)
    
    if not valid_paths:
        raise HTTPException(400, "No valid assets found (files may have been deleted)")
    
    # Run orchestrator on selected assets only with selected layouts
    orchestrator = ContentOrchestrator(
        event_name=job_data.get('event_name', 'Event'),
        event_description=job_data.get('event_description', '')
    )
    
    output_dir = orchestrator.run_with_selected_assets(
        valid_paths,
        output_root="output",
        linkedin_layout=request.linkedin_layout,
        story_layout=request.story_layout,
        reel_layout=request.reel_layout
    )
    
    # Prepare output payload
    from config import settings
    output_files = {}
    captions = {}
    root = settings.output_dir.resolve()
    
    for f in sorted(output_dir.rglob("*")):
        if not f.is_file():
            continue
        try:
            rel = f.resolve().relative_to(root)
            web_url = f"/output/{rel.as_posix()}"
        except Exception:
            web_url = str(f.resolve())
        
        output_files[f.name] = web_url
        if f.suffix in (".txt", ".md", ".json"):
            try:
                captions[f.stem] = f.read_text(encoding="utf-8").strip()
            except Exception:
                pass
    
    return safe_jsonify({
        'job_id': request.job_id,

        'output_dir': str(output_dir),
        'linkedin_layout': request.linkedin_layout,
        'story_layout': request.story_layout,
        'reel_layout': request.reel_layout,
        'selected_count': len(valid_paths),
        'status': 'completed',
        'event': job_data.get('event_name', 'Event'),
        'files': output_files,
        'captions': captions
    })


class LayoutPreviewRequest(BaseModel):
    job_id: str
    layout_type: str
    layout_id: str
    asset_ids: list[str]


@app.post("/api/layout/preview")
async def get_layout_preview(request: LayoutPreviewRequest):
    """
    Generate a preview image for selected layout with selected assets (with caching).
    """
    from PIL import Image, ImageDraw
    import base64
    import hashlib

    # Generate cache key
    sorted_asset_ids = sorted(request.asset_ids)
    cache_key = hashlib.md5(
        f"{request.layout_type}-{request.layout_id}-{'-'.join(sorted_asset_ids)}".encode()
    ).hexdigest()

    # Check cache first
    if cache_key in _preview_cache:
        return safe_jsonify({"preview_url": _preview_cache[cache_key]})


    # Get job data from APScheduler or Redis
    from api.scheduler import get_job
    job_data = get_job(request.job_id)
    if not job_data:
        raise HTTPException(404, "Job not found")

    # Find selected asset paths
    all_assets = list(job_data.get('assets') or [])
    selected_paths = []
    for asset in all_assets:
        asset_id = asset.get('id')
        asset_path = asset.get('path')
        if asset_id and asset_path and asset_id in request.asset_ids:
            selected_paths.append(asset_path)

    if not selected_paths:
        return safe_jsonify({"preview_url": None, "error": "No assets selected"})


    # Validate paths exist
    valid_paths = [p for p in selected_paths if Path(p).exists()]
    if not valid_paths:
        return safe_jsonify({"preview_url": None, "error": "No valid assets found"})


    assembler = None
    try:
        from content_engine.layout_assembler import LayoutAssembler
        assembler = LayoutAssembler()

        preview_img = None
        if request.layout_type == 'linkedin':
            preview_img = assembler.create_linkedin_collage(valid_paths[:6], request.layout_id)
            preview_img.thumbnail((300, 300), Image.Resampling.LANCZOS)
        elif request.layout_type == 'story':
            # For stories, just take first story preview
            stories = assembler.create_instagram_stories(valid_paths[:4], ["Preview"] * 4, None, request.layout_id)
            preview_img = stories[0]
            preview_img.thumbnail((200, 355), Image.Resampling.LANCZOS)
        elif request.layout_type == 'reel':
            # For reel, return a placeholder
            preview_img = Image.new('RGB', (200, 355), color='#1a1a24')
            draw = ImageDraw.Draw(preview_img)
            draw.text((100, 177), "Reel Preview", fill='white', anchor='mm')

        # Convert to base64 with lower quality for speed
        buffer = io.BytesIO()
        preview_img.save(buffer, format='JPEG', quality=70)
        img_base64 = base64.b64encode(buffer.getvalue()).decode()
        preview_url = f"data:image/jpeg;base64,{img_base64}"

        # Cache the preview
        if len(_preview_cache) >= _MAX_CACHE_SIZE:
            # Remove oldest entry if cache is full
            first_key = next(iter(_preview_cache))
            del _preview_cache[first_key]
        _preview_cache[cache_key] = preview_url

        return safe_jsonify({"preview_url": preview_url})


    except Exception as e:
        logger.error(f"Preview generation failed: {e}")
        return safe_jsonify({"preview_url": None, "error": str(e)})



@app.get("/api/jobs/{job_id}/case-study/enriched")
async def get_enriched_case_study(job_id: str):
    """Returns structured, enriched case study data for the frontend report."""
    from api.scheduler import get_job
    from collections import defaultdict
    import traceback

    try:
        job_data = get_job(job_id)
        if not job_data:
            try:
                from celery.result import AsyncResult
                from api.worker import celery_app
                result = AsyncResult(job_id, app=celery_app)
                if result.ready():
                    job_data = {"status": "completed", "result": result.result, "assets": []}
                else:
                    raise HTTPException(400, "Job not completed yet")
            except Exception as e:
                raise HTTPException(404, "Job not found") from e

        if job_data.get('status') not in ('completed', 'SUCCESS'):
            raise HTTPException(400, "Job not completed yet")

        all_assets = list(job_data.get('assets') or [])
        total_assets = len(all_assets)
        has_real_scores = any(a.get('final_score', 0) > 0.0 and a.get('final_score', 0) != 0.7 for a in all_assets[:5])

        avg_quality_score = 0.0
        avg_aesthetic_score = 0.0
        avg_face_count = 0
        category_distribution = defaultdict(int)
        top_assets = []
        rejected_assets = []

        if all_assets:
            def _to_float(v, default: float = 0.0) -> float:
                try:
                    if v is None:
                        return default
                    return float(v)
                except Exception:
                    return default

            def _to_int(v, default: int = 0) -> int:
                try:
                    if v is None:
                        return default
                    return int(v)
                except Exception:
                    return default

            quality_scores: list[float] = []
            aesthetic_scores: list[float] = []
            face_counts: list[int] = []

            category_keywords = {
                'stage': ['stage', 'presentation', 'podium', 'speaker', 'keynote', 'talk', 'lecture', 'platform'],
                'booth': ['booth', 'exhibit', 'display', 'stand', 'kiosk', 'table', 'setup', 'counter'],
                'crowd': ['crowd', 'audience', 'people', 'attendees', 'mass', 'gathering', 'spectators', 'viewers'],
                'speakers': ['speaker', 'presenter', 'host', 'moderator', 'panel', 'lecturer', 'guest'],
                'networking': ['networking', 'conversation', 'group', 'meeting', 'handshake', 'chat', 'discussion', 'interaction'],
                'awards': ['award', 'trophy', 'winner', 'prize', 'ceremony', 'medal', 'recognition'],
            }

            for asset in all_assets:
                try:
                    final_score = _to_float(asset.get('final_score', 0), 0.0)

                    # If quality_score/aesthetic_score are missing, use final_score as fallback
                    qs = asset.get('quality_score', None)
                    aes = asset.get('aesthetic_score', None)
                    qs = _to_float(qs, final_score * 0.8)
                    aes = _to_float(aes, final_score * 0.7)

                    face_count = _to_int(asset.get('face_count', 0), 0)

                    quality_scores.append(qs)
                    aesthetic_scores.append(aes)
                    face_counts.append(face_count)

                    # Determine category
                    raw_concepts = asset.get('scene_concepts', [])
                    if raw_concepts is None:
                        raw_concepts = []
                    if not isinstance(raw_concepts, list):
                        raw_concepts = [str(raw_concepts)]

                    concepts_str = ' '.join([str(c) for c in raw_concepts]).lower()
                    asset_category = 'other'
                    for cat, keywords in category_keywords.items():
                        if any(kw in concepts_str for kw in keywords):
                            asset_category = cat
                            break
                    category_distribution[asset_category] += 1

                    # Build asset info
                    asset_path = asset.get('path', '')
                    asset_info = {
                        'id': asset.get('id', ''),
                        'url': f"/uploads/{Path(asset_path).name}" if asset_path else '',
                        'filename': asset.get('filename', ''),
                        'score': final_score,
                        'quality_score': qs,
                        'aesthetic_score': aes,
                        'faces': face_count,
                        'concepts': (raw_concepts[:3] if raw_concepts else []),
                        'category': asset_category,
                        'low_confidence': final_score < 0.5
                    }

                    if final_score >= 0.5:
                        top_assets.append(asset_info)
                    else:
                        rejected_assets.append(asset_info)
                except Exception:
                    # Skip problematic asset instead of failing the whole endpoint
                    continue

            avg_quality_score = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0
            avg_aesthetic_score = sum(aesthetic_scores) / len(aesthetic_scores) if aesthetic_scores else 0.0
            avg_face_count = sum(face_counts) / len(face_counts) if face_counts else 0.0

            # Sort top assets by score
            top_assets.sort(key=lambda x: _to_float(x.get('score', 0), 0.0), reverse=True)
            rejected_assets.sort(key=lambda x: _to_float(x.get('score', 0), 0.0), reverse=True)


        return {
            'job_id': job_id,
            'event_name': job_data.get('event_name', 'Event'),
            'date': job_data.get('updated_at', datetime.now().isoformat()),
            'total_assets': total_assets,
            'selected_assets_count': len(top_assets),
            'avg_quality_score': avg_quality_score,
            'avg_aesthetic_score': avg_aesthetic_score,
            'avg_face_count': avg_face_count,
            'category_distribution': dict(category_distribution),
            'duplicates_removed': 0,
            'low_confidence_count': len(rejected_assets),
            'top_assets': top_assets[:10],
            'rejected_assets_sample': rejected_assets[:5],
            'brand_segregation': None,
            'processing_time_seconds': 0,
            'selection_logic_summary': 'Assets scored on technical quality, aesthetic quality, face presence, and event-concept relevance.',
            'has_real_scores': bool(has_real_scores)
        }
    except Exception as e:
        logger.error(f"Enriched case study failed for job {job_id}: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


# Add GFF router
from api.gff_routes import router as gff_router
app.include_router(gff_router)

# Add Studio router
try:
    from api.studio_routes import router as studio_router
    app.include_router(studio_router)
except Exception as e:
    pass

# Add Photo Intelligence router
try:
    from api.photo_intelligence_routes import router as photo_intel_router
    app.include_router(photo_intel_router)
except Exception as e:
    pass

# ── Brand threshold control ────────────────────────────────────────────────────

class BrandThresholdRequest(BaseModel):
    threshold: float


@app.post("/api/brand/threshold/{job_id}")
async def set_brand_threshold(job_id: str, req: BrandThresholdRequest):
    """Set custom brand similarity threshold for a specific job (0.30-0.80)."""
    if req.threshold < 0.30 or req.threshold > 0.80:
        raise HTTPException(
            status_code=400,
            detail="Threshold must be between 0.30 and 0.80"
        )
    from api.scheduler import set_job_threshold
    set_job_threshold(job_id, req.threshold)
    logger.info("brand_threshold_set", job_id=job_id, threshold=req.threshold)
    return {"job_id": job_id, "threshold": req.threshold}


@app.get("/api/brand/threshold/{job_id}")
async def get_brand_threshold(job_id: str):
    """Get the current brand similarity threshold for a job."""
    from api.scheduler import get_job_threshold
    from config import settings
    threshold = get_job_threshold(job_id, default=settings.brand_similarity_threshold)
    return {"job_id": job_id, "threshold": threshold}

# ── Synchronous generate (testing / small batches) ────────────────────────────

@app.post("/api/generate")
async def generate_content(
    files: List[UploadFile] = File(...),
    event_name: str = Form("Event"),
    event_description: str = Form("Event"),
):
    paths = [str(p) for p in await validate_uploads(files)]
    return await _sync_generate(paths, event_name, event_description)


# ── Groq caption regeneration (on-demand, no ML needed) ──────────────────────

@app.post("/api/captions/regenerate")
async def regenerate_captions(
    event_name: str = Form(...),
    event_description: str = Form(""),
    platform: str = Form("all"),
    scene_concepts: str = Form(""),
    face_count: int = Form(0),
):
    """Regenerate captions using Qwen2.5-1.5B-Instruct only."""
    from content_engine.copy_generator import CopyGenerator
    from content_engine.data_types import AssetMetadata

    concepts = [c.strip() for c in scene_concepts.split(",") if c.strip()]
    relevance = {c: 0.8 for c in concepts}

    synthetic_asset = AssetMetadata(
        path="synthetic",
        asset_type="image",
        quality_score=0.8,
        aesthetic_score=0.7,
        face_count=face_count,
        face_confidences=[0.9] * min(face_count, 5),
        relevance_scores=relevance,
        scene_concepts=concepts,
        final_score=0.75,
    )
    assets = [synthetic_asset]

    try:
        gen = CopyGenerator()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Qwen unavailable: {e}")

    result: dict = {"backend": gen.backend, "event": event_name, "provider": "qwen2.5-1.5b-instruct"}

    try:
        if platform in ("linkedin", "all"):
            result["linkedin"] = gen.generate_linkedin_caption(event_name, assets, event_description)
        if platform in ("instagram", "all"):
            result["instagram"] = gen.generate_instagram_caption(event_name, assets, event_description)
        if platform in ("reel", "all"):
            result["reel"] = gen.generate_reel_caption(event_name, assets, event_description)
        if platform in ("stories", "all"):
            result["stories"] = gen.generate_story_captions(event_name, 4, assets, event_description)
    except Exception as e:
        logger.error(f"Caption regeneration failed: {e}")
        raise HTTPException(status_code=503, detail=str(e))

    return result


async def _sync_generate(paths, event_name, event_description):
    import tempfile
    tmp_dir = Path(tempfile.mkdtemp(prefix="ce_gen_"))
    try:
        for p in paths:
            shutil.copy(p, tmp_dir / Path(p).name)
        from content_engine.orchestrator import ContentOrchestrator
        orch    = ContentOrchestrator(event_name=event_name, event_description=event_description)
        out_dir = orch.run(str(tmp_dir), output_root=str(settings.output_dir))
        output_files = {f.name: str(f.resolve()) for f in sorted(out_dir.iterdir()) if f.is_file()}
        return safe_jsonify({"event": event_name, "output_dir": str(out_dir.resolve()), "files": output_files})

    except Exception as e:
        logger.error(f"Generate failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _serialise_selections(selections) -> list:
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
    return results


if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
        log_level=settings.log_level.lower(),
    )
