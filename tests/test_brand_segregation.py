"""
Tests for brand segregation functionality.
"""

import pytest
from unittest.mock import patch, MagicMock

from content_engine.brand_segregator import (
    BrandSegregator,
    BrandReference,
    AssetClassification,
)


class TestBrandReference:
    """Tests for BrandReference dataclass."""

    def test_brand_reference_creation(self):
        """Test BrandReference can be created with required fields."""
        brand = BrandReference(
            brand_id="brand_a",
            brand_name="Brand A",
            render_paths=["/path/to/render1.jpg", "/path/to/render2.jpg"],
        )
        assert brand.brand_id == "brand_a"
        assert brand.brand_name == "Brand A"
        assert len(brand.render_paths) == 2

    def test_brand_reference_with_embedding(self):
        """Test BrandReference can store pre-computed embedding."""
        mock_embedding = MagicMock()
        brand = BrandReference(
            brand_id="brand_b",
            brand_name="Brand B",
            render_paths=["/path/to/render.jpg"],
            embedding=mock_embedding,
        )
        assert brand.embedding is mock_embedding


class TestAssetClassification:
    """Tests for AssetClassification dataclass."""

    def test_classification_with_brand(self):
        """Test classification with assigned brand."""
        classification = AssetClassification(
            path="/path/to/image.jpg",
            brand_id="brand_a",
            confidence=0.75,
            similarity_scores={"brand_a": 0.75, "brand_b": 0.55},
        )
        assert classification.brand_id == "brand_a"
        assert classification.confidence == 0.75
        assert classification.similarity_scores["brand_a"] == 0.75

    def test_classification_unmatched(self):
        """Test classification when no brand matches threshold."""
        classification = AssetClassification(
            path="/path/to/image.jpg",
            brand_id=None,
            confidence=0.0,
            similarity_scores={"brand_a": 0.45, "brand_b": 0.42},
        )
        assert classification.brand_id is None
        assert classification.confidence == 0.0


class TestBrandSegregator:
    """Tests for BrandSegregator class."""

    def test_init_with_valid_brands(self):
        """Test initialization with valid brand definitions."""
        brands = [
            ("brand_a", "Brand A", ["/path/to/render1.jpg"]),
            ("brand_b", "Brand B", ["/path/to/render2.jpg"]),
        ]
        
        with patch('content_engine.brand_segregator.Path.exists', return_value=True):
            segregator = BrandSegregator(brands=brands)
        
        assert len(segregator.brands) == 2
        assert segregator.brands[0].brand_id == "brand_a"
        assert segregator.brands[1].brand_id == "brand_b"

    def test_init_ignores_missing_renders(self):
        """Test initialization ignores brands with no valid render paths."""
        brands = [
            ("brand_a", "Brand A", ["/path/to/render1.jpg"]),
            ("brand_b", "Brand B", []),  # Empty - should be ignored
            ("brand_c", "Brand C", ["/nonexistent/path.jpg"]),  # Doesn't exist
        ]
        
        with patch('content_engine.brand_segregator.Path.exists', side_effect=[True, False]):
            segregator = BrandSegregator(brands=brands)
        
        # Only brand_a has a valid path
        assert len(segregator.brands) == 1
        assert segregator.brands[0].brand_id == "brand_a"

    def test_init_with_custom_threshold(self):
        """Test initialization with custom similarity threshold."""
        brands = [
            ("brand_a", "Brand A", ["/path/to/render.jpg"]),
        ]
        
        with patch('content_engine.brand_segregator.Path.exists', return_value=True):
            segregator = BrandSegregator(
                brands=brands,
                similarity_threshold=0.75,
            )
        
        assert segregator.similarity_threshold == 0.75

    def test_get_selection_logic_returns_documentation(self):
        """Test get_selection_logic returns documented string."""
        brands = [
            ("brand_a", "Brand A", ["/path/to/render.jpg"]),
        ]
        
        with patch('content_engine.brand_segregator.Path.exists', return_value=True):
            segregator = BrandSegregator(brands=brands)
        
        logic = segregator.get_selection_logic()
        
        assert "SELECTION LOGIC" in logic
        assert "Brand Reference Preparation" in logic
        assert "Asset Classification" in logic
        assert "Brand Assignment" in logic
        assert "Quality Filtering" in logic

    def test_get_selection_logic_includes_threshold(self):
        """Test selection logic documentation includes threshold value."""
        brands = [
            ("brand_a", "Brand A", ["/path/to/render.jpg"]),
        ]
        
        with patch('content_engine.brand_segregator.Path.exists', return_value=True):
            segregator = BrandSegregator(
                brands=brands,
                similarity_threshold=0.65,
            )
        
        logic = segregator.get_selection_logic()
        assert "0.65" in logic


