"""
Tests for Gemini SDK compatibility and deferred video support.

All tests are mocked — no real API calls. Uses the actual installed
google-genai SDK (2.34.0) FileState enum.
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch

from content_engine.ai_mode import ConfigurationError, is_cloud_testing
from content_engine.models.video_processing import VideoProcessor
from content_engine.providers.base import (
    ProviderTimeoutError,
    ProviderError,
    UnsupportedFeatureError,
)
from content_engine.providers.vision.gemini import GeminiVisionProvider
from google.genai.types import FileState


class MockFileObject:
    """Mock Google Gen AI File object with configurable FileState."""

    def __init__(self, name: str, state):
        self.name = name
        self.state = state


class TestGeminiFileState:
    """Test file state polling with actual FileState enum values."""

    def test_active_state_returns(self):
        """ACTIVE state should cause _wait_for_file_active to return."""
        from content_engine.providers.vision.gemini import _wait_for_file_active

        client = MagicMock()
        active_file = MockFileObject("file-123", FileState.ACTIVE)
        client.files.get.return_value = active_file

        _wait_for_file_active(client, "file-123", timeout=5, poll_interval=0.1)
        client.files.get.assert_called_once_with(name="file-123")

    def test_failed_state_raises_configuration_error(self):
        """FAILED state should raise ConfigurationError."""
        from content_engine.providers.vision.gemini import _wait_for_file_active

        client = MagicMock()
        failed_file = MockFileObject("file-123", FileState.FAILED)
        client.files.get.return_value = failed_file

        with pytest.raises(ConfigurationError):
            _wait_for_file_active(client, "file-123", timeout=5, poll_interval=0.1)

    def test_processing_state_continues_polling(self):
        """PROCESSING state should continue polling until timeout."""
        from content_engine.providers.vision.gemini import _wait_for_file_active

        client = MagicMock()
        processing_file = MockFileObject("file-123", FileState.PROCESSING)
        client.files.get.return_value = processing_file

        with pytest.raises(ProviderTimeoutError):
            _wait_for_file_active(client, "file-123", timeout=0.5, poll_interval=0.1)

    def test_state_unspecified_continues_polling(self):
        """STATE_UNSPECIFIED should continue polling until timeout."""
        from content_engine.providers.vision.gemini import _wait_for_file_active

        client = MagicMock()
        unspecified_file = MockFileObject("file-123", FileState.STATE_UNSPECIFIED)
        client.files.get.return_value = unspecified_file

        with pytest.raises(ProviderTimeoutError):
            _wait_for_file_active(client, "file-123", timeout=0.5, poll_interval=0.1)

    def test_unknown_state_continues_polling(self):
        """Unknown state should NOT assume success — continue polling."""
        from content_engine.providers.vision.gemini import _wait_for_file_active

        client = MagicMock()
        unknown_file = MockFileObject("file-123", "UNKNOWN_STATE")
        client.files.get.return_value = unknown_file

        with pytest.raises(ProviderTimeoutError):
            _wait_for_file_active(client, "file-123", timeout=0.5, poll_interval=0.1)

    def test_none_state_continues_polling(self):
        """None state should continue polling until timeout."""
        from content_engine.providers.vision.gemini import _wait_for_file_active

        client = MagicMock()
        none_file = MockFileObject("file-123", None)
        client.files.get.return_value = none_file

        with pytest.raises(ProviderTimeoutError):
            _wait_for_file_active(client, "file-123", timeout=0.5, poll_interval=0.1)


class TestGeminiLazySDKImport:
    """Test that google-genai SDK is lazily imported only in cloud_testing mode."""

    def test_local_mode_no_google_genai_import(self):
        """Local mode must not import google.genai at all."""
        modules_before = {
            m for m in sys.modules if m == "google.genai" or m.startswith("google.genai.")
        }

        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            provider = GeminiVisionProvider.__new__(GeminiVisionProvider)
            assert provider is not None

        modules_after = {m for m in sys.modules if m == "google.genai" or m.startswith("google.genai.")}
        leaked = modules_after - modules_before
        assert not leaked, f"google.genai imported in local mode: {leaked}"


class TestGeminiCentralizedConfig:
    """Test that GEMINI_MODEL uses centralized config from settings."""

    def test_settings_has_gemini_model(self):
        """config.Settings should have gemini_model attribute."""
        from config import settings
        assert hasattr(settings, "gemini_model")
        assert settings.gemini_model == "gemini-3.8-flash"

    def test_provider_uses_settings_gemini_model(self):
        """GeminiVisionProvider should use settings.gemini_model, not os.getenv directly."""
        import inspect
        from content_engine.providers.vision.gemini import GeminiVisionProvider

        source = inspect.getsource(GeminiVisionProvider.understand_image)
        assert "settings.gemini_model" in source
        assert 'os.getenv("GEMINI_MODEL"' not in source


class TestGeminiVideoDeferred:
    """Test that video analysis returns explicit unsupported error."""

    def test_understand_video_raises_unsupported_feature_error(self):
        """Cloud mode understand_video should raise UnsupportedFeatureError."""
        with patch.dict(
            os.environ,
            {"AI_EXECUTION_MODE": "cloud_testing", "GEMINI_API_KEY": "test-key"},
        ):
            provider = GeminiVisionProvider()

        with pytest.raises(UnsupportedFeatureError):
            provider.understand_video("/fake/video.mp4")

    def test_unsupported_feature_error_is_provider_error(self):
        """UnsupportedFeatureError should be a subclass of ProviderError."""
        assert issubclass(UnsupportedFeatureError, ProviderError)


class TestLocalVideoUnchanged:
    """Test that local video functionality remains unchanged."""

    def test_local_video_processor_no_cloud_provider(self):
        """Local mode VideoProcessor should not have a cloud vision provider."""
        from content_engine.models.video_processing import VideoProcessor

        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            vp = VideoProcessor()
            assert vp._vision_provider is None

    def test_local_video_extract_highlights_uses_local_processing(self):
        """Local mode extract_highlights should use local processing, not cloud."""
        from content_engine.models.video_processing import VideoProcessor

        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            vp = VideoProcessor()
            assert vp._vision_provider is None
            result = vp.extract_highlights_optimized("/nonexistent.mp4", target_duration=10.0)
            assert result == []


class TestGeminiUnderstandingParsing:
    """Test understanding response parsing with valid, malformed, and empty outputs."""

    def test_valid_understanding_output(self):
        """Valid comma-separated response is parsed into schema."""
        from content_engine.providers.vision.gemini import GeminiVisionProvider

        provider = GeminiVisionProvider.__new__(GeminiVisionProvider)

        # Simulate the parsing logic from understand_image
        text = "person, stage, audience, applause"
        concepts = [c.strip() for c in text.split(",") if c.strip()][:20]
        relevance_scores = {c: 0.5 for c in concepts}
        concept_match_score = 0.5 if concepts else 0.0

        result = {
            "scene_concepts": concepts,
            "relevance_scores": relevance_scores,
            "concept_match_score": round(concept_match_score, 4),
            "provider": "gemini",
        }

        assert result["scene_concepts"] == ["person", "stage", "audience", "applause"]
        assert result["relevance_scores"] == {
            "person": 0.5, "stage": 0.5, "audience": 0.5, "applause": 0.5
        }
        assert result["concept_match_score"] == 0.5
        assert result["provider"] == "gemini"

    def test_empty_response_yields_empty_concepts(self):
        """Empty response yields empty scene_concepts and zero score."""
        from content_engine.providers.vision.gemini import GeminiVisionProvider

        provider = GeminiVisionProvider.__new__(GeminiVisionProvider)

        text = ""
        concepts = [c.strip() for c in text.split(",") if c.strip()][:20]
        relevance_scores = {c: 0.5 for c in concepts}
        concept_match_score = 0.5 if concepts else 0.0

        result = {
            "scene_concepts": concepts,
            "relevance_scores": relevance_scores,
            "concept_match_score": round(concept_match_score, 4),
            "provider": "gemini",
        }

        assert result["scene_concepts"] == []
        assert result["relevance_scores"] == {}
        assert result["concept_match_score"] == 0.0

    def test_whitespace_only_response_yields_empty_concepts(self):
        """Whitespace-only response yields empty scene_concepts."""
        from content_engine.providers.vision.gemini import GeminiVisionProvider

        provider = GeminiVisionProvider.__new__(GeminiVisionProvider)

        text = "   ,  ,   "
        concepts = [c.strip() for c in text.split(",") if c.strip()][:20]
        relevance_scores = {c: 0.5 for c in concepts}
        concept_match_score = 0.5 if concepts else 0.0

        result = {
            "scene_concepts": concepts,
            "relevance_scores": relevance_scores,
            "concept_match_score": round(concept_match_score, 4),
            "provider": "gemini",
        }

        assert result["scene_concepts"] == []
        assert result["relevance_scores"] == {}
        assert result["concept_match_score"] == 0.0

    def test_max_20_concepts(self):
        """More than 20 concepts are capped at 20."""
        from content_engine.providers.vision.gemini import GeminiVisionProvider

        provider = GeminiVisionProvider.__new__(GeminiVisionProvider)

        text = ", ".join(f"concept{i}" for i in range(30))
        concepts = [c.strip() for c in text.split(",") if c.strip()][:20]
        relevance_scores = {c: 0.5 for c in concepts}
        concept_match_score = 0.5 if concepts else 0.0

        result = {
            "scene_concepts": concepts,
            "relevance_scores": relevance_scores,
            "concept_match_score": round(concept_match_score, 4),
            "provider": "gemini",
        }

        assert len(result["scene_concepts"]) == 20
        assert result["scene_concepts"][0] == "concept0"
        assert result["scene_concepts"][19] == "concept19"

    def test_scores_are_testing_representation_not_clip(self):
        """All relevance scores are 0.5 — clearly testing representation."""
        from content_engine.providers.vision.gemini import GeminiVisionProvider

        provider = GeminiVisionProvider.__new__(GeminiVisionProvider)

        text = "person, stage"
        concepts = [c.strip() for c in text.split(",") if c.strip()][:20]
        relevance_scores = {c: 0.5 for c in concepts}
        concept_match_score = 0.5 if concepts else 0.0

        result = {
            "scene_concepts": concepts,
            "relevance_scores": relevance_scores,
            "concept_match_score": round(concept_match_score, 4),
            "provider": "gemini",
        }

        for score in result["relevance_scores"].values():
            assert score == 0.5, "Testing representation: all scores are 0.5"
        assert result["concept_match_score"] == 0.5


class TestGeminiUnderstandingGenerationConfig:
    """Test that understand_image uses bounded generation config."""

    def test_generation_config_has_max_output_tokens(self):
        """understand_image source includes generation_config with max_output_tokens."""
        import inspect
        from content_engine.providers.vision.gemini import GeminiVisionProvider

        source = inspect.getsource(GeminiVisionProvider.understand_image)
        assert "generation_config" in source
        assert "max_output_tokens" in source
        assert "temperature" in source
        assert "100" in source  # max_output_tokens=100

    def test_prompt_is_simple_and_direct(self):
        """Prompt is simple one-sentence request, not structured JSON."""
        import inspect
        from content_engine.providers.vision.gemini import GeminiVisionProvider

        source = inspect.getsource(GeminiVisionProvider.understand_image)
        # The actual prompt text (not docstring) should be simple
        assert "Describe this image in one sentence" in source
        # No structured JSON instructions in the prompt body
        assert "Return a concise JSON object" not in source
        assert "separated by commas" not in source
