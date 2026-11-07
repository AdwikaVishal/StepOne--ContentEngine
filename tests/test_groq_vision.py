"""
Tests for GroqVisionProvider — cloud image understanding for cloud_testing mode.

All tests are mocked — no real API calls. Uses the actual installed groq SDK
for import checking but mocks all API responses.
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch

from content_engine.ai_mode import ConfigurationError, is_cloud_testing
from content_engine.providers.base import (
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    UnsupportedFeatureError,
)
from content_engine.providers.vision.groq import GroqVisionProvider


class TestGroqVisionProviderSelection:
    """Test provider selection for cloud_testing vs local mode."""

    def test_cloud_testing_returns_groq_vision_provider(self):
        """cloud_testing mode returns GroqVisionProvider."""
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "cloud_testing"}):
            from content_engine.providers.factory import get_vision_provider
            provider = get_vision_provider()
            assert isinstance(provider, GroqVisionProvider)
            assert provider.name == "groq"
            assert provider.requires_api_key is True

    def test_local_mode_returns_local_vision_provider(self):
        """local mode returns LocalVisionProvider, not GroqVisionProvider."""
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            from content_engine.providers.factory import get_vision_provider
            provider = get_vision_provider()
            from content_engine.providers.vision.local import LocalVisionProvider
            assert isinstance(provider, LocalVisionProvider)
            assert not isinstance(provider, GroqVisionProvider)


class TestGroqVisionCredentials:
    """Test credential validation for Groq vision provider."""

    def test_cloud_testing_missing_groq_key_fails(self):
        """cloud_testing mode without GROQ_API_KEY raises ConfigurationError."""
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "cloud_testing"}, clear=False):
            os.environ.pop("GROQ_API_KEY", None)
            from content_engine.providers.factory import get_vision_provider
            with pytest.raises(ConfigurationError) as exc:
                get_vision_provider()
            assert "GROQ_API_KEY" in str(exc.value)

    def test_cloud_testing_with_groq_key_succeeds(self):
        """cloud_testing mode with GROQ_API_KEY returns GroqVisionProvider."""
        with patch.dict(
            os.environ,
            {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "test-key"},
        ):
            from content_engine.providers.factory import get_vision_provider
            provider = get_vision_provider()
            assert isinstance(provider, GroqVisionProvider)


class TestGroqVisionLazySDKImport:
    """Test that groq SDK is lazily imported only when needed."""

    def test_local_mode_no_groq_sdk_import(self):
        """Local mode must not import groq SDK at provider init."""
        modules_before = {
            m for m in sys.modules if m == "groq" or m.startswith("groq.")
        }

        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            from content_engine.providers.factory import get_vision_provider
            get_vision_provider()

        modules_after = {
            m for m in sys.modules if m == "groq" or m.startswith("groq.")
        }
        leaked = modules_after - modules_before
        assert not leaked, f"groq SDK imported in local mode: {leaked}"


class TestGroqVisionProviderMocked:
    """Test GroqVisionProvider with mocked SDK responses."""

    def _make_mock_client(self, caption_text="A test image caption."):
        """Create a mock Groq client that returns caption text."""
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = caption_text
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response
        return mock_client

    def test_caption_image_mocked(self):
        """caption_image returns caption text from mocked Groq response."""
        with patch.dict(
            os.environ,
            {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "test-key"},
        ):
            provider = GroqVisionProvider()
            mock_client = self._make_mock_client(
                "A person standing on a stage at an event."
            )
            provider._client = mock_client

            caption = provider.caption_image("test_photos/download.jpg")
            assert caption == "A person standing on a stage at an event."
            assert isinstance(caption, str)
            assert len(caption) > 0

            # Verify the client was called with image_url content
            mock_client.chat.completions.create.assert_called_once()
            call_args = mock_client.chat.completions.create.call_args
            assert call_args.kwargs["model"] == "qwen/qwen3.8-27b"
            assert call_args.kwargs["max_tokens"] == 60
            assert call_args.kwargs["temperature"] == 0.0

    def test_understand_image_mocked(self):
        """understand_image returns scene_concepts from mocked response."""
        with patch.dict(
            os.environ,
            {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "test-key"},
        ):
            provider = GroqVisionProvider()
            mock_client = self._make_mock_client(
                "person, stage, audience, applause"
            )
            provider._client = mock_client

            result = provider.understand_image("test_photos/download.jpg")

            # Schema validation
            assert "scene_concepts" in result
            assert "relevance_scores" in result
            assert "concept_match_score" in result
            assert "semantic_description" in result
            assert "provider" in result
            assert result["provider"] == "groq"

            # relevance_scores must be empty (no CLIP equivalent)
            assert result["relevance_scores"] == {}
            assert result["concept_match_score"] is None

            # scene_concepts should be parsed from the response
            assert isinstance(result["scene_concepts"], list)
            assert len(result["scene_concepts"]) > 0
            assert "person" in result["scene_concepts"]
            assert "stage" in result["scene_concepts"]

            # semantic_description should contain the full text
            assert result["semantic_description"] == "person, stage, audience, applause"

    def test_understand_image_empty_response(self):
        """Empty response yields empty scene_concepts and zero scores."""
        with patch.dict(
            os.environ,
            {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "test-key"},
        ):
            provider = GroqVisionProvider()
            mock_client = self._make_mock_client("")
            provider._client = mock_client

            result = provider.understand_image("test_photos/download.jpg")

            assert result["scene_concepts"] == []
            assert result["relevance_scores"] == {}
            assert result["concept_match_score"] is None
            assert result["semantic_description"] == ""

    def test_understand_image_whitespace_response(self):
        """Whitespace-only response yields empty scene_concepts."""
        with patch.dict(
            os.environ,
            {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "test-key"},
        ):
            provider = GroqVisionProvider()
            mock_client = self._make_mock_client("   ,  ,   ")
            provider._client = mock_client

            result = provider.understand_image("test_photos/download.jpg")

            assert result["scene_concepts"] == []
            assert result["relevance_scores"] == {}
            assert result["concept_match_score"] is None

    def test_understand_image_max_20_concepts(self):
        """More than 20 concepts are capped at 20."""
        with patch.dict(
            os.environ,
            {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "test-key"},
        ):
            provider = GroqVisionProvider()
            thirty_concepts = ", ".join(f"concept{i}" for i in range(30))
            mock_client = self._make_mock_client(thirty_concepts)
            provider._client = mock_client

            result = provider.understand_image("test_photos/download.jpg")

            assert len(result["scene_concepts"]) == 20
            assert result["scene_concepts"][0] == "concept0"
            assert result["scene_concepts"][19] == "concept19"

    def test_understand_image_missing_file(self):
        """Missing image file raises ProviderError (wrapped FileNotFoundError)."""
        with patch.dict(
            os.environ,
            {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "test-key"},
        ):
            provider = GroqVisionProvider()
            with pytest.raises(ProviderError):
                provider.understand_image("nonexistent.jpg")


class TestGroqVisionErrorHandling:
    """Test error handling for various failure modes."""

    def test_timeout_error(self):
        """Timeout error raises ProviderTimeoutError."""
        with patch.dict(
            os.environ,
            {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "test-key"},
        ):
            provider = GroqVisionProvider()
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = Exception(
                "Request timed out"
            )
            provider._client = mock_client

            with pytest.raises(ProviderTimeoutError):
                provider.caption_image("test_photos/download.jpg")

    def test_rate_limit_error(self):
        """Rate limit error raises ProviderRateLimitError."""
        with patch.dict(
            os.environ,
            {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "test-key"},
        ):
            provider = GroqVisionProvider()
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = Exception(
                "rate limit exceeded: 429"
            )
            provider._client = mock_client

            with pytest.raises(ProviderRateLimitError):
                provider.caption_image("test_photos/download.jpg")

    def test_auth_error(self):
        """Authentication error raises ProviderError."""
        with patch.dict(
            os.environ,
            {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "test-key"},
        ):
            provider = GroqVisionProvider()
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = Exception(
                "Invalid API key: 401"
            )
            provider._client = mock_client

            with pytest.raises(ProviderError):
                provider.caption_image("test_photos/download.jpg")

    def test_unsupported_model_error(self):
        """Unsupported model error raises ProviderError."""
        with patch.dict(
            os.environ,
            {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "test-key"},
        ):
            provider = GroqVisionProvider()
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = Exception(
                "model 'nonexistent' does not exist"
            )
            provider._client = mock_client

            with pytest.raises(ProviderError):
                provider.caption_image("test_photos/download.jpg")


class TestGroqVisionVideoDeferred:
    """Test that video understanding is deferred."""

    def test_understand_video_raises_unsupported_feature_error(self):
        """Cloud mode understand_video should raise UnsupportedFeatureError."""
        with patch.dict(
            os.environ,
            {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "test-key"},
        ):
            provider = GroqVisionProvider()

        with pytest.raises(UnsupportedFeatureError):
            provider.understand_video("/fake/video.mp4")

    def test_unsupported_feature_error_is_provider_error(self):
        """UnsupportedFeatureError should be a subclass of ProviderError."""
        assert issubclass(UnsupportedFeatureError, ProviderError)


class TestGroqVisionNoLocalModels:
    """Test that cloud_testing mode does not load local ML models."""

    def test_cloud_mode_does_not_load_local_model_packages(self):
        """Cloud provider init must not import local model packages."""
        forbidden = ["sentence_transformers", "transformers", "ultralytics", "mlx_lm"]
        modules_before = set(
            m for m in sys.modules if any(f in m for f in forbidden)
        )

        with patch.dict(
            os.environ,
            {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "test-key"},
        ):
            from content_engine.providers.factory import get_vision_provider
            get_vision_provider()

        modules_after = set(sys.modules)
        newly_forbidden = set(
            m for m in modules_after if any(f in m for f in forbidden)
        ) - modules_before
        assert not newly_forbidden, (
            f"Local model packages loaded in cloud mode: {newly_forbidden}"
        )
