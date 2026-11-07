"""
Central configuration — reads from .env file.
Import this everywhere instead of hardcoding values.

Usage:
    from config import settings
    print(settings.upload_dir)
    print(settings.celery_broker_url)
"""

import os
from pathlib import Path
from typing import List

# Load .env from the same directory as this file (works regardless of cwd)
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent / ".env"
    load_dotenv(_env_path if _env_path.exists() else None)
except ImportError:
    pass


def _list(key: str, default: str) -> List[str]:
    """Parse a comma-separated env var into a list of stripped strings."""
    raw = os.getenv(key, default)
    return [s.strip() for s in raw.split(",") if s.strip()]


class Settings:
    def __init__(self):
        # ── Server ────────────────────────────────────────────────────────────
        self.api_host: str   = os.getenv("API_HOST", "0.0.0.0")
        self.api_port: int   = int(os.getenv("API_PORT", "8000"))
        self.api_workers: int = int(os.getenv("API_WORKERS", "1"))
        self.log_level: str  = os.getenv("LOG_LEVEL", "INFO")

        # ── CORS ──────────────────────────────────────────────────────────────
        self.cors_origins: List[str] = _list("CORS_ORIGINS", "http://localhost:5173")

        # ── Storage ───────────────────────────────────────────────────────────
        self.upload_dir: Path      = Path(os.getenv("UPLOAD_DIR",      "uploads"))
        self.output_dir: Path      = Path(os.getenv("OUTPUT_DIR",      "output"))
        self.model_cache_dir: Path = Path(os.getenv("MODEL_CACHE_DIR", "models"))
        self.log_dir: Path         = Path(os.getenv("LOG_DIR",         "logs"))
        self.max_file_size_mb: int = int(os.getenv("MAX_FILE_SIZE_MB", "200"))

        # ── Cleanup ───────────────────────────────────────────────────────────
        self.upload_retention_days: int = int(os.getenv("UPLOAD_RETENTION_DAYS", "7"))
        self.output_retention_days: int = int(os.getenv("OUTPUT_RETENTION_DAYS", "30"))

        # ── ML thresholds ─────────────────────────────────────────────────────
        self.face_confidence_threshold: float  = float(os.getenv("FACE_CONFIDENCE_THRESHOLD", "0.35"))
        self.quality_min_score: float          = float(os.getenv("QUALITY_MIN_SCORE", "0.30"))
        self.quality_blur_threshold: float     = float(os.getenv("QUALITY_BLUR_THRESHOLD", "300"))
        self.face_size_weight_threshold: float = float(os.getenv("FACE_SIZE_WEIGHT_THRESHOLD", "0.05"))
        self.brand_similarity_threshold: float = float(os.getenv("BRAND_SIMILARITY_THRESHOLD", "0.45"))
        self.brand_use_logo_detection: bool    = os.getenv("BRAND_USE_LOGO_DETECTION", "true").lower() == "true"
        self.brand_use_llm_fallback: bool      = os.getenv("BRAND_USE_LLM_FALLBACK", "true").lower() == "true"

        # ── Redis ─────────────────────────────────────────────────────────────
        self.redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

        # ── Celery ────────────────────────────────────────────────────────────
        self.celery_broker_url: str     = os.getenv("CELERY_BROKER_URL",     "redis://localhost:6379/0")
        self.celery_result_backend: str = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")
        self.celery_worker_concurrency: int         = int(os.getenv("CELERY_WORKER_CONCURRENCY", "1"))
        self.celery_worker_max_tasks_per_child: int = int(os.getenv("CELERY_WORKER_MAX_TASKS_PER_CHILD", "50"))
        self.celery_task_time_limit: int      = int(os.getenv("CELERY_TASK_TIME_LIMIT", "600"))
        self.celery_task_soft_time_limit: int = int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "540"))

        # ── Flower ────────────────────────────────────────────────────────────
        self.flower_port: int      = int(os.getenv("FLOWER_PORT", "5555"))
        self.flower_enabled: bool  = os.getenv("FLOWER_ENABLED", "true").lower() == "true"
        self.flower_user: str      = os.getenv("FLOWER_USER", "admin")
        self.flower_password: str  = os.getenv("FLOWER_PASSWORD", "admin")

        # ── Monitoring ────────────────────────────────────────────────────────
        self.sentry_dsn: str = os.getenv("SENTRY_DSN", "")

        # ── Groq LLM ──────────────────────────────────────────────────────────
        self.groq_api_key: str      = os.getenv("GROQ_API_KEY", "")
        self.groq_model: str        = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
        self.groq_service_tier: str = os.getenv("GROQ_SERVICE_TIER", "on_demand")
        self.groq_temperature: float = float(os.getenv("GROQ_TEMPERATURE", "0.7"))

        # ── Groq Vision ───────────────────────────────────────────────────────
        # Only required when AI_EXECUTION_MODE=cloud_testing
        self.groq_vision_model: str = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")

        # ── AI Execution Mode ─────────────────────────────────────────────────
        # local: MLX Qwen + local vision models (final production architecture)
        # cloud_testing: Groq + Gemini APIs, local models bypassed for routed features
        self.ai_execution_mode: str = os.getenv("AI_EXECUTION_MODE", "local")
        self.cloud_llm_provider: str = os.getenv("CLOUD_LLM_PROVIDER", "groq")
        self.cloud_vision_provider: str = os.getenv("CLOUD_VISION_PROVIDER", "gemini")

        # ── Cloud API keys ────────────────────────────────────────────────────
        # Only required when AI_EXECUTION_MODE=cloud_testing
        self.gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
        self.gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

        # ── Allowed MIME types ────────────────────────────────────────────────
        self.allowed_image_types: List[str] = [
            "image/jpeg", "image/png", "image/webp", "image/bmp", "image/tiff",
            "image/gif", "image/heic", "image/heif", "image/avif",
            "image/x-ms-bmp", "image/x-canon-cr2", "image/x-canon-cr3",
            "image/x-nikon-nef", "image/x-sony-arw", "image/x-adobe-dng",
        ]
        self.allowed_video_types: List[str] = [
            "video/mp4", "video/quicktime", "video/x-msvideo",
            "video/x-matroska", "video/webm",
            "video/x-ms-wmv", "video/x-flv", "video/mpeg",
            "video/3gpp", "video/3gpp2", "video/ogg", "video/mp2t",
            "video/x-m4v", "video/x-ms-asf", "video/x-ms-wm",
            "video/dv", "video/x-dv",
        ]
        self.allowed_image_extensions: List[str] = [
            ".jpg", ".jpeg", ".jpe", ".png", ".webp", ".bmp", ".dib",
            ".tif", ".tiff", ".gif", ".heic", ".heif", ".avif", ".jfif",
        ]
        self.allowed_video_extensions: List[str] = [
            ".mp4", ".mov", ".qt", ".avi", ".mkv", ".webm", ".m4v",
            ".wmv", ".flv", ".f4v", ".mpg", ".mpeg", ".mpe", ".m2v",
            ".m2ts", ".mts", ".ts", ".3gp", ".3g2", ".ogv", ".asf",
            ".divx", ".dv", ".vob",
        ]

    # ── Derived properties ────────────────────────────────────────────────────
    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    @property
    def allowed_mime_types(self) -> List[str]:
        return self.allowed_image_types + self.allowed_video_types

    @property
    def allowed_upload_extensions(self) -> List[str]:
        return self.allowed_image_extensions + self.allowed_video_extensions


