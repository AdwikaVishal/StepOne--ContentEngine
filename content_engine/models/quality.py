"""
Quality Assessor — Blur + Brightness + CLIP Aesthetic

Scoring:
  - blur_score: Laplacian variance (higher = sharper)
  - brightness_score: HSV V channel mean (ideal 0.4–0.8)
  - aesthetic_score: CLIP similarity to quality/dark prompt sets
  - quality_score: 0.5×blur + 0.3×brightness + 0.2×aesthetic

Adaptive calibration: first 20 images in a batch are used to
recalibrate blur and brightness thresholds for the event's lighting.
"""

import cv2
import numpy as np
from pathlib import Path
from typing import Dict, Optional
from dataclasses import dataclass, field

try:
    from config import settings as _cfg
    _DEFAULT_BLUR_THRESHOLD = _cfg.quality_blur_threshold
    _DEFAULT_FACE_CONF     = _cfg.face_confidence_threshold
except Exception:
    _DEFAULT_BLUR_THRESHOLD = 300.0
    _DEFAULT_FACE_CONF     = 0.35

# Calibratable thresholds (mutated by calibrate_batch)
_blur_threshold: float    = _DEFAULT_BLUR_THRESHOLD
_brightness_center: float  = 0.6     # ideal brightness midpoint
_brightness_tolerance: float = 0.2   # ±20% from center is good


@dataclass
class CalibrationResult:
    """Result of threshold calibration on a batch of images."""
    calibrated: bool
    blur_threshold: float
    brightness_center: float
    brightness_tolerance: float
    sample_size: int


def _default_weights() -> Dict[str, float]:
    """Load default concept weights from config file."""
    try:
        import json
        path = Path(__file__).parent.parent.parent / "config" / "concept_weights.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def get_blur_threshold() -> float:
    return _blur_threshold


def get_brightness_center() -> float:
    return _brightness_center


