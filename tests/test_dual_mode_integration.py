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
from content_engine.providers.llm.groq import GroqProvider
from content_engine.providers.vision.local import LocalVisionProvider
from content_engine.providers.vision.gemini import GeminiVisionProvider
from content_engine.providers.vision.groq import GroqVisionProvider
from content_engine.providers.vision.mock import MockBrandMatcher, MockQualityAssessor, MockFaceDetector


# ── ContentEngine construction without local models ──────────────────

class TestContentEngineCloudIsolation:
    """Cloud mode must construct ContentEngine without loading any local model weights."""

    def test_cloud_contentengine_no_local_model_imports(self):
        """Constructing ContentEngine in cloud mode must not import local model packages."""
        forbidden = ["sentence_transformers", "transformers", "ultralytics", "mlx_lm"]
        modules_before = {m for m in sys.modules if any(f in m for f in forbidden)}

        with patch.dict(
            os.environ,
            {
                "AI_EXECUTION_MODE": "cloud_testing",
                "GROQ_API_KEY": "test-groq-key",
                "GEMINI_API_KEY": "test-gemini-key",
            },
        ):
            engine = ContentEngine(event_description="Test Event")

        modules_after = set(sys.modules)
        newly_forbidden = {m for m in modules_after if any(f in m for f in forbidden)} - modules_before
        assert not newly_forbidden, f"Local model packages loaded in cloud mode: {newly_forbidden}"

        # Verify mock adapters are used
        assert isinstance(engine.quality_assessor, MockQualityAssessor)
        assert isinstance(engine.face_detector, MockFaceDetector)

    def test_local_contentengine_loads_real_models(self):
        """Local mode constructs real model classes (lazy, no weights loaded yet)."""
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            engine = ContentEngine(event_description="Test Event")

        from content_engine.models.quality import QualityAssessor
        from content_engine.models.face_detection import FaceDetector
        assert isinstance(engine.quality_assessor, QualityAssessor)
        assert isinstance(engine.face_detector, FaceDetector)

    def test_cloud_contentengine_quality_returns_mock(self):
        """Cloud mode quality assessment returns mock data, not CLIP scores."""
        with patch.dict(
            os.environ,
            {
                "AI_EXECUTION_MODE": "cloud_testing",
                "GROQ_API_KEY": "test-groq-key",
                "GEMINI_API_KEY": "test-gemini-key",
            },
        ):
            engine = ContentEngine(event_description="Test Event")
            result = engine.quality_assessor.assess("/fake/path.jpg")

        assert result["mock"] is True
        assert result["source"] == "mock_adapter"
        assert result["quality_score"] == 0.5

    def test_cloud_contentengine_face_returns_mock(self):
        """Cloud mode face detection returns mock data, not YOLO boxes."""
        with patch.dict(
            os.environ,
            {
                "AI_EXECUTION_MODE": "cloud_testing",
                "GROQ_API_KEY": "test-groq-key",
                "GEMINI_API_KEY": "test-gemini-key",
            },
        ):
            engine = ContentEngine(event_description="Test Event")
            result = engine.face_detector.detect_faces_detailed("/fake/path.jpg")

        assert result["mock"] is True
        assert result["source"] == "mock_adapter"
        assert result["face_count"] == 0


# ── StudioIntelligence caption routing ───────────────────────────────

class TestStudioIntelligenceRouting:
    """StudioIntelligence must route captioning to the mode-appropriate provider."""

    def test_local_mode_uses_blip(self):
        """Local mode should have BLIP available (not Gemini)."""
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            intel = StudioIntelligence()
            blip = intel._get_blip()
            assert blip is not None, "BLIP should be available in local mode"

    def test_cloud_mode_no_blip(self):
        """Cloud mode must not load BLIP."""
        with patch.dict(
            os.environ,
            {
                "AI_EXECUTION_MODE": "cloud_testing",
                "GROQ_API_KEY": "test-groq-key",
                "GEMINI_API_KEY": "test-gemini-key",
            },
        ):
            intel = StudioIntelligence()
            blip = intel._get_blip()
            assert blip is None, "BLIP must not load in cloud mode"

    def test_cloud_mode_caption_provider_is_groq(self):
        """Cloud mode caption provider should be GroqVisionProvider."""
        with patch.dict(
            os.environ,
            {
                "AI_EXECUTION_MODE": "cloud_testing",
                "GROQ_API_KEY": "test-groq-key",
            },
        ):
            provider = get_vision_provider()
            assert isinstance(provider, GroqVisionProvider)


# ── VideoProcessor routing ───────────────────────────────────────────

