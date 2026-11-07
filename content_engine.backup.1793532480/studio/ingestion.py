"""
Multi-image ingestion for studio.
"""
import hashlib
import mimetypes
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from config import settings


class StudioIngestion:
    IMAGE_EXTS = {ext.lower() for ext in settings.allowed_image_extensions}
    VIDEO_EXTS = {ext.lower() for ext in settings.allowed_video_extensions}
    
    def __init__(self, upload_dir: Optional[Path] = None):
        self.upload_dir = Path(upload_dir) if upload_dir else Path(settings.upload_dir) / "studio"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
    
    def validate_file(self, filename: str, content_type: Optional[str] = None) -> Tuple[bool, str]:
        ext = Path(filename).suffix.lower()
        if ext not in self.IMAGE_EXTS and ext not in self.VIDEO_EXTS:
            return False, f"Unsupported file type: {ext}"
        return True, "ok"
    
    def save_upload(self, file_content: bytes, filename: str) -> Dict[str, Any]:
        # Sanitize filename
        safe_name = Path(filename).name
        # Generate stable ID
        file_id = str(uuid.uuid4())
        ext = Path(safe_name).suffix.lower()
        stored_name = f"{file_id}{ext}"
        dest = self.upload_dir / stored_name
        
        with open(dest, "wb") as f:
            f.write(file_content)
        
        asset = {
            "id": file_id,
            "original_filename": safe_name,
            "stored_filename": stored_name,
            "path": str(dest),
            "url": f"/uploads/studio/{stored_name}",
            "size_bytes": len(file_content),
            "ext": ext,
            "mime_type": mimetypes.guess_type(safe_name)[0] or "application/octet-stream",
            "asset_type": "video" if ext in self.VIDEO_EXTS else "image",
        }
        
        if asset["asset_type"] == "image":
            try:
                with Image.open(dest) as im:
                    asset["width"], asset["height"] = im.size
                    asset["format"] = im.format
            except Exception:
                asset["width"], asset["height"] = None, None
        
        asset["sha256"] = self._hash_file(dest)
        return asset
    
    def _hash_file(self, path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
