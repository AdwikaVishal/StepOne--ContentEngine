"""
Face Detector — YOLOv11n with Size-Aware Weighting

Item 13: Weighted face scoring (foreground faces > background crowds)
  - Faces covering < 2% of image area → weight 0.4 (background)
  - Faces covering > 10% of image area → weight 1.0 (foreground)
  - Linear interpolation between

Returns:
  - detect_faces(): (face_count, confidences) — backward compatible
  - detect_faces_detailed(): full dict with bboxes, weights, weighted_score
"""

import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Optional

try:
    from config import settings as _cfg
    _DEFAULT_FACE_CONF = _cfg.face_confidence_threshold
    _SIZE_WEIGHT_THRESH = _cfg.face_size_weight_threshold
except Exception:
    _DEFAULT_FACE_CONF = 0.35
    _SIZE_WEIGHT_THRESH = 0.05

# Size-weight thresholds (item 13)
_SIZE_WEIGHT_MIN_PCT = 0.02   # <2% of image → 0.4 weight
_SIZE_WEIGHT_MAX_PCT = 0.10   # >10% of image → 1.0 weight


class FaceDetector:
    """
    YOLOv11n-based face detection with size-aware scoring.

    Item 13: Prevents background crowds from outscoring foreground portraits.
    A face covering 2% of a 1000×1000 image (20×20 px) is weighted 0.4.
    A face covering 10% (100×100 px) is weighted 1.0.
    """

    def __init__(self, confidence: float = _DEFAULT_FACE_CONF):
        self._model     = None
        self._confidence = confidence

    # ── Model lazy-load ─────────────────────────────────────────────────────────

    @property
    def model(self):
        if self._model is None:
            from ultralytics import YOLO
            from huggingface_hub import hf_hub_download

            model_path = hf_hub_download(
                repo_id="AdamCodd/YOLOv11n-face-detection",
                filename="model.pt",
            )
            self._model = YOLO(model_path)
        return self._model

    # ── Item 13: Size-aware weighting ────────────────────────────────────────────

    @staticmethod
    def _face_weight(bbox: List, img_w: float, img_h: float) -> float:
        """
        Compute face weight based on area percentage.

        Args:
            bbox: [x1, y1, x2, y2] in pixels
            img_w, img_h: image dimensions in pixels

        Returns:
            float: weight between 0.4 and 1.0
        """
        x1, y1, x2, y2 = bbox
        face_area   = (x2 - x1) * (y2 - y1)
        image_area  = img_w * img_h
        area_pct    = face_area / image_area if image_area > 0 else 0.0

        if area_pct >= _SIZE_WEIGHT_MAX_PCT:
            return 1.0
        if area_pct <= _SIZE_WEIGHT_MIN_PCT:
            return 0.4

        # Linear interpolation between 0.4 and 1.0
        t = (area_pct - _SIZE_WEIGHT_MIN_PCT) / (_SIZE_WEIGHT_MAX_PCT - _SIZE_WEIGHT_MIN_PCT)
        return 0.4 + 0.6 * t

    # ── Detection ─────────────────────────────────────────────────────────────────

    def detect_faces(self, image_path: str) -> Tuple[int, List[float]]:
        """
        Backward-compatible detection — returns (count, confidences).

        Returns:
            (face_count, confidences)
        """
        result = self.detect_faces_detailed(image_path)
        return result["face_count"], result["confidences"]

    def detect_faces_detailed(self, image_path: str) -> Dict:
        """
        Full detection with size-aware weighted scoring.

        Returns:
            {
                "face_count": int,
                "confidences": [float],
                "bboxes": [[x1, y1, x2, y2], ...],
                "bboxes_norm": [[0–1, 0–1, 0–1, 0–1], ...],
                "weights": [float],
                "weighted_score": float (0–1)
            }
        """
        import cv2

        img = cv2.imread(str(image_path))
        if img is None:
            return {
                "face_count": 0, "confidences": [],
                "bboxes": [], "bboxes_norm": [],
                "weights": [], "weighted_score": 0.0,
            }

        img_h, img_w = img.shape[:2]

        # Run YOLOv11n — pass device explicitly so MPS is used when available
        from content_engine.utils.mps_safe import MPS_DEVICE, empty_cache
        try:
            results = self.model.predict(
                image_path, conf=self._confidence, verbose=False, device=MPS_DEVICE
            )
        except Exception:
            # MPS failure — fall back to CPU silently
            results = self.model.predict(
                image_path, conf=self._confidence, verbose=False, device="cpu"
            )
        finally:
            empty_cache()

        if results[0].boxes is None or len(results[0].boxes) == 0:
            return {
                "face_count": 0, "confidences": [],
                "bboxes": [], "bboxes_norm": [],
                "weights": [], "weighted_score": 0.0,
            }

        boxes   = results[0].boxes
        bboxes  = boxes.xyxy.cpu().numpy().tolist()
        confs   = boxes.conf.cpu().tolist()

        # Compute size-aware weights
        weights = [self._face_weight(b, img_w, img_h) for b in bboxes]

        # Weighted score: sum(confidence × weight) / max_faces
        max_faces       = 10
        weighted_scores = [c * w for c, w in zip(confs, weights)]
        weighted_score  = min(1.0, sum(weighted_scores) / max_faces)

        # Normalize bboxes to 0–1
        bboxes_norm = [
            [b[0]/img_w, b[1]/img_h, b[2]/img_w, b[3]/img_h]
            for b in bboxes
        ]

        return {
            "face_count":   len(bboxes),
            "confidences":  confs,
            "bboxes":       bboxes,
            "bboxes_norm":  bboxes_norm,
            "weights":      weights,
            "weighted_score": round(weighted_score, 4),
        }