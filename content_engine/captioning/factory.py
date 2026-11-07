"""
Caption provider factory - MLX local inference only (no Groq, no silent fallback to templates).
"""

import os
from typing import Optional

from .providers.base import CaptionProvider, CaptionProviderError
from .providers.template_provider import TemplateProvider


class CaptionProviderFactory:
    """Factory for creating caption providers - MLX local only."""

    def __init__(self):
        self._providers = {}

    def get_provider(self, mode: str = "auto", force_local: bool = False,
                     allow_groq_fallback: bool = False) -> CaptionProvider:
        """
        Get caption provider - only MLX local is allowed. Groq is disabled.
        """
        mode = (mode or "local_only").lower()
        # Force MLX/local only
        if mode == "groq_only":
            raise CaptionProviderError("Groq is disabled. Only local MLX inference is supported.")
        if mode == "template_only":
            raise CaptionProviderError("Template-only mode is not allowed as the sole AI provider. MLX local model is required.")
        # Always prefer/use local/MLX
        local_provider = self._get_local_provider()
        if local_provider and local_provider.is_available():
            return local_provider
        raise CaptionProviderError(
            "Local MLX model is not available. Check MLX_MODEL_ID/MLX_MODEL_PATH configuration. "
            "Ensure .venv-mlx environment is set up with mlx-lm installed. "
            "Model must be available before generating captions."
        )

    def _get_local_provider(self) -> Optional[CaptionProvider]:
        try:
            from .providers.local_provider import LocalLLMProvider
            return LocalLLMProvider()
        except Exception:
            return None

    @staticmethod
    def get_config_from_env():
        return {
            "mode": os.getenv("CAPTION_PROVIDER_MODE", "local_only"),
            "use_local": True,
            "force_local": True,
            "local_model": os.getenv("MLX_MODEL_ID", "mlx-community/Qwen2.5-0.5B-Instruct-4bit"),
            "allow_groq_fallback": False,
        }


_factory = CaptionProviderFactory()


def get_caption_provider(mode: Optional[str] = None, **kwargs) -> CaptionProvider:
    if mode is None:
        config = CaptionProviderFactory.get_config_from_env()
        mode = config["mode"]
    kwargs["allow_groq_fallback"] = False
    kwargs["force_local"] = True
    return _factory.get_provider(mode, **kwargs)


def get_template_provider():
    """Get template provider only for explicit labeled previews."""
    return TemplateProvider()