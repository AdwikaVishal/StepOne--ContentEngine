"""
Local-only provider factory.

Content Engine operates completely offline. The only permitted LLM is the
downloaded Qwen2.5-1.5B-Instruct model in models/qwen/, served by
TorchLocalProvider (PyTorch + transformers, CUDA when available, CPU fallback).

AI_EXECUTION_MODE=local is the default and mandatory for this deployment.
cloud_testing mode (Groq/Gemini) is disabled and cannot be selected at runtime.

Providers are NOT cached across calls to avoid stale state.
"""

from typing import Optional

from content_engine.ai_mode import AIExecutionMode, ConfigurationError, get_execution_mode

from content_engine.providers.base import LLMProvider
from content_engine.providers.llm.torch_local import TorchLocalProvider
from content_engine.providers.vision.local import LocalVisionProvider


def get_llm_provider(mode: Optional[str] = None) -> LLMProvider:
    """Return the single authoritative LLM provider: TorchLocalProvider (Qwen).

    cloud_testing mode is rejected — Groq/Gemini remote inference is unreachable.
    """
    effective_mode = mode or get_execution_mode()
    if effective_mode != AIExecutionMode.LOCAL:
        raise ConfigurationError(
            "cloud_testing mode is disabled. Content Engine runs exclusively on "
            "the local Qwen2.5-1.5B-Instruct model (models/qwen/) via "
            "TorchLocalProvider. Set AI_EXECUTION_MODE=local."
        )
    return TorchLocalProvider()


def get_vision_provider(mode: Optional[str] = None) -> "VisionProvider":
    """Return the local vision provider (Florence-2 + CLIP + BLIP)."""
    effective_mode = mode or get_execution_mode()
    if effective_mode != AIExecutionMode.LOCAL:
        raise ConfigurationError(
            "cloud_testing mode is disabled. Remote vision inference is "
            "unavailable; local vision models are used instead."
        )
    return LocalVisionProvider()


def get_caption_provider(mode: Optional[str] = None) -> "VisionProvider":
    """Return the image captioning provider (local BLIP-based)."""
    return get_vision_provider(mode=mode)
