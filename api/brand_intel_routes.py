"""
Brand Intelligence Studio API routes (Phase 1 + Phase 2).

Phase 1 — Brand Reference Library:
  brand reference asset management (manifest metadata, categorization,
  replacement, removal) and reference-quality reports.

Phase 2 — Dataset Upload:
  dataset CRUD, batch/ZIP/chunked-resumable ingestion under
  /api/brand-intel/datasets. Ingestion only — no OCR, no classification.

Detection runs, review and export arrive in Phases 3-6 under the same
/api/brand-intel prefix.

All paths are confined: brand assets stay inside
output/studio/brand_assets/<profile_id>/, datasets inside
output/brand_intelligence/ (UUID-validated IDs, resolve+relative_to gates).
"""
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from api.logger import get_logger
from api.utils import safe_jsonify
from config import settings
from content_engine.studio import StudioStorage
from content_engine.brand_intel.dataset_store import (
    MAX_FILES_PER_REQUEST,
    MAX_CHUNK_BYTES,
    DatasetError,
    DatasetStore,
)
from content_engine.brand_intel.reference_quality import get_reference_quality

logger = get_logger(__name__)
router = APIRouter(prefix="/api/brand-intel", tags=["brand-intel"])

storage = StudioStorage()
dataset_store = DatasetStore()


class AssetPatchRequest(BaseModel):
    category: Optional[str] = None
    notes: Optional[str] = None


def _get_profile_or_404(profile_id: str):
    profile = storage.get_brand_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Brand profile not found")
    return profile


@router.get("/brands/{profile_id}/assets")
async def list_brand_assets(profile_id: str):
    _get_profile_or_404(profile_id)
    try:
        assets = storage.list_brand_assets(profile_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return safe_jsonify({"assets": assets})


@router.patch("/brands/{profile_id}/assets/{asset_id}")
async def update_brand_asset(profile_id: str, asset_id: str, body: AssetPatchRequest):
    _get_profile_or_404(profile_id)
    if body.category is None and body.notes is None:
        raise HTTPException(status_code=422, detail="Provide category and/or notes")
    try:
        entry = storage.update_brand_asset_entry(
            profile_id, asset_id, category=body.category, notes=body.notes)
    except ValueError as e:
        status = 404 if "not found" in str(e) else 422
        raise HTTPException(status_code=status, detail=str(e))
    return safe_jsonify({"asset": entry})


@router.delete("/brands/{profile_id}/assets/{asset_id}")
async def delete_brand_asset(profile_id: str, asset_id: str):
    _get_profile_or_404(profile_id)
    try:
        entry = storage.remove_brand_asset(profile_id, asset_id)
    except ValueError as e:
        status = 404 if "not found" in str(e) else 422
        raise HTTPException(status_code=status, detail=str(e))
    # Return the refreshed profile so the client can update its local copy
    # of logo_path / visual_references in the same round trip.
    return safe_jsonify({"status": "deleted", "asset": entry,
                         "profile": storage.get_brand_profile(profile_id)})


@router.post("/brands/{profile_id}/assets/{asset_id}/replace")
async def replace_brand_asset(
    profile_id: str,
    asset_id: str,
    file: UploadFile = File(...),
    category: str = Form(""),
    notes: str = Form(""),
):
    _get_profile_or_404(profile_id)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="Replacement file is empty")
    from config import settings
    if len(content) > settings.max_file_size_bytes:
        raise HTTPException(status_code=422, detail="Replacement file exceeds the upload limit")
    try:
        entry = storage.replace_brand_asset(profile_id, asset_id,
                                            file.filename or "asset.png", content)
        if category or notes:
            entry = storage.update_brand_asset_entry(
                profile_id, asset_id,
                category=category or None,
                notes=notes if notes else None,
            )
    except ValueError as e:
        status = 404 if "not found" in str(e) else 422
        raise HTTPException(status_code=status, detail=str(e))
    return safe_jsonify({"asset": entry,
                         "profile": storage.get_brand_profile(profile_id)})


