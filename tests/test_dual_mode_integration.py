"""
P3 integration tests for dual-mode AI architecture.

Tests that:
  - ContentEngine constructs without loading local models in cloud_testing mode
  - Local mode never imports or calls Groq/Gemini
  - Cloud mode never imports or loads MLX/CLIP/Florence/BLIP/YOLO
  - StudioIntelligence routes captioning to the right provider
  - VideoProcessor routes video analysis to Gemini in cloud mode
  - BrandMatcher uses mock scores in cloud mode (no CLIP)
  - StudioContentOrchestrator uses provider-agnostic error messages
  - Mode switching doesn't leak cached providers
  - Output schemas are compatible between modes

All tests are mocked — no real API calls, no local model loading, no FastAPI startup.
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

from content_engine.ai_mode import (
    AIExecutionMode,
    ConfigurationError,
    is_cloud_testing,
    is_local,
)
from content_engine.pipeline import ContentEngine
from content_engine.studio.intelligence import StudioIntelligence
from content_engine.studio.content_orchestrator import StudioContentOrchestrator
from content_engine.brand.brand_matcher import BrandMatcher
from content_engine.gff.orchestrator_gff import GFFOrchestrator
from content_engine.models.video_processing import VideoProcessor
from content_engine.providers import get_llm_provider, get_vision_provider
from content_engine.providers.llm.mlx import MLXProvider
from content_engine.providers.llm.torch_local import TorchLocalProvider
from content_engine.providers.llm.groq import GroqProvider
from content_engine.providers.vision.local import LocalVisionProvider
from content_engine.providers.vision.gemini import GeminiVisionProvider
from content_engine.providers.vision.groq import GroqVisionProvider
from content_engine.providers.vision.mock import MockBrandMatcher, MockQualityAssessor, MockFaceDetector


# ── ContentEngine construction (local-only) ──────────────────────────

class TestContentEngineLocalOnly:
    """Local mode constructs ContentEngine with real (lazy) model classes."""

    def test_local_contentengine_loads_real_models(self):
        """Local mode constructs real model classes (lazy, no weights loaded yet)."""
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            engine = ContentEngine(event_description="Test Event")

        from content_engine.models.quality import QualityAssessor
        from content_engine.models.face_detection import FaceDetector
        assert isinstance(engine.quality_assessor, QualityAssessor)
        assert isinstance(engine.face_detector, FaceDetector)

    def test_cloud_testing_raises_for_contentengine(self):
        """cloud_testing is unreachable; ContentEngine construction fails clearly."""
        with patch.dict(
            os.environ,
            {
                "AI_EXECUTION_MODE": "cloud_testing",
                "GROQ_API_KEY": "test-groq-key",
                "GEMINI_API_KEY": "test-gemini-key",
            },
        ):
            with pytest.raises(ConfigurationError):
                ContentEngine(event_description="Test Event")


# ── StudioIntelligence caption routing ───────────────────────────────

class TestStudioIntelligenceRouting:
    """StudioIntelligence must route captioning to the mode-appropriate provider."""

    def test_local_mode_uses_blip(self):
        """Local mode should have BLIP available (not Gemini)."""
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            intel = StudioIntelligence()
            blip = intel._get_blip()
            assert blip is not None, "BLIP should be available in local mode"

    def test_local_vision_provider_is_local(self):
        """Local mode vision provider is LocalVisionProvider, never Groq/Gemini."""
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            provider = get_vision_provider()
            assert isinstance(provider, LocalVisionProvider)
            assert provider.name == "local_vision"

    def test_cloud_testing_caption_routing_rejected(self):
        """cloud_testing is unreachable for caption routing."""
        with patch.dict(
            os.environ,
            {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "k", "GEMINI_API_KEY": "k"},
        ):
            with pytest.raises(ConfigurationError):
                get_vision_provider()


# ── VideoProcessor routing ───────────────────────────────────────────

class TestVideoProcessorRouting:
    """VideoProcessor uses local vision in local mode; cloud routing disabled."""

    def test_local_video_processor_no_cloud_provider(self):
        """Local mode VideoProcessor should not have a cloud vision provider."""
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            vp = VideoProcessor()
            assert vp._vision_provider is None

    def test_cloud_testing_video_processor_rejected(self):
        """cloud_testing is unreachable for VideoProcessor."""
        with patch.dict(
            os.environ,
            {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "k", "GEMINI_API_KEY": "k"},
        ):
            with pytest.raises(ConfigurationError):
                VideoProcessor()


# ── BrandMatcher (local-only) ────────────────────────────────────────

class TestBrandMatcherLocal:
    """BrandMatcher uses local scoring in local mode; cloud mock routing disabled."""

    def test_local_brand_matcher_uses_clip(self):
        """Local mode BrandMatcher should NOT use mock scores."""
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            matcher = BrandMatcher(
                brands=[("brand_a", "Brand A", ["/fake/render.jpg"])],
                similarity_threshold=0.60,
            )
            assert matcher._use_mock is False

    def test_brand_matcher_never_uses_groq(self):
        """BrandMatcher must never instantiate a Groq client — local scoring only."""
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            matcher = BrandMatcher(
                brands=[("brand_a", "Brand A", ["/fake/render.jpg"])],
                similarity_threshold=0.60,
            )
        assert matcher is not None
        assert matcher._groq_client is None


# ── StudioContentOrchestrator provider-agnostic errors ───────────────

class TestStudioOrchestratorErrors:
    """StudioContentOrchestrator must not reference specific model names in errors."""

    def test_error_messages_are_provider_agnostic(self):
        """Error messages should not mention 'Qwen' or specific model names."""
        orch = StudioContentOrchestrator()
        # The copy_gen uses the provider; errors should say "LLM provider" or "model"
        assert hasattr(orch.copy_gen, "_provider")
        # Verify no Qwen references in error strings
        import inspect
        source = inspect.getsource(orch._validate_generated_caption)
        assert "Qwen" not in source, "Error messages must not reference Qwen"


# ── Mode consistency (local-only) ────────────────────────────────────

class TestModeConsistency:
    """Providers are never cached; local mode always returns TorchLocalProvider."""

    def test_local_always_torch_provider(self):
        for _ in range(3):
            with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
                p = get_llm_provider()
                assert isinstance(p, TorchLocalProvider)

    def test_cloud_testing_raises(self):
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "k1", "GEMINI_API_KEY": "k2"}):
            with pytest.raises(ConfigurationError):
                get_llm_provider()


# ── Schema compatibility (local-only) ────────────────────────────────

class TestSchemaCompatibility:
    def test_understand_image_schema_local(self):
        """Local mode understand_image returns the standard schema."""
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            provider = get_vision_provider()
            result = provider.understand_image("/fake/path.jpg")

        assert "scene_concepts" in result
        assert "relevance_scores" in result
        assert "concept_match_score" in result
        assert "provider" in result
        assert result["provider"] == "local_vision"


# ── Import isolation ─────────────────────────────────────────────────

class TestImportIsolation:
    """Neither mode should import the other's SDKs at provider init."""

    def test_local_mode_no_cloud_sdk_imports(self):
        """Local mode provider init must not import groq or google-genai."""
        forbidden = ["groq", "google.genai", "google.generativeai"]
        modules_before = {m for m in sys.modules if any(f in m for f in forbidden)}

        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            get_llm_provider()
            get_vision_provider()

        modules_after = set(sys.modules)
        leaked = {m for m in modules_after if any(f in m for f in forbidden)} - modules_before
        assert not leaked, f"Cloud SDKs imported in local mode: {leaked}"

    def test_cloud_mode_raises_without_local_imports(self):
        """cloud_testing raises ConfigurationError before importing local model packages."""
        forbidden = ["sentence_transformers", "transformers", "ultralytics", "mlx_lm"]
        modules_before = {m for m in sys.modules if any(f in m for f in forbidden)}

        with patch.dict(
            os.environ,
            {
                "AI_EXECUTION_MODE": "cloud_testing",
                "GROQ_API_KEY": "k1",
                "GEMINI_API_KEY": "k2",
            },
        ):
            with pytest.raises(ConfigurationError):
                get_llm_provider()
            with pytest.raises(ConfigurationError):
                get_vision_provider()

        modules_after = set(sys.modules)
        leaked = {m for m in modules_after if any(f in m for f in forbidden)} - modules_before
        assert not leaked, f"Local model packages imported in cloud mode: {leaked}"


# ── VideoProcessor (local-only) ──────────────────────────────────────

class TestVideoProcessorLocal:
    """VideoProcessor uses local video processing; cloud routing disabled."""

    def test_local_video_processor_constructs(self):
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            vp = VideoProcessor()
            assert vp is not None

    def test_cloud_testing_video_processor_rejected(self):
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "cloud_testing", "GROQ_API_KEY": "k1", "GEMINI_API_KEY": "k2"}):
            with pytest.raises(ConfigurationError):
                VideoProcessor()
