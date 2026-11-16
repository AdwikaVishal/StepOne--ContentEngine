"""
Dataset storage for Brand Intelligence (Phase 2 — ingestion only).

Storage layout (everything under output/brand_intelligence/, protected from
cleanup.py by PROTECTED_OUTPUT_PATHS):

    brand_intelligence/
      images/<ab>/<sha256>.<ext>          # GLOBAL content-addressed store —
                                           # one physical copy per unique
                                           # content, shared across datasets
      datasets/<dataset_id>.json          # dataset manifest (counters, status)
      datasets/<dataset_id>/
        images.jsonl                      # append-only, one line per accepted
                                           # unique image (dataset-local refs)
        rejected.jsonl                    # append-only rejection log
        uploads/<upload_id>.json          # chunked-upload session state
        tmp/<upload_id>/chunk_00000 …      # chunk parts (resumable on disk)
        tmp/…                             # ZIP staging / upload staging

Design rules enforced here:
- Originals are copied, never moved or modified; source files stay untouched.
- SHA-256 decides identity: within-dataset repeats are counted as
  duplicates, cross-dataset repeats reuse the shared physical asset.
- Dataset deletion removes ONLY datasets/<id> — the shared images/ store is
  never touched, so other datasets' references survive.
- Chunk sessions are plain files on disk: retry, resume and backend restart
  are all safe; chunk writes are atomic; completion is idempotent.
- A dataset is only marked "ready" by finalize(), which reconciles counters
  against images.jsonl and verifies every referenced asset exists on disk.
- All manifests/jsonl updates happen under a re-entrant lock (single-process
  server; documented limitation).
"""
import hashlib
import json
import math
import os
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config import settings
from content_engine.brand_intel.ingestion import (
    IngestionError,
    ZipLimits,
    cleanup_dir,
    extract_zip_safely,
    file_sha256,
    validate_image_file,
)

# Upload protocol bounds.
MAX_FILES_PER_REQUEST = 50
MAX_CHUNK_BYTES = 64 * 1024 * 1024        # a single chunk may not exceed 64 MB
CHUNK_BATCH_LIMIT = 1024                  # sanity cap for chunk index paths


class DatasetError(Exception):
    """Store-level failure carrying an HTTP status for the route layer."""

    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _now() -> str:
    return datetime.utcnow().isoformat()


def _safe_filename(name: Optional[str]) -> str:
    """Flatten any client-provided name to a single safe path segment."""
    base = str(name or "").replace("\\", "/").split("/")[-1].strip()
    base = "".join(c for c in base if c not in '\x00<>:"|?*')
    return base[:255] or "unnamed"


