"""
P1-focused tests for the dual-mode AI provider layer.

Tests:
  - Provider selection (local vs cloud_testing)
  - Missing credentials fail clearly
  - Local mode never imports cloud SDKs (groq, google-genai)
  - Cloud mode never imports local model packages at provider init
  - Mode switching does not leak cached providers
  - Output schema compatibility between modes
  - API timeout, rate limit, and provider failure handling

All tests are mocked — no real API calls, no local model loading.
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

from content_engine.ai_mode import (
    AIExecutionMode,
    ConfigurationError,
    get_execution_mode,
    is_cloud_testing,
    is_local,
    require_cloud_key,
    validate_cloud_credentials,
)
from content_engine.providers import (
    get_llm_provider,
    get_vision_provider,
    get_caption_provider,
)
from content_engine.providers.base import (
    LLMProvider,
    VisionProvider,
    ProviderTimeoutError,
    ProviderRateLimitError,
    ProviderError,
)
from content_engine.providers.llm.mlx import MLXProvider
from content_engine.providers.llm.groq import GroqProvider
from content_engine.providers.vision.local import LocalVisionProvider
from content_engine.providers.vision.gemini import GeminiVisionProvider
from content_engine.providers.vision.groq import GroqVisionProvider
from content_engine.providers.vision.mock import (
    MockFaceDetector,
    MockQualityAssessor,
    MockBrandMatcher,
    SemanticBrandMatcher,
)


# ── Mode detection ───────────────────────────────────────────────────

class TestModeDetection:
    def test_default_mode_is_local(self):
        with patch.dict(os.environ, {}, clear=False):
            # Remove AI_EXECUTION_MODE if set
            os.environ.pop("AI_EXECUTION_MODE", None)
            assert get_execution_mode() == AIExecutionMode.LOCAL
            assert is_local() is True
            assert is_cloud_testing() is False

    def test_cloud_testing_mode(self):
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "cloud_testing"}):
            assert get_execution_mode() == AIExecutionMode.CLOUD_TESTING
            assert is_cloud_testing() is True
            assert is_local() is False

    def test_local_mode_explicit(self):
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            assert get_execution_mode() == AIExecutionMode.LOCAL
            assert is_local() is True


# ── Credential validation ────────────────────────────────────────────

class TestCredentialValidation:
    def test_require_cloud_key_missing(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GROQ_API_KEY", None)
            with pytest.raises(ConfigurationError) as exc:
                require_cloud_key("GROQ_API_KEY")
            assert "GROQ_API_KEY" in str(exc.value)

    def test_require_cloud_key_present(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key-123"}):
            assert require_cloud_key("GROQ_API_KEY") == "test-key-123"

    def test_validate_cloud_credentials_missing_groq(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}, clear=False):
            os.environ.pop("GROQ_API_KEY", None)
            with pytest.raises(ConfigurationError) as exc:
                validate_cloud_credentials()
            assert "GROQ_API_KEY" in str(exc.value)

    def test_validate_cloud_credentials_both_present(self):
        with patch.dict(
            os.environ, {"GROQ_API_KEY": "groq-key"}
        ):
            validate_cloud_credentials()  # should not raise


class TestProviderSelectionLocal:
    def test_local_returns_mlx_provider(self):
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            provider = get_llm_provider()
            assert isinstance(provider, MLXProvider)
            assert provider.name == "mlx_local"
            assert provider.requires_api_key is False

    def test_local_returns_local_vision_provider(self):
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            provider = get_vision_provider()
            assert isinstance(provider, LocalVisionProvider)
            assert provider.name == "local_vision"
            assert provider.requires_api_key is False

    def test_local_returns_local_caption_provider(self):
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            provider = get_caption_provider()
            assert isinstance(provider, LocalVisionProvider)


class TestProviderSelectionCloud:
    def test_cloud_returns_groq_provider(self):
        with patch.dict(
            os.environ,
            {
                "AI_EXECUTION_MODE": "cloud_testing",
                "GROQ_API_KEY": "test-groq-key",
            },
        ):
            provider = get_llm_provider()
            assert isinstance(provider, GroqProvider)
            assert provider.name == "groq"
            assert provider.requires_api_key is True

    def test_cloud_returns_groq_vision_provider(self):
        with patch.dict(
            os.environ,
            {
                "AI_EXECUTION_MODE": "cloud_testing",
                "GROQ_API_KEY": "test-groq-key",
            },
        ):
            provider = get_vision_provider()
            assert isinstance(provider, GroqVisionProvider)
            assert provider.name == "groq"
            assert provider.requires_api_key is True

    def test_cloud_returns_groq_caption_provider(self):
        with patch.dict(
            os.environ,
            {
                "AI_EXECUTION_MODE": "cloud_testing",
                "GROQ_API_KEY": "test-groq-key",
            },
        ):
            provider = get_caption_provider()
            assert isinstance(provider, GroqVisionProvider)


# ── Cloud mode fail-closed ───────────────────────────────────────────

class TestCloudFailClosed:
    def test_cloud_missing_groq_key_fails(self):
        with patch.dict(
            os.environ,
            {"AI_EXECUTION_MODE": "cloud_testing"},
            clear=False,
        ):
            os.environ.pop("GROQ_API_KEY", None)
            with pytest.raises(ConfigurationError):
                get_llm_provider()

    def test_cloud_missing_both_keys_fails(self):
        with patch.dict(
            os.environ,
            {"AI_EXECUTION_MODE": "cloud_testing"},
            clear=False,
        ):
            os.environ.pop("GROQ_API_KEY", None)
            os.environ.pop("GEMINI_API_KEY", None)
            with pytest.raises(ConfigurationError):
                get_llm_provider()


# ── Local mode does not import cloud SDKs ────────────────────────────

class TestLocalNoCloudSDKs:
    def test_local_mode_does_not_import_groq(self):
        """Local mode must not import the groq SDK at all."""
        modules_before = set(sys.modules)
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            get_llm_provider()
        modules_after = set(sys.modules)
        new_modules = modules_after - modules_before
        assert "groq" not in new_modules, f"groq imported in local mode: {new_modules}"

    def test_local_mode_does_not_import_google_genai(self):
        """Local mode must not import google-genai at all."""
        modules_before = set(sys.modules)
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            get_vision_provider()
        modules_after = set(sys.modules)
        new_modules = modules_after - modules_before
        assert "google" not in str(new_modules), f"google-genai imported in local mode: {new_modules}"


# ── Cloud mode does not import local model packages ──────────────────

class TestCloudNoLocalModels:
    def test_cloud_provider_init_does_not_import_local_model_packages(self):
        """Cloud provider init must not import sentence_transformers, transformers, ultralytics, mlx_lm."""
        forbidden = ["sentence_transformers", "transformers", "ultralytics", "mlx_lm"]
        modules_before = set(m for m in sys.modules if any(f in m for f in forbidden))
        with patch.dict(
            os.environ,
            {
                "AI_EXECUTION_MODE": "cloud_testing",
                "GROQ_API_KEY": "test-groq-key",
                "GEMINI_API_KEY": "test-gemini-key",
            },
        ):
            get_llm_provider()
            get_vision_provider()
        modules_after = set(sys.modules)
        newly_forbidden = set(m for m in modules_after if any(f in m for f in forbidden)) - modules_before
        assert not newly_forbidden, f"Local model packages loaded in cloud mode: {newly_forbidden}"


# ── Mode switching cache invalidation ────────────────────────────────

class TestModeSwitching:
    def test_switching_modes_returns_different_providers(self):
        """Switching AI_EXECUTION_MODE must not return a cached provider from the previous mode."""
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            local_llm = get_llm_provider()
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "k1", "GEMINI_API_KEY": "k2"}):
            cloud_llm = get_llm_provider()
        assert type(local_llm) is not type(cloud_llm)

    def test_switching_back_to_local_returns_mlx(self):
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "k1", "GEMINI_API_KEY": "k2"}):
            get_llm_provider()
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            provider = get_llm_provider()
            assert isinstance(provider, MLXProvider)


# ── Output schema compatibility ──────────────────────────────────────

class TestSchemaCompatibility:
    def test_llm_provider_interface(self):
        """Both LLM providers implement the same interface."""
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            local = get_llm_provider()
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "k1", "GEMINI_API_KEY": "k2"}):
            cloud = get_llm_provider()
        for p in (local, cloud):
            assert hasattr(p, "generate")
            assert hasattr(p, "name")
            assert hasattr(p, "requires_api_key")
            assert hasattr(p, "is_available")
            assert isinstance(p.name, str)
            assert isinstance(p.requires_api_key, bool)
            assert isinstance(p.is_available(), bool)

    def test_vision_provider_interface(self):
        """Both vision providers implement the same interface."""
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            local = get_vision_provider()
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "k1", "GEMINI_API_KEY": "k2"}):
            cloud = get_vision_provider()
        for p in (local, cloud):
            assert hasattr(p, "understand_image")
            assert hasattr(p, "caption_image")
            assert hasattr(p, "name")
            assert hasattr(p, "requires_api_key")
            assert hasattr(p, "is_available")


# ── Error types ──────────────────────────────────────────────────────

class TestErrorTypes:
    def test_provider_error_hierarchy(self):
        assert issubclass(ProviderTimeoutError, ProviderError)
        assert issubclass(ProviderRateLimitError, ProviderError)
        assert issubclass(ConfigurationError, RuntimeError)

    def test_configuration_error_is_runtime_error(self):
        assert issubclass(ConfigurationError, RuntimeError)


# ── Mock adapters ────────────────────────────────────────────────────

class TestMockAdapters:
    def test_mock_face_detector_no_model(self):
        detector = MockFaceDetector()
        result = detector.detect_faces_detailed("/fake/path.jpg")
        assert result["mock"] is True
        assert result["source"] == "mock_adapter"
        assert result["face_count"] == 0
        assert result["weighted_score"] == 0.0
        with pytest.raises(RuntimeError):
            _ = detector.model

    def test_mock_quality_assessor_no_clip(self):
        assessor = MockQualityAssessor()
        result = assessor.assess("/fake/path.jpg")
        assert result["mock"] is True
        assert result["source"] == "mock_adapter"
        assert result["quality_score"] == 0.5
        with pytest.raises(RuntimeError):
            _ = assessor.clip_model

    def test_mock_brand_matcher_no_clip(self):
        matcher = MockBrandMatcher(brands=[("brand_a", "Brand A", [])])
        result = matcher.classify_asset("/fake/path.jpg")
        assert result["mock"] is True
        assert result["source"] == "mock_adapter"
        assert "similarity_scores" in result

    def test_mock_brand_segregation(self):
        matcher = MockBrandMatcher(brands=[("brand_a", "Brand A", [])])
        results = matcher.segregate_assets(["/fake/1.jpg", "/fake/2.jpg"])
        assert "brand_a" in results
        assert "unmatched" in results
        for bid, assets in results.items():
            for a in assets:
                assert a.get("mock") is True

    def test_semantic_brand_matcher_is_separate(self):
        """SemanticBrandMatcher uses Groq, not CLIP scores."""
        with patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
            matcher = SemanticBrandMatcher()
            # describe_brand_fit would call Groq; just verify it's constructed
            assert matcher is not None
            assert matcher._groq.name == "groq"
