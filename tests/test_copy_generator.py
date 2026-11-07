"""Tests for CopyGenerator — event type detection, variants, platform distinctness."""
import json
import pytest
from content_engine.data_types import AssetMetadata
from content_engine.copy_generator import CopyGenerator, _detect_event_type


class _MockProvider:
    """Provider that mimics MLX client.generate() return shape."""

    name = "mlx_local"
    requires_api_key = False

    def __init__(self, text: str):
        self._text = text

    def generate(self, system, user, max_tokens, temperature):
        if "Story" in user or "Stories" in user:
            return "Frame one | Frame two | Frame three | Frame four"
        elif "LinkedIn" in user or "professional LinkedIn" in user or "LinkedIn" in system:
            return self._text or "A grounded LinkedIn update about the event. What would you take forward? #Event"
        elif "Reel" in user or "Reel" in system:
            return self._text or "A short event recap. Share your moment. #Event"
        else:
            return self._text or "A visual-first event caption. Save this recap. #Event #Community"

    def is_available(self):
        return True


def _asset(concepts: dict) -> AssetMetadata:
    return AssetMetadata(
        path="test.jpg", asset_type="image",
        quality_score=0.7, aesthetic_score=0.6,
        face_count=3, face_confidences=[0.9, 0.9, 0.9],
        relevance_scores=concepts,
        scene_concepts=list(concepts.keys()),
        final_score=0.5,
    )


@pytest.fixture(scope="module")
def gen():
    generator = CopyGenerator(use_llm=True)
    generator._provider = _MockProvider("")
    return generator


def test_event_type_award(gen):
    assets = [_asset({"award": 1.0, "applause": 1.0})]
    assert _detect_event_type(assets) == "award_ceremony"


def test_event_type_keynote(gen):
    assets = [_asset({"keynote": 1.0, "stage": 1.0})]
    assert _detect_event_type(assets) == "keynote"


def test_event_type_networking(gen):
    assets = [_asset({"networking": 1.0, "dinner": 1.0})]
    assert _detect_event_type(assets) == "networking"


def test_linkedin_caption_not_empty(gen):
    assets = [_asset({"keynote": 1.0})]
    caption = gen.generate_linkedin_caption("Test Event", assets)
    assert len(caption) > 50


def test_instagram_caption_distinct_from_linkedin(gen):
    assets = [_asset({"networking": 1.0})]
    li = gen.generate_linkedin_caption("Test Event", assets)
    ig = gen.generate_instagram_caption("Test Event", assets)
    assert li != ig


def test_story_captions_count(gen):
    assets = [_asset({"networking": 1.0})]
    caps = gen.generate_story_captions("Test Event", num_slides=4, assets=assets)
    assert len(caps) == 4


def test_variants_returns_primary_and_variants(gen):
    assets = [_asset({"keynote": 1.0})]
    result = gen.generate_variants("linkedin", "Test Event", assets, n=3)
    assert "primary" in result
    assert "variants" in result
    assert len(result["variants"]) == 2


def test_reel_caption_not_empty(gen):
    assets = [_asset({"stage": 1.0})]
    caption = gen.generate_reel_caption("Test Event", assets)
    assert len(caption) > 20


def test_batch_captions_success():
    """generate_all_captions_batch should return all platform captions via provider."""

    class BatchMockProvider:
        name = "mlx_local"
        requires_api_key = False

        def generate(self, system, user, max_tokens, temperature):
            return json.dumps({
                "linkedin": "A LinkedIn post about the event. What would you take forward? #Event",
                "instagram": "we went to the event 😅 swipe → #Event #Community",
                "reel": "Short event recap. Share your moment. #Event",
                "stories": ["We're at the event ✨", "The main stage 👀", "Best conversation 🎯", "See you next year 👋"],
            })

        def is_available(self):
            return True

    generator = CopyGenerator(use_llm=True)
    generator._provider = BatchMockProvider()

    assets = [_asset({"keynote": 1.0})]
    result = generator.generate_all_captions_batch("Test Event", assets)

    assert result is not None
    assert "linkedin" in result
    assert "instagram" in result
    assert "reel" in result
    assert "stories" in result
    assert len(result["stories"]) == 4


def test_batch_captions_json_parse_failure():
    """generate_all_captions_batch should return None on invalid JSON."""

    class BadJSONMockProvider:
        name = "mlx_local"
        requires_api_key = False

        def generate(self, system, user, max_tokens, temperature):
            return "not valid json {{{"

        def is_available(self):
            return True

    generator = CopyGenerator(use_llm=True)
    generator._provider = BadJSONMockProvider()

    assets = [_asset({"keynote": 1.0})]
    result = generator.generate_all_captions_batch("Test Event", assets)

    assert result is None


def test_empty_output_raises_runtime_error():
    """_generate should raise RuntimeError on empty provider output."""

    class EmptyMockProvider:
        name = "mlx_local"
        requires_api_key = False

        def generate(self, system, user, max_tokens, temperature):
            return ""

        def is_available(self):
            return True

    generator = CopyGenerator(use_llm=True)
    generator._provider = EmptyMockProvider()

    assets = [_asset({"keynote": 1.0})]
    with pytest.raises(RuntimeError, match="LLM generation failed"):
        generator.generate_linkedin_caption("Test Event", assets)


def test_mlx_worker_failure_raises_runtime_error():
    """Provider failure should propagate as RuntimeError."""

    class FailingMockProvider:
        name = "mlx_local"
        requires_api_key = False

        def generate(self, system, user, max_tokens, temperature):
            raise RuntimeError("Worker died")

        def is_available(self):
            return True
    generator = CopyGenerator(use_llm=True)
    generator._provider = FailingMockProvider()

    assets = [_asset({"keynote": 1.0})]
    with pytest.raises(RuntimeError, match="LLM generation failed"):
        generator.generate_linkedin_caption("Test Event", assets)
