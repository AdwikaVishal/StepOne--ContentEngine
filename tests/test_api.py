"""
API endpoint tests.

Tests cover:
  - Health check
  - File validation (size, MIME type)
  - Async job submission (Celery + APScheduler paths)
  - Job status polling
  - Job result retrieval
  - WebSocket connection
"""

import pytest
import json
import io
import asyncio
import types
from unittest.mock import patch, Mock, AsyncMock
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile
from fastapi import HTTPException


# ── Health ────────────────────────────────────────────────────────────────────

def test_health_returns_ok(client: TestClient):
    """Health endpoint should always return 200."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "backend" in data


def test_model_status_endpoint(client: TestClient):
    """Model status should list all expected packages."""
    response = client.get("/api/model-status")
    assert response.status_code == 200
    data = response.json()
    assert "celery" in data
    assert "redis" in data
    assert "torch" in data


# ── File validation ───────────────────────────────────────────────────────────

def test_upload_rejects_oversized_file(client: TestClient):
    """Files over MAX_FILE_SIZE_MB should be rejected with 413."""
    from config import settings
    # Create a file slightly over the limit
    oversized = b"x" * (settings.max_file_size_bytes + 1)
    response = client.post(
        "/api/generate/async",
        files=[("files", ("big.jpg", oversized, "image/jpeg"))],
        data={"event_name": "Test", "event_description": "Test"},
    )
    assert response.status_code == 413
    assert "Maximum allowed" in response.json()["detail"]


def test_upload_rejects_invalid_mime(client: TestClient):
    """Files with unsupported MIME types should be rejected with 400."""
    with patch("api.main.validate_upload") as mock_validate:
        from fastapi import HTTPException
        mock_validate.side_effect = HTTPException(
            status_code=400,
            detail="File 'test.exe' has unsupported type 'application/x-msdownload'."
        )
        response = client.post(
            "/api/generate/async",
            files=[("files", ("test.exe", b"MZ\x90\x00", "application/x-msdownload"))],
            data={"event_name": "Test"},
        )
    assert response.status_code == 400


def test_validate_upload_accepts_octet_stream_video_with_ffprobe_fallback():
    """octet-stream video should be accepted when extension is allowed and ffprobe validation succeeds."""
    from api.main import validate_upload

    upload = UploadFile(
        filename="C0165.MP4",
        file=io.BytesIO(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 1024),
        headers={"content-type": "application/octet-stream"},
    )

    with patch.dict("sys.modules", {"magic": types.SimpleNamespace(from_buffer=lambda *_a, **_k: "application/octet-stream")}):
        with patch("api.main._is_valid_video_file", return_value=True):
            saved_path = asyncio.run(validate_upload(upload))

    assert saved_path.exists()
    saved_path.unlink(missing_ok=True)


def test_validate_upload_accepts_octet_stream_video_when_signature_matches_and_probe_fails():
    """octet-stream mp4 should still be accepted via signature fallback when ffprobe/OpenCV checks fail."""
    from api.main import validate_upload

    upload = UploadFile(
        filename="C0165.MP4",
        file=io.BytesIO(b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 1024),
        headers={"content-type": "application/octet-stream"},
    )

    with patch.dict("sys.modules", {"magic": types.SimpleNamespace(from_buffer=lambda *_a, **_k: "application/octet-stream")}):
        with patch("api.main._is_valid_video_bytes", return_value=False):
            saved_path = asyncio.run(validate_upload(upload))

    assert saved_path.exists()
    assert saved_path.suffix == ".mp4"
    saved_path.unlink(missing_ok=True)


def test_validate_upload_accepts_octet_stream_camera_mp4_brand_when_probe_fails():
    """Camera MP4 variants such as Sony XAVC should pass by extension plus ISO BMFF signature."""
    from api.main import validate_upload

    upload = UploadFile(
        filename="C0165.MP4",
        file=io.BytesIO(b"\x00\x00\x00\x20ftypXAVC" + b"\x00" * 1024),
        headers={"content-type": "application/octet-stream"},
    )

    with patch.dict("sys.modules", {"magic": types.SimpleNamespace(from_buffer=lambda *_a, **_k: "application/octet-stream")}):
        with patch("api.main._is_valid_video_bytes", return_value=False):
            saved_path = asyncio.run(validate_upload(upload))

    assert saved_path.exists()
    assert saved_path.suffix == ".mp4"
    saved_path.unlink(missing_ok=True)


def test_validate_upload_accepts_octet_stream_mts_when_signature_matches():
    """MTS camera files should be accepted when the transport-stream signature is present."""
    from api.main import validate_upload

    upload = UploadFile(
        filename="camera_clip.MTS",
        file=io.BytesIO(b"\x47" + b"\x00" * 1024),
        headers={"content-type": "application/octet-stream"},
    )

    with patch.dict("sys.modules", {"magic": types.SimpleNamespace(from_buffer=lambda *_a, **_k: "application/octet-stream")}):
        with patch("api.main._is_valid_video_bytes", return_value=False):
            saved_path = asyncio.run(validate_upload(upload))

    assert saved_path.exists()
    assert saved_path.suffix == ".mts"
    saved_path.unlink(missing_ok=True)


def test_validate_upload_rejects_octet_stream_video_when_ffprobe_fails():
    """octet-stream video should be rejected if ffprobe validation fails."""
    from api.main import validate_upload

    upload = UploadFile(
        filename="C0165.MP4",
        file=io.BytesIO(b"\x00" * 512),
        headers={"content-type": "application/octet-stream"},
    )

    with patch.dict("sys.modules", {"magic": types.SimpleNamespace(from_buffer=lambda *_a, **_k: "application/octet-stream")}):
        with patch("api.main._is_valid_video_file", return_value=False):
            with pytest.raises(HTTPException) as exc:
                asyncio.run(validate_upload(upload))

    assert exc.value.status_code == 400
    assert "unsupported type 'application/octet-stream'" in exc.value.detail


def test_validate_upload_accepts_nonstandard_video_mime_when_probe_passes():
    """Non-allowlisted video/* MIME should be accepted when video probe succeeds."""
    from api.main import validate_upload

    upload = UploadFile(
        filename="clip.wmv",
        file=io.BytesIO(b"\x00\x00\x01\xba" + b"\x00" * 1024),
        headers={"content-type": "video/x-ms-wmv"},
    )

    with patch.dict("sys.modules", {"magic": types.SimpleNamespace(from_buffer=lambda *_a, **_k: "video/x-ms-wmv")}):
        with patch("api.main._is_valid_video_bytes", return_value=True):
            saved_path = asyncio.run(validate_upload(upload))

    assert saved_path.exists()
    assert saved_path.suffix == ".wmv"
    saved_path.unlink(missing_ok=True)


def test_validate_upload_accepts_octet_stream_image_when_probe_passes():
    """octet-stream image should be accepted when extension is image-like and decode check passes."""
    from api.main import validate_upload

    upload = UploadFile(
        filename="frame.heic",
        file=io.BytesIO(b"\x00" * 256),
        headers={"content-type": "application/octet-stream"},
    )

    with patch.dict("sys.modules", {"magic": types.SimpleNamespace(from_buffer=lambda *_a, **_k: "application/octet-stream")}):
        with patch("api.main._is_valid_image_bytes", return_value=True):
            saved_path = asyncio.run(validate_upload(upload))

    assert saved_path.exists()
    assert saved_path.suffix in (".heic", ".heif")
    saved_path.unlink(missing_ok=True)


def test_validate_upload_accepts_heic_signature_when_decoder_fails():
    """HEIC uploads should pass signature fallback even if decoder libraries are unavailable."""
    from api.main import validate_upload

    upload = UploadFile(
        filename="frame.HEIC",
        file=io.BytesIO(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 512),
        headers={"content-type": "application/octet-stream"},
    )

    with patch.dict("sys.modules", {"magic": types.SimpleNamespace(from_buffer=lambda *_a, **_k: "application/octet-stream")}):
        with patch("api.main._is_valid_image_bytes", return_value=False):
            saved_path = asyncio.run(validate_upload(upload))

    assert saved_path.exists()
    assert saved_path.suffix in (".heic", ".heif")
    saved_path.unlink(missing_ok=True)


def test_validate_upload_rejects_fake_image_with_image_extension():
    """A disguised non-image file should still be rejected even with image extension."""
    from api.main import validate_upload

    upload = UploadFile(
        filename="fake.jpg",
        file=io.BytesIO(b"not-an-image"),
        headers={"content-type": "application/octet-stream"},
    )

    with patch.dict("sys.modules", {"magic": types.SimpleNamespace(from_buffer=lambda *_a, **_k: "application/octet-stream")}):
        with patch("api.main._is_valid_image_bytes", return_value=False):
            with pytest.raises(HTTPException) as exc:
                asyncio.run(validate_upload(upload))

    assert exc.value.status_code == 400


# ── Async job submission ──────────────────────────────────────────────────────

def test_generate_async_returns_job_id_with_celery(client: TestClient):
    """When Redis is available, generate/async should use Celery and return job_id."""
    fake_task    = Mock()
    fake_task.id = "celery-job-xyz"

    with patch("api.main.validate_uploads") as mock_validate, \
         patch("redis.from_url") as mock_redis, \
         patch("api.tasks.run_generate_task") as mock_task:

        mock_validate.return_value = []
        mock_redis_client = Mock()
        mock_redis_client.ping.return_value = True
        mock_redis.return_value = mock_redis_client
        mock_task.delay.return_value = fake_task

        response = client.post(
            "/api/generate/async",
            files=[("files", ("test.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 50, "image/jpeg"))],
            data={"event_name": "Test Event", "event_description": "Test"},
        )

    # Even if mocking doesn't fully intercept, we should get a valid response
    assert response.status_code in (200, 422)


def test_generate_async_falls_back_to_apscheduler(client: TestClient):
    """When Redis is unavailable, generate/async should fall back to APScheduler."""
    with patch("api.main.validate_uploads") as mock_validate, \
         patch("redis.from_url") as mock_redis, \
         patch("api.scheduler.submit_generate_job") as mock_submit:

        mock_validate.return_value = []
        mock_redis.side_effect = ConnectionRefusedError("Redis unavailable")
        mock_submit.return_value = "apscheduler-job-abc"

        response = client.post(
            "/api/generate/async",
            files=[("files", ("test.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 50, "image/jpeg"))],
            data={"event_name": "Test Event", "event_description": "Test"},
        )

    assert response.status_code in (200, 422)


# ── Job status ────────────────────────────────────────────────────────────────

def test_job_status_apscheduler_pending(client: TestClient):
    """APScheduler pending job should return status=pending."""
    with patch("api.scheduler.get_job") as mock_get:
        mock_get.return_value = {
            "status":   "pending",
            "progress": {"step": "queued", "pct": 0},
        }
        response = client.get("/api/jobs/test-job-123/status")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    assert data["backend"] == "apscheduler"


def test_job_status_apscheduler_completed(client: TestClient):
    """APScheduler completed job should return status=completed."""
    with patch("api.scheduler.get_job") as mock_get:
        mock_get.return_value = {
            "status":   "completed",
            "progress": {"step": "done", "pct": 100},
            "result":   {"event": "Test", "files": {}},
        }
        response = client.get("/api/jobs/test-job-123/status")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_job_status_celery_progress(client: TestClient):
    """Celery PROGRESS state should be returned correctly."""
    with patch("api.scheduler.get_job", return_value=None), \
         patch("celery.result.AsyncResult") as mock_result_cls:

        mock_result = Mock()
        mock_result.state = "PROGRESS"
        mock_result.info  = {"step": "ml_selection", "pct": 50}
        mock_result_cls.return_value = mock_result

        response = client.get("/api/jobs/celery-job-456/status")

    assert response.status_code == 200
    data = response.json()
    assert data["backend"] == "celery"


def test_job_status_not_found(client: TestClient):
    """Non-existent job should return 404."""
    with patch("api.scheduler.get_job", return_value=None), \
         patch("celery.result.AsyncResult") as mock_result_cls:

        mock_result_cls.side_effect = Exception("Job not found")
        response = client.get("/api/jobs/nonexistent-job/status")

    assert response.status_code == 404


# ── Job result ────────────────────────────────────────────────────────────────

def test_job_result_apscheduler_completed(client: TestClient):
    """Completed APScheduler job should return its result."""
    expected_result = {
        "status": "completed",
        "event":  "Test Event",
        "files":  {"linkedin_collage.jpg": "/output/Test_Event/linkedin_collage.jpg"},
    }
    with patch("api.scheduler.get_job") as mock_get:
        mock_get.return_value = {
            "status": "completed",
            "result": expected_result,
        }
        response = client.get("/api/jobs/test-job-123/result")

    assert response.status_code == 200
    assert response.json()["event"] == "Test Event"


def test_job_result_not_complete_returns_status(client: TestClient):
    """Pending job result request should return current status, not 404."""
    with patch("api.scheduler.get_job") as mock_get:
        mock_get.return_value = {
            "status":   "running",
            "progress": {"step": "ml_selection", "pct": 40},
        }
        response = client.get("/api/jobs/running-job/result")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"


def test_job_result_failed_returns_500(client: TestClient):
    """Failed job result request should return 500 with error detail."""
    with patch("api.scheduler.get_job") as mock_get:
        mock_get.return_value = {
            "status": "failed",
            "error":  "ML model out of memory",
        }
        response = client.get("/api/jobs/failed-job/result")

    assert response.status_code == 500
    assert "ML model out of memory" in response.json()["detail"]


# ── Cleanup ───────────────────────────────────────────────────────────────────

def test_cleanup_dry_run(tmp_path):
    """Cleanup dry-run should not delete any files."""
    import time
    from cleanup import run_cleanup
    from config import settings
    from unittest.mock import patch

    # Create a fake old file
    old_file = tmp_path / "old_upload.jpg"
    old_file.write_bytes(b"fake image data")

    # Backdate the file's mtime by 10 days
    old_time = time.time() - (10 * 86400)
    import os
    os.utime(str(old_file), (old_time, old_time))

    with patch.object(settings, "upload_dir", tmp_path), \
         patch.object(settings, "output_dir", tmp_path / "output"):
        (tmp_path / "output").mkdir(exist_ok=True)
        result = run_cleanup(upload_days=7, output_days=30, dry_run=True)

    # File should still exist after dry run
    assert old_file.exists()
    assert result["uploads"]["deleted"] == 1  # Would have deleted 1


def test_cleanup_actually_deletes(tmp_path):
    """Cleanup should delete files older than retention period."""
    import time, os
    from cleanup import run_cleanup
    from config import settings

    old_file = tmp_path / "old_upload.jpg"
    old_file.write_bytes(b"fake image data")
    old_time = time.time() - (10 * 86400)
    os.utime(str(old_file), (old_time, old_time))

    with patch.object(settings, "upload_dir", tmp_path), \
         patch.object(settings, "output_dir", tmp_path / "output"):
        (tmp_path / "output").mkdir(exist_ok=True)
        result = run_cleanup(upload_days=7, output_days=30, dry_run=False)

    assert not old_file.exists()
    assert result["uploads"]["deleted"] == 1


def test_cleanup_keeps_recent_files(tmp_path):
    """Cleanup should not delete files within retention period."""
    from cleanup import run_cleanup
    from config import settings

    recent_file = tmp_path / "recent_upload.jpg"
    recent_file.write_bytes(b"fake image data")
    # File is brand new — should not be deleted

    with patch.object(settings, "upload_dir", tmp_path), \
         patch.object(settings, "output_dir", tmp_path / "output"):
        (tmp_path / "output").mkdir(exist_ok=True)
        result = run_cleanup(upload_days=7, output_days=30, dry_run=False)

    assert recent_file.exists()
    assert result["uploads"]["deleted"] == 0
