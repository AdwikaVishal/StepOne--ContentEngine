"""
MLX LLM provider — wraps the existing MLX client for local text generation.

Used in local mode only. Delegates to content_engine.llm.mlx_client.MLXClient
which communicates with the MLX worker subprocess via JSON-lines.
"""

from typing import Any, Dict, Optional

from content_engine.llm.mlx_client import MLXClientError, get_mlx_client


class MLXProvider:
    """MLX-based local text generation provider."""

    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None:
            self._client = get_mlx_client()
        return self._client

    def generate(
        self,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Generate text using the MLX worker."""
        client = self._get_client()
        response = client.generate(
            system=system,
            user=user,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.text.strip()

    @property
    def name(self) -> str:
        return "mlx_local"

    @property
    def requires_api_key(self) -> bool:
        return False

    def is_available(self) -> bool:
        """MLX provider is available if the worker python and script exist."""
        from content_engine.llm.mlx_config import get_config

        try:
            config = get_config()
            issues = config.validate()
            # Only fail on critical issues (missing worker paths), not warnings
            critical = [
                i for i in issues if "not found" in i
            ]
            return len(critical) == 0
        except Exception:
            return False
