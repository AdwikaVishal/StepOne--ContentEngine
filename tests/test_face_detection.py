"""Tests for FaceDetector — size weighting and backward compatibility."""
import pytest


@pytest.fixture(scope="module")
def detector():
    from content_engine.models.face_detection import FaceDetector
    return FaceDetector()


def test_no_faces_synthetic(detector, sharp_image_path):
    """Synthetic checkerboard has no faces."""
    count, confs = detector.detect_faces(sharp_image_path)
    assert isinstance(count, int)
    assert isinstance(confs, list)


def test_detailed_result_structure(detector, sharp_image_path):
    result = detector.detect_faces_detailed(sharp_image_path)
    assert "face_count" in result
    assert "confidences" in result
    assert "bboxes" in result
    assert "bboxes_norm" in result
    assert "weights" in result
    assert "weighted_score" in result
    assert 0.0 <= result["weighted_score"] <= 1.0


def test_face_weight_small():
    """Face covering < 2% of image should get weight ~0.4."""
    from content_engine.models.face_detection import FaceDetector
    # 10×10 face in 1000×1000 image = 0.01% area
    w = FaceDetector._face_weight([0, 0, 10, 10], 1000.0, 1000.0)
    assert w == pytest.approx(0.4, abs=0.01)


def test_face_weight_large():
    """Face covering > 10% of image should get weight 1.0."""
    from content_engine.models.face_detection import FaceDetector
    # 400×400 face in 1000×1000 image = 16% area
    w = FaceDetector._face_weight([0, 0, 400, 400], 1000.0, 1000.0)
    assert w == pytest.approx(1.0, abs=0.01)


def test_face_weight_medium():
    """Face at 5% area should interpolate between 0.4 and 1.0."""
    from content_engine.models.face_detection import FaceDetector
    # ~224×224 face in 1000×1000 = ~5% area
    w = FaceDetector._face_weight([0, 0, 224, 224], 1000.0, 1000.0)
    assert 0.4 < w < 1.0


def test_backward_compat_detect_faces(detector, sharp_image_path):
    """detect_faces() must still return (int, list) tuple."""
    result = detector.detect_faces(sharp_image_path)
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], int)
    assert isinstance(result[1], list)
