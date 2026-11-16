"""
Groq caption provider — DISABLED.

Content Engine runs exclusively on the local Qwen model (models/qwen/) via
TorchCaptionProvider. Groq caption generation is unreachable. This class is
retained only so that any stale import reference fails loudly and clearly.
"""

from typing import List, Optional

from .base import CaptionProvider, CaptionProviderError
from ..schema import CaptionGenerationContext, HistoricalPost


class GroqProvider(CaptionProvider):
    """Groq API-based caption adapter (disabled — local Qwen only)."""

    def __init__(self, api_key: Optional[str] = None):
        raise CaptionProviderError(
            "Groq caption generation is disabled. Content Engine uses the local "
            "Qwen2.5-1.5B-Instruct model (models/qwen/) via TorchCaptionProvider "
            "only. Groq cannot be instantiated for caption inference."
        )

    def is_available(self) -> bool:
        """Always False — Groq is disabled and unavailable for caption inference."""
        return False

    def get_name(self) -> str:
        return "groq"

    def get_capabilities(self) -> dict:
        return {
            "local": False,
            "requires_api_key": True,
            "supports_retrieval": False,
            "platforms": [],
        }

    def generate_linkedin(self, ctx: CaptionGenerationContext,
                         examples: Optional[List[HistoricalPost]] = None) -> str:
        raise CaptionProviderError("Groq generate_linkedin is disabled — local Qwen only.")

    def generate_instagram(self, ctx: CaptionGenerationContext,
                          examples: Optional[List[HistoricalPost]] = None) -> str:
        raise CaptionProviderError("Groq generate_instagram is disabled — local Qwen only.")

    def generate_reel(self, ctx: CaptionGenerationContext,
                     examples: Optional[List[HistoricalPost]] = None) -> str:
        raise CaptionProviderError("Groq generate_reel is disabled — local Qwen only.")

    def generate_stories(self, ctx: CaptionGenerationContext,
                        num_slides: int = 4,
                        examples: Optional[List[HistoricalPost]] = None) -> List[str]:
        raise CaptionProviderError("Groq generate_stories is disabled — local Qwen only.")
