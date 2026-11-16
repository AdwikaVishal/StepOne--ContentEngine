"""
Milestone 3 tests: Brand Voice Preview (local Qwen only).

Verifies:
- The endpoint generates a real sample through the local provider.
- The prompt is built from UNSAVED form values.
- A preview never modifies the saved profile on disk.
- Provider failure surfaces as a clear 503 (no hardcoded fallback).
- Invalid payloads are rejected with 422.
- A real local Qwen acceptance test (skipped when the model is absent).
"""
import json
from pathlib import Path

import pytest

from content_engine.studio import StudioStorage
from content_engine.studio.voice_preview import (
    build_voice_prompt,
    generate_voice_preview,
)


class FakeProvider:
    """Deterministic stand-in for TorchLocalProvider (pipeline tests only)."""

    name = "fake_local"

    def __init__(self, output: str = "We build calm, durable tools for teams who ship.", fail: bool = False):
        self.output = output
        self.fail = fail
        self.calls: list[dict] = []

    def generate(self, system: str, user: str, max_tokens: int, temperature: float = 0.0) -> str:
        self.calls.append({"system": system, "user": user, "max_tokens": max_tokens, "temperature": temperature})
        if self.fail:
            raise FileNotFoundError("Local Qwen model directory not found: models/qwen/")
        return self.output


class TestVoicePrompt:
    def test_prompt_uses_supplied_voice_values(self):
        system, user = build_voice_prompt({
            "name": "Aurora",
            "tone_of_voice": "playful",
            "tone_description": "Witty and light",
            "personality_traits": ["Cheeky", "Warm"],
            "target_audience": "Indie developers",
            "preferred_vocabulary": ["delight", "craft"],
            "avoid_words_claims": ["synergy", "revolutionary"],
            "emoji_preference": "moderate",
            "formality_level": "casual",
        })
        for expected in ("Aurora", "playful", "Witty and light", "Cheeky, Warm",
                         "Indie developers", "delight, craft", "synergy",
                         "moderate", "casual"):
            assert expected in user
        assert "Output ONLY" in system or "Output only" in system

    def test_prompt_omits_empty_fields(self):
        _, user = build_voice_prompt({"name": "Sparse", "mission": "", "cta_style": None})
        assert "Mission" not in user
        assert "CTA style" not in user
        assert "Sparse" in user

    def test_prompt_falls_back_to_brand_name_when_empty(self):
        _, user = build_voice_prompt({})
        assert "(not set)" in user

    def test_avoid_terms_are_flagged_as_must_not_appear(self):
        _, user = build_voice_prompt({"name": "X", "avoid_words_claims": ["guaranteed", "risk-free"]})
        assert "must never appear" in user
        assert "guaranteed, risk-free" in user


class TestGenerateVoicePreview:
    def test_returns_sample_and_metadata(self):
        provider = FakeProvider(output="A calm paragraph about shipping.")
        result = generate_voice_preview({"name": "Aurora"}, provider=provider)
        assert result["sample"] == "A calm paragraph about shipping."
        assert result["model"] == "Qwen2.5-1.5B-Instruct"
        assert result["local_only"] is True
        assert result["duration_s"] >= 0
        assert provider.calls[0]["temperature"] == 0.0

    def test_raises_on_empty_output(self):
        with pytest.raises(RuntimeError, match="empty voice sample"):
            generate_voice_preview({"name": "X"}, provider=FakeProvider(output="   "))

    def test_raises_when_provider_fails(self):
        with pytest.raises(FileNotFoundError, match="Local Qwen model directory"):
            generate_voice_preview({"name": "X"}, provider=FakeProvider(fail=True))

    def test_no_provider_saved_anything(self, tmp_path):
        storage = StudioStorage(base_dir=tmp_path)
        storage.create_brand_profile({"name": "Static", "tone_of_voice": "formal"})
        before = sorted(p.name for p in (tmp_path / "brand_profiles").glob("*.json"))
        generate_voice_preview({"name": "Dynamic", "tone_of_voice": "playful"},
                               provider=FakeProvider())
        after = sorted(p.name for p in (tmp_path / "brand_profiles").glob("*.json"))
        assert before == after


