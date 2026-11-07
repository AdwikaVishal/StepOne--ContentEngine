"""
Groq LLM provider — cloud text generation for cloud_testing mode.

Uses the groq SDK (groq>=1.0.0). Lazy-imported so local mode never imports it.
"""

import os
from typing import Optional

from content_engine.ai_mode import ConfigurationError, require_cloud_key


class GroqProvider:
    """Groq API text generation provider."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or require_cloud_key("GROQ_API_KEY")
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from groq import Groq
            except ImportError as exc:
                raise ConfigurationError(
                    "groq SDK is not installed. Install it with "
                    "'pip install groq>=1.0.0' or switch AI_EXECUTION_MODE to 'local'."
                ) from exc
            self._client = Groq(api_key=self.api_key)
        return self._client

    def generate(
        self,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Generate text using the Groq API."""
        client = self._get_client()
        try:
            response = client.chat.completions.create(
                model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:
            msg = str(exc).lower()
            if "timeout" in msg:
                from content_engine.providers.base import ProviderTimeoutError

                raise ProviderTimeoutError(f"Groq request timed out: {exc}") from exc
            if "rate limit" in msg or "429" in msg:
                from content_engine.providers.base import ProviderRateLimitError

                raise ProviderRateLimitError(f"Groq rate limit exceeded: {exc}") from exc
            from content_engine.providers.base import ProviderError

            raise ProviderError(f"Groq request failed: {exc}") from exc

    @property
    def name(self) -> str:
        return "groq"

    @property
    def requires_api_key(self) -> bool:
        return True

    def is_available(self) -> bool:
        """True if GROQ_API_KEY is set and the groq SDK is importable."""
        if not os.getenv("GROQ_API_KEY"):
            return False
        try:
            import groq  # noqa: F401
            return True
        except ImportError:
            return False
