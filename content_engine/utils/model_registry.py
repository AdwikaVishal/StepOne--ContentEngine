"""
Thread-safe shared model registry for the Content Engine.

Loads heavy local models (CLIP, etc.) exactly once per process and reuses the
same instance across every component and worker thread. This eliminates the
meta-tensor error caused by concurrent ``SentenceTransformer`` initialization
on CUDA (``torch.nn.Module.to()`` cannot move meta/empty tensors).

Design goals (per the Windows-migration remediation task):
  * Load the original CLIP model only once per process.
  * Thread-safe initialization with ``threading.Lock``.
  * Simultaneous callers wait for the first initialization rather than
    loading another copy of the weights.
  * Reuse the same CLIP instance wherever the architecture/preprocessing is
    compatible (all consumers call ``.encode(...)``).
  * Atomic initialization: a failed load leaves the registry empty so a later
    retry works; no partially initialized model is ever registered.
  * Explicit device placement via :class:`DeviceManager`.
  * Local-only loading (relies on ``HF_HUB_OFFLINE`` / ``TRANSFORMERS_OFFLINE``).
  * Clean error reporting: exceptions are not swallowed and no fake embeddings
    are ever returned.

Usage:
    from content_engine.utils.model_registry import ModelRegistry
    clip = ModelRegistry.get_instance().get_clip()
"""

from __future__ import annotations

import threading
from typing import Optional

from content_engine.utils.device_manager import get_device_manager


class ModelRegistry:
    """
    Process-wide registry of shared, lazily-loaded ML models.

    The registry is a singleton. Model loading is guarded by a lock so that
    concurrent callers block on the first initialization and receive the exact
    same instance afterwards.
    """

    _instance: Optional["ModelRegistry"] = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "ModelRegistry":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        # Guard for CLIP lazy-load. A separate lock (rather than re-using the
        # DeviceManager lock) keeps model lifecycle concerns isolated.
        self._clip_lock = threading.Lock()
        self._clip: Optional[object] = None
        self._clip_device: Optional[str] = None
        self._clip_load_error: Optional[Exception] = None

    @classmethod
    def get_instance(cls) -> "ModelRegistry":
        """Return the process-wide ModelRegistry (lazy, thread-safe)."""
        return cls()

    # ── device selection ──────────────────────────────────────────────────

    def _select_device(self) -> str:
        """Best device for CLIP, honoring the DeviceManager selection."""
        dm = get_device_manager()
        if dm is None:
            return "cpu"
        return dm.selected_device

    # ── CLIP ──────────────────────────────────────────────────────────────

    def get_clip(self):
        """
        Return the shared CLIP (SentenceTransformer) model.

        The model is loaded from ``config.CLIP_MODEL_PATH`` (``models/clip``)
        on the first call and reused on every subsequent call. The load is
        atomic: if it raises, ``self._clip`` stays ``None`` so a later call
        retries instead of returning a broken half-built model.

        Returns:
            The loaded SentenceTransformer instance (already on its device).
        """
        # Fast path: already loaded.
        if self._clip is not None:
            return self._clip

        with self._clip_lock:
            # Double-check after acquiring the lock: another thread may have
            # finished loading while this one was waiting.
            if self._clip is not None:
                return self._clip

            # A previous failed attempt must not poison the registry: clear any
            # stored error so this call can retry from scratch.
            self._clip_load_error = None

            from sentence_transformers import SentenceTransformer
            from config import CLIP_MODEL_PATH

            device = self._select_device()

            try:
                model = SentenceTransformer(CLIP_MODEL_PATH, device=device)
            except Exception as exc:
                # Record the failure for diagnostics but do NOT cache a model.
                # Leaving self._clip = None keeps the registry retryable.
                self._clip_load_error = exc
                raise

            self._clip = model
            self._clip_device = device

            # Register once with the DeviceManager so memory tracking reflects
            # the shared instance (not one entry per component).
            try:
                dm = get_device_manager()
                if dm is not None and not dm.is_model_loaded("clip"):
                    estimated_vram = 577.0 if device.startswith("cuda") else 0.0
                    estimated_ram = 106.0
                    import time

                    dm.register_model(
                        "clip",
                        model=model,
                        device=device,
                        vram_mb=estimated_vram,
                        ram_mb=estimated_ram,
                        load_time_seconds=0.0,
                    )
            except Exception:
                # Registration is best-effort; it must never break model access.
                pass

            return model

    def get_clip_device(self) -> Optional[str]:
        """Return the device the shared CLIP instance resides on (or None)."""
        return self._clip_device

    def clip_load_error(self) -> Optional[Exception]:
        """Return the last CLIP load error, if any (useful for diagnostics)."""
        return self._clip_load_error

    def is_clip_loaded(self) -> bool:
        """True once CLIP has been successfully loaded."""
        return self._clip is not None

    def unload_clip(self) -> None:
        """Drop the shared CLIP instance (mainly for tests / process teardown)."""
        with self._clip_lock:
            self._clip = None
            self._clip_device = None
            self._clip_load_error = None
        try:
            dm = get_device_manager()
            if dm is not None:
                dm.unregister_model("clip")
        except Exception:
            pass


# ── Convenience module-level accessor ──────────────────────────────────────

_registry: Optional[ModelRegistry] = None
_registry_lock = threading.Lock()


def get_model_registry() -> ModelRegistry:
    """Return the process-wide ModelRegistry."""
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = ModelRegistry.get_instance()
        return _registry


def get_clip():
    """Convenience: return the shared CLIP model from the global registry."""
    return get_model_registry().get_clip()


def get_clip_device() -> Optional[str]:
    """Convenience: return the device of the shared CLIP instance (or None)."""
    return get_model_registry().get_clip_device()
