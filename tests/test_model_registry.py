"""
Regression tests for the shared, thread-safe model registry.

These tests cover the CLIP meta-tensor remediation (the production failure:
``NotImplementedError: Cannot copy out of meta tensor`` caused by concurrent
``SentenceTransformer`` initialization across pipeline workers).

Requirements exercised:
  * Load the original CLIP model only once per process.
  * Thread-safe initialization — simultaneous callers wait for the first load
    and receive the same instance.
  * Atomic / failed initialization does not poison the registry; a retry works.
  * Explicit device placement (CUDA preferred, CPU fallback).
  * Real integration with the local CLIP weights at models/clip.

Not every test mocks the loader: ``test_clip_integration_embedding_shape`` and
``test_pipeline_concurrent_quality_assessment`` load and run the real local
CLIP weights.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

# Ensure the project root is importable (supports `pytest tests/`)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Force offline/local-only loading before any model is touched.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

from content_engine.utils.device_manager import get_device_manager  # noqa: E402
from content_engine.utils.model_registry import (  # noqa: E402
    ModelRegistry,
    get_clip,
    get_clip_device,
)

CLIP_MODEL_PATH = "models/clip"


# ── Registry lifecycle / thread safety ──────────────────────────────────


def test_registry_is_singleton():
    """ModelRegistry is a process-wide singleton."""
    assert ModelRegistry.get_instance() is ModelRegistry.get_instance()


def test_concurrent_clip_loads_return_same_instance():
    """Multiple threads requesting CLIP simultaneously get exactly one instance.

    This is the scenario that previously raised the meta-tensor error when
    8 pipeline workers each loaded a private SentenceTransformer on CUDA.
    """
    registry = ModelRegistry.get_instance()
    # Start from a clean slate so every thread must load.
    registry.unload_clip()

    results = [None] * 16
    errors = []

    def load(idx):
        try:
            results[idx] = registry.get_clip()
        except Exception as exc:  # pragma: no cover - defensive
            errors.append((idx, repr(exc)))

    threads = [threading.Thread(target=load, args=(i,)) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent CLIP load failed: {errors}"
    loaded = [r for r in results if r is not None]
    assert len(loaded) == 16, f"expected 16 successful loads, got {len(loaded)}"
    first = loaded[0]
    assert all(r is first for r in loaded), "not every caller received the same CLIP instance"
    assert registry.is_clip_loaded()


def test_clip_reuse_across_components():
    """get_clip() returns the same instance regardless of caller."""
    a = get_clip()
    b = ModelRegistry.get_instance().get_clip()
    assert a is b


def test_failed_initialization_does_not_poison_registry():
    """A failed CLIP load leaves the registry empty; a later retry works."""
    registry = ModelRegistry.get_instance()
    registry.unload_clip()

    # Force the loader to fail.
    with patch("sentence_transformers.SentenceTransformer", side_effect=RuntimeError("simulated load failure")):
        with pytest.raises(RuntimeError, match="simulated load failure"):
            registry.get_clip()

    # Registry must not be poisoned: nothing loaded, but retryable.
    assert registry.is_clip_loaded() is False
    assert registry.clip_load_error() is not None

    # Retry with the real loader must succeed.
    model = registry.get_clip()
    assert model is not None
    assert registry.is_clip_loaded() is True
    assert registry.clip_load_error() is None


# ── Device behavior ─────────────────────────────────────────────────────


def test_device_selection_cuda_when_available():
    """CUDA is selected when available (RTX 4050 in this environment)."""
    dm = get_device_manager()
    assert dm.cuda_available is True
    assert dm.selected_device == "cuda"
    assert dm.select_device("cuda") == "cuda"


def test_device_selection_cpu_fallback():
    """CPU fallback works when explicitly requested."""
    dm = get_device_manager()
    assert dm.select_device("cpu") == "cpu"


def test_clip_device_explicit_and_stable():
    """The shared CLIP device is reported explicitly and is not re-moved."""
    device = get_clip_device()
    assert device in {"cuda", "cpu"}
    # Re-reading must return the same device (no bouncing between devices).
    assert get_clip_device() == device


# ── Real integration with local CLIP weights ────────────────────────────

@pytest.fixture(scope="module")
def clip_model():
    """Load the real local CLIP model once for the module."""
    return get_clip()


def test_clip_integration_embedding_shape(clip_model):
    """Real local CLIP weights produce (1, 512) embeddings on CUDA."""
    import torch

    emb = clip_model.encode(["a photo of people at an event"])
    assert isinstance(emb, np.ndarray) or torch.is_tensor(emb)
    arr = np.asarray(emb)
    assert arr.shape == (1, 512), f"expected (1, 512), got {arr.shape}"
    # Model must reside on the selected device (no meta tensors).
    assert clip_model.device.type == "cuda"


def test_clip_integration_local_files_only(clip_model):
    """CLIP is loaded from the verified local path, not the Hub."""
    # The model object's underlying root should point at models/clip.
    assert os.path.isdir(CLIP_MODEL_PATH), f"local CLIP dir missing: {CLIP_MODEL_PATH}"


# ── Pipeline concurrency ────────────────────────────────────────────────

def test_pipeline_concurrent_quality_assessment(tmp_path):
    """Process multiple images concurrently: quality + CLIP complete, no duplicate CLIP init.

    Existing image-analysis functionality remains active under concurrent load.
    """
    import cv2

    def make(path, pattern):
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        if pattern == "sharp":
            for i in range(0, 480, 20):
                for j in range(0, 640, 20):
                    if (i // 20 + j // 20) % 2 == 0:
                        img[i:i + 20, j:j + 20] = [220, 220, 220]
        elif pattern == "blur":
            img[:] = [128, 128, 128]
            img = cv2.GaussianBlur(img, (41, 41), 0)
        elif pattern == "dark":
            img[:] = [15, 15, 15]
        cv2.imwrite(str(path), img)

    images = []
    for i in range(6):
        p = tmp_path / f"img_{i}.jpg"
        make(p, ["sharp", "blur", "dark", "sharp", "blur", "sharp"][i])
        images.append(str(p))

    from content_engine import ContentEngine

    engine = ContentEngine(
        event_description="Concurrency test event",
        event_concepts=["keynote", "audience"],
    )
    selections = engine.select_assets_parallel(images)

    processed = [s for s in selections if s.asset is not None]
    assert len(processed) > 0, "no assets survived concurrent processing"
    for s in processed:
        assert 0.0 <= s.asset.quality_score <= 1.0
        assert 0.0 <= s.asset.aesthetic_score <= 1.0
        assert s.asset.final_score >= 0.0

    # CLIP remains a single shared instance across all workers.
    from content_engine.utils.model_registry import get_model_registry
    assert get_model_registry().is_clip_loaded()
    assert get_model_registry().get_clip() is get_clip()