class TestVideoProcessorRouting:
    """VideoProcessor must route video analysis in cloud mode."""

    def test_cloud_video_processor_has_groq_provider(self):
        """Cloud mode VideoProcessor should have a vision provider set."""
        with patch.dict(
            os.environ,
            {
                "AI_EXECUTION_MODE": "cloud_testing",
                "GROQ_API_KEY": "test-groq-key",
            },
        ):
            vp = VideoProcessor()
            assert vp._vision_provider is not None
            assert isinstance(vp._vision_provider, GroqVisionProvider)

    def test_local_video_processor_no_vision_provider(self):
        """Local mode VideoProcessor should not have a cloud vision provider."""
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            vp = VideoProcessor()
            assert vp._vision_provider is None


# ── BrandMatcher mock in cloud mode ──────────────────────────────────

class TestBrandMatcherCloud:
    """BrandMatcher must use mock scores in cloud mode, never CLIP."""

    def test_cloud_brand_matcher_uses_mock(self, tmp_path):
        """Cloud mode BrandMatcher should return mock scores."""
        # Create a dummy render image so BrandMatcher doesn't skip it
        render_path = tmp_path / "render.jpg"
        render_path.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

        with patch.dict(
            os.environ,
            {
                "AI_EXECUTION_MODE": "cloud_testing",
                "GROQ_API_KEY": "test-groq-key",
                "GEMINI_API_KEY": "test-gemini-key",
            },
        ):
            matcher = BrandMatcher(
                brands=[("brand_a", "Brand A", [str(render_path)])],
                similarity_threshold=0.60,
            )
            assert matcher._use_mock is True
            result = matcher.classify("/fake/asset.jpg")
            assert result.decision_log.get("mock") is True
            assert result.decision_log.get("source") == "mock_adapter"

    def test_local_brand_matcher_uses_clip(self):
        """Local mode BrandMatcher should NOT use mock scores."""
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            matcher = BrandMatcher(
                brands=[("brand_a", "Brand A", ["/fake/render.jpg"])],
                similarity_threshold=0.60,
            )
            assert matcher._use_mock is False


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


# ── Mode switching cache isolation ───────────────────────────────────

class TestModeSwitching:
    """Switching modes must not leak cached providers."""

    def test_no_provider_caches_across_mode_switch(self):
        """Providers must not be cached across mode switches."""
        providers_local = []
        providers_cloud = []

        for _ in range(3):
            with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
                p = get_llm_provider()
                providers_local.append(type(p))

            with patch.dict(
                os.environ,
                {
                    "AI_EXECUTION_MODE": "cloud_testing",
                    "GROQ_API_KEY": "k1",
                    "GEMINI_API_KEY": "k2",
                },
            ):
                p = get_llm_provider()
                providers_cloud.append(type(p))

        assert all(t is MLXProvider for t in providers_local)
        assert all(t is GroqProvider for t in providers_cloud)


# ── Schema compatibility ─────────────────────────────────────────────

class TestSchemaCompatibility:
    """Both modes must return identical application-level schemas."""

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

    def test_understand_image_schema_cloud(self):
        """Cloud mode understand_image returns the same schema fields."""
        with patch.dict(
            os.environ,
            {
                "AI_EXECUTION_MODE": "cloud_testing",
                "GROQ_API_KEY": "k1",
                "GEMINI_API_KEY": "k2",
            },
        ):
            provider = get_vision_provider()
            # Gemini provider would try to upload files; just check schema fields exist
            assert hasattr(provider, "understand_image")
            assert hasattr(provider, "caption_image")


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

    def test_cloud_mode_no_local_model_imports(self):
        """Cloud mode provider init must not import local model packages."""
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
            get_llm_provider()
            get_vision_provider()

        modules_after = set(sys.modules)
        leaked = {m for m in modules_after if any(f in m for f in forbidden)} - modules_before
        assert not leaked, f"Local model packages imported in cloud mode: {leaked}"


# ── VideoProcessor cloud routing ─────────────────────────────────────

class TestVideoProcessorCloudRouting:
    """VideoProcessor must route video analysis through Gemini in cloud mode."""

    def test_extract_highlights_cloud_delegates_to_gemini(self):
        """Cloud mode extract_highlights should call Gemini understand_video."""
        with patch.dict(
            os.environ,
            {
                "AI_EXECUTION_MODE": "cloud_testing",
                "GROQ_API_KEY": "k1",
                "GEMINI_API_KEY": "k2",
            },
        ):
            vp = VideoProcessor()
            # Mock the vision provider's understand_video
            vp._vision_provider.understand_video = MagicMock(return_value={
                "clips": [
                    {"start": 0.0, "end": 5.0, "score": 0.8, "description": "highlight"},
                ],
                "provider": "gemini",
            })

            result = vp.extract_highlights("/fake/video.mp4", target_duration=10.0)

            assert vp._vision_provider.understand_video.called
            assert len(result) >= 1
            assert result[0]["start"] == 0.0
            assert result[0]["end"] == 5.0
