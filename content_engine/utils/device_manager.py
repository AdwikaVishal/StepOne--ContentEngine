"""
Centralized device management for Content Engine.

Provides:
- Device selection: CUDA (NVIDIA) preferred, CPU fallback, MPS preserved for macOS
- VRAM-aware model loading decisions
- Model lifecycle management (load/unload, cache cleanup)
- Shared device state across all model loaders

Usage:
    from content_engine.utils.device_manager import DeviceManager, get_device_manager

    dm = get_device_manager()
    device = dm.select_device(prefer="cuda")  # returns "cuda" or "cpu"
    dm.register_model("clip", model, vram_mb=577)
    dm.unload_model("clip")
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional

import torch


@dataclass
class ModelRegistration:
    """Tracks a loaded model's device and memory footprint."""

    name: str
    device: str
    vram_mb: float = 0.0
    ram_mb: float = 0.0
    load_time_seconds: float = 0.0
    loaded_at: float = 0.0


class DeviceManager:
    """
    Singleton device manager for the Content Engine.

    Responsibilities:
    1. Select the best available device (CUDA > MPS > CPU)
    2. Track loaded models and their VRAM usage
    3. Prevent loading models that would exceed VRAM budget
    4. Provide model unloading and CUDA cache cleanup
    """

    _instance: Optional["DeviceManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "DeviceManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        # ── Configuration from environment ──
        self._preferred_device = os.getenv("DEVICE", "").strip().lower()
        self._vram_budget_mb = float(
            os.getenv("CE_VRAM_BUDGET_MB", "5120")  # Leave ~1 GB headroom on 6 GB card
        )
        self._force_cpu = os.getenv("CE_FORCE_CPU", "false").strip().lower() in {"1", "true", "yes", "on"}

        # ── Device selection ──
        self._cuda_available = torch.cuda.is_available() and not self._force_cpu
        self._mps_available = torch.backends.mps.is_available() and not self._force_cpu
        self._selected_device: Optional[str] = None

        # ── Model registry ──
        self._models: Dict[str, ModelRegistration] = {}
        self._registry_lock = threading.Lock()

        # ── Florence-2 always on CPU (float16 crashes on MPS/CUDA in this workload) ──
        self._florence_device = "cpu"
        self._florence_dtype = torch.float32

    # ── Device selection ──

    @property
    def cuda_available(self) -> bool:
        return self._cuda_available

    @property
    def mps_available(self) -> bool:
        return self._mps_available

    @property
    def selected_device(self) -> str:
        """Return the best device for general model loading."""
        if self._selected_device is not None:
            return self._selected_device

        if self._preferred_device:
            req = self._preferred_device
            if req.startswith("cuda") and not self._cuda_available:
                self._selected_device = "cpu"
            elif req == "mps" and not self._mps_available:
                self._selected_device = "cpu"
            else:
                self._selected_device = req
        elif self._cuda_available:
            self._selected_device = "cuda"
        elif self._mps_available:
            self._selected_device = "mps"
        else:
            self._selected_device = "cpu"

        return self._selected_device

    @property
    def florence_device(self) -> str:
        """Florence-2 always runs on CPU (float32) to avoid MPS/CUDA float16 crashes."""
        return self._florence_device

    @property
    def florence_dtype(self):
        return self._florence_dtype

    def select_device(self, prefer: str = "auto") -> str:
        """
        Explicit device selection.

        Args:
            prefer: "cuda", "mps", "cpu", or "auto" (default)
        """
        if prefer == "auto":
            return self.selected_device
        if prefer.startswith("cuda") and not self._cuda_available:
            return "cpu"
        if prefer == "mps" and not self._mps_available:
            return "cpu"
        return prefer

    def vram_available_mb(self) -> float:
        """Return estimated VRAM still available (budget minus registered usage)."""
        if not self._cuda_available:
            return float("inf")  # CPU has no VRAM limit in this context
        used = sum(m.vram_mb for m in self._models.values() if m.device.startswith("cuda"))
        return max(0.0, self._vram_budget_mb - used)

    def vram_total_mb(self) -> float:
        if self._cuda_available and torch.cuda.is_available():
            return torch.cuda.get_device_properties(0).total_memory / 1024**2
        return 0.0

    # ── Model registry ──

    def register_model(
        self,
        name: str,
        model: Optional[object] = None,
        device: Optional[str] = None,
        vram_mb: float = 0.0,
        ram_mb: float = 0.0,
        load_time_seconds: float = 0.0,
    ) -> None:
        """Register a loaded model with its device and memory footprint."""
        with self._registry_lock:
            import time

            self._models[name] = ModelRegistration(
                name=name,
                device=device or self.selected_device,
                vram_mb=vram_mb,
                ram_mb=ram_mb,
                load_time_seconds=load_time_seconds,
                loaded_at=time.time(),
            )

    def unregister_model(self, name: str) -> None:
        """Remove a model from the registry."""
        with self._registry_lock:
            self._models.pop(name, None)

    def get_model(self, name: str) -> Optional[ModelRegistration]:
        """Get registration info for a loaded model."""
        with self._registry_lock:
            return self._models.get(name)

    def list_models(self) -> Dict[str, ModelRegistration]:
        """Return all registered models."""
        with self._registry_lock:
            return dict(self._models)

    def is_model_loaded(self, name: str) -> bool:
        with self._registry_lock:
            return name in self._models

    # ── VRAM budget checks ──

    def can_load_on_cuda(self, estimated_vram_mb: float) -> bool:
        """Check if a model with estimated_vram_mb can fit in remaining VRAM budget."""
        if not self._cuda_available:
            return False
        return self.vram_available_mb() >= estimated_vram_mb

    def recommend_device(self, estimated_vram_mb: float, model_name: str = "") -> str:
        """
        Recommend a device for a model given its estimated VRAM usage.

        Returns "cuda" if it fits in budget, otherwise "cpu".
        """
        if not self._cuda_available:
            return "cpu"
        if self.can_load_on_cuda(estimated_vram_mb):
            return "cuda"
        # Not enough VRAM — fall back to CPU
        return "cpu"

    # ── Lifecycle management ──

    def clear_cuda_cache(self) -> None:
        """Clear CUDA cache and run Python GC."""
        if self._cuda_available and torch.cuda.is_available():
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass
        import gc

        gc.collect()

    def unload_model(self, name: str) -> None:
        """Unregister a model and clear cache if it was on CUDA."""
        with self._registry_lock:
            reg = self._models.pop(name, None)
        if reg and reg.device.startswith("cuda"):
            self.clear_cuda_cache()

    def unload_all(self) -> None:
        """Unregister all models and clear CUDA cache."""
        with self._registry_lock:
            self._models.clear()
        self.clear_cuda_cache()

    def get_status(self) -> Dict:
        """Return a status dict for logging/diagnostics."""
        with self._registry_lock:
            models_info = {
                name: {
                    "device": reg.device,
                    "vram_mb": round(reg.vram_mb, 1),
                    "ram_mb": round(reg.ram_mb, 1),
                    "load_time_seconds": round(reg.load_time_seconds, 3),
                }
                for name, reg in self._models.items()
            }

        total_vram_used = sum(m.vram_mb for m in self._models.values() if m.device.startswith("cuda"))

        return {
            "selected_device": self.selected_device,
            "cuda_available": self._cuda_available,
            "mps_available": self._mps_available,
            "florence_device": self._florence_device,
            "vram_budget_mb": self._vram_budget_mb,
            "vram_used_mb": round(total_vram_used, 1),
            "vram_available_mb": round(self.vram_available_mb(), 1),
            "vram_total_mb": round(self.vram_total_mb(), 1),
            "models": models_info,
        }


# ── Global instance ──

_manager: Optional[DeviceManager] = None
_manager_lock = threading.Lock()


def get_device_manager() -> DeviceManager:
    """Return the process-wide DeviceManager (lazy, thread-safe)."""
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = DeviceManager()
        return _manager


def reset_device_manager() -> None:
    """Reset the global DeviceManager (for testing)."""
    global _manager
    with _manager_lock:
        if _manager is not None:
            _manager.unload_all()
        _manager = None
