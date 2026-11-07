"""
Mode-aware provider factory.

Selects LLM and vision providers based on AI_EXECUTION_MODE:

  - local:        MLX Qwen + local Florence-2/CLIP/BLIP
  - cloud_testing: Groq + Gemini, local models bypassed

Providers are NOT cached across mode switches to prevent cache leakage.
"""

import os
from typing import Optional

from content_engine.ai_mode import (
    AIExecutionMode,
    ConfigurationError,
    get_execution_mode,
    is_cloud_testing,
    is_local,
    validate_cloud_credentials,
)

from content_engine.providers.base import LLMProvider
from content_engine.providers.llm.groq import GroqProvider
from content_engine.providers.llm.mlx import MLXProvider
from content_engine.providers.vision.groq import GroqVisionProvider
from content_engine.providers.vision.local import LocalVisionProvider


def get_llm_provider(mode: Optional[str] = None) -> LLMProvider:
    """Return the LLM provider for the given (or current) execution mode.

    In cloud_testing mode, validates that GROQ_API_KEY is present before
    instantiating the Groq provider. Fails clearly if missing.
    """
    effective_mode = mode or get_execution_mode()

    if effective_mode == AIExecutionMode.CLOUD_TESTING:
        validate_cloud_credentials()
        return GroqProvider()

    # Default: local mode
    return MLXProvider()


def get_vision_provider(mode: Optional[str] = None) -> "VisionProvider":
    """Return the vision provider for the given (or current) execution mode.

    In cloud_testing mode, validates that GROQ_API_KEY is present before
    instantiating the GroqVisionProvider. Fails clearly if missing.
    Gemini remains available as a separate import but is not the active
    cloud_testing vision provider.
    """
    effective_mode = mode or get_execution_mode()

    if effective_mode == AIExecutionMode.CLOUD_TESTING:
        validate_cloud_credentials()
        return GroqVisionProvider()

    # Default: local mode
    return LocalVisionProvider()


def get_caption_provider(mode: Optional[str] = None) -> "VisionProvider":
    """Return the image captioning provider for the given (or current) mode.

    In cloud_testing mode, routes to GroqVisionProvider captioning.
    In local mode, routes to BLIP-based local captioning.
    """
    return get_vision_provider(mode=mode)