class DatasetStore:
    """All dataset CRUD, ingestion and chunked-upload state."""

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else (
            settings.output_dir / "brand_intelligence")
        self.datasets_dir = self.root / "datasets"
        self.images_dir = self.root / "images"
        self.datasets_dir.mkdir(parents=True, exist_ok=True)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        # Re-entrant: complete_upload() holds the lock across ingest_batch().
        self._lock = threading.RLock()

    # ── Path helpers (all confinement lives here) ────────────────────────────

    def dataset_id(self, dataset_id: Any) -> str:
        """Validate an ID as a UUID — this is the path-confinement gate."""
        try:
            return str(uuid.UUID(str(dataset_id)))
        except (ValueError, TypeError, AttributeError, OSError):
            raise DatasetError("not_found", "Dataset not found", 404)

    def _manifest_path(self, ds_id: str) -> Path:
        return self.datasets_dir / f"{ds_id}.json"

    def _dataset_dir(self, ds_id: str) -> Path:
        return self.datasets_dir / ds_id

    def _jsonl_path(self, ds_id: str) -> Path:
        return self._dataset_dir(ds_id) / "images.jsonl"

    def _rejected_path(self, ds_id: str) -> Path:
        return self._dataset_dir(ds_id) / "rejected.jsonl"

    def _uploads_dir(self, ds_id: str) -> Path:
        return self._dataset_dir(ds_id) / "uploads"

    def tmp_dir(self, ds_id: str) -> Path:
        return self._dataset_dir(ds_id) / "tmp"

    def resolve_stored(self, stored_path: str) -> Path:
        """Resolve a manifest-relative store path, confined to self.root."""
        candidate = (self.root / str(stored_path)).resolve()
        try:
            candidate.relative_to(self.root.resolve())
        except (ValueError, OSError):
            raise DatasetError(
                "validation", "Stored path escapes the store root", 422)
        return candidate

    # ── Low-level file helpers ───────────────────────────────────────────────

    @staticmethod
    def _read_json(path: Path) -> Optional[Dict[str, Any]]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _write_json_atomic(path: Path, data: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".tmp-{uuid.uuid4().hex}")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    @staticmethod
    def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        if not path.exists():
            return rows
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue        # a torn line must not break reads
                    if isinstance(row, dict):
                        rows.append(row)
        except OSError:
            pass
        return rows

    @staticmethod
    def _append_jsonl(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
        if not rows:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def _load_manifest(self, ds_id: str) -> Dict[str, Any]:
        manifest = self._read_json(self._manifest_path(ds_id))
        if manifest is None:
            raise DatasetError("not_found", "Dataset not found", 404)
        return manifest

    # ── Dataset CRUD ─────────────────────────────────────────────────────────

    def create_dataset(self, name: str, description: str = "") -> Dict[str, Any]:
        name = str(name or "").strip()
        description = str(description or "").strip()
        if not name:
            raise DatasetError("validation", "Dataset name is required")
        if len(name) > 200:
            raise DatasetError(
                "validation", "Dataset name must be at most 200 characters")
        if len(description) > 2000:
            raise DatasetError(
                "validation",
                "Dataset description must be at most 2000 characters")
        with self._lock:
            ds_id = str(uuid.uuid4())
            now = _now()
            manifest = {
                "id": ds_id,
                "name": name,
                "description": description,
                "created_at": now,
                "updated_at": now,
                "status": "ingesting",
                "source": {"kind": "files"},
                "image_count": 0,
                "duplicate_count": 0,
                "shared_count": 0,
                "rejected_count": 0,
                "rejected_reasons": {},
                "bytes_total": 0,
            }
            self._dataset_dir(ds_id).mkdir(parents=True, exist_ok=True)
            self._uploads_dir(ds_id).mkdir(parents=True, exist_ok=True)
            self.tmp_dir(ds_id).mkdir(parents=True, exist_ok=True)
            self._write_json_atomic(self._manifest_path(ds_id), manifest)
            return manifest

    def list_datasets(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            entries = sorted(self.datasets_dir.glob("*.json"))
        except OSError:
            return out
        for path in entries:
            manifest = self._read_json(path)
            if not manifest or "id" not in manifest:
                continue
            try:
                ds_id = self.dataset_id(manifest.get("id"))
            except DatasetError:
                continue          # never let one corrupt file break the list
            manifest["pending_uploads"] = self._pending_sessions(ds_id)
            out.append(manifest)
        out.sort(key=lambda m: m.get("created_at", ""), reverse=True)
        return out

    def get_dataset(self, dataset_id: Any) -> Dict[str, Any]:
        ds_id = self.dataset_id(dataset_id)
        with self._lock:
            manifest = self._load_manifest(ds_id)
            manifest["pending_uploads"] = self._pending_sessions(ds_id)
            return manifest

    def delete_dataset(self, dataset_id: Any) -> Dict[str, Any]:
        """Delete ONLY the dataset's own files.

        The shared content-addressed store (brand_intelligence/images/) is
        never modified — other datasets referencing the same SHA-256 keep
        working (requirement: deletion must not break shared assets).
        """
        ds_id = self.dataset_id(dataset_id)
        with self._lock:
            manifest = self._load_manifest(ds_id)
            self._manifest_path(ds_id).unlink(missing_ok=True)
            cleanup_dir(self._dataset_dir(ds_id))
            return {
                "status": "deleted",
                "id": ds_id,
                "name": manifest.get("name", ""),
                "note": "Shared content-addressed assets were left intact",
            }

    def _note_source(self, manifest: Dict[str, Any], kind: str) -> None:
        current = (manifest.get("source") or {}).get("kind", "files")
        if current == kind:
            return
        if current in ("files", "zip") and current != kind:
            manifest["source"] = {"kind": "mixed"}
        else:
            manifest["source"] = {"kind": kind}

    # ── Ingestion ────────────────────────────────────────────────────────────

    def ingest_batch(
        self,
        dataset_id: Any,
        items: Sequence[Tuple[str, Path]],
    ) -> Dict[str, Any]:
        """Ingest (original_filename, source_path) pairs.

        Items are processed strictly one at a time and the source file is
        streamed (hash) / opened (decode) per item — peak memory is a single
        image, never the batch, so arbitrarily large datasets can be pushed
        through incrementally.

        Idempotent: re-sending already-ingested content yields `duplicate`
        (same dataset) without touching counters; rejections are deduped by
        (content sha, filename) in rejected.jsonl.
        """
        ds_id = self.dataset_id(dataset_id)
        if len(items) > MAX_FILES_PER_REQUEST:
            raise DatasetError(
                "validation",
                f"At most {MAX_FILES_PER_REQUEST} files per request")
        with self._lock:
            manifest = self._load_manifest(ds_id)
            dataset_shas = {
                row.get("sha256") for row in self._read_jsonl(
                    self._jsonl_path(ds_id)) if row.get("sha256")}
            rejected_keys = {
                (row.get("sha256"), row.get("original_filename"))
                for row in self._read_jsonl(self._rejected_path(ds_id))}

            results: List[Dict[str, Any]] = []
            new_lines: List[Dict[str, Any]] = []
            new_rejections: List[Dict[str, Any]] = []
            image_count = 0
            duplicate_count = 0
            shared_count = 0
            rejected_count = 0
            rejected_reasons: Dict[str, int] = dict(
                manifest.get("rejected_reasons") or {})
            bytes_total = 0
            accepted_now = 0

            for original_filename, source_path in items:
                original = _safe_filename(original_filename)
                source_path = Path(source_path)
                try:
                    meta = validate_image_file(source_path, original)
                except IngestionError as exc:
                    sha = file_sha256(source_path) if source_path.exists() \
                        else "missing"
                    key = (sha, original)
                    if key not in rejected_keys:
                        rejected_keys.add(key)
                        rejected_count += 1
                        rejected_reasons[exc.code] = (
                            rejected_reasons.get(exc.code, 0) + 1)
                        new_rejections.append({
                            "sha256": sha,
                            "original_filename": original,
                            "reason": exc.code,
                            "detail": exc.message,
                            "rejected_at": _now(),
                        })
                    results.append({
                        "filename": original,
                        "status": "rejected",
                        "reason": exc.code,
                        "detail": exc.message,
                    })
                    continue

                sha = meta["sha256"]
                if sha in dataset_shas:
                    duplicate_count += 1
                    results.append({
                        "filename": original,
                        "status": "duplicate",
                        "sha256": sha,
                        "detail": "Identical content already in this dataset",
                    })
                    continue

                stored_path = f"images/{sha[:2]}/{sha}{meta['extension']}"
                dest = self.resolve_stored(stored_path)
                shared = dest.exists()
                if not shared:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    staging = dest.with_name(
                        dest.name + f".tmp-{uuid.uuid4().hex}")
                    try:
                        shutil.copyfile(source_path, staging)
                        os.replace(staging, dest)   # atomic publish
                    except OSError:
                        staging.unlink(missing_ok=True)
                        raise DatasetError(
                            "storage",
                            f"Could not store {original}", 500)

                dataset_shas.add(sha)
                image_count += 1
                bytes_total += meta["bytes"]
                if shared:
                    shared_count += 1
                accepted_now += 1
                new_lines.append({
                    "image_id": sha[:16],
                    "stored_path": stored_path,
                    "original_filename": original,
                    "sha256": sha,
                    "bytes": meta["bytes"],
                    "width": meta["width"],
                    "height": meta["height"],
                    "format": meta["format"],
                    "uploaded_at": _now(),
                    "duplicate_of": None,
                })
                results.append({
                    "filename": original,
                    "status": "accepted",
                    "sha256": sha,
                    "shared": shared,
                    "stored_path": stored_path,
                    "width": meta["width"],
                    "height": meta["height"],
                    "format": meta["format"],
                    "bytes": meta["bytes"],
                })

            # ── Single atomic manifest update + append-only logs ────────────
            manifest["image_count"] = (
                manifest.get("image_count", 0) + image_count)
            manifest["duplicate_count"] = (
                manifest.get("duplicate_count", 0) + duplicate_count)
            manifest["shared_count"] = (
                manifest.get("shared_count", 0) + shared_count)
            manifest["rejected_count"] = (
                manifest.get("rejected_count", 0) + rejected_count)
            manifest["rejected_reasons"] = rejected_reasons
            manifest["bytes_total"] = manifest.get("bytes_total", 0) + bytes_total
            if accepted_now and manifest.get("status") == "ready":
                # New content after finalize → needs verification again.
                manifest["status"] = "ingesting"
            manifest["updated_at"] = _now()

            self._append_jsonl(self._jsonl_path(ds_id), new_lines)
            self._append_jsonl(self._rejected_path(ds_id), new_rejections)
            self._write_json_atomic(self._manifest_path(ds_id), manifest)

            stats = {
                "accepted": sum(1 for r in results
                                if r["status"] == "accepted"),
                "duplicate": duplicate_count,
                "rejected": sum(1 for r in results
                                if r["status"] == "rejected"),
                "shared": sum(1 for r in results
                              if r["status"] == "accepted" and r.get("shared")),
            }
            return {"results": results, "stats": stats, "manifest": manifest}

    def ingest_zip(
        self,
        dataset_id: Any,
        zip_path: Path,
        original_name: str,
        limits: Optional[ZipLimits] = None,
    ) -> Dict[str, Any]:
        """Securely extract a ZIP into a per-dataset temp dir and ingest it.

        The temp dir always lives inside datasets/<id>/tmp/ and is removed in
        a finally block — success, failure or exception. Nothing is ever
        written outside it.
        """
        ds_id = self.dataset_id(dataset_id)
        zip_path = Path(zip_path)
        extract_dir = self.tmp_dir(ds_id) / f"zip_{uuid.uuid4().hex}"
        try:
            try:
                extracted = extract_zip_safely(zip_path, extract_dir, limits)
            except IngestionError as exc:
                cleanup_dir(extract_dir)
                raise DatasetError(exc.code, exc.message, 422)

            outcome = self.ingest_batch(
                ds_id, [(name, path) for path, name in extracted.files])
            outcome["skipped"] = extracted.skipped

            with self._lock:
                manifest = self._load_manifest(ds_id)
                self._note_source(manifest, "zip")
                manifest.setdefault("source", {})["original_name"] = \
                    _safe_filename(original_name)
                manifest["updated_at"] = _now()
                self._write_json_atomic(self._manifest_path(ds_id), manifest)
                outcome["manifest"] = manifest
            return outcome
        finally:
            cleanup_dir(extract_dir)

    # ── Chunked, resumable upload sessions ───────────────────────────────────

    @staticmethod
    def _session_public(session: Dict[str, Any]) -> Dict[str, Any]:
        received = sorted(int(k) for k in (session.get("received") or {}))
        return {
            "upload_id": session.get("upload_id"),
            "filename": session.get("filename"),
            "total_bytes": session.get("total_bytes"),
            "chunk_size": session.get("chunk_size"),
            "total_chunks": session.get("total_chunks"),
            "status": session.get("status"),
            "created_at": session.get("created_at"),
            "received_chunks": received,
            "missing_chunks": [
                i for i in range(session.get("total_chunks", 0))
                if i not in received],
        }

    def _session_path(self, ds_id: str, upload_id: str) -> Path:
        return self._uploads_dir(ds_id) / f"{upload_id}.json"

    def _chunk_dir(self, ds_id: str, upload_id: str) -> Path:
        return self.tmp_dir(ds_id) / upload_id

    def _load_session(self, ds_id: str, upload_id: str) -> Dict[str, Any]:
        session = self._read_json(self._session_path(ds_id, upload_id))
        if session is None:
            raise DatasetError(
                "not_found", "Upload session not found", 404)
        return session

    @staticmethod
    def _validate_upload_id(upload_id: Any) -> str:
        try:
            return str(uuid.UUID(str(upload_id)))
        except (ValueError, TypeError, AttributeError, OSError):
            raise DatasetError(
                "not_found", "Upload session not found", 404)

    def _pending_sessions(self, ds_id: str) -> int:
        count = 0
        try:
            for path in self._uploads_dir(ds_id).glob("*.json"):
                session = self._read_json(path)
                if session and session.get("status") == "pending":
                    count += 1
        except OSError:
            pass
        return count

    def create_upload_session(
        self,
        dataset_id: Any,
        filename: str,
        total_bytes: int,
        total_chunks: int,
        upload_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create (or resume) a chunked upload session for ONE image file.

        All session state lives on disk, so an interrupted upload resumes
        after a backend restart: re-creating with the same parameters (or the
        same upload_id) returns the existing session and its received chunks.
        """
        ds_id = self.dataset_id(dataset_id)
        filename = _safe_filename(filename)
        try:
            total_bytes = int(total_bytes)
            total_chunks = int(total_chunks)
        except (TypeError, ValueError):
            raise DatasetError("validation", "Invalid upload sizes")
        if total_bytes <= 0:
            raise DatasetError("validation", "total_bytes must be positive")
        if total_bytes > settings.max_file_size_bytes:
            raise DatasetError(
                "too_large",
                f"File exceeds the {settings.max_file_size_mb}MB per-file "
                "limit", 413)
        if total_chunks < 1 or total_chunks > total_bytes:
            raise DatasetError(
                "validation",
                "total_chunks must be between 1 and total_bytes")
        chunk_size = math.ceil(total_bytes / total_chunks)
        if chunk_size > MAX_CHUNK_BYTES:
            raise DatasetError(
                "validation",
                f"Chunk size {chunk_size} exceeds the "
                f"{MAX_CHUNK_BYTES // (1024 * 1024)}MB chunk limit")

        if upload_id is not None:
            upload_id = self._validate_upload_id(upload_id)
        else:
            upload_id = str(uuid.uuid4())

        with self._lock:
            self._load_manifest(ds_id)          # 404 for unknown dataset
            session_path = self._session_path(ds_id, upload_id)
            existing = self._read_json(session_path)
            if existing is not None:
                same = (
                    existing.get("filename") == filename
                    and existing.get("total_bytes") == total_bytes
                    and existing.get("total_chunks") == total_chunks)
                if not same:
                    raise DatasetError(
                        "conflict",
                        "An upload session with this ID already exists with "
                        "different parameters", 409)
                return self._session_public(existing)

            session = {
                "upload_id": upload_id,
                "dataset_id": ds_id,
                "filename": filename,
                "total_bytes": total_bytes,
                "chunk_size": chunk_size,
                "total_chunks": total_chunks,
                "created_at": _now(),
                "status": "pending",
                "received": {},
            }
            self._chunk_dir(ds_id, upload_id).mkdir(parents=True, exist_ok=True)
            self._write_json_atomic(session_path, session)
            return self._session_public(session)

    def save_chunk(
        self,
        dataset_id: Any,
        upload_id: str,
        chunk_index: int,
        data: bytes,
    ) -> Dict[str, Any]:
        """Store one chunk. Idempotent: an identical re-submission succeeds
        (200, duplicate=True); a conflicting re-submission of the same index
        is rejected (409) so corrupted resumes are impossible."""
        ds_id = self.dataset_id(dataset_id)
        upload_id = self._validate_upload_id(upload_id)
        try:
            chunk_index = int(chunk_index)
        except (TypeError, ValueError):
            raise DatasetError("validation", "Invalid chunk index")

        with self._lock:
            session = self._load_session(ds_id, upload_id)
            if session.get("status") == "complete":
                return {
                    "duplicate": True,
                    "already_complete": True,
                    "session": self._session_public(session),
                }
            total_chunks = session["total_chunks"]
            if chunk_index < 0 or chunk_index >= total_chunks:
                raise DatasetError(
                    "validation",
                    f"Chunk index {chunk_index} out of range "
                    f"(0..{total_chunks - 1})")
            chunk_size = session["chunk_size"]
            expected = chunk_size if chunk_index < total_chunks - 1 else (
                session["total_bytes"] - chunk_size * (total_chunks - 1))
            if len(data) != expected:
                raise DatasetError(
                    "validation",
                    f"Chunk {chunk_index} is {len(data)} bytes, "
                    f"expected {expected}", 422)

            chunk_dir = self._chunk_dir(ds_id, upload_id)
            chunk_dir.mkdir(parents=True, exist_ok=True)
            chunk_path = chunk_dir / f"chunk_{chunk_index:05d}"
            incoming_sha = hashlib.sha256(data).hexdigest()

            if chunk_path.exists():
                recorded = (session.get("received") or {}).get(
                    str(chunk_index))
                existing_sha = recorded or file_sha256(chunk_path)
                if existing_sha == incoming_sha:
                    return {
                        "duplicate": True,
                        "session": self._session_public(session),
                    }
                raise DatasetError(
                    "conflict",
                    f"Chunk {chunk_index} was already stored with different "
                    "content", 409)

            staging = chunk_path.with_name(
                chunk_path.name + f".tmp-{uuid.uuid4().hex}")
            with open(staging, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(staging, chunk_path)

            session.setdefault("received", {})[str(chunk_index)] = incoming_sha
            self._write_json_atomic(
                self._session_path(ds_id, upload_id), session)
            return {
                "duplicate": False,
                "session": self._session_public(session),
            }

    def complete_upload(
        self,
        dataset_id: Any,
        upload_id: str,
    ) -> Dict[str, Any]:
        """Reassemble, validate and ingest a fully-received upload.

        Idempotent: completing twice returns the stored first result. Crash
        safety: chunks are removed only AFTER the manifest was updated, and
        re-running ingestion is a SHA-256 no-op, so no image is ever lost or
        double-counted.
        """
        ds_id = self.dataset_id(dataset_id)
        upload_id = self._validate_upload_id(upload_id)
        with self._lock:
            session = self._load_session(ds_id, upload_id)
            if session.get("status") == "complete":
                return session.get("result") or {
                    "upload_id": upload_id,
                    "status": "already_complete"}

            total_chunks = session["total_chunks"]
            received = session.get("received") or {}
            missing = [i for i in range(total_chunks)
                       if str(i) not in received]
            if missing:
                raise DatasetError(
                    "conflict",
                    f"Upload incomplete: {len(missing)} of {total_chunks} "
                    "chunks missing", 409)

            chunk_dir = self._chunk_dir(ds_id, upload_id)
            assembled = chunk_dir / "assembled.tmp"
            try:
                with open(assembled, "wb") as out:
                    for i in range(total_chunks):
                        part = chunk_dir / f"chunk_{i:05d}"
                        if not part.exists():
                            raise DatasetError(
                                "conflict",
                                f"Chunk {i} disappeared before completion",
                                409)
                        with open(part, "rb") as src:
                            shutil.copyfileobj(src, out)
                    out.flush()
                    os.fsync(out.fileno())
                if assembled.stat().st_size != session["total_bytes"]:
                    raise DatasetError(
                        "conflict",
                        "Assembled size does not match the declared size",
                        409)

                outcome = self.ingest_batch(
                    ds_id, [(session["filename"], assembled)])
                outcome["upload_id"] = upload_id
                outcome["filename"] = session["filename"]

                session["status"] = "complete"
                session["completed_at"] = _now()
                session["result"] = outcome
                self._write_json_atomic(
                    self._session_path(ds_id, upload_id), session)
                # Chunks are expendable only AFTER the session record (with
                # the stored result) is safely on disk.
                cleanup_dir(chunk_dir)
            finally:
                assembled.unlink(missing_ok=True)
            return outcome

    def list_upload_sessions(self, dataset_id: Any) -> List[Dict[str, Any]]:
        ds_id = self.dataset_id(dataset_id)
        out: List[Dict[str, Any]] = []
        uploads_dir = self._uploads_dir(ds_id)
        if not uploads_dir.exists():
            return out
        for path in sorted(uploads_dir.glob("*.json")):
            session = self._read_json(path)
            if session and session.get("status") == "pending":
                out.append(self._session_public(session))
        return out

    def discard_upload(self, dataset_id: Any, upload_id: str) -> Dict[str, Any]:
        """Throw away an abandoned pending session and its chunk parts."""
        ds_id = self.dataset_id(dataset_id)
        upload_id = self._validate_upload_id(upload_id)
        with self._lock:
            session = self._load_session(ds_id, upload_id)
            if session.get("status") == "complete":
                raise DatasetError(
                    "conflict", "Completed uploads cannot be discarded", 409)
            self._session_path(ds_id, upload_id).unlink(missing_ok=True)
            cleanup_dir(self._chunk_dir(ds_id, upload_id))
            return {"status": "discarded", "upload_id": upload_id}

    # ── Finalize (verification gate) ─────────────────────────────────────────

    def finalize_dataset(self, dataset_id: Any) -> Dict[str, Any]:
        """Verify then mark the dataset ready.

        Refuses while chunked uploads are pending; reconciles manifest
        counters against images.jsonl; verifies every referenced physical
        asset exists in the shared store. Only then does status become
        "ready" — a dataset is never complete until verified.
        """
        ds_id = self.dataset_id(dataset_id)
        with self._lock:
            manifest = self._load_manifest(ds_id)
            pending = self.list_upload_sessions(ds_id)
            if pending:
                names = [p["filename"] for p in pending]
                raise DatasetError(
                    "conflict",
                    "Cannot finalize: incomplete uploads pending "
                    f"({', '.join(names)})", 409)

            rows = self._read_jsonl(self._jsonl_path(ds_id))
            missing = [r.get("original_filename", "?") for r in rows
                       if not self.resolve_stored(
                           r.get("stored_path", "")).exists()]
            if missing:
                raise DatasetError(
                    "conflict",
                    f"Cannot finalize: {len(missing)} stored asset(s) "
                    f"missing (e.g. {missing[0]})", 409)

            # Reconcile counters from the append-only log (source of truth).
            manifest["image_count"] = len(rows)
            manifest["bytes_total"] = sum(
                int(r.get("bytes") or 0) for r in rows)
            manifest["status"] = "ready"
            manifest["finalized_at"] = _now()
            manifest["updated_at"] = _now()
            self._write_json_atomic(self._manifest_path(ds_id), manifest)
            manifest["pending_uploads"] = 0
            return manifest

    # ── Image listing ────────────────────────────────────────────────────────

    def list_images(
        self,
        dataset_id: Any,
        offset: int = 0,
        limit: int = 50,
        q: str = "",
    ) -> Dict[str, Any]:
        ds_id = self.dataset_id(dataset_id)
        self._load_manifest(ds_id)
        rows = self._read_jsonl(self._jsonl_path(ds_id))
        query = (q or "").strip().lower()
        if query:
            rows = [r for r in rows
                    if query in str(r.get("original_filename", "")).lower()
                    or str(r.get("sha256", "")).startswith(query)
                    or query in str(r.get("image_id", "")).lower()]
        total = len(rows)
        offset = max(0, int(offset))
        limit = min(max(1, int(limit)), 200)
        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "images": rows[offset:offset + limit],
        }
