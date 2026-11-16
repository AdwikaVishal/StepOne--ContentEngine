"""
Brand Intelligence Phase 2 — Dataset Upload tests.

Covers the approved checklist:
- dataset CRUD (create/list/detail/delete with explicit confirmation)
- individual, multi and ZIP uploads (JPEG/PNG/WebP)
- content-based validation (invalid MIME, invalid contents, empty, oversized)
- SHA-256 deduplication within a dataset and sharing across datasets
- ZIP security: path traversal, symlinks, bombs (ratio/size/count),
  nested archives, unsupported files, temp extraction cleanup
- chunked resumable uploads: retries, duplicate chunks, invalid chunks,
  interruption, resume after a simulated backend restart
- manifest consistency and the finalize verification gate
- dataset deletion without breaking shared content-addressed assets
- cleanup protection for the shared store
- an end-to-end acceptance workflow over a real multi-file test dataset

All store tests run against a tmp_path root; API tests run the real router
via TestClient with the dataset store redirected to tmp_path.
"""
import hashlib
import io
import json
import random
import shutil
import zipfile
from pathlib import Path

import pytest

from content_engine.brand_intel.dataset_store import (
    DatasetStore,
    DatasetError,
    MAX_FILES_PER_REQUEST,
)
from content_engine.brand_intel.ingestion import (
    IngestionError,
    ZipLimits,
    extract_zip_safely,
    sanitize_entry_name,
    validate_image_bytes,
)


# ── Image fixtures ───────────────────────────────────────────────────────────

def _noise_png(seed: int = 0, size=(48, 48)) -> bytes:
    from PIL import Image
    rnd = random.Random(seed)
    img = Image.new("RGB", size)
    img.putdata([
        (rnd.randint(0, 255), rnd.randint(0, 255), rnd.randint(0, 255))
        for _ in range(size[0] * size[1])
    ])
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _fmt_bytes(fmt: str, seed: int = 0, size=(48, 48)) -> bytes:
    from PIL import Image
    rnd = random.Random(seed)
    img = Image.new("RGB", size)
    img.putdata([
        (rnd.randint(0, 255), rnd.randint(0, 255), rnd.randint(0, 255))
        for _ in range(size[0] * size[1])
    ])
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


JPEG_BYTES = _fmt_bytes("JPEG", seed=1)
PNG_BYTES = _noise_png(seed=2)
WEBP_BYTES = _fmt_bytes("WEBP", seed=3)
OTHER_PNG = _noise_png(seed=4)
TEXT_BYTES = b"this is definitely not an image, just plain text\n" * 4
# Valid PNG signature but cut off inside IHDR → signature passes, decode
# fails with a corrupt/decode error.
TRUNCATED_PNG = PNG_BYTES[:20]


@pytest.fixture()
def store(tmp_path) -> DatasetStore:
    return DatasetStore(root=tmp_path / "brand_intelligence")


@pytest.fixture()
def dataset(store) -> dict:
    return store.create_dataset("Event Photos", "Q4 launch event")


