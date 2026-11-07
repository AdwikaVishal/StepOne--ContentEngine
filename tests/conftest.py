"""
Shared fixtures for all tests.
Creates synthetic images and videos so tests run without real event assets.
"""

import os
import sys
import tempfile
import numpy as np
import pytest
import cv2
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Image fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def sharp_image_path(tmp_path_factory):
    """A sharp, well-lit synthetic image (should pass quality floor)."""
    tmp  = tmp_path_factory.mktemp("imgs")
    path = str(tmp / "sharp.jpg")
    # Checkerboard pattern — high Laplacian variance
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    for i in range(0, 480, 20):
        for j in range(0, 640, 20):
            if (i // 20 + j // 20) % 2 == 0:
                img[i:i+20, j:j+20] = [200, 200, 200]
    cv2.imwrite(path, img)
    return path


@pytest.fixture(scope="session")
def dark_image_path(tmp_path_factory):
    """A very dark image (should fail quality floor)."""
    tmp  = tmp_path_factory.mktemp("imgs")
    path = str(tmp / "dark.jpg")
    img  = np.full((480, 640, 3), 10, dtype=np.uint8)
    cv2.imwrite(path, img)
    return path


@pytest.fixture(scope="session")
def blurry_image_path(tmp_path_factory):
    """A blurry image."""
    tmp  = tmp_path_factory.mktemp("imgs")
    path = str(tmp / "blurry.jpg")
    img  = np.full((480, 640, 3), 128, dtype=np.uint8)
    img  = cv2.GaussianBlur(img, (51, 51), 0)
    cv2.imwrite(path, img)
    return path


@pytest.fixture(scope="session")
def test_video_path(tmp_path_factory):
    """A short synthetic MP4 video (requires ffmpeg)."""
    import subprocess
    tmp  = tmp_path_factory.mktemp("vids")
    path = str(tmp / "test.mp4")
    try:
        subprocess.run(
            ["ffmpeg", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
             "-t", "5", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             path, "-y", "-loglevel", "quiet"],
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("ffmpeg not available")
    return path


@pytest.fixture(scope="session")
def sample_images_dir(tmp_path_factory):
    """Directory with 5 synthetic test images."""
    tmp = tmp_path_factory.mktemp("sample_imgs")
    for i in range(5):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        # Different patterns for variety
        color = [i * 50, 200 - i * 30, 100 + i * 20]
        img[100:380, 100:540] = color
        cv2.imwrite(str(tmp / f"test_image_{i}.jpg"), img)
    return tmp


# ── FastAPI test client ───────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def app():
    """FastAPI app instance for testing."""
    from api.main import app as fastapi_app
    return fastapi_app


@pytest.fixture(scope="session")
def client(app):
    """Synchronous test client for FastAPI app."""
    from fastapi.testclient import TestClient
    return TestClient(app)


# ── Mock fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def mock_celery_task():
    """Mock Celery task submission — returns a fake task with a known ID."""
    with patch("api.tasks.run_generate_task.delay") as mock:
        fake_task      = Mock()
        fake_task.id   = "test-job-abc123"
        mock.return_value = fake_task
        yield mock


@pytest.fixture
def mock_redis_available():
    """Mock Redis as available."""
    with patch("redis.from_url") as mock_redis:
        mock_client = Mock()
        mock_client.ping.return_value = True
        mock_redis.return_value = mock_client
        yield mock_redis


@pytest.fixture
def mock_redis_unavailable():
    """Mock Redis as unavailable (connection refused)."""
    with patch("redis.from_url") as mock_redis:
        mock_redis.side_effect = ConnectionRefusedError("Redis not available")
        yield mock_redis


@pytest.fixture
def sample_upload_files():
    """Multipart form files for upload endpoint testing."""
    return [
        ("files", (f"test_{i}.jpg", b"\xff\xd8\xff" + b"\x00" * 100, "image/jpeg"))
        for i in range(3)
    ]


@pytest.fixture
def temp_output_dir(tmp_path):
    """Temporary output directory for generation tests."""
    out = tmp_path / "output"
    out.mkdir()
    return out
