"""Regression tests for asset selection reporting and confidence scoring.

Covers the findings of the post-E2E acceptance audit:

- ``selected_assets_count`` reflects *confidence-based ML selection*
  (``final_score >= 0.5``), not output-layout usage. The backend's
  ``collage``/``stories`` counts count assets chosen for layouts regardless of
  the confidence threshold, so they are a different metric.
- ``avg_confidence_score`` is reported separately from ``avg_quality_score``.
  High technical quality (blur/brightness/aesthetic) can coexist with low final
  confidence because face presence (30%) and concept relevance (20%) weight the
  composite score.
- The 0.5 low-confidence review threshold is preserved (not lowered).
"""
from unittest.mock import patch

from fastapi.testclient import TestClient


def _job(assets):
    return {
        "job_id": "sel-job-1",
        "status": "completed",
        "event_name": "Test Event",
        "updated_at": "2026-11-10T00:00:00",
        "assets": assets,
    }


def test_case_study_selected_counts_confidence_based_selection(client: TestClient):
    """selected_assets_count = assets reaching the 0.5 confidence threshold.

    Three assets are technically good (quality_score ~0.9) but score below 0.5
    final confidence because they lack faces/concepts; only one asset passes.
    """
    assets = [
        {"final_score": 0.28, "quality_score": 0.92, "aesthetic_score": 0.88, "face_count": 0, "scene_concepts": [], "path": "a.jpg", "id": "asset-0", "filename": "a.jpg"},
        {"final_score": 0.35, "quality_score": 0.90, "aesthetic_score": 0.85, "face_count": 0, "scene_concepts": [], "path": "b.jpg", "id": "asset-1", "filename": "b.jpg"},
        {"final_score": 0.45, "quality_score": 0.88, "aesthetic_score": 0.82, "face_count": 1, "scene_concepts": ["stage"], "path": "c.jpg", "id": "asset-2", "filename": "c.jpg"},
        {"final_score": 0.72, "quality_score": 0.85, "aesthetic_score": 0.80, "face_count": 4, "scene_concepts": ["stage", "audience"], "path": "d.jpg", "id": "asset-3", "filename": "d.jpg"},
    ]
    with patch("api.scheduler.get_job", return_value=_job(assets)):
        response = client.get("/api/jobs/sel-job-1/case-study/enriched")
    assert response.status_code == 200
    data = response.json()

    assert data["total_assets"] == 4
    # Only 1 of 4 assets reached the 0.5 confidence threshold.
    assert data["selected_assets_count"] == 1
    assert data["low_confidence_count"] == 3

    # avg_confidence_score is the mean of final_score, distinct from avg technical quality.
    assert abs(data["avg_confidence_score"] - 0.45) < 0.01
    assert data["avg_quality_score"] > 0.8  # technically good despite low confidence
    assert data["avg_confidence_score"] < 0.5


def test_confidence_threshold_not_lowered(client: TestClient):
    """The low-confidence review threshold remains 0.5 (not lowered to match counts)."""
    assets = [
        {"final_score": 0.49, "quality_score": 0.9, "aesthetic_score": 0.9, "face_count": 0, "scene_concepts": [], "path": "a.jpg", "id": "a", "filename": "a.jpg"},
        {"final_score": 0.50, "quality_score": 0.9, "aesthetic_score": 0.9, "face_count": 0, "scene_concepts": [], "path": "b.jpg", "id": "b", "filename": "b.jpg"},
    ]
    with patch("api.scheduler.get_job", return_value=_job(assets)):
        response = client.get("/api/jobs/sel-job-2/case-study/enriched")
    assert response.status_code == 200
    data = response.json()

    # 0.49 < 0.5 -> rejected; 0.50 >= 0.5 -> selected. Threshold unchanged.
    assert data["selected_assets_count"] == 1
    assert data["low_confidence_count"] == 1


def test_case_study_reports_avg_confidence_score(client: TestClient):
    """The enriched case study exposes avg_confidence_score (Task 2 label fix)."""
    assets = [
        {"final_score": 0.6, "quality_score": 0.8, "aesthetic_score": 0.7, "face_count": 1, "scene_concepts": ["stage"], "path": "a.jpg", "id": "a", "filename": "a.jpg"},
        {"final_score": 0.8, "quality_score": 0.9, "aesthetic_score": 0.8, "face_count": 2, "scene_concepts": ["stage", "audience"], "path": "b.jpg", "id": "b", "filename": "b.jpg"},
    ]
    with patch("api.scheduler.get_job", return_value=_job(assets)):
        response = client.get("/api/jobs/sel-job-3/case-study/enriched")
    assert response.status_code == 200
    data = response.json()
    assert "avg_confidence_score" in data
    assert abs(data["avg_confidence_score"] - 0.7) < 0.01
    assert data["selected_assets_count"] == 2
