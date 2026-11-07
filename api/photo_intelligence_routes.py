"""
Photo Intelligence API routes.
"""
import json
import os
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, UploadFile, HTTPException, Form, Request
from fastapi.responses import JSONResponse

from api.logger import get_logger
from api.utils import safe_jsonify
from config import settings
from content_engine.photo_intelligence import PhotoIntelligenceAnalyzer

logger = get_logger(__name__)
router = APIRouter(prefix="/api/photo-intelligence", tags=["photo-intelligence"])

analyzer = PhotoIntelligenceAnalyzer()


@router.post("/analyze")
async def analyze_photos(
    files: List[UploadFile] = File(...),
    brief: str = Form(""),
    duplicate_threshold: int = Form(5),
    similarity_threshold: int = Form(8),
):
    """Analyze batch of photos with quality signals, grouping, and recommendations."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    
    # Create temp storage for analysis
    import tempfile
    import shutil
    tmp_dir = Path(tempfile.mkdtemp(prefix="photo_intel_"))
    
    assets = []
    try:
        for f in files:
            try:
                # Validate filename
                filename = f.filename or "upload"
                ext = Path(filename).suffix.lower()
                allowed = set(settings.allowed_image_extensions) | set(settings.allowed_video_extensions)
                if ext not in allowed:
                    logger.warning(f"Unsupported file type: {filename}")
                    continue
                
                content = await f.read()
                if len(content) > settings.max_file_size_bytes:
                    logger.warning(f"File too large: {filename}")
                    continue
                
                # Save temporarily
                asset_id = str(uuid.uuid4())
                safe_name = f"{asset_id}{ext}"
                path = tmp_dir / safe_name
                with open(path, 'wb') as out:
                    out.write(content)
                
                assets.append({
                    "id": asset_id,
                    "path": str(path),
                    "original_filename": filename,
                    "asset_type": "video" if ext in settings.allowed_video_extensions else "image",
                })
            except Exception as e:
                logger.error(f"Error processing file {f.filename}: {e}")
                continue
        
        if not assets:
            raise HTTPException(status_code=400, detail="No valid files to analyze")
        
        # Update analyzer thresholds
        analyzer.duplicate_threshold = duplicate_threshold
        analyzer.similarity_threshold = similarity_threshold
        
        result = analyzer.analyze_batch(assets, brief=brief)
        return safe_jsonify(result.to_dict())
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Photo intelligence analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Keep files for now - in production would manage lifecycle
        pass


@router.post("/select")
async def update_selection(request: Request):
    """Update user selection (accept/reject/reorder)."""
    try:
        body = await request.json()
        # This would need to store state; for now return success
        return safe_jsonify({"status": "updated", "selections": body})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sequence")
async def get_final_sequence(request: Request):
    """Get final ordered sequence based on user preferences."""
    try:
        body = await request.json()
        # Simplified - in production would use stored state
        return safe_jsonify({"sequence": body.get("sequence", [])})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health():
    return safe_jsonify({
        "status": "ok",
        "module": "photo_intelligence",
        "note": "Heuristic scores are not ground-truth AI predictions"
    })
