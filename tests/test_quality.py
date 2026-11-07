"""Tests for QualityAssessor."""
import pytest
import numpy as np


@pytest.fixture(scope="module")
def assessor():
    from content_engine.models.quality import QualityAssessor
    quality_assessor = QualityAssessor()
    # These tests cover deterministic blur/brightness/composite math. Keep
    # CLIP inference isolated so pytest never downloads model weights.
    quality_assessor.compute_aesthetic_score = lambda image: 0.5
    return quality_assessor


def test_sharp_image_scores_high(assessor, sharp_image_path):
    result = assessor.assess(sharp_image_path)
    assert result["blur_score"] > 0.5, "Sharp image should have high blur score"
    assert result["quality_score"] >= 0.0


def test_dark_image_scores_low_brightness(assessor, dark_image_path):
    result = assessor.assess(dark_image_path)
    assert result["brightness_score"] < 0.3, "Dark image should have low brightness score"


def test_blurry_image_scores_low_blur(assessor, blurry_image_path):
    result = assessor.assess(blurry_image_path)
    assert result["blur_score"] < 0.3, "Blurry image should have low blur score"


def test_missing_file_returns_zeros(assessor):
    result = assessor.assess("/nonexistent/path.jpg")
    assert result["quality_score"] == 0.0
    assert result["aesthetic_score"] == 0.0


def test_all_scores_in_range(assessor, sharp_image_path):
    result = assessor.assess(sharp_image_path)
    for key, val in result.items():
        assert 0.0 <= val <= 1.0, f"{key} out of range: {val}"


def test_composite_formula(assessor, sharp_image_path):
    """Composite = 0.5*blur + 0.3*brightness + 0.2*aesthetic."""
    r = assessor.assess(sharp_image_path)
    expected = r["blur_score"] * 0.5 + r["brightness_score"] * 0.3 + r["aesthetic_score"] * 0.2
    assert abs(r["quality_score"] - expected) < 0.001
