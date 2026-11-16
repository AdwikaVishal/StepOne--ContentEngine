"""
Tests for SmartCropper — subject-aware intelligent cropping.

Uses controlled :class:`FocalAnalysis` instances so crop behaviour is
deterministic and does not depend on model detection output. Also includes a
few integration checks against real synthetic images.
"""
import os
import tempfile

import cv2
import numpy as np
import pytest

from content_engine.composition import FocalAnalyzer, SmartCropper, FocalAnalysis
from content_engine.composition.smart_crop import (
    _iou, _to_norm_box, orig_wider,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

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


def _write_synthetic_image(path, w=800, h=600):
    """A simple synthetic image so PIL/OpenCV can open it."""
    img = np.full((h, w, 3), 60, dtype=np.uint8)
    img[h // 4: 3 * h // 4, w // 4: 3 * w // 4] = 200
    cv2.imwrite(path, img)


# ── Crop geometry / aspect-ratio tests ──────────────────────────────────────

@pytest.fixture
def cropper():
    return SmartCropper()


def test_crop_returns_exact_target_size(cropper):
    path = os.path.join(tempfile.mkdtemp(), "img.jpg")
    _write_synthetic_image(path)
    a = _make_analysis(path)
    result = cropper.compute_crop(path, 1080, 1350, analysis=a)
    # The source crop box matches the target aspect ratio...
    assert abs(result.crop_box[2] - result.crop_box[0]) / max(1, (result.crop_box[3] - result.crop_box[1])) == pytest.approx(1080 / 1350, abs=0.02)
    # ...and rendering produces the exact target size.
    img, _ = cropper.crop_image(path, 1080, 1350, analysis=a)
    assert img.size == (1080, 1350)
    assert 0.0 <= result.composition_score <= 1.0


def test_crop_box_within_source_bounds(cropper):
    path = os.path.join(tempfile.mkdtemp(), "img.jpg")
    _write_synthetic_image(path)
    a = _make_analysis(path)
    for tw, th in [(1080, 1080), (1080, 1350), (1080, 1920), (1920, 1080)]:
        r = cropper.compute_crop(path, tw, th, analysis=a)
        x1, y1, x2, y2 = r.crop_box
        assert 0 <= x1 < x2 <= a.width
        assert 0 <= y1 < y2 <= a.height
        # Crop aspect matches target
        assert abs((x2 - x1) / (y2 - y1) - tw / th) < 0.02


def test_preserves_target_ratio(cropper):
    path = os.path.join(tempfile.mkdtemp(), "img.jpg")
    _write_synthetic_image(path)
    a = _make_analysis(path)
    r = cropper.compute_crop(path, 1080, 1920, analysis=a)  # 9:16
    assert abs((r.crop_box[2] - r.crop_box[0]) / (r.crop_box[3] - r.crop_box[1]) - 9 / 16) < 0.02
    r = cropper.compute_crop(path, 1080, 1080, analysis=a)  # 1:1
    assert abs((r.crop_box[2] - r.crop_box[0]) / (r.crop_box[3] - r.crop_box[1]) - 1) < 0.02


# ── Subject-position tests ──────────────────────────────────────────────────

def _subject_visibility(result, main_subject):
    """Fraction of the (normalised) main subject inside the chosen crop."""
    cx = _to_norm_box(result.crop_box, 800, 600)
    sx1, sy1, sx2, sy2 = main_subject  # already normalised 0-1
    inter_x = max(0, min(sx2, cx[2]) - max(sx1, cx[0]))
    inter_y = max(0, min(sy2, cx[3]) - max(sy1, cx[1]))
    subj_area = (sx2 - sx1) * (sy2 - sy1)
    return (inter_x * inter_y / subj_area) if subj_area > 0 else 0.0


@pytest.mark.parametrize("name,subject", [
    ("left",  (0.00, 0.30, 0.18, 0.70)),
    ("right", (0.82, 0.30, 1.00, 0.70)),
    ("top",   (0.30, 0.00, 0.70, 0.22)),
    ("bottom",(0.30, 0.78, 0.70, 1.00)),
    ("centre",(0.40, 0.40, 0.60, 0.60)),
])
def test_subject_preserved_across_aspects(cropper, name, subject):
    """The crop should centre on the subject regardless of where it sits."""
    path = os.path.join(tempfile.mkdtemp(), "img.jpg")
    _write_synthetic_image(path)
    sx1, sy1, sx2, sy2 = subject
    a = _make_analysis(path, main_subject=subject,
                       focal_point=((sx1 + sx2) / 2, (sy1 + sy2) / 2))
    for tw, th in [(1080, 1350), (1080, 1920), (1080, 1080), (1920, 1080)]:
        r = cropper.compute_crop(path, tw, th, analysis=a)
        vis = _subject_visibility(r, subject)
        assert vis >= 0.6, f"{name}@{tw}x{th}: subject visibility {vis:.2f} too low (crop {r.crop_box})"


# ── Multiple subjects ───────────────────────────────────────────────────────

def test_two_subjects_best_effort(cropper):
    path = os.path.join(tempfile.mkdtemp(), "img.jpg")
    _write_synthetic_image(path)
    # Two subjects at opposite edges; a single crop can't fully contain both.
    a = _make_analysis(
        path,
        main_subject=(0.05, 0.30, 0.20, 0.70),
        secondary=[(0.80, 0.30, 0.95, 0.70)],
        focal_point=(0.5, 0.5),
        scene="group",
    )
    r = cropper.compute_crop(path, 1080, 1350, analysis=a)  # 4:5 of landscape -> width-limited
    # At least the main subject should be preserved.
    vis = _subject_visibility(r, (0.05, 0.30, 0.20, 0.70))
    assert vis >= 0.6
    assert r.scene_type == "group"


# ── Faces near boundary ─────────────────────────────────────────────────────

def test_face_not_cut_at_boundary(cropper):
    path = os.path.join(tempfile.mkdtemp(), "img.jpg")
    _write_synthetic_image(path)
    # A large face touching the LEFT edge of the source.
    face_bbox = (0.00, 0.25, 0.12, 0.75)
    a = _make_analysis(
        path,
        faces=[type("D", (), {
            "label": "face", "bbox": face_bbox,
            "bbox_px": (0, 150, 96, 450), "confidence": 0.95,
            "_weight": 1.0,
        })()],
        main_subject=face_bbox,
        focal_point=(0.06, 0.5),
    )
    r = cropper.compute_crop(path, 1080, 1350, analysis=a)
    cn = r.crop_box_norm
    # Face should be inside or at the crop edge, not cut through.
    assert cn[0] <= face_bbox[0] + 0.02 or cn[0] == 0.0
    assert r.faces_preserved >= 0


# ── Invalid / edge inputs ───────────────────────────────────────────────────

def test_invalid_image_returns_safe_result(cropper):
    result = cropper.compute_crop("/nonexistent/path.jpg", 1080, 1080)
    assert result.composition_score == 0.0
    assert result.crop_box == (0, 0, 1080, 1080)
    assert len(result.warnings) > 0


def test_very_small_image(cropper):
    path = os.path.join(tempfile.mkdtemp(), "tiny.jpg")
    cv2.imwrite(path, np.full((30, 30, 3), 128, dtype=np.uint8))
    a = _make_analysis(path, w=30, h=30)
    r = cropper.compute_crop(path, 1080, 1080, analysis=a)
    # Source image is square, so the crop box is the whole image (30x30),
    # then upscaled to the target 1080x1080 by crop_image.
    assert r.crop_box == (0, 0, 30, 30)
    img, _ = cropper.crop_image(path, 1080, 1080, analysis=a)
    assert img.size == (1080, 1080)
    assert r.composition_score >= 0.0


def test_manual_focal_override_no_models(cropper):
    path = os.path.join(tempfile.mkdtemp(), "img.jpg")
    _write_synthetic_image(path)
    result = cropper.compute_crop(path, 1080, 1920, manual_focal=(0.2, 0.5))
    assert result.manual_override is True
    cn = result.crop_box_norm
    # Crop should be anchored left (focal x=0.2).
    assert cn[0] < 0.5


# ── Utility function tests ──────────────────────────────────────────────────

def test_iou_and_norm_box():
    a = (0.0, 0.0, 0.5, 0.5)
    b = (0.25, 0.25, 0.75, 0.75)
    # intersection 0.0625, union 0.4375 -> 0.142857
    assert abs(_iou(a, b) - (0.0625 / 0.4375)) < 1e-6
    assert _to_norm_box((0, 0, 400, 300), 800, 600) == (0.0, 0.0, 0.5, 0.5)


def test_orig_wider():
    assert orig_wider(800, 600, 1080 / 1350) is True   # 1.33 > 0.8
    assert orig_wider(600, 800, 1080 / 1350) is False  # 0.75 < 0.8


# ── Integration: analyzer + cropper on a real synthetic image ───────────────

def test_analyzer_and_cropper_integration():
    path = os.path.join(tempfile.mkdtemp(), "img.jpg")
    _write_synthetic_image(path)
    analyzer = FocalAnalyzer()
    analysis = analyzer.analyze(path)
    assert analysis.width == 800 and analysis.height == 600
    assert analysis.orientation == "landscape"
    assert 0.0 <= analysis.confidence <= 1.0
    assert analysis.scene_type in {
        "portrait", "group", "architecture", "product",
        "event_stage", "screen", "general",
    }
    cropper = SmartCropper(analyzer=analyzer)
    r = cropper.compute_crop(path, 1080, 1920, analysis=analysis)
    # 800x600 landscape -> 9:16 crops width to 338px then resizes to 1080x1920.
    assert abs(r.crop_box[2] - r.crop_box[0]) / max(1, (r.crop_box[3] - r.crop_box[1])) == pytest.approx(1080 / 1920, abs=0.02)
    img, _ = cropper.crop_image(path, 1080, 1920, analysis=analysis)
    assert img.size == (1080, 1920)
    assert 0.0 <= r.composition_score <= 1.0
    # to_dict must be JSON-serialisable
    import json
    json.dumps(r.to_dict())
