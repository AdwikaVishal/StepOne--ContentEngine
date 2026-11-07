"""
Tests for Brand Profiles functionality.
"""
import os
import tempfile
from pathlib import Path
import pytest

from content_engine.studio import StudioStorage


class TestBrandProfilesPersistence:
    def test_create_brand_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = StudioStorage(base_dir=Path(tmpdir))
            profile = storage.create_brand_profile({
                "name": "Test Brand",
                "description": "A test brand",
                "tone_of_voice": "friendly"
            })
            assert profile["id"]
            assert profile["name"] == "Test Brand"
            assert profile["tone_of_voice"] == "friendly"
            assert storage.get_brand_profile(profile["id"]) is not None
    
    def test_update_brand_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = StudioStorage(base_dir=Path(tmpdir))
            profile = storage.create_brand_profile({"name": "Original"})
            profile["name"] = "Updated"
            profile["tone_of_voice"] = "bold"
            updated = storage.save_brand_profile(profile)
            assert updated["name"] == "Updated"
            retrieved = storage.get_brand_profile(profile["id"])
            assert retrieved["tone_of_voice"] == "bold"
    
    def test_list_brand_profiles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = StudioStorage(base_dir=Path(tmpdir))
            p1 = storage.create_brand_profile({"name": "Brand1"})
            p2 = storage.create_brand_profile({"name": "Brand2"})
            profiles = storage.list_brand_profiles()
            assert len(profiles) == 2
    
    def test_duplicate_brand_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = StudioStorage(base_dir=Path(tmpdir))
            original = storage.create_brand_profile({
                "name": "Original",
                "tone_of_voice": "professional",
                "preferred_cta": "Learn more"
            })
            dup = storage.duplicate_brand_profile(original["id"], "Copy Brand")
            assert dup is not None
            assert dup["id"] != original["id"]
            assert dup["name"] == "Copy Brand"
            assert dup["tone_of_voice"] == "professional"
            assert dup["preferred_cta"] == "Learn more"
    
    def test_delete_brand_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = StudioStorage(base_dir=Path(tmpdir))
            profile = storage.create_brand_profile({"name": "ToDelete"})
            pid = profile["id"]
            assert storage.get_brand_profile(pid) is not None
            ok = storage.delete_brand_profile(pid)
            assert ok is True
            assert storage.get_brand_profile(pid) is None
    
    def test_delete_nonexistent_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = StudioStorage(base_dir=Path(tmpdir))
            ok = storage.delete_brand_profile("nonexistent")
            assert ok is False
    
    def test_brand_profile_isolation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = StudioStorage(base_dir=Path(tmpdir))
            p1 = storage.create_brand_profile({"name": "Brand1", "brand_colors": ["#FF0000"]})
            p2 = storage.create_brand_profile({"name": "Brand2", "brand_colors": ["#0000FF"]})
            assert storage.get_brand_profile(p1["id"])["brand_colors"] == ["#FF0000"]
            assert storage.get_brand_profile(p2["id"])["brand_colors"] == ["#0000FF"]
    
    def test_project_brand_profile_linking(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = StudioStorage(base_dir=Path(tmpdir))
            project = storage.create_project(name="Test")
            profile = storage.create_brand_profile({"name": "MyBrand"})
            project["brand_profile_id"] = profile["id"]
            storage.save_project(project)
            loaded = storage.get_project(project["id"])
            assert loaded["brand_profile_id"] == profile["id"]
    
    def test_brand_assets_isolation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = StudioStorage(base_dir=Path(tmpdir))
            p1 = storage.create_brand_profile({"name": "Brand1"})
            p2 = storage.create_brand_profile({"name": "Brand2"})
            path1 = storage.save_brand_asset(p1["id"], "logo.png", b"fake1")
            path2 = storage.save_brand_asset(p2["id"], "logo.png", b"fake2")
            assert Path(path1).parent.name == p1["id"]
            assert Path(path2).parent.name == p2["id"]
            assert path1 != path2
            with open(path1, 'rb') as f:
                assert f.read() == b"fake1"

    def test_brand_profile_validation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = StudioStorage(base_dir=Path(tmpdir))
            with pytest.raises(ValueError, match="required"):
                storage.create_brand_profile({"name": "   "})
            with pytest.raises(ValueError, match="six-digit hex"):
                storage.create_brand_profile({"name": "Test", "brand_colors": ["red"]})
            with pytest.raises(ValueError, match="must be a list"):
                storage.create_brand_profile({"name": "Test", "fonts": "Inter"})

    def test_duplicate_brand_assets_are_copied_and_isolated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = StudioStorage(base_dir=Path(tmpdir))
            original = storage.create_brand_profile({"name": "Brand"})
            original_asset = Path(storage.save_brand_asset(original["id"], "logo.png", b"logo"))
            original["logo_path"] = str(original_asset)
            storage.save_brand_profile(original)
            duplicate = storage.duplicate_brand_profile(original["id"])
            duplicate_asset = Path(duplicate["logo_path"])
            assert duplicate_asset != original_asset
            assert duplicate_asset.parent.name == duplicate["id"]
            duplicate_asset.write_bytes(b"copy")
            assert original_asset.read_bytes() == b"logo"

    def test_profile_edit_does_not_mutate_existing_saved_post(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = StudioStorage(base_dir=Path(tmpdir))
            profile = storage.create_brand_profile({"name": "Before"})
            project = storage.create_project(name="Post")
            project["brand_profile_id"] = profile["id"]
            project["content"] = {"platform_variants": {"instagram": {"caption": "Already saved"}}}
            storage.save_project(project)
            profile["name"] = "After"
            storage.save_brand_profile(profile)
            assert storage.get_project(project["id"])["content"]["platform_variants"]["instagram"]["caption"] == "Already saved"

    def test_project_profile_switching(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = StudioStorage(base_dir=Path(tmpdir))
            first = storage.create_brand_profile({"name": "First"})
            second = storage.create_brand_profile({"name": "Second"})
            project = storage.create_project(name="Post")
            project["brand_profile_id"] = first["id"]
            storage.save_project(project)
            loaded = storage.get_project(project["id"])
            loaded["brand_profile_id"] = second["id"]
            storage.save_project(loaded)
            active = storage.get_brand_profile(storage.get_project(project["id"])["brand_profile_id"])
            assert active["name"] == "Second"
            assert storage.get_brand_profile("deleted-or-missing") is None

    def test_profile_switch_api_and_invalid_profile(self, monkeypatch):
        import content_engine.studio as studio
        monkeypatch.setattr(studio, "StudioContentOrchestrator", lambda: None)
        from api import studio_routes
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        app = FastAPI()
        app.include_router(studio_routes.router)
        client = TestClient(app)
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = StudioStorage(base_dir=Path(tmpdir))
            monkeypatch.setattr(studio_routes, "storage", storage)
            first = storage.create_brand_profile({"name": "First"})
            second = storage.create_brand_profile({"name": "Second"})
            project = storage.create_project(name="Existing post")
            project["content"] = {"saved": "keep"}
            storage.save_project(project)
            response = client.post(f"/api/studio/projects/{project['id']}/brand-profile", json={"brand_profile_id": first["id"]})
            assert response.status_code == 200
            response = client.post(f"/api/studio/projects/{project['id']}/brand-profile", json={"brand_profile_id": second["id"]})
            assert response.status_code == 200
            response = client.post(f"/api/studio/projects/{project['id']}/brand-profile", json={"brand_profile_id": "missing"})
            assert response.status_code == 404
            assert storage.get_project(project["id"])["content"] == {"saved": "keep"}

    def test_brand_asset_paths_cannot_cross_profiles(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = StudioStorage(base_dir=Path(tmpdir))
            profile = storage.create_brand_profile({"name": "Brand"})
            profile["logo_path"] = str(Path(tmpdir) / "outside.png")
            with pytest.raises(ValueError, match="inside their profile"):
                storage.save_brand_profile(profile)
    
    def test_prompt_construction_with_brand_rules(self):
        from content_engine.studio.content_orchestrator import StudioContentOrchestrator
        orch = StudioContentOrchestrator.__new__(StudioContentOrchestrator)
        brand = {
            "name": "TestBrand",
            "campaign_objectives": "Build awareness",
            "tone_of_voice": "bold",
            "target_audience": "Developers",
            "preferred_vocabulary": ["innovate", "build"],
            "avoid_words_claims": ["best", "#1"],
            "preferred_cta": "Try it now",
            "hashtag_guidance": "Use tech hashtags"
        }
        section = orch._build_brand_prompt_section(brand)
        assert "TestBrand" in section
        assert "bold" in section
        assert "Developers" in section
        assert "innovate" in section
        assert "AVOID" in section
        assert "Try it now" in section
        assert "#1" in section
        assert "campaign" in section.lower() or "objectives" in section.lower()

    def test_prompt_and_output_brand_rule_checks(self):
        from content_engine.studio.content_orchestrator import StudioContentOrchestrator
        orch = StudioContentOrchestrator.__new__(StudioContentOrchestrator)
        brand = {"id": "profile-1", "name": "North", "description": "Outdoor gear", "campaign_objectives": "Drive trials", "preferred_vocabulary": ["trail"], "avoid_words_claims": ["best"]}
        prompt = orch._build_brand_prompt_section(brand)
        assert "Outdoor gear" in prompt and "Drive trials" in prompt
        check = orch._check_brand_rules({"platform_variants": {"instagram": {"caption": "The best gear"}}}, brand)
        assert not check["passed"]
        assert {v["rule"] for v in check["violations"]} == {"avoid_words_claims", "preferred_vocabulary_missing"}
        hashtag_check = orch._check_brand_rules(
            {"platform_variants": {"instagram": {"caption": "A trail update #one #two"}}},
            {"id": "profile-2", "hashtag_guidance": "Use 3-5 hashtags"},
        )
        assert any(v["rule"] == "hashtag_count" for v in hashtag_check["violations"])