class TestVoicePreviewApi:
    def _client(self, monkeypatch, tmp_path):
        import content_engine.studio as studio
        monkeypatch.setattr(studio, "StudioContentOrchestrator", lambda: None)
        from api import studio_routes
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(studio_routes.router)
        storage = StudioStorage(base_dir=Path(tmp_path))
        monkeypatch.setattr(studio_routes, "storage", storage)
        return TestClient(app), storage

    def test_preview_uses_unsaved_values_and_does_not_save(self, monkeypatch, tmp_path):
        import content_engine.studio.voice_preview as vp
        client, storage = self._client(monkeypatch, tmp_path)
        created = storage.create_brand_profile({
            "name": "Saved Brand",
            "tone_of_voice": "professional",
            "emoji_preference": "none",
        })
        saved_file = Path(tmp_path) / "brand_profiles" / f"{created['id']}.json"
        bytes_before = saved_file.read_bytes()

        captured = FakeProvider(output="Preview paragraph.")
        monkeypatch.setattr(vp, "get_llm_provider", lambda *a, **k: captured)

        # Preview carries UNSAVED edits (playful tone, emoji, new audience).
        resp = client.post("/api/studio/brand-profiles/voice-preview", json={
            "name": "Saved Brand",
            "tone_of_voice": "playful",
            "emoji_preference": "moderate",
            "target_audience": "Weekend makers",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["sample"] == "Preview paragraph."
        assert body["local_only"] is True

        # The unsaved values reached the model prompt…
        prompt = captured.calls[0]["user"]
        assert "playful" in prompt
        assert "moderate" in prompt
        assert "Weekend makers" in prompt

        # …and the saved profile was not touched.
        assert saved_file.read_bytes() == bytes_before
        stored = storage.get_brand_profile(created["id"])
        assert stored["tone_of_voice"] == "professional"
        assert stored["emoji_preference"] == "none"
        assert "target_audience" not in json.loads(bytes_before) or \
            json.loads(bytes_before)["target_audience"] == ""

    def test_provider_failure_returns_503(self, monkeypatch, tmp_path):
        import content_engine.studio.voice_preview as vp
        client, _ = self._client(monkeypatch, tmp_path)
        monkeypatch.setattr(vp, "get_llm_provider",
                            lambda *a, **k: FakeProvider(fail=True))
        resp = client.post("/api/studio/brand-profiles/voice-preview", json={"name": "X"})
        assert resp.status_code == 503
        assert "Local Qwen unavailable" in resp.json()["detail"]

    def test_non_object_payload_rejected(self, monkeypatch, tmp_path):
        client, _ = self._client(monkeypatch, tmp_path)
        resp = client.post("/api/studio/brand-profiles/voice-preview", json=["not", "an", "object"])
        assert resp.status_code == 422

    def test_empty_object_still_produces_a_prompt(self, monkeypatch, tmp_path):
        import content_engine.studio.voice_preview as vp
        client, _ = self._client(monkeypatch, tmp_path)
        captured = FakeProvider(output="Generic sample.")
        monkeypatch.setattr(vp, "get_llm_provider", lambda *a, **k: captured)
        resp = client.post("/api/studio/brand-profiles/voice-preview", json={})
        assert resp.status_code == 200
        assert "Output only the paragraph" in captured.calls[0]["user"]


QWEN_MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "qwen"


@pytest.mark.skipif(
    not (QWEN_MODEL_DIR / "config.json").exists(),
    reason="local Qwen model not present under models/qwen/",
)
class TestRealLocalQwenAcceptance:
    """Acceptance test against the real local Qwen2.5-1.5B-Instruct model.

    Proves the preview endpoint path performs genuine local inference.
    Skipped automatically when the model directory is absent.
    """

    def test_real_qwen_generates_distinct_samples_for_different_voices(self):
        from content_engine.studio.voice_preview import generate_voice_preview

        professional = generate_voice_preview({
            "name": "Northwind Tools",
            "tone_of_voice": "professional",
            "formality_level": "formal",
            "writing_style": "precise and structured",
            "sentence_length": "short",
            "personality_traits": ["Authoritative", "Technical"],
            "target_audience": "enterprise engineering leaders",
            "emoji_preference": "none",
            "avoid_words_claims": ["game-changer"],
            "preferred_cta": "Request a briefing",
        })
        playful = generate_voice_preview({
            "name": "Northwind Tools",
            "tone_of_voice": "friendly",
            "formality_level": "casual",
            "writing_style": "conversational and warm",
            "sentence_length": "mixed",
            "personality_traits": ["Energetic", "Community-driven"],
            "target_audience": "weekend makers",
            "emoji_preference": "moderate",
            "preferred_cta": "Come build with us",
        })

        for result in (professional, playful):
            assert result["local_only"] is True
            assert result["model"] == "Qwen2.5-1.5B-Instruct"
            assert len(result["sample"].split()) >= 20  # a real paragraph
            assert result["sample"].count("\n") < 6      # not a rambling completion

        # Observably different outputs for different voices (semantic, not exact).
        assert professional["sample"] != playful["sample"]
        # Prohibited term must not be introduced.
        assert "game-changer" not in professional["sample"]
        # No emoji in the professional sample (emoji_preference: none).
        assert not any(ord(ch) > 0x2100 for ch in professional["sample"])
