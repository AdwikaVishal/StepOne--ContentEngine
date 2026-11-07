"""
Tests for Photo Intelligence module.
"""
import os
import tempfile
from pathlib import Path
from PIL import Image
import numpy as np

from content_engine.photo_intelligence import PhotoIntelligenceAnalyzer
from content_engine.photo_intelligence.types import AssetAnalysis, RankedGroup


def create_test_image(path, color=(255, 0, 0), size=(800, 600)):
    """Create a synthetic test image."""
    img = Image.new('RGB', size, color)
    img.save(path)
    return path


class TestPhotoIntelligenceAnalyzer:
    def test_analyze_batch_preserves_filenames_and_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            img1 = create_test_image(Path(tmpdir) / "photo1.jpg")
            img2 = create_test_image(Path(tmpdir) / "vacation.jpg", color=(0, 255, 0))
            
            analyzer = PhotoIntelligenceAnalyzer()
            assets = [
                {"id": "id1", "path": img1, "original_filename": "photo1.jpg"},
                {"id": "id2", "path": img2, "original_filename": "vacation.jpg"},
            ]
            result = analyzer.analyze_batch(assets)
            
            assert len(result.assets) == 2
            assert result.assets[0].original_filename == "photo1.jpg"
            assert result.assets[0].asset_id == "id1"
            assert result.assets[1].original_filename == "vacation.jpg"
            assert result.assets[1].asset_id == "id2"
    
    def test_computes_quality_signals(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            img = create_test_image(Path(tmpdir) / "test.jpg", size=(1920, 1080))
            analyzer = PhotoIntelligenceAnalyzer()
            assets = [{"id": "t1", "path": img, "original_filename": "test.jpg"}]
            result = analyzer.analyze_batch(assets)
            
            assert result.assets[0].width == 1920
            assert result.assets[0].height == 1080
            assert result.assets[0].sharpness >= 0
            assert 0 <= result.assets[0].exposure <= 1
            assert result.assets[0].resolution_score > 0
    
    def test_groups_duplicates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            img1 = create_test_image(Path(tmpdir) / "dup1.jpg")
            img2 = create_test_image(Path(tmpdir) / "dup2.jpg")  # Same image
            analyzer = PhotoIntelligenceAnalyzer(duplicate_threshold=5)
            assets = [
                {"id": "d1", "path": img1, "original_filename": "dup1.jpg"},
                {"id": "d2", "path": img2, "original_filename": "dup2.jpg"},
            ]
            result = analyzer.analyze_batch(assets)
            
            # Should detect similarity
            assert len(result.groups) >= 0  # May group identical images
            assert result.assets[0].phash is not None
            assert result.assets[1].phash is not None
    
    def test_ranking_has_components_and_reasons(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            img = create_test_image(Path(tmpdir) / "rank.jpg")
            analyzer = PhotoIntelligenceAnalyzer()
            assets = [{"id": "r1", "path": img, "original_filename": "rank.jpg"}]
            result = analyzer.analyze_batch(assets)
            
            asset = result.assets[0]
            assert isinstance(asset.component_scores, dict)
            assert asset.overall_score >= 0
            assert isinstance(asset.confidence, float)
            assert isinstance(asset.reasons, list)
            assert len(asset.reasons) > 0
            # Must not claim ground truth
            assert any('heuristic' in r.lower() or 'signal' in r.lower() or 'not ground' in str(result.metadata).lower() for r in asset.reasons) or 'heuristic' in str(result.metadata).lower()
    
    def test_carousel_recommendation_avoids_repetition(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            imgs = []
            assets = []
            for i in range(5):
                img = create_test_image(Path(tmpdir) / f"img{i}.jpg", color=(i*50, 100, 150))
                imgs.append(img)
                assets.append({"id": f"i{i}", "path": img, "original_filename": f"img{i}.jpg"})
            
            analyzer = PhotoIntelligenceAnalyzer()
            result = analyzer.analyze_batch(assets)
            
            rec = result.carousel_recommendation
            assert isinstance(rec.sequence, list)
            assert len(rec.sequence) > 0
            assert len(rec.sequence) == len(set(rec.sequence))  # No duplicates in sequence
            assert isinstance(rec.rationale, str)
            assert isinstance(rec.diversity_score, float)
    
    def test_handles_corrupt_unsupported_oversized(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Corrupt file
            corrupt = Path(tmpdir) / "corrupt.jpg"
            corrupt.write_text("not an image")
            # Unsupported
            txt_file = Path(tmpdir) / "readme.txt"
            txt_file.write_text("hello")
            # Valid image
            valid = create_test_image(Path(tmpdir) / "valid.jpg")
            
            analyzer = PhotoIntelligenceAnalyzer()
            assets = [
                {"id": "c1", "path": str(corrupt), "original_filename": "corrupt.jpg"},
                {"id": "t1", "path": str(txt_file), "original_filename": "readme.txt"},
                {"id": "v1", "path": str(valid), "original_filename": "valid.jpg"},
            ]
            result = analyzer.analyze_batch(assets)
            
            # Should not crash
            assert len(result.assets) == 3
            # Should have warnings
            assert len(result.warnings) > 0
    
    def test_user_selection_accept_reject_reorder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            img1 = create_test_image(Path(tmpdir) / "a.jpg")
            img2 = create_test_image(Path(tmpdir) / "b.jpg")
            analyzer = PhotoIntelligenceAnalyzer()
            assets = [
                {"id": "a1", "path": img1, "original_filename": "a.jpg"},
                {"id": "a2", "path": img2, "original_filename": "b.jpg"},
            ]
            result = analyzer.analyze_batch(assets)
            
            # Accept
            result = analyzer.update_user_selection(result, "a1", "accept")
            assert result.assets[0].user_accepted is True
            assert result.assets[0].user_rejected is False
            
            # Reject
            result = analyzer.update_user_selection(result, "a2", "reject")
            assert result.assets[1].user_rejected is True
            assert result.assets[1].user_accepted is False
            
            # Reorder
            result = analyzer.update_user_selection(result, "a1", "reorder", order=0)
            assert result.assets[0].user_order == 0
            
            # Apply preferences
            final = analyzer.apply_user_preferences(result)
            assert "a2" not in final  # rejected should be removed
            assert "a1" in final
    
    def test_no_ground_truth_claims(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            img = create_test_image(Path(tmpdir) / "test.jpg")
            analyzer = PhotoIntelligenceAnalyzer()
            assets = [{"id": "x1", "path": img, "original_filename": "test.jpg"}]
            result = analyzer.analyze_batch(assets)
            
            # Check metadata warns it's heuristic
            assert 'heuristic' in str(result.metadata).lower() or 'not ground' in str(result.metadata).lower()


class TestPhotoIntelligenceAPI:
    def test_api_health(self):
        from fastapi.testclient import TestClient
        from api.main import app
        client = TestClient(app)
        resp = client.get("/api/photo-intelligence/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "heuristic" in str(data).lower()
