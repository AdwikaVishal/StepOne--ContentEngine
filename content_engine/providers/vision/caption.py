"""
Caption vision provider — routes image captioning to the mode-appropriate provider.

In local mode: BLIP-based captioning via LocalVisionProvider.
In cloud_testing mode: Gemini captioning via GeminiVisionProvider.

This is a thin adapter used by StudioIntelligence and other caption consumers.
"""

from content_engine.ai_mode import is_cloud_testing
from typing import Optional


class CaptionVisionProvider:
    """Caption-focused vision provider adapter."""

    def __init__(self, mode: Optional[str] = None):
        from content_engine.providers.factory import get_vision_provider

        self._provider = get_vision_provider(mode=mode)

    def caption_image(self, image_path: str) -> str:
        """Return an image caption using the mode-appropriate provider."""
        return self._provider.caption_image(image_path)

    def understand_image(self, image_path: str):
        """Return scene understanding using the mode-appropriate provider."""
        return self._provider.understand_image(image_path)

    @property
    def name(self) -> str:
        return self._provider.name

    @property
    def requires_api_key(self) -> bool:
        return self._provider.requires_api_key

    def is_available(self) -> bool:
        return self._provider.is_available()
