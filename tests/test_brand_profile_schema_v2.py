"""
Milestone 2 tests: rich flat brand schema + backward-compatible migration.

Covers:
- Legacy profile files (v1, 13 data fields) load unchanged with additive defaults.
- Reading never rewrites legacy files (no migration side effects).
- New profiles accept the extended flat schema.
- Partial updates preserve omitted fields.
- Duplicates carry all new fields.
- Logo / visual references stay accessible and confined.
- Unknown fields are still rejected.
- CRUD persistence keeps working.
"""
import json
import shutil
from pathlib import Path

import pytest

from content_engine.studio import StudioStorage


# The real legacy profile that exists on disk (v1 schema, has a logo).
LEGACY_CRACKERS_PATH = (
    Path(__file__).resolve().parent.parent
    / "output" / "studio" / "brand_profiles"
    / "f273c615-ae36-48ce-95df-c8c606d88363.json"
)

V1_FIELDS = {
    "name", "description", "target_audience", "campaign_objectives",
    "tone_of_voice", "preferred_vocabulary", "avoid_words_claims",
    "preferred_cta", "hashtag_guidance", "logo_path", "brand_colors",
    "fonts", "visual_references",
}

# Flat v2 fields added by Milestone 2 (all optional).
V2_FIELDS = {
    "industry", "website", "tagline", "mission", "core_values",
    "tone_description", "personality_traits", "formality_level",
    "writing_style", "sentence_length", "person_preference",
    "secondary_audience", "audience_demographics", "audience_interests",
    "audience_pain_points", "technical_level", "communication_expectations",
    "industry_vocabulary", "emoji_preference", "capitalization_preferences",
    "linkedin_style", "instagram_style", "story_style", "reel_style",
    "preferred_caption_length", "preferred_hook_style", "cta_style",
    "content_themes", "topics_to_avoid",
    "visual_style", "logo_usage_guidelines", "text_overlay_preferences",
    # Brand Intelligence Phase 1 (additive).
    "brand_category", "known_text_aliases", "reference_notes",
}


def _make_storage(tmpdir: str) -> StudioStorage:
    return StudioStorage(base_dir=Path(tmpdir))


