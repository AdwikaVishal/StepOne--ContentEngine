"""
Abstract base classes and exceptions for AI providers.

All providers implement these interfaces so that cloud_testing and local
modes return identical application-level response schemas.
"""

import abc
from typing import Any, Dict, Optional


class ConfigurationError(RuntimeError):
    """Raised when required provider configuration is missing or invalid."""


class ProviderError(RuntimeError):
    """Base exception for provider failures."""


class ProviderTimeoutError(ProviderError):
    """Raised when a provider request times out."""


class ProviderRateLimitError(ProviderError):
    """Raised when a provider rate limit is exceeded."""


class UnsupportedFeatureError(ProviderError):
    """Raised when a provider feature is intentionally not yet supported."""


class LLMProvider(abc.ABC):
    """Text generation provider interface.

    Both MLX (local) and Groq (cloud_testing) implement this contract.
    """

    @abc.abstractmethod
    def generate(
        self,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Generate text from a system + user prompt.

        Returns the generated text string.
        """
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable provider name (e.g. 'mlx_local', 'groq')."""
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def requires_api_key(self) -> bool:
        """True if this provider requires an API key to operate."""
        raise NotImplementedError

    def is_available(self) -> bool:
        """True if the provider can be used (credential + SDK present)."""
        return True


class VisionProvider(abc.ABC):
    """Image/video understanding provider interface.

    Both local (Florence-2 + CLIP) and cloud_testing (Gemini) implement
    this contract, returning the same application-level schema.
    """

    @abc.abstractmethod
    def understand_image(self, image_path: str) -> Dict[str, Any]:
        """Return scene understanding for an image.

        Schema:
          {
            "scene_concepts": List[str],
            "relevance_scores": Dict[str, float],
            "concept_match_score": float,
          }
        """
        raise NotImplementedError

    @abc.abstractmethod
    def caption_image(self, image_path: str) -> str:
        """Return a free-text image caption."""
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable provider name (e.g. 'local_vision', 'gemini')."""
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def requires_api_key(self) -> bool:
        """True if this provider requires an API key to operate."""
        raise NotImplementedError

    def is_available(self) -> bool:
        """True if the provider can be used (credential + SDK present)."""
        return True
