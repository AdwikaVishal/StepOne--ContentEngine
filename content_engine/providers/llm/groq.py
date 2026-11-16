"""
Groq LLM provider — DISABLED.

Content Engine runs exclusively on the local Qwen model (models/qwen/). Groq
remote inference is unreachable. This class is retained only so that any stale
import reference fails loudly and clearly instead of silently calling the cloud.
"""

from content_engine.ai_mode import ConfigurationError


class GroqProvider:
    """Groq API text generation provider (disabled — local Qwen only)."""

    def __init__(self, api_key: str | None = None):
        raise ConfigurationError(
            "Groq remote inference is disabled. Content Engine uses the local "
            "Qwen2.5-1.5B-Instruct model (models/qwen/) only. Groq cannot be "
            "instantiated for inference."
        )

    def generate(self, system: str, user: str, max_tokens: int, temperature: float) -> str:
        raise ConfigurationError("Groq generate() is disabled — local Qwen only.")

    @property
    def name(self) -> str:
        return "groq"

    @property
    def requires_api_key(self) -> bool:
        return True

    def is_available(self) -> bool:
        """Always False — Groq is disabled and unavailable for inference."""
        return False