class TestLegacyProfileMigration:
    def test_schema_is_additive_superset_of_v1(self):
        """The new defaults must keep every v1 field with identical semantics."""
        defaults = StudioStorage.BRAND_PROFILE_DEFAULTS
        assert V1_FIELDS.issubset(defaults.keys())
        assert V2_FIELDS.issubset(defaults.keys())
        assert V1_FIELDS.isdisjoint(V2_FIELDS)
        # v1 defaults unchanged
        assert defaults["name"] == ""
        assert defaults["tone_of_voice"] == "professional"
        assert defaults["logo_path"] is None
        for key in ("preferred_vocabulary", "avoid_words_claims", "brand_colors",
                    "fonts", "visual_references"):
            assert defaults[key] == []

    @pytest.mark.skipif(not LEGACY_CRACKERS_PATH.exists(),
                        reason="legacy Crackers profile not present on disk")
    def test_crackers_profile_loads_unchanged(self, tmp_path):
        """The existing Crackers profile loads with identical v1 values."""
        store = tmp_path / "studio"
        (store / "brand_profiles").mkdir(parents=True)
        (store / "brand_assets").mkdir(parents=True)
        original_bytes = LEGACY_CRACKERS_PATH.read_bytes()
        shutil.copy(LEGACY_CRACKERS_PATH, store / "brand_profiles" / LEGACY_CRACKERS_PATH.name)
        target = store / "brand_profiles" / LEGACY_CRACKERS_PATH.name

        storage = StudioStorage(base_dir=store)
        raw_before = json.loads(original_bytes)
        loaded = storage.get_brand_profile(raw_before["id"])

        assert loaded is not None
        # Every v1 value preserved exactly.
        for key, value in raw_before.items():
            assert loaded[key] == value, f"v1 field {key} changed"
        assert loaded["name"] == "Crackers"
        # Additive v2 defaults present without modifying v1 data.
        for key in V2_FIELDS:
            assert key in loaded, f"v2 default {key} missing"
            assert loaded[key] in ("", []), f"v2 default {key} not empty"
        # Reading must not rewrite the file (no migration side effects).
        assert target.read_bytes() == original_bytes, "legacy file was rewritten on read"

    @pytest.mark.skipif(not LEGACY_CRACKERS_PATH.exists(),
                        reason="legacy Crackers profile not present on disk")
    def test_all_existing_profiles_load(self):
        storage = StudioStorage()  # real output dir
        profiles = storage.list_brand_profiles()
        assert profiles, "expected at least the Crackers profile"
        for profile in profiles:
            # Full schema visible on every profile after read-merge.
            assert V1_FIELDS.issubset(profile.keys())
            assert V2_FIELDS.issubset(profile.keys())
            assert profile.get("name")

    def test_legacy_file_gains_defaults_on_later_explicit_save(self, tmp_path):
        """A legacy file written by hand keeps loading; defaults appear in the
        merged view, and only an explicit save persists them."""
        store = tmp_path / "studio"
        bp_dir = store / "brand_profiles"
        bp_dir.mkdir(parents=True)
        legacy = {
            "name": "Legacy Co", "description": "old", "target_audience": "",
            "campaign_objectives": "", "tone_of_voice": "casual",
            "preferred_vocabulary": ["joy"], "avoid_words_claims": ["scam"],
            "preferred_cta": "Join us", "hashtag_guidance": "",
            "logo_path": None, "brand_colors": [], "fonts": [],
            "visual_references": [], "id": "11111111-1111-1111-1111-111111111111",
            "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
        }
        path = bp_dir / f"{legacy['id']}.json"
        path.write_text(json.dumps(legacy))

        storage = StudioStorage(base_dir=store)
        loaded = storage.get_brand_profile(legacy["id"])
        assert loaded["tone_of_voice"] == "casual"
        assert loaded["preferred_vocabulary"] == ["joy"]
        assert loaded["emoji_preference"] == ""
        assert loaded["core_values"] == []
        # File untouched by read.
        assert json.loads(path.read_text()) == legacy

        # Explicit save persists the full merged schema without data loss.
        saved = storage.save_brand_profile(loaded)
        on_disk = json.loads(path.read_text())
        assert on_disk["preferred_vocabulary"] == ["joy"]
        assert on_disk["avoid_words_claims"] == ["scam"]
        assert on_disk["emoji_preference"] == ""
        assert saved["name"] == "Legacy Co"