settings = Settings()

# Ensure required directories exist at import time
for _d in (settings.upload_dir, settings.output_dir, settings.log_dir):
    _d.mkdir(parents=True, exist_ok=True)


# ── Caption Provider Settings ──────────────────────────────────────────────────
CAPTION_PROVIDER_MODE = os.getenv("CAPTION_PROVIDER_MODE", "auto")
CAPTION_USE_LOCAL = os.getenv("CAPTION_USE_LOCAL", "false").lower() == "true"
CAPTION_FORCE_LOCAL = os.getenv("CAPTION_FORCE_LOCAL", "false").lower() == "true"
CAPTION_LOCAL_MODEL = os.getenv("CAPTION_LOCAL_MODEL", "")
CAPTION_ALLOW_GROQ_FALLBACK = os.getenv("CAPTION_ALLOW_GROQ_FALLBACK", "true").lower() == "true"
CAPTION_HISTORICAL_DATA_PATH = os.getenv("CAPTION_HISTORICAL_DATA_PATH", "data/historical")


# ── Qwen Local Model Settings ─────────────────────────────────────────────────
CAPTION_LOCAL_MODEL = os.getenv("CAPTION_LOCAL_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")
CAPTION_LOCAL_MODEL_PATH = os.getenv("CAPTION_LOCAL_MODEL_PATH", "")
CAPTION_MAX_NEW_TOKENS = int(os.getenv("CAPTION_MAX_NEW_TOKENS", "256"))
CAPTION_TEMPERATURE = float(os.getenv("CAPTION_TEMPERATURE", "0.7"))

# Image captioning (Salesforce BLIP). Weights are loaded only when a caption is
# requested; local-only is the safe default and never fetches model files.
BLIP_MODEL_ID = os.getenv("BLIP_MODEL_ID", "Salesforce/blip-image-captioning-base")
BLIP_MODEL_PATH = os.getenv("BLIP_MODEL_PATH", "")
BLIP_LOCAL_FILES_ONLY = os.getenv("BLIP_LOCAL_FILES_ONLY", "true").lower() == "true"
BLIP_MAX_IMAGE_SIDE = int(os.getenv("BLIP_MAX_IMAGE_SIDE", "1024"))
BLIP_MAX_FILE_SIZE_MB = int(os.getenv("BLIP_MAX_FILE_SIZE_MB", "50"))
BLIP_MAX_PIXELS = int(os.getenv("BLIP_MAX_PIXELS", "40000000"))
BLIP_MAX_BATCH_IMAGES = int(os.getenv("BLIP_MAX_BATCH_IMAGES", "20"))


# ── Qwen Local Model Settings (Task 5) ─────────────────────────────────────────
CAPTION_LOCAL_MODEL = os.getenv("CAPTION_LOCAL_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")
CAPTION_LOCAL_MODEL_PATH = os.getenv("CAPTION_LOCAL_MODEL_PATH", "")
