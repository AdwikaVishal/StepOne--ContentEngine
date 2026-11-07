"""Tests for Qwen-only enforcement and provider-based copy generation."""
import pytest
from types import ModuleType, SimpleNamespace

from content_engine.captioning.factory import CaptionProviderFactory
from content_engine.captioning.providers.base import CaptionProviderError
from content_engine.copy_generator import CopyGenerator


def test_factory_no_groq_fallback():
    factory = CaptionProviderFactory()
    with pytest.raises(CaptionProviderError):
        factory.get_provider(mode="groq_only")
    with pytest.raises(CaptionProviderError):
        factory.get_provider(mode="template_only")


class _FailingProvider:
    """Provider that always raises on generate()."""

    name = "failing"
    requires_api_key = False

    def generate(self, system, user, max_tokens, temperature):
        raise RuntimeError("checkpoint missing")

    def is_available(self):
        return True


def test_copy_generator_no_silent_fallback(monkeypatch):
    """CopyGenerator must surface provider failures, not fall back to templates."""
    gen = CopyGenerator.__new__(CopyGenerator)
    gen._provider = _FailingProvider()

    with pytest.raises(RuntimeError, match="LLM generation failed"):
        gen.generate_linkedin_caption("Test", [])


def test_copy_generator_loads_model_lazily(monkeypatch):
    """CopyGenerator construction must not load any model."""
    calls = []

    class _TrackingProvider:
        name = "mlx_local"
        requires_api_key = False

        def generate(self, system, user, max_tokens, temperature):
            calls.append("generate")
            raise RuntimeError("should not be called during construction")

        def is_available(self):
            return True

    monkeypatch.setattr(
        "content_engine.providers.get_llm_provider",
        lambda: _TrackingProvider(),
    )
    generator = CopyGenerator()
    assert generator.backend == "mlx_local"
    assert calls == [], "Model must not load during CopyGenerator construction"


def test_story_generation_failure_does_not_return_template_copy():
    generator = CopyGenerator.__new__(CopyGenerator)
    generator._provider = type("BrokenProvider", (), {
        "name": "test",
        "requires_api_key": False,
        "generate": lambda self, *args, **kwargs: (_ for _ in ()).throw(RuntimeError("inference failed")),
    })()

    with pytest.raises(RuntimeError, match="LLM generation failed"):
        generator.generate_story_captions("Fictional Summit", num_slides=2)


def test_brand_generation_failure_does_not_return_template_copy():
    generator = CopyGenerator.__new__(CopyGenerator)
    generator._provider = type("BrokenProvider", (), {
        "name": "test",
        "requires_api_key": False,
        "generate": lambda self, *args, **kwargs: (_ for _ in ()).throw(RuntimeError("inference failed")),
    })()

    with pytest.raises(RuntimeError, match="LLM generation failed"):
        generator.generate_brand_carousel_caption("Example Brand", "Fictional Summit", [])
