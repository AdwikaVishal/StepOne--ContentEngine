"""
Local LLM provider facade.

Historically this provider only spoke to the Apple-Silicon MLX worker. It now
selects the best available local backend at first use:

  LOCAL_LLM_BACKEND=auto   MLX when its worker is configured, else PyTorch
  LOCAL_LLM_BACKEND=mlx    force the MLX worker (macOS only)
  LOCAL_LLM_BACKEND=torch  force PyTorch/transformers

The public class name and ``name`` property are kept as ``MLXProvider`` /
``mlx_local`` for backwards compatibility with existing callers and tests.
Use ``backend`` to see which engine actually runs.
"""

import os
from typing import Optional

from content_engine.llm.mlx_client import MLXClientError, get_mlx_client
from content_engine.providers.llm.torch_local import TorchLocalProvider


class MLXProvider:
    """Local text generation provider (MLX or PyTorch backend)."""

    def __init__(self) -> None:
        self._client = None
        self._torch: Optional[TorchLocalProvider] = None
        self._backend: Optional[str] = None

    # ── backend selection ────────────────────────────────────────────────────

    @staticmethod
    def _mlx_configured() -> bool:
        from content_engine.llm.mlx_config import get_config

        try:
            issues = get_config().validate()
        except Exception:
            return False
        # Only missing worker paths are fatal; value warnings are fine.
        return not any("not found" in issue for issue in issues)

    def _select_backend(self) -> str:
        if self._backend is not None:
            return self._backend
        requested = os.getenv("LOCAL_LLM_BACKEND", "auto").strip().lower()
        if requested == "torch":
            self._backend = "torch"
        elif requested == "mlx":
            self._backend = "mlx"
        else:
            self._backend = "mlx" if self._mlx_configured() else "torch"
        return self._backend

    def _get_client(self):
        if self._client is None:
            self._client = get_mlx_client()
        return self._client

    def _torch_provider(self) -> TorchLocalProvider:
        if self._torch is None:
            self._torch = TorchLocalProvider()
        return self._torch

    # ── LLMProvider contract ─────────────────────────────────────────────────

    def generate(
        self,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        if self._select_backend() == "torch":
            return self._torch_provider().generate(
                system=system,
                user=user,
                max_tokens=max_tokens,
                temperature=temperature,
            )

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
        # Kept for backwards compatibility (see module docstring).
        return "mlx_local"

    @property
    def backend(self) -> str:
        return self._select_backend()

    @property
    def requires_api_key(self) -> bool:
        return False

    def is_available(self) -> bool:
        """True when either MLX or the PyTorch fallback can run."""
        backend = self._select_backend()
        if backend == "mlx":
            return self._mlx_configured()
        return self._torch_provider().is_available()
