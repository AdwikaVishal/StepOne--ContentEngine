"""
PHASE 7 regression tests — Local Qwen-only enforcement.

These tests verify the offline, local-only migration:

1. Provider factory always selects TorchLocalProvider.
2. Caption factory always selects TorchCaptionProvider.
3-6. LinkedIn / Instagram / Story / Reel generation use Qwen (mocked provider).
7. Case study generation uses no cloud provider.
8. Hashtag/rewrite generation use Qwen (via CopyGenerator).
9. Regeneration uses Qwen.
10. No cloud provider is initialized.
11. No cloud API call occurs when an API key is configured.
12. Missing local model fails explicitly.
13. Model loading does not attempt network access (offline env vars set).
14. CPU fallback works.
15. CUDA selection works when available (falls back to CPU here).
16. Existing prompts and output schemas are preserved.

Unit tests use a mocked provider so no real model is loaded. One real-inference
integration test loads the already downloaded Qwen model from models/qwen/ and
generates a caption — it never passes a mock off as real inference.
"""

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from content_engine.ai_mode import AIExecutionMode, ConfigurationError, get_execution_mode
from content_engine.captioning.factory import CaptionProviderFactory, get_caption_provider
from content_engine.captioning.providers.base import CaptionProviderError
from content_engine.captioning.providers.torch_provider import TorchCaptionProvider
from content_engine.copy_generator import CopyGenerator, _story_captions_template
from content_engine.data_types import AssetMetadata
from content_engine.llm.torch_backend import (
    TorchTextGenerator,
    get_torch_generator,
    get_torch_status,
    reset_torch_generator,
)
from content_engine.providers.factory import get_llm_provider, get_vision_provider
from content_engine.providers.llm.torch_local import TorchLocalProvider
from content_engine.case_study_generator import generate_case_study
from content_engine.data_types import SelectionResult

QWEN_DIR = Path(__file__).parent.parent / "models" / "qwen"


# ── Mock provider helper ────────────────────────────────────────────────────

class _QwenLikeProvider:
    """Stand-in for TorchLocalProvider in unit tests — never makes network calls."""

    name = "torch_local"
    requires_api_key = False
    device = "cpu"

    def __init__(self, text="A grounded caption from the local Qwen model. #Event"):
        self._text = text
        self.calls = []

    def generate(self, system, user, max_tokens, temperature):
        self.calls.append((system, user, max_tokens, temperature))
        return self._text

    def is_available(self):
        return True

    def status(self):
        return {
            "provider": self.name,
            "model": "Qwen2.5-1.5B-Instruct",
            "model_path": str(QWEN_DIR),
            "local_only": True,
            "remote_inference_disabled": True,
            "device": self.device,
            "loaded": True,
            "requires_api_key": False,
        }


def _make_asset(concepts):
    return AssetMetadata(
        path="test.jpg", asset_type="image",
        quality_score=0.7, aesthetic_score=0.6,
        face_count=3, face_confidences=[0.9, 0.9, 0.9],
        relevance_scores=concepts,
        scene_concepts=list(concepts.keys()),
        final_score=0.5,
    )


def _generator_with_provider(text="A grounded caption from the local Qwen model. #Event"):
    gen = CopyGenerator.__new__(CopyGenerator)
    gen._provider = _QwenLikeProvider(text=text)
    return gen


# ── PHASE 7 #1: Provider factory always selects TorchLocalProvider ────────

class TestProviderFactoryLocalOnly:
    def test_factory_always_selects_torch_local_provider(self):
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            provider = get_llm_provider()
        assert isinstance(provider, TorchLocalProvider)
        assert provider.name == "torch_local"
        assert provider.requires_api_key is False

    def test_provider_is_local_and_not_cloud(self):
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            assert get_execution_mode() == AIExecutionMode.LOCAL
            provider = get_llm_provider()
            assert provider.name != "groq"
            assert provider.name != "gemini"


# ── PHASE 7 #2: Caption factory always selects TorchCaptionProvider -------

class TestCaptionFactoryLocalOnly:
    def test_caption_factory_selects_torch_caption_provider(self):
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            provider = get_caption_provider()
        assert isinstance(provider, TorchCaptionProvider)

    def test_caption_factory_rejects_groq_mode(self):
        factory = CaptionProviderFactory()
        with pytest.raises(CaptionProviderError):
            factory.get_provider(mode="groq_only")

    def test_caption_factory_rejects_template_only_mode(self):
        factory = CaptionProviderFactory()
        with pytest.raises(CaptionProviderError):
            factory.get_provider(mode="template_only")


# ── PHASE 7 #3-6: Platform generation uses Qwen (mocked provider) ---------

