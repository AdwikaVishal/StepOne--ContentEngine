"""
Provider package — abstract interfaces and mode-aware factory.

Subpackages:
  llm   — text generation providers (MLX, Groq)
  vision — image/video understanding providers (local Florence-2+CLIP, Gemini)

The factory in providers/factory.py selects providers based on AI_EXECUTION_MODE.
"""

from content_engine.providers.base import (
    ConfigurationError,
    LLMProvider,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    VisionProvider,
)

from content_engine.providers.factory import (
    get_caption_provider,
    get_llm_provider,
    get_vision_provider,
)

__all__ = [
    "ConfigurationError",
    "LLMProvider",
    "ProviderError",
    "ProviderRateLimitError",
    "ProviderTimeoutError",
    "VisionProvider",
    "get_caption_provider",
    "get_llm_provider",
    "get_vision_provider",
]
