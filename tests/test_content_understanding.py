"""
Tests for ContentUnderstander — concept matching, weights, graceful degradation.
These tests mock Florence-2 to avoid loading the full model in CI.
"""

import pytest
from unittest.mock import MagicMock, patch
from content_engine.models.content_understanding import ContentUnderstander, DEFAULT_EVENT_CONCEPTS


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def understander_no_model():
    """
    ContentUnderstander with Florence-2 mocked out.
    Only tests the concept scoring logic, not the vision model.
    """
    with patch("transformers.AutoModelForCausalLM.from_pretrained") as mock_model, \
         patch("transformers.AutoProcessor.from_pretrained") as mock_proc:
        mock_model.return_value = MagicMock()
        mock_proc.return_value = MagicMock()
        cu = ContentUnderstander()
    return cu


# ── Concept scoring tests ─────────────────────────────────────────────────────

def test_empty_labels_returns_zeros(understander_no_model):
    """No detected labels → all concept scores should be 0."""
    scores = understander_no_model._score_concepts([])
    assert all(v == 0.0 for v in scores.values())
    assert set(scores.keys()) == set(DEFAULT_EVENT_CONCEPTS)


def test_scores_in_range(understander_no_model):
    """All scores must be in [0, 1]."""
    scores = understander_no_model._score_concepts(["person", "microphone", "stage"])
    for concept, score in scores.items():
        assert 0.0 <= score <= 1.0, f"{concept} score out of range: {score}"


def test_concept_weights_applied(understander_no_model):
    """Higher weight should increase score for matching concept."""
    labels = ["award", "trophy"]
    scores_default = understander_no_model._score_concepts(labels)
    scores_weighted = understander_no_model._score_concepts(
        labels, concept_weights={"award": 2.0}
    )
    # Award score with weight 2.0 should be >= default (capped at 1.0)
    assert scores_weighted.get("award", 0) >= scores_default.get("award", 0)


def test_concept_weights_cap_at_one(understander_no_model):
    """Weighted scores must never exceed 1.0."""
    labels = ["keynote", "speech", "stage"]
    scores = understander_no_model._score_concepts(
        labels, concept_weights={"keynote": 10.0}
    )
    assert scores.get("keynote", 0) <= 1.0


def test_understand_image_missing_file(understander_no_model):
    """Missing file should return empty result, not raise."""
    result = understander_no_model.understand_image("/nonexistent/path.jpg")
    assert result["scene_concepts"] == []
    assert result["concept_match_score"] == 0.0
    assert result["relevance_scores"] == {}


def test_understand_image_returns_required_keys(understander_no_model, sharp_image_path):
    """understand_image must always return the three required keys."""
    # Mock _run_object_detection to avoid loading Florence-2
    understander_no_model._run_object_detection = MagicMock(return_value=["person", "microphone"])
    result = understander_no_model.understand_image(sharp_image_path)
    assert "scene_concepts" in result
    assert "relevance_scores" in result
    assert "concept_match_score" in result


def test_understand_image_returns_required_keys(understander_no_model, sharp_image_path):
    """understand_image must always return the three required keys."""
    # Mock _run_object_detection to avoid loading Florence-2
    understander_no_model._run_object_detection = MagicMock(return_value=["person", "microphone"])
    result = understander_no_model.understand_image(sharp_image_path)
    assert "scene_concepts" in result
    assert "relevance_scores" in result
    assert "concept_match_score" in result


def test_concept_match_score_none_cloud_mode(understander_no_model):
    """
    cloud_testing mode returns concept_match_score=None from the provider.
    ContentUnderstander must preserve None (not coerce to 0.0) so downstream
    scoring treats it as 'no measurement' rather than 'zero similarity'.
    """
    import os
    from content_engine.pipeline import ContentEngine

    original_mode = os.environ.get("AI_EXECUTION_MODE")
    os.environ["AI_EXECUTION_MODE"] = "cloud_testing"

    try:
        # Mock the vision provider to return None concept_match_score
        understander_no_model._vision_provider = MagicMock()
        understander_no_model._vision_provider.understand_image.return_value = {
            "scene_concepts": ["person"],
            "relevance_scores": {},
            "concept_match_score": None,
            "semantic_description": "A person on stage",
            "provider": "groq",
        }

        result = understander_no_model.understand_image("/fake/path.jpg")
        assert result["concept_match_score"] is None, "Cloud mode must return None, not 0.0"
        assert result["relevance_scores"] == {}
        assert result["scene_concepts"] == ["person"]
    finally:
        if original_mode is None:
            os.environ.pop("AI_EXECUTION_MODE", None)
        else:
            os.environ["AI_EXECUTION_MODE"] = original_mode


def test_default_concepts_list():
    """DEFAULT_EVENT_CONCEPTS must have exactly 15 entries."""
    assert len(DEFAULT_EVENT_CONCEPTS) == 15


def test_custom_event_concepts():
    """ContentUnderstander should accept custom concept list."""
    with patch("transformers.AutoModelForCausalLM.from_pretrained") as m1, \
         patch("transformers.AutoProcessor.from_pretrained") as m2:
        m1.return_value = MagicMock()
        m2.return_value = MagicMock()
        custom = ["product demo", "launch event", "press conference"]
        cu = ContentUnderstander(event_concepts=custom)
    assert cu.event_concepts == custom


def test_load_default_weights():
    """Default weights JSON should load without error."""
    weights = ContentUnderstander._load_default_weights()
    # Should return a dict (may be empty if file not found, but not raise)
    assert isinstance(weights, dict)