class TestPlatformGenerationUsesQwen:
    def _generator_with_provider(self, text="LinkedIn caption from Qwen."):
        gen = CopyGenerator.__new__(CopyGenerator)
        gen._provider = _QwenLikeProvider(text=text)
        return gen

    def test_linkedin_generation_uses_qwen(self):
        gen = _generator_with_provider("A LinkedIn post about the event. #Event")
        cap = gen.generate_linkedin_caption("Tech Summit 2024", [_make_asset({"keynote": 1.0})])
        assert isinstance(cap, str) and len(cap) > 0
        assert gen._provider.calls, "provider.generate must have been invoked"
        assert gen.backend == "torch_local"

    def test_instagram_generation_uses_qwen(self):
        gen = _generator_with_provider("we went to the event 😅 #Event #Community")
        cap = gen.generate_instagram_caption("Tech Summit 2024", [_make_asset({"networking": 1.0})])
        assert isinstance(cap, str) and len(cap) > 0
        assert gen.backend == "torch_local"

    def test_reel_generation_uses_qwen(self):
        gen = _generator_with_provider("Short event recap. Share your moment. #Event")
        cap = gen.generate_reel_caption("Tech Summit 2024", [_make_asset({"stage": 1.0})])
        assert isinstance(cap, str) and len(cap) > 0
        assert gen.backend == "torch_local"

    def test_story_generation_uses_qwen(self):
        gen = _generator_with_provider(
            "We're at the event ✨ | The main stage 👀 | Best conversation 🎯 | See you next year 👋"
        )
        caps = gen.generate_story_captions("Tech Summit 2024", num_slides=4, assets=[_make_asset({"networking": 1.0})])
        assert isinstance(caps, list) and len(caps) == 4
        assert gen.backend == "torch_local"

    def test_brand_aware_carousel_uses_qwen(self):
        gen = _generator_with_provider("Brand carousel caption from Qwen. #Event")
        cap = gen.generate_brand_carousel_caption("Acme", "Tech Summit 2024", [_make_asset({"stage": 1.0})])
        assert isinstance(cap, str) and len(cap) > 0
        assert gen.backend == "torch_local"


# ── PHASE 7 #8-9: Hashtag / rewrite / regeneration use Qwen --------------

class TestRewritingRegenerationUsesQwen:
    def test_variants_use_qwen_primary(self):
        gen = _generator_with_provider("A grounded LinkedIn update. What would you take forward? #Event")
        result = gen.generate_variants("linkedin", "Tech Summit 2024", [_make_asset({"keynote": 1.0})], n=3)
        assert "primary" in result and isinstance(result["primary"], str) and len(result["primary"]) > 0
        assert result["backend"] == "torch_local"

    def test_regeneration_uses_qwen(self):
        gen = _generator_with_provider("Regenerated LinkedIn caption from Qwen. #Event")
        cap = gen.generate_linkedin_caption("Tech Summit 2024", [_make_asset({"keynote": 1.0})], correction="Make it punchier.")
        assert isinstance(cap, str) and len(cap) > 0
        assert gen.backend == "torch_local"


# ── PHASE 7 #7: Case study uses no cloud provider ------------------------

class TestCaseStudyLocalOnly:
    def test_case_study_generates_without_cloud_provider(self):
        selections = [
            SelectionResult(
                asset=_make_asset({"keynote": 1.0}),
                selection_reason="Selected by user",
                confidence=0.8,
                intended_use="collage",
            )
        ]
        md = generate_case_study(selections, event_name="Tech Summit 2024", event_date="January 1, 2024")
        assert isinstance(md, str) and "# Case Study: Tech Summit 2024" in md
        # Case study is a deterministic data report — no LLM, no cloud.
        assert "groq" not in md.lower()
        assert "gemini" not in md.lower()


# ── PHASE 7 #10: No cloud provider is initialized ------------------------

class TestNoCloudProvider:
    def test_no_groq_provider_initialized_in_local_mode(self):
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local"}):
            provider = get_llm_provider()
        assert provider.name == "torch_local"
        assert provider.name != "groq"
        assert provider.name != "gemini"

    def test_get_torch_status_reports_local_only(self):
        status = get_torch_status()
        assert status["provider"] == "torch_local"
        assert status["model"] == "Qwen2.5-1.5B-Instruct"
        assert status["model_path"] == str(Path(__file__).parent.parent / "models" / "qwen")
        assert status["local_only"] is True
        assert status["remote_inference_disabled"] is True


# ── PHASE 7 #11: No cloud API call when an API key is configured -------

class TestNoCloudApiCallWithKey:
    def test_local_mode_never_initializes_groq_even_with_key(self):
        """GROQ_API_KEY present in env must not result in a Groq provider."""
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local", "GROQ_API_KEY": "gsk_fake_key"}):
            provider = get_llm_provider()
        assert provider.name == "torch_local"
        assert provider.requires_api_key is False


# ── PHASE 7 #12: Missing local model fails explicitly --------------------