class TestExtendedSchema:
    def test_new_profile_accepts_extended_schema(self, tmp_path):
        storage = _make_storage(str(tmp_path))
        profile = storage.create_brand_profile({
            "name": "Aurora",
            "industry": "Developer tools",
            "website": "https://aurora.dev",
            "tagline": "Ship faster",
            "mission": "Empower developers",
            "core_values": ["Craft", "Simplicity"],
            "tone_description": "Professional and approachable",
            "personality_traits": ["Curious", "Innovative"],
            "formality_level": "semi-formal",
            "writing_style": "concise technical prose",
            "sentence_length": "short",
            "person_preference": "third-person",
            "secondary_audience": "Engineering managers",
            "audience_demographics": "25-40, urban",
            "audience_interests": "Open source, DX",
            "audience_pain_points": "Slow releases",
            "technical_level": "expert",
            "communication_expectations": "No fluff",
            "industry_vocabulary": "CI/CD, SLO, PR",
            "emoji_preference": "none",
            "capitalization_preferences": "Sentence case",
            "linkedin_style": "insight-led",
            "instagram_style": "visual-first",
            "story_style": "behind-the-scenes",
            "reel_style": "fast cuts",
            "preferred_caption_length": "120 words",
            "preferred_hook_style": "question",
            "cta_style": "formal invitation",
            "content_themes": ["Engineering", "Culture"],
            "topics_to_avoid": ["Politics"],
            "visual_style": "dark minimal",
            "logo_usage_guidelines": "Clear space 1x",
            "text_overlay_preferences": "Bottom third only",
        })
        assert profile["industry"] == "Developer tools"
        assert profile["personality_traits"] == ["Curious", "Innovative"]
        assert profile["topics_to_avoid"] == ["Politics"]
        loaded = storage.get_brand_profile(profile["id"])
        assert loaded["tagline"] == "Ship faster"
        assert loaded["text_overlay_preferences"] == "Bottom third only"

    def test_omitted_new_fields_default_to_empty(self, tmp_path):
        storage = _make_storage(str(tmp_path))
        profile = storage.create_brand_profile({"name": "Minimal"})
        for key in V2_FIELDS:
            assert profile[key] in ("", []), f"{key} should default"

    def test_partial_update_preserves_omitted_fields(self, tmp_path):
        storage = _make_storage(str(tmp_path))
        profile = storage.create_brand_profile({
            "name": "Partial",
            "industry": "Fintech",
            "emoji_preference": "none",
            "core_values": ["Trust"],
            "preferred_cta": "Open an account",
        })
        # Simulate the PUT route: load, update with a subset, save.
        stored = storage.get_brand_profile(profile["id"])
        stored.update({"name": "Partial Renamed"})
        updated = storage.save_brand_profile(stored)
        assert updated["name"] == "Partial Renamed"
        assert updated["industry"] == "Fintech"
        assert updated["emoji_preference"] == "none"
        assert updated["core_values"] == ["Trust"]
        assert updated["preferred_cta"] == "Open an account"
        # Untouched v1/v2 fields keep their defaults too.
        assert updated["mission"] == ""
        assert updated["hashtag_guidance"] == ""

    def test_duplicate_preserves_all_new_fields(self, tmp_path):
        storage = _make_storage(str(tmp_path))
        original = storage.create_brand_profile({
            "name": "Source",
            "industry": "Healthcare",
            "personality_traits": ["Empathetic"],
            "content_themes": ["Education"],
            "visual_style": "soft photography",
            "brand_colors": ["#112233"],
        })
        dup = storage.duplicate_brand_profile(original["id"])
        assert dup["id"] != original["id"]
        for key in V2_FIELDS:
            assert dup[key] == original[key], f"duplicate lost {key}"
        assert dup["brand_colors"] == ["#112233"]
        # Duplicate is independent: editing it must not touch the source.
        dup["industry"] = "Retail"
        storage.save_brand_profile(dup)
        assert storage.get_brand_profile(original["id"])["industry"] == "Healthcare"

    def test_logo_and_visual_references_accessible_after_migration(self, tmp_path):
        storage = _make_storage(str(tmp_path))
        profile = storage.create_brand_profile({"name": "Assets"})
        logo = storage.save_brand_asset(profile["id"], "logo.png", b"\x89PNG-fake")
        ref = storage.save_brand_asset(profile["id"], "ref.jpg", b"\xff\xd8-fake")
        profile["logo_path"] = logo
        profile["visual_references"] = [ref]
        storage.save_brand_profile(profile)
        # Round-trip through a read that now includes v2 defaults.
        storage.save_brand_profile(storage.get_brand_profile(profile["id"]))
        loaded = storage.get_brand_profile(profile["id"])
        assert loaded["logo_path"] == logo
        assert loaded["visual_references"] == [ref]
        assert Path(loaded["logo_path"]).exists()
        assert Path(loaded["visual_references"][0]).exists()

    def test_unknown_field_rejected_on_create_and_save(self, tmp_path):
        storage = _make_storage(str(tmp_path))
        with pytest.raises(ValueError, match="Unknown brand profile field"):
            storage.create_brand_profile({"name": "X", "voice": {"tone": "a"}})
        with pytest.raises(ValueError, match="Unknown brand profile field"):
            storage.create_brand_profile({"name": "X", "nested_group": "y"})
        profile = storage.create_brand_profile({"name": "Y"})
        profile["bogus_field"] = "nope"
        with pytest.raises(ValueError, match="Unknown brand profile field"):
            storage.save_brand_profile(profile)

    def test_new_field_validation_limits(self, tmp_path):
        storage = _make_storage(str(tmp_path))
        with pytest.raises(ValueError, match="industry must be a string"):
            storage.create_brand_profile({"name": "X", "industry": 42})
        with pytest.raises(ValueError, match="at most 200 characters"):
            storage.create_brand_profile({"name": "X", "industry": "a" * 201})
        with pytest.raises(ValueError, match="core_values must be a list"):
            storage.create_brand_profile({"name": "X", "core_values": "craft"})
        with pytest.raises(ValueError, match="at most 50 items"):
            storage.create_brand_profile({"name": "X", "core_values": ["v"] * 51})

    def test_list_field_dedup_and_strip(self, tmp_path):
        storage = _make_storage(str(tmp_path))
        # Existing v1 semantics: strip whitespace, drop empties, dedupe
        # case-sensitively (preserved unchanged for all list fields).
        profile = storage.create_brand_profile({
            "name": "Dedup",
            "personality_traits": [" Bold ", "Bold", "", "Warm", "Warm "],
        })
        assert profile["personality_traits"] == ["Bold", "Warm"]