class QualityAssessor:
    """
    Assesses image quality across three dimensions:
    1. Technical sharpness (Laplacian variance)
    2. Exposure (HSV V channel)
    3. Aesthetic (CLIP semantic similarity)
    """

    def __init__(self):
        self._clip_model = None  # Lazy-loaded
        self._clip_device = "cpu"  # Will be set on first use

        # High/low quality reference embeddings (populated lazily)
        self._high_emb: Optional[np.ndarray] = None
        self._low_emb: Optional[np.ndarray] = None

    # ── CLIP lazy-load ─────────────────────────────────────────────────────────

    @property
    def clip_model(self):
        if self._clip_model is None:
            from sentence_transformers import SentenceTransformer
            from content_engine.utils.mps_safe import MPS_DEVICE
            self._clip_device = MPS_DEVICE
            self._clip_model = SentenceTransformer("clip-ViT-B-32", device=self._clip_device)
            self._high_emb = None
        return self._clip_model

    # ── Blur detection ──────────────────────────────────────────────────────────

    @staticmethod
    def compute_blur_score(image: np.ndarray, threshold: Optional[float] = None) -> float:
        """
        Laplacian variance → normalised blur score.
        Higher variance = sharper image.
        threshold is the recalibrated blur threshold for this batch.
        """
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        if threshold is None:
            threshold = _blur_threshold
        return min(1.0, laplacian_var / threshold)

    # ── Brightness detection ─────────────────────────────────────────────────────

    @staticmethod
    def compute_brightness_score(image: np.ndarray) -> float:
        """
        HSV V channel mean → score penalising underexposure or overexposure.
        Ideal brightness is 0.4–0.8; outside that range gets penalised.
        """
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        mean_v = hsv[:, :, 2].mean() / 255.0

        center = _brightness_center
        tol    = _brightness_tolerance

        if mean_v < center - tol:
            # Underexposed — linear ramp up to ideal
            return max(0.0, mean_v / (center - tol))
        elif mean_v > center + tol:
            # Overexposed — linear ramp down from ideal
            return max(0.0, 1.0 - (mean_v - (center + tol)) / tol)
        return 1.0

    # ── CLIP aesthetic scoring ───────────────────────────────────────────────────

    def compute_aesthetic_score(self, image: np.ndarray) -> float:
        """
        CLIP similarity to high_quality vs low_quality prompt sets.
        Returns 0–1 where 1 = matches professional photography.
        """
        import torch
        pil_image = self._cv2_to_pil(image)
        image_emb = self.clip_model.encode(pil_image)

        # Lazy initialise reference embeddings
        if self._high_emb is None:
            self._high_emb = self.clip_model.encode([
                "professional photography", "well lit", "sharp focus",
                "good composition", "vibrant colors", "clear subject",
                "high quality photo", "good exposure",
            ]).mean(axis=0)

            self._low_emb = self.clip_model.encode([
                "blurry photo", "dark image", "overexposed",
                "grainy", "out of focus", "poor lighting",
                "low quality", "bad composition",
            ]).mean(axis=0)

        high_sim = torch.cosine_similarity(
            torch.tensor(image_emb), torch.tensor(self._high_emb), dim=0
        ).item()
        low_sim = torch.cosine_similarity(
            torch.tensor(image_emb), torch.tensor(self._low_emb), dim=0
        ).item()

        from content_engine.utils.mps_safe import empty_cache
        empty_cache()

        # Map to 0–1: (high_sim - low_sim + 1) / 2
        return float(np.clip((high_sim - low_sim + 1.0) / 2.0, 0.0, 1.0))

    # ── Main assess ──────────────────────────────────────────────────────────────

    def assess(self, image_path: str) -> Dict[str, float]:
        """
        Full quality assessment of an image.
        Uses reduced resolution (max 800px) for 20-30% faster processing.

        Returns:
            {
                "blur_score": 0–1,
                "brightness_score": 0–1,
                "aesthetic_score": 0–1,
                "quality_score": weighted composite
            }
        """
        image = cv2.imread(str(image_path))
        if image is None:
            return {
                "blur_score": 0.0, "brightness_score": 0.0,
                "aesthetic_score": 0.0, "quality_score": 0.0,
            }

        # Downscale large images for faster quality assessment (20-30% speedup)
        h, w = image.shape[:2]
        max_dim = 800
        if max(h, w) > max_dim:
            scale = max_dim / max(h, w)
            new_w, new_h = int(w * scale), int(h * scale)
            image = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)

        blur_score       = self.compute_blur_score(image)
        brightness_score = self.compute_brightness_score(image)
        aesthetic_score  = self.compute_aesthetic_score(image)

        quality_score = (
            blur_score       * 0.5 +
            brightness_score * 0.3 +
            aesthetic_score  * 0.2
        )

        return {
            "blur_score":       round(blur_score, 4),
            "brightness_score": round(brightness_score, 4),
            "aesthetic_score":  round(aesthetic_score, 4),
            "quality_score":    round(quality_score, 4),
        }

    # ── Batch calibration (Item 18) ─────────────────────────────────────────────

    def calibrate_batch(self, image_paths: list) -> Dict:
        """
        Analyse up to 20 images to recalibrate blur and brightness
        thresholds for the event's lighting conditions.

        Calibrates:
          - _blur_threshold: set to median + IQR of Laplacian variance
          - _brightness_center: set to mean of V-channel means

        Returns calibration metadata dict.
        """
        global _blur_threshold, _brightness_center, _brightness_tolerance

        sample = image_paths[:20]
        blur_values    = []
        bright_values  = []

        for path in sample:
            img = cv2.imread(str(path))
            if img is None:
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            blur_values.append(cv2.Laplacian(gray, cv2.CV_64F).var())

            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            bright_values.append(hsv[:, :, 2].mean() / 255.0)

        if not blur_values:
            return {"calibrated": False, "reason": "no images loaded"}

        # Calibrate blur threshold: median + IQR (robust to outliers)
        blur_arr      = np.array(blur_values)
        blur_median   = np.median(blur_arr)
        blur_q75      = np.percentile(blur_arr, 75)
        new_threshold = max(blur_median, blur_q75 * 0.8)  # At least 80% of Q75

        # Calibrate brightness: use mean (adapted to event lighting)
        new_brightness_center = float(np.mean(bright_values))

        _blur_threshold          = new_threshold
        _brightness_center       = new_brightness_center
        _brightness_tolerance    = 0.2

        return {
            "calibrated":            True,
            "blur_threshold":        round(_blur_threshold, 2),
            "brightness_center":     round(_brightness_center, 4),
            "brightness_tolerance":  _brightness_tolerance,
            "sample_size":           len(blur_values),
        }

    # ── Helpers ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _cv2_to_pil(frame: np.ndarray):
        """BGR numpy array → PIL Image (RGB)."""
        from PIL import Image
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb)