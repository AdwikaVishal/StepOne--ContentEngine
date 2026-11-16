"""
Cross-platform local text generation via PyTorch + transformers.

This is the Windows/Linux/CPU counterpart to the Apple-only MLX backend. A
single lazily-loaded model instance is shared by every caller (copy generation
and captioning) so weights are never duplicated in memory.

Configuration (environment):
  TORCH_LLM_MODEL            HF repo id or local path (default: models/qwen/)
  TORCH_LLM_DEVICE           cuda | cpu (default: cuda when available)
  TORCH_LLM_LOCAL_FILES_ONLY true/false (default: true — offline-only)
  TORCH_DTYPE / TORCH_LLM_DTYPE  float16 | bfloat16 | float32 (default: fp16 on CUDA)
  TORCH_LLM_MAX_CONTEXT      max context tokens (default: 4096)
"""

from __future__ import annotations

import os
import threading
import time
from typing import Optional

# ── Offline enforcement ─────────────────────────────────────────────
# Hugging Face / transformers / huggingface-hub must never reach the network.
# These are set here (before any transformers import) so the local-only
# guarantee holds for every loader in the process, regardless of import order.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TORCH_LLM_LOCAL_FILES_ONLY", "true")

from config import QWEN_MODEL_PATH
from content_engine.utils.device_manager import get_device_manager
from content_engine.utils.mps_safe import register_model, unregister_model


DEFAULT_MODEL_ID = QWEN_MODEL_PATH

# Last model-loading error observed by the shared generator. Populated by
# TorchTextGenerator._load/_ensure_loaded and surfaced via get_torch_status()
# so operators can see loading failures in logs and through /api/llm/status.
_LAST_LOAD_ERROR: Optional[str] = None
_LAST_LOAD_ERROR_LOCK = threading.Lock()


def _record_load_error(message: str) -> None:
    global _LAST_LOAD_ERROR
    with _LAST_LOAD_ERROR_LOCK:
        _LAST_LOAD_ERROR = message


def get_torch_status() -> dict:
    """Return introspection data for the local Qwen backend (offline, local-only)."""
    from content_engine.utils.device_manager import get_device_manager

    dm = get_device_manager()
    reg = dm.get_model("qwen") if dm is not None else None
    with _LAST_LOAD_ERROR_LOCK:
        last_error = _LAST_LOAD_ERROR
    return {
        "provider": "torch_local",
        "model": "Qwen2.5-1.5B-Instruct",
        "model_path": str(QWEN_MODEL_PATH),
        "local_only": True,
        "remote_inference_disabled": True,
        "offline_enforcement": {
            "HF_HUB_OFFLINE": os.getenv("HF_HUB_OFFLINE"),
            "TRANSFORMERS_OFFLINE": os.getenv("TRANSFORMERS_OFFLINE"),
            "HF_HUB_DISABLE_TELEMETRY": os.getenv("HF_HUB_DISABLE_TELEMETRY"),
            "TORCH_LLM_LOCAL_FILES_ONLY": os.getenv("TORCH_LLM_LOCAL_FILES_ONLY"),
        },
        "device": None,
        "loaded": False,
        "last_load_error": last_error,
        "registration": {
            "device": reg.device if reg else None,
            "vram_mb": reg.vram_mb if reg else None,
            "load_time_seconds": reg.load_time_seconds if reg else None,
        }
        if reg
        else None,
    }


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def is_torch_backend_available() -> bool:
    """True when torch + transformers can be imported."""
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        return True
    except Exception:
        return False


