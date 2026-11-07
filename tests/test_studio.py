"""
Tests for studio functionality.
"""
import os
import tempfile
from pathlib import Path

from content_engine.studio import StudioStorage, StudioIngestion, StudioIntelligence, StudioContentOrchestrator


def test_studio_storage_create_project():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StudioStorage(base_dir=Path(tmpdir))
        project = storage.create_project(name="Test", brief="Test brief", platforms=["linkedin"])
        assert project["id"]
        assert project["name"] == "Test"
        assert project["platforms"] == ["linkedin"]
        assert storage.get_project(project["id"]) is not None


def test_studio_storage_draft():
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = StudioStorage(base_dir=Path(tmpdir))
        project = storage.create_project(name="Test")
        draft = storage.save_draft(project["id"], {"test": True})
        assert draft["draft_id"]
        assert storage.get_draft(draft["draft_id"]) is not None


def test_studio_ingestion_validate():
    ingestion = StudioIngestion()
    ok, _ = ingestion.validate_file("photo.jpg")
    assert ok
    ok, _ = ingestion.validate_file("video.mp4")
    assert ok
    ok, _ = ingestion.validate_file("bad.txt")
    assert not ok


def test_studio_caption_results_match_asset_ids_and_keep_partial_failures(tmp_path):
    from PIL import Image

    image_paths = []
    for name, color in (("one.jpg", "red"), ("two.jpg", "blue")):
        path = tmp_path / name
        Image.new("RGB", (16, 16), color=color).save(path)
        image_paths.append(str(path))

    class PartialCaptioner:
        model_identifier = "mock-blip"

        def caption_many(self, entries):
            assert [item["asset_id"] for item in entries] == ["asset-1", "asset-2"]
            return [
                {"asset_id": "asset-2", "caption": None, "caption_status": "error",
                 "caption_model": self.model_identifier, "caption_error": "one image failed"},
                {"asset_id": "asset-1", "caption": "a person at a table", "caption_status": "completed",
                 "caption_model": self.model_identifier, "caption_error": None},
            ]

    intelligence = StudioIntelligence()
    intelligence._get_pipeline = lambda: None
    intelligence._get_blip = lambda: PartialCaptioner()
    result = intelligence.analyze_assets([
        {"id": "asset-1", "path": image_paths[0], "asset_type": "image"},
        {"id": "asset-2", "path": image_paths[1], "asset_type": "image"},
    ], brief="people networking")

    by_id = {item["asset_id"]: item for item in result["analyzed"]}
    assert by_id["asset-1"]["caption"] == "a person at a table"
    assert by_id["asset-2"]["caption_status"] == "error"
    assert by_id["asset-2"]["caption_error"] == "one image failed"


def test_studio_selection_keeps_highest_ranked_duplicate():
    intelligence = StudioIntelligence()
    analyzed = [
        {"asset_id": "duplicate-low", "duplicates": ["duplicate-high"],
         "relevance": 0.1, "quality": {"final_score": 0.1}, "sharpness": 10},
        {"asset_id": "duplicate-high", "duplicates": ["duplicate-low"],
         "relevance": 0.9, "quality": {"final_score": 0.9}, "sharpness": 900},
        {"asset_id": "independent", "duplicates": [],
         "relevance": 0.5, "quality": {"final_score": 0.5}, "sharpness": 500},
    ]

    result = intelligence.select_best_images(analyzed, max_count=2)
    assert [item["asset_id"] for item in result["selected"]] == [
        "duplicate-high", "independent",
    ]


def test_studio_content_orchestrator_with_mocked_mlx():
    orch = StudioContentOrchestrator()

    class MockProvider:
        name = "mock_mlx"
        requires_api_key = False

        def generate(self, system, user, max_tokens, temperature):
            return "Mocked local model copy for the test event. #Test"

        def is_available(self):
            return True

    orch.copy_gen._provider = MockProvider()
    result = orch.generate_post(
        event_name="Test Event",
        selected_assets=[],
        brief="A great event",
        platforms=["linkedin", "instagram"],
    )
    assert result["narrative"]
    assert "linkedin" in result["platform_variants"]
    assert "instagram" in result["platform_variants"]
    assert result["platform_variants"]["linkedin"]["caption"].startswith("Mocked")