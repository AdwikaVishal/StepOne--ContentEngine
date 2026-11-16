"""
Caption provider factory — local inference only (no Groq, no silent fallback to templates).

The PyTorch/transformers TorchCaptionProvider (backed by the shared Qwen model in
models/qwen/) is the only caption provider. Groq and template-only modes are
rejected; generation failures are surfaced to the caller, never converted into
template copy.
"""

import os
from typing import Optional

from .providers.base import CaptionProvider, CaptionProviderError
from .providers.template_provider import TemplateProvider


class CaptionProviderFactory:
    """Factory for creating caption providers — local inference only."""

    def __init__(self):
        self._providers = {}

    def get_provider(self, mode: str = "auto", force_local: bool = True,
                     allow_groq_fallback: bool = False) -> CaptionProvider:
        """
        Get caption provider — only local inference is allowed. Groq is disabled.
        Template-only mode is not permitted as a generation provider.
        """
        mode = (mode or "local_only").lower()
        if mode == "groq_only":
            raise CaptionProviderError(
                "Groq is disabled. Only local Qwen inference is supported for captions."
            )
        if mode == "template_only":
            raise CaptionProviderError(
                "Template-only mode is not allowed as the sole AI provider. "
                "A local Qwen model is required before generating captions."
            )
        # Always prefer/use local Qwen provider.
        local_provider = self._get_local_provider()
        if local_provider is not None and local_provider.is_available():
            return local_provider
        raise CaptionProviderError(
            "Local Qwen model is not available. Check TORCH_LLM_MODEL/QWEN_MODEL_PATH "
            "configuration (models/qwen/). Model must be available before generating captions."
        )

    def _get_local_provider(self) -> Optional[CaptionProvider]:
        try:
            from .providers.torch_provider import TorchCaptionProvider
            return TorchCaptionProvider()
        except Exception:
            return None

    @staticmethod
    def get_config_from_env():
        return {
            "mode": os.getenv("CAPTION_PROVIDER_MODE", "local_only"),
            "use_local": True,
            "force_local": True,
            "local_model": os.getenv("TORCH_LLM_MODEL", "models/qwen/"),
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
    """Get template provider only for explicit labeled previews (never generation)."""
    return TemplateProvider()