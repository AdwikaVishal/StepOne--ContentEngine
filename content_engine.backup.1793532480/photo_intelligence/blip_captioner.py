"""Lazy, cached BLIP image captioning with bounded and validated input."""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List

from PIL import Image, ImageOps, UnidentifiedImageError

from config import (BLIP_LOCAL_FILES_ONLY, BLIP_MAX_BATCH_IMAGES,
                    BLIP_MAX_FILE_SIZE_MB, BLIP_MAX_IMAGE_SIDE, BLIP_MAX_PIXELS,
                    BLIP_MODEL_ID, BLIP_MODEL_PATH)


class ImageCaptionError(RuntimeError):
    pass


class ImageValidationError(ImageCaptionError):
    pass


class BlipImageCaptioner:
    """A single-process lazy model wrapper. Inject `loader` for unit tests."""
    def __init__(self, model_id: str = BLIP_MODEL_ID, model_path: str = BLIP_MODEL_PATH,
                 local_files_only: bool = BLIP_LOCAL_FILES_ONLY,
                 max_image_side: int = BLIP_MAX_IMAGE_SIDE,
                 max_file_size_mb: int = BLIP_MAX_FILE_SIZE_MB,
                 max_pixels: int = BLIP_MAX_PIXELS,
                 max_batch_images: int = BLIP_MAX_BATCH_IMAGES, loader=None):
        self.model_id = model_id
        self.model_path = model_path or None
        self.local_files_only = local_files_only
        self.max_image_side = max_image_side
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self.max_pixels = max_pixels
        self.max_batch_images = max_batch_images
        self._loader = loader or self._load_transformers
        self._processor = self._model = None
        self._load_error = None
        self._lock = threading.RLock()

    @property
    def model_identifier(self) -> str:
        return self.model_path or self.model_id

    def _load_transformers(self):
        from transformers import BlipForConditionalGeneration, BlipProcessor
        source = self.model_path or self.model_id
        try:
            processor = BlipProcessor.from_pretrained(source, local_files_only=self.local_files_only)
            model = BlipForConditionalGeneration.from_pretrained(source, local_files_only=self.local_files_only)
        except Exception as exc:
            if self.local_files_only:
                raise ImageCaptionError(
                    f"BLIP weights are missing or unreadable at {source}. Install them explicitly, "
                    "or set BLIP_LOCAL_FILES_ONLY=false to allow an on-demand download during captioning. "
                    "Application startup never downloads model weights."
                ) from exc
            raise ImageCaptionError(f"Could not load BLIP model {source}: {exc}") from exc
        return processor, model

    def _get_model(self):
        with self._lock:
            if self._load_error:
                raise self._load_error
            if self._model is None:
                try:
                    self._processor, self._model = self._loader()
                except Exception as exc:
                    self._load_error = exc if isinstance(exc, ImageCaptionError) else ImageCaptionError(f"BLIP model load failed: {exc}")
                    raise self._load_error
            return self._processor, self._model

    def _prepare(self, path: str) -> Image.Image:
        image_path = Path(path)
        if not image_path.is_file():
            raise ImageValidationError(f"Image file does not exist: {path}")
        if image_path.stat().st_size > self.max_file_size_bytes:
            raise ImageValidationError(f"Image exceeds {self.max_file_size_bytes // (1024 * 1024)} MB limit: {path}")
        try:
            with Image.open(image_path) as source:
                source.verify()
            with Image.open(image_path) as source:
                if source.format not in {"JPEG", "PNG", "WEBP", "BMP", "TIFF", "GIF"}:
                    raise ImageValidationError(f"Unsupported image format {source.format!r}: {path}")
                if source.width * source.height > self.max_pixels:
                    raise ImageValidationError(f"Image exceeds {self.max_pixels} pixel limit: {path}")
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((self.max_image_side, self.max_image_side), Image.Resampling.LANCZOS)
                return image
        except ImageValidationError:
            raise
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ImageValidationError(f"Invalid or unreadable image {path}: {exc}") from exc

    def caption(self, path: str, asset_id: str) -> Dict[str, Any]:
        return self.caption_many([{"path": path, "asset_id": asset_id}])[0]

    def caption_many(self, assets: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        entries = list(assets)
        if len(entries) > self.max_batch_images:
            raise ImageValidationError(f"Batch has {len(entries)} images; limit is {self.max_batch_images}.")
        output = []
        # Validate individually and infer serially to bound peak memory on 8 GB systems.
        for entry in entries:
            aid, path = entry.get("asset_id"), entry.get("path")
            row = {"asset_id": aid, "caption": None, "caption_status": "pending",
                   "caption_model": self.model_identifier, "caption_error": None}
            try:
                image = self._prepare(path or "")
                processor, model = self._get_model()
                import torch
                inputs = processor(images=image, return_tensors="pt")
                device = next(model.parameters()).device if hasattr(model, "parameters") else "cpu"
                inputs = {key: value.to(device) if hasattr(value, "to") else value for key, value in inputs.items()}
                with torch.inference_mode():
                    generated = model.generate(**inputs, max_new_tokens=40, num_beams=2)
                row["caption"] = processor.decode(generated[0], skip_special_tokens=True).strip()
                row["caption_status"] = "completed" if row["caption"] else "empty"
                image.close()
            except ImageValidationError as exc:
                row.update(caption_status="invalid_image", caption_error=str(exc))
            except Exception as exc:
                row.update(caption_status="error", caption_error=str(exc))
            output.append(row)
        return output


_default_captioner = None
_default_lock = threading.Lock()


def get_blip_captioner() -> BlipImageCaptioner:
    global _default_captioner
    with _default_lock:
        if _default_captioner is None:
            _default_captioner = BlipImageCaptioner()
        return _default_captioner
