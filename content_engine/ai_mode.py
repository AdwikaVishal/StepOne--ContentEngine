"""
AI execution mode detection and credential validation.

Controls whether the application runs in:
  - local:        MLX Qwen + local vision models (final production architecture)
  - cloud_testing: Groq + Gemini APIs, local models bypassed for routed features

This module reads environment variables directly via os.getenv to avoid
circular imports with config.py.
"""

import os


class AIExecutionMode:
    LOCAL = "local"
    CLOUD_TESTING = "cloud_testing"


class ConfigurationError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def get_execution_mode() -> str:
    """Return the active AI execution mode. Defaults to 'local'."""
    return os.getenv("AI_EXECUTION_MODE", AIExecutionMode.LOCAL)


def is_cloud_testing() -> bool:
    """True when AI_EXECUTION_MODE=cloud_testing."""
    return get_execution_mode() == AIExecutionMode.CLOUD_TESTING


def is_local() -> bool:
    """True when AI_EXECUTION_MODE=local (default)."""
    return get_execution_mode() == AIExecutionMode.LOCAL


def require_cloud_key(var_name: str) -> str:
    """Return the value of a required cloud API key, or raise ConfigurationError."""
    value = os.getenv(var_name, "")
    if not value:
        raise ConfigurationError(
            f"cloud_testing mode requires {var_name} to be set. "
            f"Add {var_name} to your environment or .env, or switch "
            f"AI_EXECUTION_MODE back to 'local'."
        )
    return value


def validate_cloud_credentials() -> None:
    """Validate that all credentials required for cloud_testing are present.

    Called by provider factory when instantiating cloud providers.
    Raises ConfigurationError with a clear message if any key is missing.
    Only GROQ_API_KEY is required — Groq serves as both LLM and vision
    provider in cloud_testing mode. Gemini remains available as a separate
    import but is not the active cloud_testing vision provider.
    """
    require_cloud_key("GROQ_API_KEY")
