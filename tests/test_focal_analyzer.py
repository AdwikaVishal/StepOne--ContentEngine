"""
Tests for FocalAnalyzer — focal-point / subject detection analysis.

Uses controlled inputs and direct calls to internal helpers so behaviour is
deterministic, plus one integration check on a real synthetic image.
"""
import os
import tempfile

import cv2
import numpy as np
import pytest

from content_engine.composition.focal_analyzer import (
    FocalAnalyzer, FocalAnalysis, Detection,
    _norm_box, _iou, _box_area,
)


def _make_det(label="face", bbox=(0.1, 0.1, 0.3, 0.3),
              bbox_px=(80, 60, 240, 180), confidence=0.9, weight=1.0):
    d = Detection(label=label, bbox=bbox, bbox_px=bbox_px, confidence=confidence)
    d._weight = weight
    return d


def _make_analysis(image_path="x.jpg", w=800, h=600,
                   main_subject=None, secondary=None, faces=None,
                   focal_point=(0.5, 0.5), scene="general",
                   confidence=0.9):
    return FocalAnalysis(
        image_path=image_path, width=w, height=h,
        orientation=("portrait" if h > w else "landscape" if w > h else "square"),
        faces=faces or [], people=[], objects=[], salient_regions=[],
        main_subject=main_subject, secondary_subjects=secondary or [],
        focal_point=focal_point,
        focal_region=(0.0, 0.0, 1.0, 1.0) if main_subject is None else main_subject,
        scene_type=scene, scene_type_confidence=0.9, confidence=confidence,
        models_used=["test"],
    )


# ── Helper functions ─────────────────────────────────────────────────────────

def test_norm_box_clamps():
    assert _norm_box(0, 0, 100, 100, 200, 200) == (0.0, 0.0, 0.5, 0.5)
    # Negative / out-of-range values are clamped to [0, 1].
    assert _norm_box(-10, -10, 300, 300, 200, 200) == (0.0, 0.0, 1.0, 1.0)
    assert _norm_box(0, 0, 0, 0, 200, 200) == (0.0, 0.0, 0.0, 0.0)


def test_iou():
    assert _iou((0.0, 0.0, 0.5, 0.5), (0.5, 0.5, 1.0, 1.0)) == 0.0
    assert _iou((0.0, 0.0, 1.0, 1.0), (0.2, 0.2, 0.8, 0.8)) == pytest.approx(0.36)
    assert _iou((0.0, 0.0, 1.0, 1.0), (0.0, 0.0, 1.0, 1.0)) == 1.0
    assert _iou((0.0, 0.0, 0.1, 0.1), (0.9, 0.9, 1.0, 1.0)) == 0.0


def test_box_area():
    assert _box_area((0.0, 0.0, 0.5, 0.5)) == 0.25
    assert _box_area((0.0, 0.0, 0.0, 0.0)) == 0.0


# ── Analysis structure ───────────────────────────────────────────────────────

def _write_synthetic_image(path, w=800, h=600):
    img = np.full((h, w, 3), 60, dtype=np.uint8)
    img[h // 4: 3 * h // 4, w // 4: 3 * w // 4] = 200
    cv2.imwrite(path, img)


@pytest.fixture
def analyzer():
    return FocalAnalyzer()


def test_analyze_returns_valid_structure(analyzer):
    path = os.path.join(tempfile.mkdtemp(), "img.jpg")
    _write_synthetic_image(path)
    a = analyzer.analyze(path)
    assert isinstance(a, FocalAnalysis)
    assert a.width == 800 and a.height == 600
    assert a.orientation in ("landscape", "portrait", "square")
    assert isinstance(a.faces, list)
    assert isinstance(a.people, list)
    assert isinstance(a.objects, list)
    assert isinstance(a.salient_regions, list)
    assert a.main_subject is None or len(a.main_subject) == 4
    assert len(a.focal_point) == 2
    assert len(a.focal_region) == 4
    assert 0.0 <= a.confidence <= 1.0
    assert a.scene_type in {
        "portrait", "group", "architecture", "product",
        "event_stage", "screen", "general",
    }
    assert isinstance(a.models_used, list)


def test_analyze_focal_point_inside_region(analyzer):
    path = os.path.join(tempfile.mkdtemp(), "img.jpg")
    _write_synthetic_image(path)
    a = analyzer.analyze(path)
    fx, fy = a.focal_point
    rx1, ry1, rx2, ry2 = a.focal_region
    assert rx1 <= fx <= rx2
    assert ry1 <= fy <= ry2


def test_analyze_invalid_image(analyzer):
    a = analyzer.analyze("/nonexistent/path.jpg")
    assert a.width == 0 and a.height == 0
    assert a.confidence == 0.0


def test_analyze_caching(analyzer):
    path = os.path.join(tempfile.mkdtemp(), "img.jpg")
    _write_synthetic_image(path)
    a1 = analyzer.analyze(path)
    a2 = analyzer.analyze(path)
    assert a1 is a2  # same cached object
    analyzer.clear_cache()
    a3 = analyzer.analyze(path)
    assert a3 is not a1


# ── Subject / scene classification ──────────────────────────────────────────

def test_classify_group():
    fa = FocalAnalyzer()
    faces = [_make_det() for _ in range(3)]
    scene, conf = fa._classify_scene(faces, [], [], [], 800, 600)
    assert scene == "group"


def test_classify_portrait():
    fa = FocalAnalyzer()
    faces = [_make_det()]
    scene, conf = fa._classify_scene(faces, [], [], [], 800, 600)
    assert scene == "portrait"


def test_classify_general():
    fa = FocalAnalyzer()
    scene, conf = fa._classify_scene([], [], [], [], 800, 600)
    assert scene == "general"


def test_select_subjects_faces_win():
    fa = FocalAnalyzer()
    faces = [_make_det(bbox=(0.4, 0.4, 0.6, 0.6), weight=1.0)]
    main, secondary = fa._select_subjects(faces, [], [], [], 800, 600)
    assert main == (0.4, 0.4, 0.6, 0.6)


def test_select_subjects_fallback_to_centre():
    fa = FocalAnalyzer()
    main, secondary = fa._select_subjects([], [], [], [], 800, 600)
    assert main == (0.35, 0.35, 0.65, 0.65)


# ── Confidence ──────────────────────────────────────────────────────────────

def test_confidence_range():
    fa = FocalAnalyzer()
    conf = fa._compute_confidence([], [], [], None, None, 0.5)
    assert 0.0 <= conf <= 1.0


# ── FocalAnalysis dataclass ─────────────────────────────────────────────────

def test_focal_analysis_to_dict_json_serialisable():
    a = _make_analysis()
    import json
    payload = a.to_dict()
    json.dumps(payload)  # must not raise
    assert payload["width"] == 800
    assert payload["height"] == 600
    assert payload["orientation"] == "landscape"
    assert "faces" in payload and "objects" in payload


def test_focal_analysis_properties():
    a = _make_analysis(main_subject=(0.2, 0.2, 0.4, 0.4), secondary=[(0.6, 0.6, 0.8, 0.8)])
    assert a.size == (800, 600)
    assert a.face_count == 0
    assert a.subject_count == 2
