"""
Tests for GroqVisionProvider — now DISABLED.

Content Engine uses local vision models (Florence-2 + CLIP + BLIP) only.
GroqVisionProvider cannot be instantiated for inference; any construction
attempt raises ConfigurationError.
"""

import os
import sys
import pytest
from unittest.mock import patch

from content_engine.ai_mode import ConfigurationError
from content_engine.providers.base import ProviderError
from content_engine.providers.vision.groq import GroqVisionProvider


class TestGroqVisionDisabled:
    """GroqVisionProvider is fail-closed: construction always raises."""

    def test_construction_raises_configuration_error(self):
        with patch.dict(
            os.environ,
            {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "test-key"},
        ):
            with pytest.raises(ConfigurationError):
                GroqVisionProvider()

    def test_construction_raises_regardless_of_key(self):
        with patch.dict(
            os.environ,
            {"AI_EXECUTION_MODE": "cloud_testing"},
            clear=False,
        ):
            os.environ.pop("GROQ_API_KEY", None)
            with pytest.raises(ConfigurationError):
                GroqVisionProvider()


class TestGroqVisionProviderSelection:
    """Local mode never returns GroqVisionProvider."""

    def test_local_mode_returns_local_vision_provider(self):
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            from content_engine.providers.factory import get_vision_provider
            from content_engine.providers.vision.local import LocalVisionProvider

            provider = get_vision_provider()
            assert isinstance(provider, LocalVisionProvider)
            assert not isinstance(provider, GroqVisionProvider)

    def test_cloud_testing_get_vision_provider_raises(self):
        with patch.dict(
            os.environ,
            {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "test-key"},
        ):
            from content_engine.providers.factory import get_vision_provider

            with pytest.raises(ConfigurationError):
                get_vision_provider()


class TestGroqVisionNoLocalModels:
    """cloud_testing raises before importing local ML model packages."""

    def test_cloud_mode_does_not_load_local_model_packages(self):
        forbidden = ["sentence_transformers", "transformers", "ultralytics", "mlx_lm"]
        modules_before = set(
            m for m in sys.modules if any(f in m for f in forbidden)
        )

        with patch.dict(
            os.environ,
            {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "test-key"},
        ):
            with pytest.raises(ConfigurationError):
                GroqVisionProvider()

        modules_after = set(sys.modules)
        newly_forbidden = set(
            m for m in modules_after if any(f in m for f in forbidden)
        ) - modules_before
        assert not newly_forbidden, (
            f"Local model packages loaded in cloud mode: {newly_forbidden}"
        )


class TestGroqVisionErrorTypesUnchanged:
    """Provider error types remain importable even though Groq is disabled."""

    def test_provider_error_types_exist(self):
        assert issubclass(ProviderError, Exception)