class TorchTextGenerator:
    """Lazy, thread-safe wrapper around a causal LM."""

    def __init__(
        self,
        model_id: Optional[str] = None,
        device: Optional[str] = None,
    ) -> None:
        # Prefer the locally downloaded Qwen model over any remote HF repo id
        # that may be set in .env. This guarantees offline operation.
        env_model = os.getenv("TORCH_LLM_MODEL", "")
        if env_model and os.path.isdir(env_model):
            self.model_id = model_id or env_model
        else:
            self.model_id = model_id or QWEN_MODEL_PATH
        self._requested_device = (device or os.getenv("TORCH_LLM_DEVICE", "")).strip().lower()
        self._tokenizer = None
        self._model = None
        self._device = "cpu"
        self._lock = threading.Lock()

    # ── loading ──────────────────────────────────────────────────────────────

    def _resolve_device(self) -> str:
        import torch

        dm = get_device_manager()

        if self._requested_device:
            if self._requested_device.startswith("cuda") and not torch.cuda.is_available():
                return "cpu"
            if self._requested_device == "mps" and not torch.backends.mps.is_available():
                return "cpu"
            return self._requested_device

        # Use DeviceManager for device selection (VRAM-aware)
        if dm.cuda_available:
            # Qwen needs ~2.9 GB VRAM; check budget
            if dm.can_load_on_cuda(3000.0):
                return "cuda"
            # Not enough VRAM — fall back to CPU
            return "cpu"
        if dm.mps_available:
            return "mps"
        return "cpu"

    def _resolve_dtype(self, device: str):
        import torch

        if device == "cpu":
            return torch.float32
        name = (os.getenv("TORCH_LLM_DTYPE") or os.getenv("TORCH_DTYPE") or "").strip().lower()
        if name in {"float32", "fp32", "full"}:
            return torch.float32
        if name in {"bfloat16", "bf16"}:
            return torch.bfloat16
        return torch.float16

    def _load(self, device: str) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        # Guard: refuse to resolve any remote repo. The model must already exist
        # as a local directory; otherwise raise immediately so no network lookup
        # is ever attempted (offline-only guarantee).
        if not os.path.isdir(self.model_id):
            msg = (
                f"Local Qwen model directory not found: {self.model_id}. "
                "Place the Qwen2.5-1.5B-Instruct files under models/qwen/ "
                "(or set TORCH_LLM_MODEL to an existing local directory). "
                "Offline mode is enforced; no remote repository lookup or download "
                "will be attempted."
            )
            _record_load_error(msg)
            raise FileNotFoundError(msg)

        # Production path always loads from the already downloaded local
        # directory. No repository resolution, no remote lookups, no downloads.
        local_only = True
        # low_cpu_mem_usage requires accelerate; use it only when available so
        # offline loading does not depend on an extra package.
        try:
            import accelerate  # noqa: F401
            low_cpu_mem_usage = True
        except Exception:
            low_cpu_mem_usage = False
        dtype = self._resolve_dtype(device)
        t0 = time.perf_counter()
        try:
            tokenizer = AutoTokenizer.from_pretrained(self.model_id, local_files_only=local_only)
            model = AutoModelForCausalLM.from_pretrained(
                self.model_id,
                torch_dtype=dtype,
                low_cpu_mem_usage=low_cpu_mem_usage,
                local_files_only=local_only,
            )
            model.to(device)
            model.eval()
        except Exception as exc:
            _record_load_error(f"{type(exc).__name__}: {exc}")
            raise
        load_time = time.perf_counter() - t0
        self._tokenizer = tokenizer
        self._model = model
        self._device = device

        # Register with DeviceManager
        estimated_vram = 2945.0 if device.startswith("cuda") else 0.0
        estimated_ram = 48.0
        dm = get_device_manager()
        if dm is not None:
            dm.register_model(
                "qwen",
                model=model,
                device=device,
                vram_mb=estimated_vram,
                ram_mb=estimated_ram,
                load_time_seconds=load_time,
            )

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        device = self._resolve_device()
        try:
            self._load(device)
        except Exception:
            if device == "cpu":
                raise
            # CUDA/MPS load failed (e.g. OOM) — fall back to CPU once.
            try:
                import torch
                if device.startswith("cuda"):
                    torch.cuda.empty_cache()
            except Exception:
                pass
            self._load("cpu")

    # ── generation ───────────────────────────────────────────────────────────

    def generate(
        self,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float = 0.0,
    ) -> str:
        with self._lock:
            self._ensure_loaded()
            import torch

            tokenizer = self._tokenizer
            model = self._model
            assert tokenizer is not None and model is not None

            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": user})

            if tokenizer.chat_template:
                prompt = tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
            else:
                prompt = f"{system}\n\n{user}\n\nAnswer:" if system else f"{user}\n\nAnswer:"

            encoded = tokenizer(
                prompt,
                return_tensors="pt",
                truncation=True,
                max_length=int(os.getenv("TORCH_LLM_MAX_CONTEXT", "4096")),
            )
            encoded = {key: value.to(self._device) for key, value in encoded.items()}

            generation_kwargs = {
                "max_new_tokens": max(1, int(max_tokens)),
                "pad_token_id": tokenizer.eos_token_id,
            }
            if temperature and temperature > 0:
                generation_kwargs.update(do_sample=True, temperature=float(temperature))
            else:
                generation_kwargs.update(do_sample=False)

            with torch.inference_mode():
                output = model.generate(**encoded, **generation_kwargs)

            new_tokens = output[0][encoded["input_ids"].shape[1]:]
            return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

    # ── introspection ────────────────────────────────────────────────────────

    @property
    def device(self) -> str:
        return self._device

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def unload(self) -> None:
        with self._lock:
            if self._model is not None:
                dm = get_device_manager()
                if dm is not None:
                    dm.unregister_model("qwen")
            self._model = None
            self._tokenizer = None
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass


_generator: Optional[TorchTextGenerator] = None
_generator_lock = threading.Lock()


def get_torch_generator() -> TorchTextGenerator:
    """Return the process-wide shared generator (lazy, lock-protected)."""
    global _generator
    with _generator_lock:
        if _generator is None:
            _generator = TorchTextGenerator()
        return _generator


def reset_torch_generator() -> None:
    """Drop the shared generator (used by tests / explicit reloads)."""
    global _generator
    with _generator_lock:
        if _generator is not None:
            _generator.unload()
        _generator = None