class TestCrudStillWorks:
    def test_create_read_update_delete_roundtrip(self, tmp_path):
        storage = _make_storage(str(tmp_path))
        created = storage.create_brand_profile({"name": "Roundtrip", "website": "https://x.dev"})
        assert storage.get_brand_profile(created["id"])["website"] == "https://x.dev"
        assert len(storage.list_brand_profiles()) == 1

        created["description"] = "updated"
        created["tagline"] = "new tagline"
        storage.save_brand_profile(created)
        loaded = storage.get_brand_profile(created["id"])
        assert loaded["description"] == "updated"
        assert loaded["tagline"] == "new tagline"
        assert loaded["website"] == "https://x.dev"

        assert storage.delete_brand_profile(created["id"]) is True
        assert storage.get_brand_profile(created["id"]) is None
        assert storage.list_brand_profiles() == []


class TestApiContract:
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

    def test_api_create_with_extended_schema(self, monkeypatch, tmp_path):
        client, storage = self._client(monkeypatch, tmp_path)
        resp = client.post("/api/studio/brand-profiles", json={
            "name": "API Brand",
            "industry": "SaaS",
            "emoji_preference": "none",
            "personality_traits": ["Precise"],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["industry"] == "SaaS"
        assert body["cta_style"] == ""  # additive default present

    def test_api_partial_put_preserves_omitted_fields(self, monkeypatch, tmp_path):
        client, storage = self._client(monkeypatch, tmp_path)
        created = storage.create_brand_profile({
            "name": "Before", "industry": "Gaming", "mission": "Play more",
            "topics_to_avoid": ["Spoiler"],
        })
        resp = client.put(f"/api/studio/brand-profiles/{created['id']}",
                          json={"name": "After"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "After"
        assert body["industry"] == "Gaming"
        assert body["mission"] == "Play more"
        assert body["topics_to_avoid"] == ["Spoiler"]

    def test_api_rejects_unknown_field(self, monkeypatch, tmp_path):
        client, storage = self._client(monkeypatch, tmp_path)
        created = storage.create_brand_profile({"name": "Strict"})
        resp = client.put(f"/api/studio/brand-profiles/{created['id']}",
                          json={"made_up": 1})
        assert resp.status_code == 422
        assert "Unknown brand profile field" in resp.json()["detail"]
        # Failed update must not corrupt the stored profile.
        assert storage.get_brand_profile(created["id"])["name"] == "Strict"

    def test_api_duplicate_and_delete_with_new_fields(self, monkeypatch, tmp_path):
        client, storage = self._client(monkeypatch, tmp_path)
        created = storage.create_brand_profile({"name": "Dup Source", "visual_style": "mono"})
        resp = client.post(f"/api/studio/brand-profiles/{created['id']}/duplicate", json={})
        assert resp.status_code == 200
        dup = resp.json()
        assert dup["visual_style"] == "mono"
        assert dup["name"].endswith("(Copy)")
        resp = client.delete(f"/api/studio/brand-profiles/{dup['id']}")
        assert resp.status_code == 200
        assert storage.get_brand_profile(dup["id"]) is None
        assert storage.get_brand_profile(created["id"]) is not None