@router.get("/brands/{profile_id}/reference-quality")
async def reference_quality(profile_id: str):
    report = get_reference_quality(storage, profile_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Brand profile not found")
    return safe_jsonify(report)


# ════════════════════════════════════════════════════════════════════════════
# Phase 2 — Dataset Upload (ingestion only)
# ════════════════════════════════════════════════════════════════════════════

class DatasetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class UploadSessionRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    total_bytes: int = Field(gt=0)
    total_chunks: int = Field(gt=0)
    upload_id: Optional[str] = None


def _ds_error(exc: DatasetError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


async def _stage_upload(upload: UploadFile, dest: Path) -> None:
    """Stream an UploadFile to disk in 1MB pieces — one file in memory at
    most, never a whole batch or archive."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as out:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)


def _client_filename(upload: UploadFile) -> str:
    raw = str(upload.filename or "unnamed")
    return raw.replace("\\", "/").split("/")[-1] or "unnamed"


@router.post("/datasets")
async def create_dataset(body: DatasetCreateRequest):
    try:
        manifest = dataset_store.create_dataset(body.name, body.description)
    except DatasetError as e:
        raise _ds_error(e)
    return safe_jsonify(manifest)


@router.get("/datasets")
async def list_datasets():
    try:
        datasets = dataset_store.list_datasets()
    except DatasetError as e:
        raise _ds_error(e)
    return safe_jsonify({"datasets": datasets})


@router.get("/datasets/{dataset_id}")
async def get_dataset(dataset_id: str):
    try:
        manifest = dataset_store.get_dataset(dataset_id)
    except DatasetError as e:
        raise _ds_error(e)
    return safe_jsonify(manifest)


@router.delete("/datasets/{dataset_id}")
async def delete_dataset(
    dataset_id: str,
    confirm: str = Query(..., description="Must equal the dataset name"),
):
    """Explicit-confirmation deletion: `confirm` must exactly match the
    dataset name (typed by the user in the UI). Shared content-addressed
    assets are never deleted."""
    try:
        manifest = dataset_store.get_dataset(dataset_id)
        if confirm != manifest["name"]:
            raise DatasetError(
                "confirmation",
                "Confirmation does not match the dataset name", 400)
        result = dataset_store.delete_dataset(dataset_id)
    except DatasetError as e:
        raise _ds_error(e)
    return safe_jsonify(result)


@router.post("/datasets/{dataset_id}/upload")
async def upload_dataset_files(
    dataset_id: str,
    files: List[UploadFile] = File(...),
):
    """Batch image upload (individual / multi-select chunks of a dataset).

    Files are staged one at a time to the dataset's temp dir, then ingested
    with one manifest transaction. Re-sending a batch is idempotent.
    """
    try:
        ds_id = dataset_store.dataset_id(dataset_id)
        if not files:
            raise DatasetError("validation", "No files provided")
        if len(files) > MAX_FILES_PER_REQUEST:
            raise DatasetError(
                "validation",
                f"At most {MAX_FILES_PER_REQUEST} files per request — "
                "send the dataset in chunks")
        tmp_dir = dataset_store.tmp_dir(ds_id)
        tmp_dir.mkdir(parents=True, exist_ok=True)

        staged = []
        try:
            for upload in files:
                staging = tmp_dir / f"stage_{uuid.uuid4().hex}"
                await _stage_upload(upload, staging)
                staged.append((_client_filename(upload), staging))
            outcome = dataset_store.ingest_batch(ds_id, staged)
        finally:
            for _, path in staged:
                path.unlink(missing_ok=True)
    except DatasetError as e:
        raise _ds_error(e)
    return safe_jsonify(outcome)


@router.post("/datasets/{dataset_id}/upload-zip")
async def upload_dataset_zip(
    dataset_id: str,
    file: UploadFile = File(...),
):
    """Secure ZIP ingestion: streamed to a temp file inside the dataset,
    pre-scanned for traversal/symlinks/bombs, extracted only into the
    dataset's temp dir, then removed. Unsupported/nested entries are
    reported as skipped; hostile archives abort with 422."""
    zip_path = None
    try:
        ds_id = dataset_store.dataset_id(dataset_id)
        if not str(file.filename or "").lower().endswith(".zip"):
            raise DatasetError(
                "validation", "ZIP upload requires a .zip file")
        tmp_dir = dataset_store.tmp_dir(ds_id)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        zip_path = tmp_dir / f"upload_{uuid.uuid4().hex}.zip"
        await _stage_upload(file, zip_path)
        outcome = dataset_store.ingest_zip(
            ds_id, zip_path, _client_filename(file))
    except DatasetError as e:
        raise _ds_error(e)
    finally:
        if zip_path is not None:
            zip_path.unlink(missing_ok=True)
    return safe_jsonify(outcome)


@router.post("/datasets/{dataset_id}/uploads")
async def create_upload_session(dataset_id: str, body: UploadSessionRequest):
    """Create or resume a chunked upload session (state lives on disk, so
    it survives backend restarts)."""
    try:
        session = dataset_store.create_upload_session(
            dataset_id,
            filename=body.filename,
            total_bytes=body.total_bytes,
            total_chunks=body.total_chunks,
            upload_id=body.upload_id,
        )
    except DatasetError as e:
        raise _ds_error(e)
    return safe_jsonify(session)


@router.get("/datasets/{dataset_id}/uploads")
async def list_upload_sessions(dataset_id: str):
    try:
        sessions = dataset_store.list_upload_sessions(dataset_id)
    except DatasetError as e:
        raise _ds_error(e)
    return safe_jsonify({"uploads": sessions})


@router.post("/datasets/{dataset_id}/uploads/{upload_id}/chunks/{chunk_index}")
async def upload_chunk(
    dataset_id: str,
    upload_id: str,
    chunk_index: int,
    file: UploadFile = File(...),
):
    """Idempotent chunk submission: identical retries succeed, conflicting
    content for an already-stored index is rejected with 409."""
    try:
        data = await file.read()
        if len(data) > MAX_CHUNK_BYTES:
            raise DatasetError(
                "too_large", "Chunk exceeds the 64MB chunk limit", 413)
        result = dataset_store.save_chunk(
            dataset_id, upload_id, chunk_index, data)
    except DatasetError as e:
        raise _ds_error(e)
    return safe_jsonify(result)


@router.post("/datasets/{dataset_id}/uploads/{upload_id}/complete")
async def complete_upload(dataset_id: str, upload_id: str):
    """Reassemble + validate + ingest. Idempotent: completing twice returns
    the original result."""
    try:
        outcome = dataset_store.complete_upload(dataset_id, upload_id)
    except DatasetError as e:
        raise _ds_error(e)
    return safe_jsonify(outcome)


@router.delete("/datasets/{dataset_id}/uploads/{upload_id}")
async def discard_upload(dataset_id: str, upload_id: str):
    """Discard an abandoned pending upload session and its chunk parts."""
    try:
        result = dataset_store.discard_upload(dataset_id, upload_id)
    except DatasetError as e:
        raise _ds_error(e)
    return safe_jsonify(result)


@router.post("/datasets/{dataset_id}/finalize")
async def finalize_dataset(dataset_id: str):
    """Verification gate: refuses while uploads are pending, reconciles
    counters against images.jsonl, verifies every referenced asset exists,
    then marks the dataset ready."""
    try:
        manifest = dataset_store.finalize_dataset(dataset_id)
    except DatasetError as e:
        raise _ds_error(e)
    return safe_jsonify(manifest)


@router.get("/datasets/{dataset_id}/images")
async def list_dataset_images(
    dataset_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    q: str = Query(""),
):
    try:
        page = dataset_store.list_images(
            dataset_id, offset=offset, limit=limit, q=q)
    except DatasetError as e:
        raise _ds_error(e)
    return safe_jsonify(page)
