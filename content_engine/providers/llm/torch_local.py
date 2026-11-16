"""
PyTorch/transformers local LLM provider (Windows/Linux/CPU).

The single authoritative LLM provider for Content Engine. Wraps the shared,
lazily-loaded Qwen model from :mod:`content_engine.llm.torch_backend`.
"""

from content_engine.providers.base import LLMProvider
from content_engine.llm.torch_backend import get_torch_generator, is_torch_backend_available

from config import QWEN_MODEL_PATH


class TorchLocalProvider(LLMProvider):
    """Local text generation backed by transformers (CUDA when available, CPU fallback)."""

    MODEL = "Qwen2.5-1.5B-Instruct"
    MODEL_PATH = str(QWEN_MODEL_PATH)

    def __init__(self) -> None:
        self._generator = None

    def _get_generator(self):
        if self._generator is None:
            self._generator = get_torch_generator()
        return self._generator

    def generate(
        self,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        return self._get_generator().generate(
            system=system,
            user=user,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    @property
    def name(self) -> str:
        return "torch_local"

    @property
    def requires_api_key(self) -> bool:
        return False

    @property
    def device(self) -> str:
        """Resolved device (cuda/cpu). Reads without forcing a load when possible."""
        if self._generator is not None:
            return self._generator.device
        return "cpu"

    @property
    def is_loaded(self) -> bool:
        return self._generator is not None and self._generator.is_loaded

    def is_available(self) -> bool:
        return is_torch_backend_available()

    def status(self) -> dict:
        """Provider introspection for /api/llm-status and logs."""
        return {
            "provider": self.name,
            "model": self.MODEL,
            "model_path": self.MODEL_PATH,
            "local_only": True,
            "remote_inference_disabled": True,
            "device": self.device,
            "loaded": self.is_loaded,
            "requires_api_key": self.requires_api_key,
        }