class TestBrandSegregatorClassify:
    """Tests for BrandSegregator.classify_asset method."""

    def test_classify_without_clip_returns_unmatched(self):
        """Test classification returns unmatched when CLIP unavailable."""
        brands = [
            ("brand_a", "Brand A", ["/path/to/render.jpg"]),
        ]
        
        with patch('content_engine.brand_segregator.Path.exists', return_value=True):
            with patch('content_engine.brand_segregator._CLIP_AVAILABLE', False):
                segregator = BrandSegregator(brands=brands)
        
        result = segregator.classify_asset("/path/to/image.jpg")
        
        assert result.brand_id is None
        assert result.confidence == 0.0

    def test_classify_with_no_brands_returns_unmatched(self):
        """Test classification returns unmatched when no brands configured."""
        with patch('content_engine.brand_segregator.Path.exists', return_value=False):
            segregator = BrandSegregator(brands=[])
        
        result = segregator.classify_asset("/path/to/image.jpg")
        
        assert result.brand_id is None
        assert result.path == "/path/to/image.jpg"


class TestBrandSegregatorSegregate:
    """Tests for BrandSegregator.segregate_assets method."""

    def test_segregate_empty_list(self):
        """Test segregating empty asset list."""
        brands = [
            ("brand_a", "Brand A", ["/path/to/render.jpg"]),
        ]
        
        with patch('content_engine.brand_segregator.Path.exists', return_value=True):
            with patch('content_engine.brand_segregator._CLIP_AVAILABLE', False):
                segregator = BrandSegregator(brands=brands)
        
        result = segregator.segregate_assets([])
        
        assert "brand_a" in result
        assert "unmatched" in result
        assert len(result["brand_a"]) == 0
        assert len(result["unmatched"]) == 0

    def test_segregate_returns_brand_dict_structure(self):
        """Test segregate returns correct dictionary structure."""
        brands = [
            ("brand_a", "Brand A", ["/path/to/render.jpg"]),
            ("brand_b", "Brand B", ["/path/to/render2.jpg"]),
        ]
        
        with patch('content_engine.brand_segregator.Path.exists', return_value=True):
            with patch('content_engine.brand_segregator._CLIP_AVAILABLE', False):
                segregator = BrandSegregator(brands=brands)
        
        result = segregator.segregate_assets(["/path/to/image1.jpg"])
        
        assert isinstance(result, dict)
        assert "brand_a" in result
        assert "brand_b" in result
        assert "unmatched" in result
        assert isinstance(result["brand_a"], list)


class TestDefaultThreshold:
    """Tests for default threshold values."""

    def test_default_threshold_is_060(self):
        """Test default similarity threshold is 0.60."""
        brands = [("brand", "Brand", ["/path/to/render.jpg"])]
        
        with patch('content_engine.brand_segregator.Path.exists', return_value=True):
            segregator = BrandSegregator(brands=brands)
        
        assert segregator.DEFAULT_THRESHOLD == 0.60

    def test_min_matching_assets_value(self):
        """Test minimum matching assets constant."""
        brands = [("brand", "Brand", ["/path/to/render.jpg"])]
        
        with patch('content_engine.brand_segregator.Path.exists', return_value=True):
            segregator = BrandSegregator(brands=brands)
        
        assert segregator.MIN_MATCHING_ASSETS == 5


# Integration-style tests (mocked external dependencies)

class TestSegregatorIntegration:
    """Integration-style tests with mocked CLIP."""

    def test_multiple_assets_segregation(self):
        """Test segregating multiple assets into correct buckets."""
        brands = [
            ("brand_a", "Brand A", ["/path/to/render_a.jpg"]),
            ("brand_b", "Brand B", ["/path/to/render_b.jpg"]),
        ]
        
        with patch('content_engine.brand_segregator.Path.exists', return_value=True):
            with patch('content_engine.brand_segregator._CLIP_AVAILABLE', False):
                segregator = BrandSegregator(brands=brands)
        
        assets = [f"/path/to/image_{i}.jpg" for i in range(5)]
        result = segregator.segregate_assets(assets)
        
        assert len(result["brand_a"]) == 0
        assert len(result["brand_b"]) == 0
        assert len(result["unmatched"]) == 5

    def test_unmatched_bucket_present(self):
        """Test unmatched bucket is always present in results."""
        brands = [
            ("brand_a", "Brand A", ["/path/to/render.jpg"]),
        ]
        
        with patch('content_engine.brand_segregator.Path.exists', return_value=True):
            with patch('content_engine.brand_segregator._CLIP_AVAILABLE', False):
                segregator = BrandSegregator(brands=brands)
        
        result = segregator.segregate_assets(["/any/path.jpg"])
        
        assert "unmatched" in result
        assert isinstance(result["unmatched"], list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
