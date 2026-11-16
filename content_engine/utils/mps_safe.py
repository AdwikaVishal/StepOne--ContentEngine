"""
Cross-platform device selection and GPU memory management.

Historically this module only handled Apple Silicon MPS. It now also supports
CUDA (Windows/Linux/NVIDIA) and CPU-only machines. The public names
(``MPS_DEVICE``, ``FLORENCE_DEVICE``, ``FLORENCE_DTYPE``, ``empty_cache``) are
kept for backwards compatibility with existing call sites and tests.

This module now delegates to :class:`content_engine.utils.device_manager.DeviceManager`
for centralized device selection and VRAM-aware model lifecycle management.
"""

import gc
import os
from typing import Optional

import torch

from content_engine.utils.device_manager import DeviceManager, get_device_manager

# ── Backward-compatible module-level state (delegated to DeviceManager) ──
# These are evaluated at import time and reflect the DeviceManager's selection.
_dm = get_device_manager()

# Apple Silicon Metal backend
MPS_AVAILABLE: bool = torch.backends.mps.is_available()
# NVIDIA / AMD CUDA backend
CUDA_AVAILABLE: bool = torch.cuda.is_available()


def _select_device() -> str:
    """Pick the fastest stable device, honouring an explicit ``DEVICE`` env."""
    return _dm.selected_device


# Best device for models that are stable on the selected accelerator
# (YOLO, CLIP, SentenceTransformer). Name kept for backwards compatibility.
MPS_DEVICE: str = _dm.selected_device

# Florence-2 is unstable in float16 and on MPS; keep it on CPU everywhere.
FLORENCE_DEVICE: str = _dm.florence_device
FLORENCE_DTYPE = _dm.florence_dtype


def empty_cache() -> None:
    """Clear the active GPU cache and run Python GC. Call after inference."""
    _dm.clear_cuda_cache()


def set_memory_fraction(fraction: float = 0.0) -> None:
    """No-op kept for MPS compatibility.

    ``PYTORCH_MPS_HIGH_WATERMARK_RATIO`` causes invalid watermark errors, and
    CUDA memory fractions are not needed for this workload.
    """
    pass


# ── DeviceManager-aware helpers ──

def get_device_manager() -> DeviceManager:  # type: ignore[misc]
    """Return the process-wide DeviceManager."""
    return _dm


def recommend_device(estimated_vram_mb: float, model_name: str = "") -> str:
    """Recommend CUDA or CPU for a model based on remaining VRAM budget."""
    return _dm.recommend_device(estimated_vram_mb, model_name)


def register_model(
    name: str,
    model: Optional[object] = None,
    device: Optional[str] = None,
    vram_mb: float = 0.0,
    ram_mb: float = 0.0,
    load_time_seconds: float = 0.0,
) -> None:
    """Register a loaded model with the DeviceManager."""
    _dm.register_model(name, model, device, vram_mb, ram_mb, load_time_seconds)


def unregister_model(name: str) -> None:
    """Remove a model from the DeviceManager registry."""
    _dm.unregister_model(name)


def is_model_loaded(name: str) -> bool:
    return _dm.is_model_loaded(name)