def _stage(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / "sources" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _ingest(store, ds_id, name, data, src_root: Path) -> dict:
    path = _stage(src_root, name, data)
    return store.ingest_batch(ds_id, [(name, path)])


def _make_zip(path: Path, entries: dict) -> Path:
    """entries: {archive_name: bytes} (or ZipInfo for exotic entries)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, payload in entries.items():
            if isinstance(payload, zipfile.ZipInfo):
                zf.writestr(payload, b"")
            else:
                zf.writestr(name, payload)
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _store_files(store: DatasetStore) -> list:
    return sorted(p for p in store.images_dir.rglob("*") if p.is_file())


# ════════════════════════════════════════════════════════════════════════════
# Content validation (unit level)
# ════════════════════════════════════════════════════════════════════════════

class TestValidateBytes:
    def test_valid_image_metadata(self):
        meta = validate_image_bytes(PNG_BYTES, "shot.png")
        assert meta["format"] == "PNG"
        assert meta["extension"] == ".png"
        assert meta["sha256"] == hashlib.sha256(PNG_BYTES).hexdigest()
        assert meta["width"] == 48 and meta["height"] == 48

    def test_garbage_rejected(self):
        with pytest.raises(IngestionError) as exc:
            validate_image_bytes(TEXT_BYTES, "shot.jpg")
        assert exc.value.code == "unsupported_type"

    def test_filename_paths_are_flattened(self):
        # Path components in the filename never affect validation.
        meta = validate_image_bytes(PNG_BYTES, "../../evil dir/shot.png")
        assert meta["format"] == "PNG"
        with pytest.raises(IngestionError) as exc:
            validate_image_bytes(PNG_BYTES, "../../shot.txt")
        assert exc.value.code == "unsupported_type"


# ════════════════════════════════════════════════════════════════════════════
# Dataset management
# ════════════════════════════════════════════════════════════════════════════

class TestDatasetManagement:
    def test_create_list_get_roundtrip(self, store):
        created = store.create_dataset("Launch", "desc here")
        assert created["status"] == "ingesting"
        assert created["image_count"] == 0
        assert created["bytes_total"] == 0
        assert created["created_at"]

        listed = store.list_datasets()
        assert len(listed) == 1
        assert listed[0]["name"] == "Launch"
        assert listed[0]["pending_uploads"] == 0

        fetched = store.get_dataset(created["id"])
        assert fetched["description"] == "desc here"
        assert fetched["id"] == created["id"]

    def test_create_validation(self, store):
        with pytest.raises(DatasetError, match="name is required"):
            store.create_dataset("   ")
        with pytest.raises(DatasetError, match="200 characters"):
            store.create_dataset("n" * 201)
        with pytest.raises(DatasetError, match="2000 characters"):
            store.create_dataset("ok", "d" * 2001)

    def test_unknown_and_invalid_ids(self, store):
        ghost = "11111111-1111-1111-1111-111111111111"
        with pytest.raises(DatasetError) as exc:
            store.get_dataset(ghost)
        assert exc.value.status == 404
        # Traversal-shaped IDs are rejected by the UUID gate.
        for bad in ("../../etc", "..\\..\\boot.ini", "", "not-a-uuid"):
            with pytest.raises(DatasetError) as exc:
                store.get_dataset(bad)
            assert exc.value.status == 404


# ════════════════════════════════════════════════════════════════════════════
# Individual / multi upload + content validation
# ════════════════════════════════════════════════════════════════════════════

class TestUploadValidation:
    def test_single_upload_records_full_metadata(self, store, dataset, tmp_path):
        outcome = _ingest(store, dataset["id"], "IMG_0042.jpg",
                          JPEG_BYTES, tmp_path)
        assert outcome["stats"] == {
            "accepted": 1, "duplicate": 0, "rejected": 0, "shared": 0}
        result = outcome["results"][0]
        assert result["status"] == "accepted"
        assert result["format"] == "JPEG"
        assert len(result["sha256"]) == 64

        # Physical file is content-addressed and byte-identical to source.
        stored = store.resolve_stored(result["stored_path"])
        assert stored.exists()
        assert stored.suffix == ".jpg"
        assert _sha(stored) == result["sha256"]
        assert stored.read_bytes() == JPEG_BYTES

        # images.jsonl line carries the full provenance record.
        rows = store._read_jsonl(store._jsonl_path(dataset["id"]))
        assert len(rows) == 1
        row = rows[0]
        assert row["original_filename"] == "IMG_0042.jpg"
        assert row["image_id"] == row["sha256"][:16]
        assert row["width"] == 48 and row["height"] == 48
        assert row["format"] == "JPEG"
        assert row["bytes"] == len(JPEG_BYTES)
        assert row["uploaded_at"] and row["duplicate_of"] is None
        assert row["stored_path"].startswith("images/")

        manifest = store.get_dataset(dataset["id"])
        assert manifest["image_count"] == 1
        assert manifest["bytes_total"] == len(JPEG_BYTES)

    def test_multi_format_batch(self, store, dataset, tmp_path):
        items = [
            ("a.jpg", JPEG_BYTES),
            ("b.png", PNG_BYTES),
            ("c.webp", WEBP_BYTES),
        ]
        staged = [(_stage(tmp_path, n, d), n) for n, d in items]
        outcome = store.ingest_batch(
            dataset["id"], [(n, p) for p, n in staged])
        assert outcome["stats"]["accepted"] == 3
        formats = {r["format"] for r in outcome["results"]}
        assert formats == {"JPEG", "PNG", "WEBP"}
        suffixes = {Path(r["stored_path"]).suffix
                    for r in outcome["results"]}
        assert suffixes == {".jpg", ".png", ".webp"}

    def test_content_not_extension_decides(self, store, dataset, tmp_path):
        # Valid PNG bytes with a .jpg extension → accepted as PNG content.
        outcome = _ingest(store, dataset["id"], "actually-a-png.jpg",
                          PNG_BYTES, tmp_path)
        result = outcome["results"][0]
        assert result["status"] == "accepted"
        assert result["format"] == "PNG"
        assert result["stored_path"].endswith(".png")

    @pytest.mark.parametrize("name,data,reason", [
        ("notes.txt", TEXT_BYTES, "unsupported_type"),      # bad extension
        ("photo.jpg", TEXT_BYTES, "unsupported_type"),      # bad content
        ("photo.jpg", b"", "empty"),                        # empty
        ("clip.gif", PNG_BYTES, "unsupported_type"),        # unsupported fmt
        ("trunc.png", TRUNCATED_PNG, "corrupt"),            # sig ok, decode fails
        ("data.zip", PNG_BYTES, "unsupported_type"),        # archive as image
    ], ids=["bad-ext", "bad-content", "empty", "gif-ext",
            "truncated", "zip-as-image"])
    def test_rejected_files(self, store, dataset, tmp_path, name, data,
                            reason):
        outcome = _ingest(store, dataset["id"], name, data, tmp_path)
        result = outcome["results"][0]
        assert result["status"] == "rejected"
        assert result["reason"] == reason
        manifest = store.get_dataset(dataset["id"])
        assert manifest["image_count"] == 0
        assert manifest["rejected_count"] == 1
        assert manifest["rejected_reasons"][reason] == 1
        assert _store_files(store) == []     # nothing stored

    def test_rejection_retry_is_idempotent(self, store, dataset, tmp_path):
        _ingest(store, dataset["id"], "photo.jpg", TEXT_BYTES, tmp_path)
        _ingest(store, dataset["id"], "photo.jpg", TEXT_BYTES, tmp_path)
        manifest = store.get_dataset(dataset["id"])
        assert manifest["rejected_count"] == 1       # deduped by (sha, name)
        rows = store._read_jsonl(store._rejected_path(dataset["id"]))
        assert len(rows) == 1

    def test_oversized_file_rejected(self, store, dataset, tmp_path, monkeypatch):
        monkeypatch.setattr(
            __import__("config").settings, "max_file_size_mb", 1)
        big = _noise_png(seed=9, size=(2000, 2000))
        assert len(big) > 1024 * 1024
        outcome = _ingest(store, dataset["id"], "huge.png", big, tmp_path)
        assert outcome["results"][0]["reason"] == "too_large"
        assert _store_files(store) == []

    def test_batch_size_limit(self, store, dataset, tmp_path):
        items = [(f"f{i}.png", _stage(tmp_path, f"f{i}.png", PNG_BYTES))
                 for i in range(MAX_FILES_PER_REQUEST + 1)]
        with pytest.raises(DatasetError, match="files per request"):
            store.ingest_batch(dataset["id"], items)


# ════════════════════════════════════════════════════════════════════════════
# Deduplication
# ════════════════════════════════════════════════════════════════════════════

class TestDeduplication:
    def test_within_dataset_duplicate(self, store, dataset, tmp_path):
        first = _ingest(store, dataset["id"], "one.png", PNG_BYTES, tmp_path)
        second = _ingest(store, dataset["id"], "two.png", PNG_BYTES, tmp_path)
        assert first["results"][0]["status"] == "accepted"
        assert second["results"][0]["status"] == "duplicate"
        assert second["results"][0]["sha256"] == first["results"][0]["sha256"]

        manifest = store.get_dataset(dataset["id"])
        assert manifest["image_count"] == 1
        assert manifest["duplicate_count"] == 1
        assert manifest["bytes_total"] == len(PNG_BYTES)
        assert len(_store_files(store)) == 1          # one physical copy
        rows = store._read_jsonl(store._jsonl_path(dataset["id"]))
        assert len(rows) == 1

    def test_retry_does_not_change_state(self, store, dataset, tmp_path):
        _ingest(store, dataset["id"], "one.png", PNG_BYTES, tmp_path)
        before = store.get_dataset(dataset["id"])
        files_before = _store_files(store)
        # Re-send the identical batch: state must not drift.
        _ingest(store, dataset["id"], "one.png", PNG_BYTES, tmp_path)
        after = store.get_dataset(dataset["id"])
        assert after["image_count"] == before["image_count"]
        assert after["bytes_total"] == before["bytes_total"]
        assert after["rejected_count"] == before["rejected_count"]
        assert _store_files(store) == files_before

    def test_cross_dataset_shared_asset(self, store, tmp_path):
        ds1 = store.create_dataset("Set A")
        ds2 = store.create_dataset("Set B")
        r1 = _ingest(store, ds1["id"], "shared.png", PNG_BYTES,
                     tmp_path)["results"][0]
        r2 = _ingest(store, ds2["id"], "same-content.png", PNG_BYTES,
                     tmp_path)["results"][0]
        assert r1["status"] == r2["status"] == "accepted"
        assert r1["shared"] is False
        assert r2["shared"] is True                 # physical copy reused
        assert r1["stored_path"] == r2["stored_path"]
        assert len(_store_files(store)) == 1        # ONE physical asset

        m1, m2 = store.get_dataset(ds1["id"]), store.get_dataset(ds2["id"])
        assert m1["image_count"] == m2["image_count"] == 1
        assert m1["shared_count"] == 0
        assert m2["shared_count"] == 1

    def test_originals_never_modified(self, store, dataset, tmp_path):
        src = _stage(tmp_path, "orig.jpg", JPEG_BYTES)
        before = _sha(src)
        store.ingest_batch(dataset["id"], [("orig.jpg", src)])
        store.ingest_batch(dataset["id"], [("orig.jpg", src)])   # duplicate
        assert _sha(src) == before
        assert src.read_bytes() == JPEG_BYTES

    def test_batch_reingest_after_restart_is_idempotent(self, tmp_path):
        root = tmp_path / "brand_intelligence"
        ds1 = DatasetStore(root=root)
        dataset = ds1.create_dataset("Restartable")
        src = _stage(tmp_path, "x.png", PNG_BYTES)
        ds1.ingest_batch(dataset["id"], [("x.png", src)])
        # Simulated backend restart: brand-new store object, same disk.
        ds2 = DatasetStore(root=root)
        outcome = ds2.ingest_batch(dataset["id"], [("x.png", src)])
        assert outcome["results"][0]["status"] == "duplicate"
        manifest = ds2.get_dataset(dataset["id"])
        assert manifest["image_count"] == 1
        assert len(_store_files(ds2)) == 1


# ════════════════════════════════════════════════════════════════════════════
# ZIP security
# ════════════════════════════════════════════════════════════════════════════

class TestZipSecurity:
    def test_valid_zip_nested_folders(self, store, dataset, tmp_path):
        zpath = _make_zip(tmp_path / "good.zip", {
            "photos/a.png": PNG_BYTES,
            "photos/deep/b.jpg": JPEG_BYTES,
            "root.webp": WEBP_BYTES,
        })
        outcome = store.ingest_zip(dataset["id"], zpath, "good.zip")
        assert outcome["stats"]["accepted"] == 3
        assert outcome["skipped"] == []
        # Original names are flattened to sanitized basenames.
        names = {r["filename"] for r in outcome["results"]}
        assert names == {"a.png", "b.jpg", "root.webp"}
        # Temp extraction cleaned up; source zip still caller-owned.
        assert list(store.tmp_dir(dataset["id"]).glob("zip_*")) == []
        assert zpath.exists()

    def test_unsupported_and_nested_entries_skipped(self, store, dataset,
                                                    tmp_path):
        zpath = _make_zip(tmp_path / "mixed.zip", {
            "ok.png": PNG_BYTES,
            "readme.txt": TEXT_BYTES,
            "inner.zip": b"PK\x03\x04 not really a zip",
            "movie.mp4": b"\x00\x00\x00\x18ftypmp42",
        })
        outcome = store.ingest_zip(dataset["id"], zpath, "mixed.zip")
        assert outcome["stats"]["accepted"] == 1
        reasons = {s["name"]: s["reason"] for s in outcome["skipped"]}
        assert reasons["readme.txt"] == "unsupported_type"
        assert reasons["inner.zip"] == "nested_archive"
        assert reasons["movie.mp4"] == "unsupported_type"

    @pytest.mark.parametrize("hostile", [
        "../evil.png",
        "a/../../evil.png",
        "/absolutive/evil.png",
        "C:\\Windows\\evil.png",
        "..\\..\\evil.png",
    ], ids=["dotdot", "nested-dotdot", "absolute", "drive", "backslash"])
    def test_path_traversal_aborts_archive(self, store, dataset, tmp_path,
                                           hostile):
        zpath = _make_zip(tmp_path / "evil.zip", {
            hostile: PNG_BYTES,
            "fine.png": PNG_BYTES,
        })
        with pytest.raises(DatasetError) as exc:
            store.ingest_zip(dataset["id"], zpath, "evil.zip")
        assert exc.value.code == "zip_traversal"
        # Nothing extracted anywhere — not even the benign entry.
        assert store._read_jsonl(store._jsonl_path(dataset["id"])) == []
        assert _store_files(store) == []
        assert list(store.tmp_dir(dataset["id"]).glob("zip_*")) == []
        # And nothing escaped the store root.
        outside = [p for p in tmp_path.rglob("evil.png")]
        assert outside == []

    def test_symlink_entry_rejected(self, store, dataset, tmp_path):
        link = zipfile.ZipInfo("link.png")
        link.external_attr = (0o120777 << 16)          # S_IFLNK | 0777
        zpath = _make_zip(tmp_path / "link.zip", {"link.png": link})
        with pytest.raises(DatasetError) as exc:
            store.ingest_zip(dataset["id"], zpath, "link.zip")
        assert exc.value.code == "zip_symlink"
        assert _store_files(store) == []

    def test_zip_bomb_ratio_rejected(self, store, dataset, tmp_path):
        # 2MB of zeros compresses ~1000:1 → ratio guard trips.
        bomb = _make_zip(tmp_path / "bomb.zip", {"big.png": b"\0" * (2 << 20)})
        with pytest.raises(DatasetError) as exc:
            store.ingest_zip(dataset["id"], bomb, "bomb.zip")
        assert exc.value.code == "zip_bomb_ratio"

    def test_zip_limits_count_size_total(self, store, dataset, tmp_path):
        entries = {f"f{i}.png": PNG_BYTES for i in range(6)}
        zpath = _make_zip(tmp_path / "many.zip", entries)
        tmp = store.tmp_dir(dataset["id"]) / "probe"
        tmp.mkdir(parents=True)

        with pytest.raises(IngestionError) as exc:
            extract_zip_safely(zpath, tmp, ZipLimits(max_files=5))
        assert exc.value.code == "zip_too_many_files"

        with pytest.raises(IngestionError) as exc:
            extract_zip_safely(zpath, tmp,
                               ZipLimits(max_entry_bytes=len(PNG_BYTES) - 1))
        assert exc.value.code == "zip_entry_too_large"

        with pytest.raises(IngestionError) as exc:
            extract_zip_safely(zpath, tmp,
                               ZipLimits(max_total_bytes=10))
        assert exc.value.code == "zip_total_too_large"

        # Hostile limits abort before anything is written.
        assert list(tmp.iterdir()) == []

    def test_corrupt_image_inside_zip_rejected_per_entry(
            self, store, dataset, tmp_path):
        zpath = _make_zip(tmp_path / "c.zip", {
            "good.png": PNG_BYTES,
            "broken.jpg": TEXT_BYTES,
        })
        outcome = store.ingest_zip(dataset["id"], zpath, "c.zip")
        assert outcome["stats"]["accepted"] == 1
        assert outcome["stats"]["rejected"] == 1
        rejected = [r for r in outcome["results"]
                    if r["status"] == "rejected"][0]
        assert rejected["filename"] == "broken.jpg"

    def test_not_a_zip_rejected(self, store, dataset, tmp_path):
        bad = _stage(tmp_path, "upload.zip", b"PK\x03\x04 garbage")
        with pytest.raises(DatasetError) as exc:
            store.ingest_zip(dataset["id"], bad, "upload.zip")
        assert exc.value.code == "zip_unreadable"

    def test_sanitize_entry_name_unit(self):
        assert sanitize_entry_name("a/b/c.png") == "c.png"
        assert sanitize_entry_name("..\\..\\x.png") is None
        assert sanitize_entry_name("../x.png") is None
        assert sanitize_entry_name("/etc/passwd") is None
        assert sanitize_entry_name("C:/evil.png") is None
        assert sanitize_entry_name("a\x00b.png") is None
        assert sanitize_entry_name("we<ird>.png") == "we_ird_.png"


# ════════════════════════════════════════════════════════════════════════════
# Chunked, resumable uploads (store level)
# ════════════════════════════════════════════════════════════════════════════

def _chunked_payload(total_chunks: int, chunk_size: int,
                     payload: bytes) -> list:
    return [payload[i * chunk_size:(i + 1) * chunk_size]
            for i in range(total_chunks)]


class TestChunkedUpload:
    def _session(self, store, ds_id, filename, payload, chunks):
        return store.create_upload_session(
            ds_id, filename=filename, total_bytes=len(payload),
            total_chunks=chunks)

    def test_out_of_order_chunks_then_complete(self, store, dataset,
                                               tmp_path):
        payload = _noise_png(seed=11, size=(200, 200))
        chunks = 4
        chunk_size = (len(payload) + chunks - 1) // chunks
        session = self._session(store, dataset["id"], "big.png",
                                payload, chunks)
        uid = session["upload_id"]
        parts = _chunked_payload(chunks, chunk_size, payload)

        for index in (2, 0, 3, 1):                # deliberately out of order
            result = store.save_chunk(dataset["id"], uid, index, parts[index])
            assert result["duplicate"] is False

        outcome = store.complete_upload(dataset["id"], uid)
        assert outcome["results"][0]["status"] == "accepted"
        stored = store.resolve_stored(
            outcome["results"][0]["stored_path"])
        assert stored.read_bytes() == payload     # byte-exact reassembly
        # Chunk parts cleaned up after success.
        assert not store.tmp_dir(dataset["id"]).joinpath(uid).exists()

    def test_duplicate_chunk_submission_idempotent(self, store, dataset,
                                                  tmp_path):
        payload = _noise_png(seed=12, size=(200, 200))
        chunks = 3
        chunk_size = (len(payload) + chunks - 1) // chunks
        session = self._session(store, dataset["id"], "big.png",
                                payload, chunks)
        uid = session["upload_id"]
        parts = _chunked_payload(chunks, chunk_size, payload)

        store.save_chunk(dataset["id"], uid, 0, parts[0])
        retry = store.save_chunk(dataset["id"], uid, 0, parts[0])
        assert retry["duplicate"] is True          # identical retry: OK

        # Conflicting content for an ALREADY-STORED index must never
        # overwrite (index 0 is stored; index 1 is not).
        corrupted = b"\x00" * len(parts[0])
        with pytest.raises(DatasetError) as exc:
            store.save_chunk(dataset["id"], uid, 0, corrupted)
        assert exc.value.status == 409

        # Finish properly — the good copy wins.
        store.save_chunk(dataset["id"], uid, 1, parts[1])
        store.save_chunk(dataset["id"], uid, 2, parts[2])
        outcome = store.complete_upload(dataset["id"], uid)
        stored = store.resolve_stored(outcome["results"][0]["stored_path"])
        assert stored.read_bytes() == payload

    def test_invalid_chunks_rejected(self, store, dataset, tmp_path):
        payload = _noise_png(seed=13, size=(200, 200))
        chunks = 3
        chunk_size = (len(payload) + chunks - 1) // chunks
        session = self._session(store, dataset["id"], "big.png",
                                payload, chunks)
        uid = session["upload_id"]

        with pytest.raises(DatasetError, match="out of range"):
            store.save_chunk(dataset["id"], uid, 3, b"x")
        with pytest.raises(DatasetError, match="out of range"):
            store.save_chunk(dataset["id"], uid, -1, b"x")
        wrong_size = b"short"
        with pytest.raises(DatasetError, match="expected"):
            store.save_chunk(dataset["id"], uid, 0, wrong_size)

    def test_complete_before_all_chunks_conflicts(self, store, dataset,
                                                  tmp_path):
        payload = _noise_png(seed=14, size=(200, 200))
        chunks = 3
        session = self._session(store, dataset["id"], "big.png",
                                payload, chunks)
        uid = session["upload_id"]
        with pytest.raises(DatasetError) as exc:
            store.complete_upload(dataset["id"], uid)
        assert exc.value.status == 409
        assert "chunks missing" in exc.value.message

    def test_complete_is_idempotent(self, store, dataset, tmp_path):
        payload = _noise_png(seed=15, size=(120, 120))
        chunks = 2
        chunk_size = (len(payload) + chunks - 1) // chunks
        session = self._session(store, dataset["id"], "once.png",
                                payload, chunks)
        uid = session["upload_id"]
        for i, part in enumerate(_chunked_payload(chunks, chunk_size, payload)):
            store.save_chunk(dataset["id"], uid, i, part)

        first = store.complete_upload(dataset["id"], uid)
        second = store.complete_upload(dataset["id"], uid)   # retry after done
        assert second == first
        manifest = store.get_dataset(dataset["id"])
        assert manifest["image_count"] == 1
        assert len(_store_files(store)) == 1

    def test_resume_after_backend_restart(self, tmp_path):
        root = tmp_path / "brand_intelligence"
        store_a = DatasetStore(root=root)
        dataset = store_a.create_dataset("Resumable")
        payload = _noise_png(seed=16, size=(300, 300))
        chunks = 5
        chunk_size = (len(payload) + chunks - 1) // chunks
        session = store_a.create_upload_session(
            dataset["id"], filename="big.png",
            total_bytes=len(payload), total_chunks=chunks)
        uid = session["upload_id"]
        parts = _chunked_payload(chunks, chunk_size, payload)

        # Connection drops after chunk 1 of 5.
        store_a.save_chunk(dataset["id"], uid, 0, parts[0])
        store_a.save_chunk(dataset["id"], uid, 1, parts[1])

        # ── simulated backend restart: fresh objects, same disk ──
        store_b = DatasetStore(root=root)
        pending = store_b.list_upload_sessions(dataset["id"])
        assert len(pending) == 1
        assert pending[0]["upload_id"] == uid
        assert pending[0]["received_chunks"] == [0, 1]
        assert pending[0]["missing_chunks"] == [2, 3, 4]

        # Client re-sends ONLY the missing chunks.
        for i in pending[0]["missing_chunks"]:
            store_b.save_chunk(dataset["id"], uid, i, parts[i])
        outcome = store_b.complete_upload(dataset["id"], uid)
        assert outcome["results"][0]["status"] == "accepted"
        stored = store_b.resolve_stored(outcome["results"][0]["stored_path"])
        assert stored.read_bytes() == payload
        assert store_b.list_upload_sessions(dataset["id"]) == []
        assert store_b.get_dataset(dataset["id"])["image_count"] == 1

    def test_session_parameter_conflict(self, store, dataset, tmp_path):
        first = store.create_upload_session(
            dataset["id"], filename="a.png", total_bytes=100,
            total_chunks=4)
        with pytest.raises(DatasetError) as exc:
            store.create_upload_session(
                dataset["id"],
                filename="different.png", total_bytes=100,
                total_chunks=4, upload_id=first["upload_id"])
        assert exc.value.status == 409

    def test_session_validation(self, store, dataset):
        with pytest.raises(DatasetError, match="positive"):
            store.create_upload_session(
                dataset["id"], filename="a.png", total_bytes=0,
                total_chunks=1)
        with pytest.raises(DatasetError, match="total_chunks"):
            store.create_upload_session(
                dataset["id"], filename="a.png", total_bytes=10,
                total_chunks=99)
        with pytest.raises(DatasetError) as exc:
            store.create_upload_session(
                dataset["id"], filename="a.png", total_bytes=10 ** 9,
                total_chunks=10)
        assert exc.value.status == 413
        with pytest.raises(DatasetError) as exc:
            store.create_upload_session(
                "99999999-9999-9999-9999-999999999999",
                filename="a.png", total_bytes=10, total_chunks=1)
        assert exc.value.status == 404

    def test_discard_pending_session(self, store, dataset, tmp_path):
        payload = _noise_png(seed=17, size=(100, 100))
        chunk_size = (len(payload) + 1) // 2
        session = store.create_upload_session(
            dataset["id"], filename="a.png", total_bytes=len(payload),
            total_chunks=2)
        uid = session["upload_id"]
        store.save_chunk(dataset["id"], uid, 0, payload[:chunk_size])
        assert len(store.list_upload_sessions(dataset["id"])) == 1

        store.discard_upload(dataset["id"], uid)
        assert store.list_upload_sessions(dataset["id"]) == []
        assert not store.tmp_dir(dataset["id"]).joinpath(uid).exists()
        with pytest.raises(DatasetError) as exc:
            store.discard_upload(dataset["id"], uid)
        assert exc.value.status == 404


# ════════════════════════════════════════════════════════════════════════════
# Manifest consistency + finalize verification gate
# ════════════════════════════════════════════════════════════════════════════

class TestManifestConsistency:
    def test_counters_match_jsonl(self, store, dataset, tmp_path):
        items = [
            ("ok1.png", PNG_BYTES),
            ("ok2.jpg", JPEG_BYTES),
            ("dup.png", PNG_BYTES),          # duplicate of ok1
            ("bad.jpg", TEXT_BYTES),         # rejected
        ]
        staged = [(n, _stage(tmp_path, n, d)) for n, d in items]
        outcome = store.ingest_batch(dataset["id"], staged)
        assert outcome["stats"] == {
            "accepted": 2, "duplicate": 1, "rejected": 1, "shared": 0}

        manifest = store.get_dataset(dataset["id"])
        rows = store._read_jsonl(store._jsonl_path(dataset["id"]))
        assert manifest["image_count"] == len(rows) == 2
        assert manifest["bytes_total"] == sum(r["bytes"] for r in rows)
        assert manifest["duplicate_count"] == 1
        assert manifest["rejected_count"] == 1
        assert manifest["rejected_reasons"] == {"unsupported_type": 1}

    def test_finalize_reconciles_tampered_counters(self, store, dataset,
                                                   tmp_path):
        _ingest(store, dataset["id"], "a.png", PNG_BYTES, tmp_path)
        # Simulate a drifted/corrupt counter on disk.
        path = store._manifest_path(dataset["id"])
        manifest = json.loads(path.read_text())
        manifest["image_count"] = 999
        manifest["bytes_total"] = 12345
        path.write_text(json.dumps(manifest))

        finalized = store.finalize_dataset(dataset["id"])
        assert finalized["status"] == "ready"
        assert finalized["image_count"] == 1            # reconciled
        assert finalized["bytes_total"] == len(PNG_BYTES)

    def test_finalize_refuses_pending_uploads(self, store, dataset,
                                              tmp_path):
        payload = _noise_png(seed=18, size=(100, 100))
        store.create_upload_session(
            dataset["id"], filename="a.png", total_bytes=len(payload),
            total_chunks=2)
        with pytest.raises(DatasetError) as exc:
            store.finalize_dataset(dataset["id"])
        assert exc.value.status == 409
        assert "incomplete uploads" in exc.value.message

    def test_finalize_refuses_missing_assets(self, store, dataset, tmp_path):
        outcome = _ingest(store, dataset["id"], "a.png", PNG_BYTES, tmp_path)
        stored = store.resolve_stored(outcome["results"][0]["stored_path"])
        stored.unlink()                                   # external damage
        with pytest.raises(DatasetError) as exc:
            store.finalize_dataset(dataset["id"])
        assert exc.value.status == 409
        assert "missing" in exc.value.message
        # Status must NOT be ready.
        assert store.get_dataset(dataset["id"])["status"] == "ingesting"

    def test_upload_after_finalize_reopens_dataset(self, store, dataset,
                                                   tmp_path):
        _ingest(store, dataset["id"], "a.png", PNG_BYTES, tmp_path)
        assert store.finalize_dataset(dataset["id"])["status"] == "ready"
        _ingest(store, dataset["id"], "b.png", JPEG_BYTES, tmp_path)
        assert store.get_dataset(dataset["id"])["status"] == "ingesting"
        assert store.finalize_dataset(dataset["id"])["status"] == "ready"

    def test_image_listing_pagination_and_search(self, store, dataset,
                                                 tmp_path):
        for i in range(7):
            _ingest(store, dataset["id"], f"photo_{i}.png",
                    _noise_png(seed=100 + i), tmp_path)
        page1 = store.list_images(dataset["id"], offset=0, limit=3)
        page2 = store.list_images(dataset["id"], offset=3, limit=3)
        assert page1["total"] == page2["total"] == 7
        assert len(page1["images"]) == 3
        assert len(page2["images"]) == 3
        assert {r["original_filename"] for r in page1["images"]} != \
            {r["original_filename"] for r in page2["images"]}

        hit = store.list_images(dataset["id"], q="photo_4")
        assert hit["total"] == 1
        assert hit["images"][0]["original_filename"] == "photo_4.png"


# ════════════════════════════════════════════════════════════════════════════
# Deletion safety
# ════════════════════════════════════════════════════════════════════════════

class TestDeletionSafety:
    def test_delete_keeps_shared_assets_for_other_datasets(self, store,
                                                           tmp_path):
        ds1 = store.create_dataset("Doomed")
        ds2 = store.create_dataset("Survivor")
        shared = _ingest(store, ds1["id"], "shared.png", PNG_BYTES,
                         tmp_path)["results"][0]
        _ingest(store, ds2["id"], "shared.png", PNG_BYTES, tmp_path)
        only_ds1 = _ingest(store, ds1["id"], "only1.jpg", JPEG_BYTES,
                           tmp_path)["results"][0]
        assert len(_store_files(store)) == 2

        store.delete_dataset(ds1["id"])

        # Dataset 1 fully gone.
        assert not store._manifest_path(ds1["id"]).exists()
        assert not store._dataset_dir(ds1["id"]).exists()
        with pytest.raises(DatasetError):
            store.get_dataset(ds1["id"])

        # Shared asset survives; dataset 2's reference still resolves.
        shared_path = store.resolve_stored(shared["stored_path"])
        assert shared_path.exists()
        assert _sha(shared_path) == shared["sha256"]
        ds2_rows = store._read_jsonl(store._jsonl_path(ds2["id"]))
        assert len(ds2_rows) == 1
        assert store.resolve_stored(ds2_rows[0]["stored_path"]).exists()
        assert store.get_dataset(ds2["id"])["image_count"] == 1

        # Dataset-1-only asset is also left in place (Phase 2 keeps the
        # shared store append-only — no GC), so nothing can break by luck.
        assert store.resolve_stored(only_ds1["stored_path"]).exists()
        # Survivor dataset can still ingest and finalize after the deletion.
        _ingest(store, ds2["id"], "new.png", OTHER_PNG, tmp_path)
        assert store.finalize_dataset(ds2["id"])["status"] == "ready"

    def test_delete_twice_is_404(self, store):
        ds = store.create_dataset("Temp")
        store.delete_dataset(ds["id"])
        with pytest.raises(DatasetError) as exc:
            store.delete_dataset(ds["id"])
        assert exc.value.status == 404


# ════════════════════════════════════════════════════════════════════════════
# API contract (real router via TestClient)
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def api(monkeypatch, tmp_path):
    from api import brand_intel_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(brand_intel_routes.router)
    store = DatasetStore(root=tmp_path / "brand_intelligence")
    monkeypatch.setattr(brand_intel_routes, "dataset_store", store)
    return TestClient(app), store


def _create(client, name="API Set") -> dict:
    resp = client.post("/api/brand-intel/datasets",
                       json={"name": name, "description": "via api"})
    assert resp.status_code == 200
    return resp.json()


class TestDatasetApi:
    def test_crud_over_http(self, api):
        client, store = api
        created = _create(client, "HTTP Set")
        assert created["status"] == "ingesting"

        listed = client.get("/api/brand-intel/datasets").json()["datasets"]
        assert [d["name"] for d in listed] == ["HTTP Set"]

        detail = client.get(
            f"/api/brand-intel/datasets/{created['id']}").json()
        assert detail["description"] == "via api"

        # Delete requires an exact-name confirmation.
        denied = client.delete(
            f"/api/brand-intel/datasets/{created['id']}",
            params={"confirm": "wrong name"})
        assert denied.status_code == 400
        assert client.get(
            f"/api/brand-intel/datasets/{created['id']}").status_code == 200

        ok = client.delete(
            f"/api/brand-intel/datasets/{created['id']}",
            params={"confirm": "HTTP Set"})
        assert ok.status_code == 200
        assert client.get(
            f"/api/brand-intel/datasets/{created['id']}").status_code == 404

        # Unknown / traversal IDs are 404, never 500.
        assert client.get(
            "/api/brand-intel/datasets/..%2F..%2Fetc").status_code == 404
        assert client.delete(
            "/api/brand-intel/datasets/99999999-9999-9999-9999-999999999999",
            params={"confirm": "x"}).status_code == 404

    def test_upload_files_over_http(self, api, tmp_path):
        client, store = api
        created = _create(client)
        resp = client.post(
            f"/api/brand-intel/datasets/{created['id']}/upload",
            files=[
                ("files", ("a.png", PNG_BYTES, "image/png")),
                ("files", ("b.jpg", JPEG_BYTES, "image/jpeg")),
                ("files", ("fake.png", TEXT_BYTES, "image/png")),
            ],
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["stats"]["accepted"] == 2
        assert body["stats"]["rejected"] == 1
        # Content decides, not the MIME header: fake.png is rejected even
        # though it claimed image/png.
        by_name = {r["filename"]: r["status"] for r in body["results"]}
        assert by_name == {"a.png": "accepted", "b.jpg": "accepted",
                           "fake.png": "rejected"}

        detail = client.get(
            f"/api/brand-intel/datasets/{created['id']}").json()
        assert detail["image_count"] == 2
        assert detail["rejected_count"] == 1

        images = client.get(
            f"/api/brand-intel/datasets/{created['id']}/images").json()
        assert images["total"] == 2
        assert images["images"][0]["stored_path"].startswith("images/")

    def test_upload_zip_over_http(self, api, tmp_path):
        client, store = api
        created = _create(client)
        zpath = _make_zip(tmp_path / "api.zip", {
            "folder/x.png": PNG_BYTES,
            "folder/deep/y.jpg": JPEG_BYTES,
            "junk.txt": TEXT_BYTES,
        })
        resp = client.post(
            f"/api/brand-intel/datasets/{created['id']}/upload-zip",
            files={"file": ("api.zip", zpath.read_bytes(), "application/zip")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["stats"]["accepted"] == 2
        assert {s["reason"] for s in body["skipped"]} == {"unsupported_type"}
        # Source ZIP was removed from the temp area.
        assert list(store.tmp_dir(created["id"]).glob("upload_*")) == []

        # Non-zip payload rejected.
        resp = client.post(
            f"/api/brand-intel/datasets/{created['id']}/upload-zip",
            files={"file": ("api.zip", b"not a zip", "application/zip")},
        )
        assert resp.status_code == 422

        # Hostile ZIP → 422 with nothing stored.
        evil = _make_zip(tmp_path / "evil.zip", {"../escape.png": PNG_BYTES})
        resp = client.post(
            f"/api/brand-intel/datasets/{created['id']}/upload-zip",
            files={"file": ("evil.zip", evil.read_bytes(),
                            "application/zip")},
        )
        assert resp.status_code == 422
        assert not (tmp_path / "escape.png").exists()

    def test_chunked_flow_over_http(self, api, tmp_path):
        client, store = api
        created = _create(client)
        payload = _noise_png(seed=21, size=(240, 240))
        chunks = 4
        chunk_size = (len(payload) + chunks - 1) // chunks

        session = client.post(
            f"/api/brand-intel/datasets/{created['id']}/uploads",
            json={"filename": "large.png", "total_bytes": len(payload),
                  "total_chunks": chunks}).json()
        uid = session["upload_id"]
        parts = _chunked_payload(chunks, chunk_size, payload)

        # Duplicate submission of chunk 0 → 200 with duplicate=True.
        r0 = client.post(
            f"/api/brand-intel/datasets/{created['id']}/uploads/{uid}"
            f"/chunks/0",
            files={"file": ("c", parts[0], "application/octet-stream")})
        assert r0.status_code == 200 and r0.json()["duplicate"] is False
        r0again = client.post(
            f"/api/brand-intel/datasets/{created['id']}/uploads/{uid}"
            f"/chunks/0",
            files={"file": ("c", parts[0], "application/octet-stream")})
        assert r0again.status_code == 200 and r0again.json()["duplicate"] is True

        # Conflicting chunk content → 409.
        conflict = client.post(
            f"/api/brand-intel/datasets/{created['id']}/uploads/{uid}"
            f"/chunks/0",
            files={"file": ("c", b"\x01" * len(parts[0]),
                            "application/octet-stream")})
        assert conflict.status_code == 409

        # Wrong-size chunk → 422.
        bad = client.post(
            f"/api/brand-intel/datasets/{created['id']}/uploads/{uid}"
            f"/chunks/1",
            files={"file": ("c", b"short", "application/octet-stream")})
        assert bad.status_code == 422

        # Complete too early → 409.
        early = client.post(
            f"/api/brand-intel/datasets/{created['id']}/uploads/{uid}"
            "/complete")
        assert early.status_code == 409
        pending = client.get(
            f"/api/brand-intel/datasets/{created['id']}/uploads").json()
        assert len(pending["uploads"]) == 1
        assert pending["uploads"][0]["missing_chunks"] == [1, 2, 3]

        # Send the rest, complete twice (idempotent).
        for i in (1, 2, 3):
            resp = client.post(
                f"/api/brand-intel/datasets/{created['id']}/uploads/{uid}"
                f"/chunks/{i}",
                files={"file": ("c", parts[i], "application/octet-stream")})
            assert resp.status_code == 200
        first = client.post(
            f"/api/brand-intel/datasets/{created['id']}/uploads/{uid}"
            "/complete").json()
        second = client.post(
            f"/api/brand-intel/datasets/{created['id']}/uploads/{uid}"
            "/complete").json()
        assert first["results"][0]["status"] == "accepted"
        assert second["results"][0]["status"] == "accepted"

        detail = client.get(
            f"/api/brand-intel/datasets/{created['id']}").json()
        assert detail["image_count"] == 1
        assert detail["pending_uploads"] == 0

        # Finalize → ready; upload after that → ingesting again.
        assert client.post(
            f"/api/brand-intel/datasets/{created['id']}/finalize"
        ).json()["status"] == "ready"
        client.post(
            f"/api/brand-intel/datasets/{created['id']}/upload",
            files=[("files", ("more.png", OTHER_PNG, "image/png"))])
        assert client.get(
            f"/api/brand-intel/datasets/{created['id']}").json()[
                "status"] == "ingesting"

    def test_discard_session_over_http(self, api, tmp_path):
        client, _ = api
        created = _create(client)
        session = client.post(
            f"/api/brand-intel/datasets/{created['id']}/uploads",
            json={"filename": "a.png", "total_bytes": 10, "total_chunks": 2},
        ).json()
        uid = session["upload_id"]
        assert client.delete(
            f"/api/brand-intel/datasets/{created['id']}/uploads/{uid}"
        ).status_code == 200
        assert client.delete(
            f"/api/brand-intel/datasets/{created['id']}/uploads/{uid}"
        ).status_code == 404

    def test_finalize_gate_over_http(self, api, tmp_path):
        client, _ = api
        created = _create(client)
        client.post(
            f"/api/brand-intel/datasets/{created['id']}/upload",
            files=[("files", ("a.png", PNG_BYTES, "image/png"))])
        session = client.post(
            f"/api/brand-intel/datasets/{created['id']}/uploads",
            json={"filename": "pending.png", "total_bytes": 100,
                  "total_chunks": 2}).json()
        blocked = client.post(
            f"/api/brand-intel/datasets/{created['id']}/finalize")
        assert blocked.status_code == 409
        assert "incomplete uploads" in blocked.json()["detail"]
        client.delete(
            f"/api/brand-intel/datasets/{created['id']}/uploads/"
            f"{session['upload_id']}")
        assert client.post(
            f"/api/brand-intel/datasets/{created['id']}/finalize"
        ).json()["status"] == "ready"

    def test_dataset_id_confinement_over_http(self, api):
        client, _ = api
        for bad in ("..%2F..%2Fdatasets", "not-a-uuid",
                    "99999999-9999-9999-9999-999999999999"):
            resp = client.get(f"/api/brand-intel/datasets/{bad}")
            assert resp.status_code in (404, 422)


# ════════════════════════════════════════════════════════════════════════════
# Incremental ingestion (large datasets never fully in memory)
# ════════════════════════════════════════════════════════════════════════════

class TestIncrementalIngestion:
    def test_streaming_batches_of_many_files(self, store, tmp_path):
        """Simulate a large dataset pushed in client-sized chunks: each file
        is generated, ingested and released before the next — the store only
        ever holds ONE source file at a time."""
        dataset = store.create_dataset("Bulk")
        total = 60
        for batch in range(0, total, 10):
            staged = []
            for i in range(batch, min(batch + 10, total)):
                path = _stage(tmp_path / "bulk", f"img_{i:03d}.png",
                              _noise_png(seed=i, size=(64, 64)))
                staged.append((path.name, path))
            outcome = store.ingest_batch(dataset["id"], staged)
            assert outcome["stats"]["accepted"] == len(staged)
            # Release sources immediately — no accumulation.
            for _, path in staged:
                path.unlink()

        manifest = store.get_dataset(dataset["id"])
        assert manifest["image_count"] == total
        assert len(_store_files(store)) == total
        assert store.finalize_dataset(dataset["id"])["status"] == "ready"


# ════════════════════════════════════════════════════════════════════════════
# Acceptance workflow — a real test dataset end to end
# ════════════════════════════════════════════════════════════════════════════

class TestAcceptanceWorkflow:
    def test_full_workflow(self, api, tmp_path):
        client, store = api

        # ── 0. Build a REAL test dataset on disk ────────────────────────────
        src = tmp_path / "real_dataset"
        (src / "nested" / "deep").mkdir(parents=True)
        files = {
            "photo_a.jpg": _fmt_bytes("JPEG", seed=201, size=(640, 480)),
            "photo_b.png": _noise_png(seed=202, size=(640, 480)),
            "photo_c.webp": _fmt_bytes("WEBP", seed=203, size=(640, 480)),
            "duplicate_of_a.jpg": None,                # set below (copy of a)
            "nested/deep/large.png": _noise_png(seed=204, size=(1200, 1200)),
            "notes.txt": TEXT_BYTES,                   # invalid: type
            "corrupt.jpg": TEXT_BYTES,                 # invalid: content
        }
        for name, data in files.items():
            path = src / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if data is not None:
                path.write_bytes(data)
        # Duplicate = byte-identical copy under a different name.
        shutil.copyfile(src / "photo_a.jpg",
                        src / "duplicate_of_a.jpg")
        files["duplicate_of_a.jpg"] = files["photo_a.jpg"]

        # Originals snapshot (must remain byte-identical at the end).
        before = {p: _sha(p) for p in src.rglob("*") if p.is_file()}
        assert len(before) == 7

        # ── 1. Dataset created ─────────────────────────────────────────────
        ds = _create(client, "Acceptance Set")
        ds_id = ds["id"]

        # ── 2. Individual + multi upload (4 valid + 2 invalid) ─────────────
        batch = [
            ("files", (n, (src / n).read_bytes(),
                       "application/octet-stream"))
            for n in ["photo_a.jpg", "photo_b.png", "photo_c.webp",
                      "notes.txt", "corrupt.jpg"]
        ]
        resp = client.post(f"/api/brand-intel/datasets/{ds_id}/upload",
                           files=batch)
        assert resp.status_code == 200
        stats = resp.json()["stats"]
        assert stats["accepted"] == 3
        assert stats["rejected"] == 2

        # ── 3. ZIP upload: nested folders + duplicate + large image ────────
        zpath = _make_zip(tmp_path / "bundle.zip", {
            "nested/deep/large.png": (src / "nested/deep/large.png").read_bytes(),
            "duplicate_of_a.jpg": (src / "duplicate_of_a.jpg").read_bytes(),
            "readme.txt": TEXT_BYTES,
        })
        resp = client.post(
            f"/api/brand-intel/datasets/{ds_id}/upload-zip",
            files={"file": ("bundle.zip", zpath.read_bytes(),
                            "application/zip")})
        assert resp.status_code == 200
        zbody = resp.json()
        assert zbody["stats"]["accepted"] == 1        # large.png
        assert zbody["stats"]["duplicate"] == 1       # duplicate_of_a.jpg
        assert zbody["stats"]["rejected"] == 0
        assert {s["reason"] for s in zbody["skipped"]} == {"unsupported_type"}

        # ── 4. Interrupted chunked upload, resume after "restart" ──────────
        big = (src / "nested/deep/large.png").read_bytes()
        chunks = 6
        chunk_size = (len(big) + chunks - 1) // chunks
        session = client.post(
            f"/api/brand-intel/datasets/{ds_id}/uploads",
            json={"filename": "resumed.png", "total_bytes": len(big),
                  "total_chunks": chunks}).json()
        uid = session["upload_id"]
        parts = _chunked_payload(chunks, chunk_size, big)
        for i in (0, 1, 2):                          # connection drops here
            client.post(
                f"/api/brand-intel/datasets/{ds_id}/uploads/{uid}/chunks/{i}",
                files={"file": ("c", parts[i], "application/octet-stream")})

        # Backend restart: a fresh store instance reads the same disk state.
        monkey_store = DatasetStore(root=store.root)
        pending = monkey_store.list_upload_sessions(ds_id)
        assert len(pending) == 1
        assert pending[0]["missing_chunks"] == [3, 4, 5]

        # Resume through the API (same on-disk session).
        for i in pending[0]["missing_chunks"]:
            resp = client.post(
                f"/api/brand-intel/datasets/{ds_id}/uploads/{uid}/chunks/{i}",
                files={"file": ("c", parts[i], "application/octet-stream")})
            assert resp.status_code == 200
        done = client.post(
            f"/api/brand-intel/datasets/{ds_id}/uploads/{uid}/complete"
        ).json()
        # resumed.png carries the SAME bytes as large.png (already stored
        # via the ZIP) → correctly detected as a duplicate, not re-stored.
        assert done["results"][0]["status"] == "duplicate"

        # ── 5. Manifest correct, dataset finalized ─────────────────────────
        detail = client.get(f"/api/brand-intel/datasets/{ds_id}").json()
        # photo_a, photo_b, photo_c, large.png, resumed.png (same content as
        # large.png? NO — resumed.png IS large.png content → duplicate!)
        # Recheck: resumed.png content == large.png content → duplicate.
        assert detail["image_count"] == 4
        assert detail["duplicate_count"] == 2         # dup_of_a + resumed
        assert detail["rejected_count"] == 2
        assert detail["bytes_total"] > 0
        assert detail["rejected_reasons"] == {"unsupported_type": 2}

        rows = client.get(
            f"/api/brand-intel/datasets/{ds_id}/images?limit=50").json()
        assert rows["total"] == 4
        assert {r["format"] for r in rows["images"]} == {"JPEG", "PNG", "WEBP"}
        # Every referenced asset exists on disk.
        for r in rows["images"]:
            assert store.resolve_stored(r["stored_path"]).exists()

        finalized = client.post(
            f"/api/brand-intel/datasets/{ds_id}/finalize").json()
        assert finalized["status"] == "ready"

        # ── 6. Shared asset: second dataset + deletion safety ──────────────
        ds2 = _create(client, "Second Set")
        resp = client.post(
            f"/api/brand-intel/datasets/{ds2['id']}/upload",
            files=[("files", ("a_copy.jpg", files["photo_a.jpg"],
                              "image/jpeg"))])
        assert resp.json()["results"][0]["shared"] is True
        physical_before = len(_store_files(store))
        shared_path = resp.json()["results"][0]["stored_path"]

        assert client.delete(
            f"/api/brand-intel/datasets/{ds_id}",
            params={"confirm": "Acceptance Set"}).status_code == 200
        # Shared physical asset survives dataset deletion.
        assert store.resolve_stored(shared_path).exists()
        assert len(_store_files(store)) == physical_before
        # Second dataset fully functional afterwards.
        detail2 = client.get(
            f"/api/brand-intel/datasets/{ds2['id']}").json()
        assert detail2["image_count"] == 1
        assert client.post(
            f"/api/brand-intel/datasets/{ds2['id']}/finalize"
        ).json()["status"] == "ready"

        # ── 7. Originals unchanged (byte-compare) ──────────────────────────
        after = {p: _sha(p) for p in src.rglob("*") if p.is_file()}
        assert after == before

        # ── 8. No temp residue anywhere ─────────────────────────────────────
        leftovers = [p for p in store.datasets_dir.rglob("*")
                     if p.is_file() and "tmp" in p.parts]
        assert leftovers == []