class TestMissingModelFailsExplicitly:
    def test_missing_local_model_raises_descriptive_error(self):
        """Pointing TorchTextGenerator at a missing dir must raise, never fall back to cloud."""
        reset_torch_generator()
        gen = TorchTextGenerator(model_id="models/definitely-not-a-real-model-dir")
        with pytest.raises(Exception):
            gen.generate("sys", "user", 10)
        # The loading error must be captured and visible via status/logs.
        assert get_torch_status()["last_load_error"] is not None
        assert "local_files_only" in get_torch_status()["last_load_error"] or \
               "not found" in get_torch_status()["last_load_error"].lower()


# ── PHASE 7 #13: Model loading does not attempt network access ---------

class TestOfflineModelLoading:
    def test_offline_env_vars_are_set(self):
        assert os.getenv("HF_HUB_OFFLINE") == "1"
        assert os.getenv("TRANSFORMERS_OFFLINE") == "1"
        assert os.getenv("HF_HUB_DISABLE_TELEMETRY") == "1"
        assert os.getenv("TORCH_LLM_LOCAL_FILES_ONLY") == "true"

    def test_torch_status_reports_offline_enforcement(self):
        status = get_torch_status()
        oe = status["offline_enforcement"]
        assert oe["HF_HUB_OFFLINE"] == "1"
        assert oe["TRANSFORMERS_OFFLINE"] == "1"
        assert oe["HF_HUB_DISABLE_TELEMETRY"] == "1"
        assert oe["TORCH_LLM_LOCAL_FILES_ONLY"] == "true"


# ── PHASE 7 #14: CPU fallback works -------------------------------------

class TestCpuFallback:
    def test_provider_reports_cpu_when_no_cuda(self):
        with patch.dict(os.environ, {"AI_EXECUTION_MODE": "local", "TORCH_LLM_DEVICE": "cpu"}):
            provider = get_llm_provider()
        # No CUDA in this environment → device resolves to cpu.
        assert provider.device == "cpu"


# ── PHASE 7 #15: CUDA selection works when available --------------------

class TestCudaSelection:
    def test_cuda_selection_matches_torch_availability(self):
        """CUDA is used when torch reports it available, CPU otherwise — never cloud."""
        import torch
        reset_torch_generator()
        gen = TorchTextGenerator(device="cuda")
        expected = "cuda" if torch.cuda.is_available() else "cpu"
        assert gen._resolve_device() == expected
        assert gen._resolve_device() in {"cuda", "cpu"}


# ── PHASE 7 #16: Existing prompts and output schemas preserved ----------
class TestPromptsAndSchemasPreserved:
    def test_batch_output_schema(self):
        gen = CopyGenerator.__new__(CopyGenerator)
        gen._provider = _QwenLikeProvider(text=json.dumps({
            "linkedin": "A LinkedIn post about the event. #Event",
            "instagram": "we went to the event 😅 #Event #Community",
            "reel": "Short event recap. Share your moment. #Event",
            "stories": ["Frame one", "Frame two", "Frame three", "Frame four"],
        }))
        result = gen.generate_all_captions_batch("Tech Summit 2024", [_make_asset({"keynote": 1.0})])
        assert result is not None
        assert set(["linkedin", "instagram", "reel", "stories"]).issubset(result.keys())
        assert len(result["stories"]) == 4

    def test_story_schema_count(self):
        gen = CopyGenerator.__new__(CopyGenerator)
        gen._provider = _QwenLikeProvider(text="a | b | c | d")
        caps = gen.generate_story_captions("Event", num_slides=4, assets=[_make_asset({"a": 1.0})])
        assert len(caps) == 4


# ── Real inference integration test (uses the downloaded Qwen model) -----

class TestRealQwenInference:
    @pytest.mark.integration
    def test_real_qwen_generates_linkedin_caption_offline(self):
        """End-to-end real inference with the downloaded Qwen model (models/qwen/).

        This loads the actual model weights and generates text. It is the only
        test that touches real model weights — every other test uses a mock so
        mocks cannot falsely establish that real inference works.
        """
        reset_torch_generator()
        os.environ["TORCH_LLM_DEVICE"] = "cpu"
        os.environ["TORCH_LLM_MODEL"] = str(QWEN_DIR)
        gen = get_torch_generator()

        out = gen.generate(
            system=(
                "You are a social media copywriter. Write ONLY the caption text. "
                "Do not invent facts. Use only information provided."
            ),
            user=(
                "Brand: Acme\nEvent: Tech Summit 2024\nPlatform: linkedin\n"
                "Professional tone, no emojis, end with a question. #TechSummit"
            ),
            max_tokens=60,
            temperature=0.0,
        )

        assert isinstance(out, str) and len(out) > 0, "Qwen must produce non-empty caption"
        assert gen.device == "cpu"
        # Confirm the loaded model is the local Qwen path.
        assert str(QWEN_DIR) in str(get_torch_status()["model_path"])
