"""
Smart, subject-aware image cropping engine.

Given an original image and a :class:`FocalAnalysis`, this module computes the
best crop box for any target aspect ratio. It:

1. Generates multiple candidate crop boxes anchored on the focal region,
   subjects and faces.
2. Scores every candidate on face preservation, subject coverage, saliency
   retention, visual balance, boundary safety and semantic relevance.
3. Applies face-preserving boundary protection and minimum-subject-visibility
   constraints.
4. Returns the highest-scoring crop with a full breakdown and warnings.

All crops are computed from the *original* image; the original is never
modified. No stretching or distortion is ever applied.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

import cv2
import numpy as np
from PIL import Image

from .focal_analyzer import FocalAnalyzer, FocalAnalysis
from content_engine.utils.model_registry import get_clip
from content_engine.utils.mps_safe import empty_cache

try:
    from api.logger import get_logger
    _log = get_logger(__name__)
except Exception:  # pragma: no cover - logging unavailable
    import logging
    _log = logging.getLogger(__name__)

# ── Base composition-score weights ───────────────────────────────────────────
# These sum to 1.0. Tuned so no single cue (e.g. faces) dominates; architecture,
# product, landscape and event photographs all receive appropriate analysis.
_BASE_W_FACE_PRESERVE = 0.22   # faces fully inside, not cut by boundary
_BASE_W_SUBJECT_COVER = 0.20   # main + secondary subject coverage
_BASE_W_SALIENCY = 0.16        # saliency retained inside the crop
_BASE_W_BALANCE = 0.14         # focal point well-placed within the crop
_BASE_W_BOUNDARY = 0.12        # important subjects not touching crop edge
_BASE_W_SEMANTIC = 0.10        # CLIP semantic relevance (top candidates only)
_BASE_W_GENERAL_SCENE = 0.06   # non-face scenes still score well

# Scenes where faces/people are the primary subject (portrait / group /
# event_stage). For these, face & subject preservation is boosted at the
# expense of the generic "cover the whole scene" term, so a group photo is not
# cropped to centre on one person while cutting the others out.
_SCENE_WEIGHT_OVERRIDES = {
    "portrait": {
        "_W_FACE_PRESERVE": 0.32,
        "_W_SUBJECT_COVER": 0.28,
        "_W_GENERAL_SCENE": 0.02,
    },
    "group": {
        "_W_FACE_PRESERVE": 0.30,
        "_W_SUBJECT_COVER": 0.26,
        "_W_GENERAL_SCENE": 0.02,
    },
    "event_stage": {
        "_W_FACE_PRESERVE": 0.28,
        "_W_SUBJECT_COVER": 0.24,
        "_W_GENERAL_SCENE": 0.02,
    },
}


def _scene_weights(scene_type: str) -> Dict[str, float]:
    """Return the composition-score weights for a given scene type."""
    overrides = _SCENE_WEIGHT_OVERRIDES.get(scene_type, {})
    return {
        "_W_FACE_PRESERVE": overrides.get("_W_FACE_PRESERVE", _BASE_W_FACE_PRESERVE),
        "_W_SUBJECT_COVER": overrides.get("_W_SUBJECT_COVER", _BASE_W_SUBJECT_COVER),
        "_W_SALIENCY": _BASE_W_SALIENCY,
        "_W_BALANCE": _BASE_W_BALANCE,
        "_W_BOUNDARY": _BASE_W_BOUNDARY,
        "_W_SEMANTIC": _BASE_W_SEMANTIC,
        "_W_GENERAL_SCENE": overrides.get("_W_GENERAL_SCENE", _BASE_W_GENERAL_SCENE),
    }

# Minimum fraction of the main subject that must remain inside the crop.
_MIN_SUBJECT_VISIBILITY = 0.55

# If a face would be cut by the crop boundary, this penalty is applied.
_FACE_CUT_PENALTY = 0.5

# Number of candidates taken forward to (optional) CLIP semantic scoring.
_CLIP_TOP_K = 4

# Target format presets ─────────────────────────────────────────────────────
# Each entry: (width, height). LinkedIn collage tile sizes are supplied by the
# caller (they depend on the chosen grid layout), so they have no fixed preset.
TARGET_PRESETS: Dict[str, Tuple[int, int]] = {
    "instagram_carousel": (1080, 1350),  # 4:5
    "instagram_story": (1080, 1920),  # 9:16
    "instagram_reel_cover": (1080, 1920),  # 9:16
    "landscape_16_9": (1920, 1080),  # 16:9
    "square_1_1": (1080, 1080),  # 1:1
}


@dataclass
class CropCandidate:
    """One candidate crop box with its composition score."""

    box: Tuple[int, int, int, int]  # (x1, y1, x2, y2) in original pixels
    score: float  # 0-1 composite composition score
    breakdown: Dict[str, float] = field(default_factory=dict)


@dataclass
class CropResult:
    """Result of computing one intelligent crop."""

    image_path: str
    target_w: int
    target_h: int
    target_ratio: float
    source_w: int
    source_h: int
    crop_box: Tuple[int, int, int, int]  # chosen box, original-image pixels
    crop_box_norm: Tuple[float, float, float, float]
    crop_w: int
    crop_h: int
    composition_score: float
    breakdown: Dict[str, float] = field(default_factory=dict)
    scene_type: str = "general"
    subjects_preserved: List[str] = field(default_factory=list)
    faces_preserved: int = 0
    faces_total: int = 0
    warnings: List[str] = field(default_factory=list)
    trade_off: Optional[str] = None
    manual_override: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "image_path": self.image_path,
            "target_w": self.target_w,
            "target_h": self.target_h,
            "target_ratio": round(self.target_ratio, 4),
            "source_w": self.source_w,
            "source_h": self.source_h,
            "crop_box": self.crop_box,
            "crop_box_norm": self.crop_box_norm,
            "crop_w": self.crop_w,
            "crop_h": self.crop_h,
            "composition_score": round(self.composition_score, 4),
            "breakdown": {k: round(v, 4) for k, v in self.breakdown.items()},
            "scene_type": self.scene_type,
            "subjects_preserved": self.subjects_preserved,
            "faces_preserved": self.faces_preserved,
            "faces_total": self.faces_total,
            "warnings": self.warnings,
            "trade_off": self.trade_off,
            "manual_override": self.manual_override,
        }


class SmartCropper:
    """
    Computes intelligent, subject-aware crops for any target aspect ratio.

    The same image can be cropped independently for each output format (LinkedIn
    tile, carousel slide, story frame, …). Each crop optimises what to preserve
    for *that* aspect ratio.
    """

    def __init__(self, analyzer: Optional[FocalAnalyzer] = None):
        self._analyzer = analyzer or FocalAnalyzer()
        self._clip_model = None

    # ── Public API ─────────────────────────────────────────────────────────

    def compute_crop(
        self,
        image_path: str,
        target_w: int,
        target_h: int,
        analysis: Optional[FocalAnalysis] = None,
        manual_focal: Optional[Tuple[float, float]] = None,
    ) -> CropResult:
        """
        Compute the best crop of ``image_path`` for ``target_w x target_h``.

        Args:
            image_path: Path to the source image.
            target_w, target_h: Output dimensions in pixels.
            analysis: Optional pre-computed :class:`FocalAnalysis` (reused across
                formats to avoid re-running detection).
            manual_focal: Optional (x, y) normalised focal-point override.
                When provided, the crop is anchored here without re-running AI.

        Returns:
            A :class:`CropResult` describing the chosen crop, its score and any
            warnings/trade-offs.
        """
        if manual_focal is not None:
            # Manual override: build a lightweight analysis centred on the
            # provided focal point without running detection models.
            if analysis is None:
                try:
                    img = Image.open(image_path).convert("RGB")
                    sw, sh = img.size
                except Exception:
                    sw, sh = target_w, target_h
                analysis = FocalAnalysis(
                    image_path=image_path,
                    width=sw,
                    height=sh,
                    orientation=("portrait" if sh > sw else
                                 "landscape" if sw > sh else "square"),
                    focal_point=manual_focal,
                    focal_region=(0.0, 0.0, 1.0, 1.0),
                    scene_type="general",
                    confidence=0.5,
                    models_used=["manual-override"],
                )
            result = self._compute_crop(analysis, target_w, target_h)
            result.manual_override = True
            return result

        if analysis is None:
            analysis = self._analyzer.analyze(image_path)
        return self._compute_crop(analysis, target_w, target_h)

    def crop_image(
        self,
        image_path: str,
        target_w: int,
        target_h: int,
        analysis: Optional[FocalAnalysis] = None,
        manual_focal: Optional[Tuple[float, float]] = None,
    ) -> Tuple[Image.Image, CropResult]:
        """
        Convenience: compute the crop and return the cropped PIL image + result.

        The returned image is resized to exactly (target_w, target_h) with
        LANCZOS. The original image file is never modified.
        """
        result = self.compute_crop(
            image_path, target_w, target_h,
            analysis=analysis, manual_focal=manual_focal,
        )
        img = Image.open(image_path).convert("RGB")
        cropped = img.crop(result.crop_box)
        if cropped.size != (target_w, target_h):
            cropped = cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)
        return cropped, result

    # ── Internal: core computation ─────────────────────────────────────────

    def _compute_crop(self, analysis: FocalAnalysis,
                      target_w: int, target_h: int) -> CropResult:
        img_w, img_h = analysis.width, analysis.height
        if img_w <= 0 or img_h <= 0:
            return self._empty_result(
                analysis, target_w, target_h,
                ["source image has invalid dimensions"],
            )

        target_ratio = target_w / target_h
        orig_ratio = img_w / img_h

        # Largest rectangle inside the source matching the target ratio.
        if orig_ratio > target_ratio:
            # Source is wider: keep full height, crop width.
            crop_w = max(1, int(round(img_h * target_ratio)))
            crop_h = img_h
            x_min, x_max = 0, img_w - crop_w
            y_min, y_max = 0, 0
        else:
            # Source is taller: keep full width, crop height.
            crop_w = img_w
            crop_h = max(1, int(round(img_w / target_ratio)))
            x_min, x_max = 0, 0
            y_min, y_max = 0, img_h - crop_h

        # Anchor points around which candidate centres are generated.
        anchors = self._candidate_anchors(analysis, img_w, img_h)

        # Generate candidate boxes.
        candidates: List[CropCandidate] = []
        steps_x = 5
        steps_y = 5
        for ax, ay in anchors:
            for i in range(steps_x):
                for j in range(steps_y):
                    cx = ax + (i - (steps_x - 1) / 2) * (crop_w * 0.12)
                    cy = ay + (j - (steps_y - 1) / 2) * (crop_h * 0.12)
                    if x_max > x_min:
                        cx = float(np.clip(
                            cx, x_min + crop_w / 2, x_max + crop_w / 2))
                    if y_max > y_min:
                        cy = float(np.clip(
                            cy, y_min + crop_h / 2, y_max + crop_h / 2))
                    x1 = int(round(cx - crop_w / 2))
                    y1 = int(round(cy - crop_h / 2))
                    x1 = int(np.clip(x1, x_min, x_max))
                    y1 = int(np.clip(y1, y_min, y_max))
                    box = (x1, y1, x1 + crop_w, y1 + crop_h)
                    score, breakdown = self._score_candidate(
                        box, analysis, img_w, img_h, target_ratio)
                    candidates.append(CropCandidate(
                        box=box, score=score, breakdown=breakdown))

        # Always include the pure centre crop and the focal-anchored crop as
        # explicit candidates (guarantees sane fallback behaviour).
        for cx, cy in [(img_w / 2, img_h / 2),
                       (analysis.focal_point[0] * img_w,
                        analysis.focal_point[1] * img_h)]:
            x1 = int(np.clip(int(round(cx - crop_w / 2)), x_min, x_max))
            y1 = int(np.clip(int(round(cy - crop_h / 2)), y_min, y_max))
            box = (x1, y1, x1 + crop_w, y1 + crop_h)
            score, breakdown = self._score_candidate(
                box, analysis, img_w, img_h, target_ratio)
            candidates.append(CropCandidate(
                box=box, score=score, breakdown=breakdown))

        # Rank and pick the best candidate.
        candidates.sort(key=lambda c: -c.score)
        best = candidates[0]

        # Optional CLIP semantic re-score of the top candidates.
        self._apply_clip_scoring(candidates[:_CLIP_TOP_K], analysis,
                                 img_w, img_h, target_w, target_h)
        candidates.sort(key=lambda c: -c.score)
        best = candidates[0]

        # Hard safety net: never deliver a crop that excludes every detected
        # face. If the winning crop cuts out all people, re-centre on the face
        # position that keeps the most face area in frame.
        if analysis.faces:
            def _max_face_coverage(box: Tuple[int, int, int, int]) -> float:
                bn = _to_norm_box(box, img_w, img_h)
                return max(_coverage(bn, d.bbox) for d in analysis.faces)

            if _max_face_coverage(best.box) < 0.90:
                best_face_box = None
                best_face_score = -1.0
                for d in analysis.faces:
                    cx = (d.bbox[0] + d.bbox[2]) / 2 * img_w
                    cy = (d.bbox[1] + d.bbox[3]) / 2 * img_h
                    x1 = int(np.clip(round(cx - crop_w / 2), x_min, x_max))
                    y1 = int(np.clip(round(cy - crop_h / 2), y_min, y_max))
                    box = (x1, y1, x1 + crop_w, y1 + crop_h)
                    m = _max_face_coverage(box)
                    if m > best_face_score:
                        best_face_score = m
                        best_face_box = box
                cur = _max_face_coverage(best.box)
                if best_face_box is not None and best_face_score > cur:
                    score, breakdown = self._score_candidate(
                        best_face_box, analysis, img_w, img_h, target_ratio)
                    best = CropCandidate(box=best_face_box, score=score,
                                         breakdown=breakdown)
                    best.breakdown.setdefault("_warnings", []).append(
                        "face_recovery")

        # Boundary protection: shift the box so faces/subjects are not cut.
        best, adjusted = self._protect_boundaries(
            best, analysis, img_w, img_h, crop_w, crop_h, target_ratio)

        # Minimum subject visibility check.
        best, visibility_warn = self._enforce_subject_visibility(
            best, analysis, img_w, img_h, target_ratio)

        warnings: List[str] = []
        if "_warnings" in best.breakdown:
            warnings.extend(best.breakdown.pop("_warnings"))
        if adjusted:
            warnings.append(
                "Crop shifted to avoid cutting detected faces/subjects")
        if visibility_warn:
            warnings.append(visibility_warn)
        if (not analysis.faces and not analysis.people
                and not analysis.objects and not analysis.salient_regions):
            warnings.append(
                "No detectable focal region; using composition fallback")

        trade_off = None
        if best.score < 0.55:
            trade_off = (
                "Could not preserve all important subjects in this "
                "aspect ratio; least-destructive crop selected."
            )

        # Subjects preserved (for the report).
        subjects_preserved = self._subjects_in_box(
            best.box, analysis, img_w, img_h)
        faces_preserved = self._faces_in_box(best.box, analysis)

        norm_box = _to_norm_box(best.box, img_w, img_h)
        return CropResult(
            image_path=analysis.image_path,
            target_w=target_w, target_h=target_h,
            target_ratio=target_ratio,
            source_w=img_w, source_h=img_h,
            crop_box=best.box,
            crop_box_norm=norm_box,
            crop_w=crop_w, crop_h=crop_h,
            composition_score=best.score,
            breakdown=best.breakdown,
            scene_type=analysis.scene_type,
            subjects_preserved=subjects_preserved,
            faces_preserved=faces_preserved,
            faces_total=len(analysis.faces),
            warnings=warnings,
            trade_off=trade_off,
        )

    # ── Candidate anchors ──────────────────────────────────────────────────

    def _candidate_anchors(self, analysis: FocalAnalysis,
                           img_w: int, img_h: int) -> List[Tuple[float, float]]:
        """Anchor points (in pixels) around which crop centres are generated."""
        anchors: List[Tuple[float, float]] = []
        fp_x = analysis.focal_point[0] * img_w
        fp_y = analysis.focal_point[1] * img_h
        anchors.append((fp_x, fp_y))

        # Main subject centre.
        if analysis.main_subject is not None:
            mx = (analysis.main_subject[0] + analysis.main_subject[2]) / 2 * img_w
            my = (analysis.main_subject[1] + analysis.main_subject[3]) / 2 * img_h
            anchors.append((mx, my))

        # Face centroids (each important face).
        for det in analysis.faces[:4]:
            cx = (det.bbox[0] + det.bbox[2]) / 2 * img_w
            cy = (det.bbox[1] + det.bbox[3]) / 2 * img_h
            anchors.append((cx, cy))

        # Secondary subject centres.
        for sub in analysis.secondary_subjects[:2]:
            cx = (sub[0] + sub[2]) / 2 * img_w
            cy = (sub[1] + sub[3]) / 2 * img_h
            anchors.append((cx, cy))

        # Salient region centres.
        for reg in analysis.salient_regions[:2]:
            cx = (reg[0] + reg[2]) / 2 * img_w
            cy = (reg[1] + reg[3]) / 2 * img_h
            anchors.append((cx, cy))

        # Group anchor: centre of the union of all face boxes (and, when no
        # faces are detected, all subject boxes). For group photos this gives
        # the candidate grid a centre point that tries to keep every person in
        # frame rather than fixating on a single main subject.
        all_subject_boxes = [d.bbox for d in analysis.faces] + \
            ([analysis.main_subject] if analysis.main_subject else []) + \
            list(analysis.secondary_subjects[:3])
        if all_subject_boxes:
            gx1 = min(b[0] for b in all_subject_boxes)
            gy1 = min(b[1] for b in all_subject_boxes)
            gx2 = max(b[2] for b in all_subject_boxes)
            gy2 = max(b[3] for b in all_subject_boxes)
            anchors.append(((gx1 + gx2) / 2 * img_w, (gy1 + gy2) / 2 * img_h))

        # Centre of image (always a fallback anchor).
        anchors.append((img_w / 2, img_h / 2))

        # Rule-of-thirds positions relative to the focal point.
        anchors.append((fp_x + (img_w / 2 - fp_x) / 3, fp_y))
        anchors.append((fp_x, fp_y + (img_h / 2 - fp_y) / 3))

        return anchors

    # ── Composition scoring ────────────────────────────────────────────────

    def _score_candidate(self, box: Tuple[int, int, int, int],
                         analysis: FocalAnalysis,
                         img_w: int, img_h: int,
                         target_ratio: float) -> Tuple[float, Dict[str, float]]:
        box_norm = _to_norm_box(box, img_w, img_h)
        breakdown: Dict[str, float] = {}
        breakdown["_warnings"] = []

        # Scene-aware weights: portrait / group / event_stage scenes boost
        # face & subject preservation so multi-subject crops don't cut out
        # secondary people to centre on a single main subject.
        W = _scene_weights(analysis.scene_type)

        # 1. Face preservation (faces fully inside, penalty if cut by edge).
        face_score = self._score_faces(box_norm, analysis)
        breakdown["face_preservation"] = face_score

        # 2. Subject coverage (main + secondary subjects).
        subj_score = self._score_subjects(box_norm, analysis)
        breakdown["subject_coverage"] = subj_score

        # 3. Saliency retention.
        sal_score = self._score_saliency(box, img_w, img_h, analysis)
        breakdown["saliency_retention"] = sal_score

        # 4. Visual balance (focal point placement within crop).
        bal_score = self._score_balance(box_norm, analysis)
        breakdown["visual_balance"] = bal_score

        # 5. Boundary safety (subjects not touching crop edge).
        bound_score = self._score_boundary(box_norm, analysis)
        breakdown["boundary_safety"] = bound_score

        # 6. General-scene term (rewards covering the scene evenly for
        #    non-face subjects so architecture/product/landscape score well).
        scene_score = self._score_general_scene(box_norm, analysis)
        breakdown["general_scene"] = scene_score

        # Weighted composite (semantic added later for top candidates).
        score = (
            W["_W_FACE_PRESERVE"] * face_score
            + W["_W_SUBJECT_COVER"] * subj_score
            + W["_W_SALIENCY"] * sal_score
            + W["_W_BALANCE"] * bal_score
            + W["_W_BOUNDARY"] * bound_score
            + W["_W_GENERAL_SCENE"] * scene_score
        )

        # Safety net: a crop that excludes essentially every detected face is
        # fundamentally wrong for people photos, no matter how strong its
        # saliency / balance / scene coverage. Penalise it heavily so the
        # engine always prefers a crop that keeps at least one person in frame.
        if analysis.faces:
            max_face_cov = max(_coverage(box_norm, d.bbox) for d in analysis.faces)
            if max_face_cov < 0.10:
                score *= 0.1

        breakdown["semantic_relevance"] = 0.0  # filled by CLIP pass
        return score, breakdown

    def _score_faces(self, box_norm, analysis) -> float:
        """Score how well faces are preserved inside the crop."""
        if not analysis.faces:
            return 0.6  # neutral when no faces
        total = 0.0
        cut_any = False
        all_fully_inside = True
        for det in analysis.faces:
            weight = getattr(det, "_weight", 0.5)
            cover = _coverage(box_norm, det.bbox)
            if cover >= 0.98:
                # Face fully inside crop.
                total += 1.0 * weight
            elif cover > 0.0:
                # Face partially inside: credit proportional to coverage.
                total += cover * weight
                all_fully_inside = False
                if _touches_boundary(box_norm, det.bbox):
                    cut_any = True
            else:
                # Face outside the crop.
                all_fully_inside = False
                if _box_intersects_edge(box_norm, det.bbox):
                    cut_any = True
        score = total / max(1, len(analysis.faces))
        # Strong penalty when any face is cut by the crop boundary.
        if cut_any:
            score *= (1.0 - _FACE_CUT_PENALTY)
        # Bonus when every face made it fully inside.
        if all_fully_inside and analysis.faces:
            score = min(1.0, score * 1.1)
        return float(np.clip(score, 0.0, 1.0))

    def _score_subjects(self, box_norm, analysis) -> float:
        """Coverage of main + secondary subjects."""
        score = 0.0
        count = 0
        if analysis.main_subject is not None:
            score += _coverage(box_norm, analysis.main_subject)
            count += 1
        for sub in analysis.secondary_subjects[:3]:
            score += 0.5 * _coverage(box_norm, sub)
            count += 0.5
        if count == 0:
            return 0.5
        return float(np.clip(score / max(count, 1), 0.0, 1.0))

    def _score_saliency(self, box: Tuple[int, int, int, int],
                        img_w: int, img_h: int,
                        analysis: FocalAnalysis) -> float:
        """Approximate saliency retention via salient-region coverage."""
        if not analysis.salient_regions and analysis.main_subject is None:
            return 0.5
        box_n = _to_norm_box(box, img_w, img_h)
        cover = 0.0
        if analysis.salient_regions:
            cover = max(_coverage(box_n, r) for r in analysis.salient_regions)
        if analysis.main_subject is not None:
            cover = max(cover, _coverage(box_n, analysis.main_subject))
        return float(np.clip(cover, 0.0, 1.0))

    def _score_balance(self, box_norm, analysis) -> float:
        """
        Visual balance: reward the focal point being well-placed inside the
        crop (near centre or rule-of-thirds), penalise it near the edge.
        """
        fx, fy = analysis.focal_point
        inside = (box_norm[0] <= fx <= box_norm[2]
                  and box_norm[1] <= fy <= box_norm[3])
        if not inside:
            return 0.25
        cx = (box_norm[0] + box_norm[2]) / 2.0
        cy = (box_norm[1] + box_norm[3]) / 2.0
        dist = math.hypot(fx - cx, fy - cy)
        max_dist = math.hypot(0.5, 0.5)
        balance = 1.0 - (dist / max_dist)
        thirds_x = min(abs(fx - 1 / 3), abs(fx - 2 / 3))
        thirds_y = min(abs(fy - 1 / 3), abs(fy - 2 / 3))
        thirds_bonus = max(0.0, 0.5 - min(thirds_x, thirds_y)) * 0.3
        return float(np.clip(balance * 0.7 + thirds_bonus, 0.0, 1.0))

    def _score_boundary(self, box_norm, analysis) -> float:
        """
        Boundary safety: penalise important subjects touching the crop edge.
        """
        penalty = 0.0
        subjects = []
        if analysis.main_subject is not None:
            subjects.append(analysis.main_subject)
        subjects.extend(analysis.secondary_subjects[:2])
        for det in analysis.faces:
            subjects.append(det.bbox)
        for sub in subjects:
            if _touches_boundary(box_norm, sub):
                penalty += 0.25
        return float(np.clip(1.0 - min(penalty, 1.0), 0.0, 1.0))

    def _score_general_scene(self, box_norm, analysis) -> float:
        """
        Even-scene coverage: for non-face scenes (architecture, landscape,
        product), reward covering a broad, balanced portion of the image.
        """
        area = _box_area(box_norm)
        if area >= 0.5:
            return 0.9
        if area >= 0.25:
            return 0.7
        return 0.4

    def _apply_clip_scoring(self, candidates: List[CropCandidate],
                            analysis: FocalAnalysis,
                            img_w: int, img_h: int,
                            target_w: int, target_h: int) -> None:
        """Optionally re-score top candidates with CLIP semantic relevance."""
        clip = self._clip()
        if clip is None:
            return
        description = self._scene_description(analysis)
        if not description:
            return
        try:
            import torch
            text_emb = clip.encode([description])
            for cand in candidates:
                box = cand.box
                crop_img = Image.open(
                    analysis.image_path).convert("RGB").crop(box)
                img_emb = clip.encode([crop_img])
                sim = float(torch.cosine_similarity(
                    torch.tensor(img_emb[0]), torch.tensor(text_emb[0]), dim=0))
                sem = (sim + 1.0) / 2.0  # map to 0-1
                cand.breakdown["semantic_relevance"] = sem
                W = _scene_weights(analysis.scene_type)
                cand.score = (
                    W["_W_FACE_PRESERVE"] * cand.breakdown.get("face_preservation", 0)
                    + W["_W_SUBJECT_COVER"] * cand.breakdown.get("subject_coverage", 0)
                    + W["_W_SALIENCY"] * cand.breakdown.get("saliency_retention", 0)
                    + W["_W_BALANCE"] * cand.breakdown.get("visual_balance", 0)
                    + W["_W_BOUNDARY"] * cand.breakdown.get("boundary_safety", 0)
                    + W["_W_SEMANTIC"] * sem
                    + W["_W_GENERAL_SCENE"] * cand.breakdown.get("general_scene", 0)
                )
                empty_cache()
        except Exception as exc:
            _log.debug("clip_scoring_failed", error=str(exc))

    def _clip(self):
        if self._clip_model is None:
            try:
                self._clip_model = get_clip()
            except Exception:
                self._clip_model = None
        return self._clip_model

    @staticmethod
    def _scene_description(analysis: FocalAnalysis) -> str:
        parts = [analysis.scene_type]
        parts.extend(d.label for d in analysis.faces[:2])
        parts.extend(d.label for d in analysis.people[:2])
        parts.extend(d.label for d in analysis.objects[:3])
        return ", ".join(dict.fromkeys(p for p in parts if p))

    # ── Boundary protection ────────────────────────────────────────────────

    def _protect_boundaries(self, best: CropCandidate, analysis: FocalAnalysis,
                            img_w: int, img_h: int,
                            crop_w: int, crop_h: int,
                            target_ratio: float) -> Tuple[CropCandidate, bool]:
        """
        Shift the crop box so detected faces/subjects are not cut by the crop
        boundary. Returns (possibly-adjusted candidate, was_adjusted).
        """
        box = list(best.box)
        x1, y1, x2, y2 = box
        adjusted = False

        if orig_wider(analysis.width, analysis.height, target_ratio):
            x_min, x_max = 0, analysis.width - crop_w
            y_min, y_max = 0, 0
        else:
            x_min, x_max = 0, 0
            y_min, y_max = 0, analysis.height - crop_h

        # Boundary protection is about faces: never slice a detected face in
        # half at the crop edge. Full-body / secondary subjects are positioned
        # by the scoring and visibility-enforcement stages instead, so they are
        # not chased here (chasing them would march the box across the frame
        # and cut out everything else).
        protectees: List[Tuple[float, float, float, float]] = []
        for det in analysis.faces:
            weight = getattr(det, "_weight", 0.5)
            if weight >= 0.6:
                protectees.append(tuple(det.bbox_px))

        # Iterate: protecting one face must not un-protect another. A few
        # passes is enough to converge for typical group layouts.
        for _pass in range(3):
            pass_adjusted = False
            for (fx1, fy1, fx2, fy2) in protectees:
                cut_left = fx1 < x1 and fx2 > x1 and fx2 <= x2
                cut_right = fx2 > x2 and fx1 >= x1 and fx1 < x2
                cut_top = fy1 < y1 and fy2 > y1 and fy2 <= y2
                cut_bottom = fy2 > y2 and fy1 >= y1 and fy1 < y2
                if cut_left:
                    x1 = int(max(0, int(round(fx1)) - 2))
                    x2 = x1 + crop_w
                    if x2 > analysis.width:
                        x2 = analysis.width
                        x1 = x2 - crop_w
                    pass_adjusted = True
                if cut_right:
                    x2 = int(min(analysis.width, int(round(fx2)) + 2))
                    x1 = x2 - crop_w
                    if x1 < 0:
                        x1 = 0
                        x2 = crop_w
                    pass_adjusted = True
                if cut_top:
                    y1 = int(max(0, int(round(fy1)) - 2))
                    y2 = y1 + crop_h
                    if y2 > analysis.height:
                        y2 = analysis.height
                        y1 = y2 - crop_h
                    pass_adjusted = True
                if cut_bottom:
                    y2 = int(min(analysis.height, int(round(fy2)) + 2))
                    y1 = y2 - crop_h
                    if y1 < 0:
                        y1 = 0
                        y2 = crop_h
                    pass_adjusted = True
            adjusted = adjusted or pass_adjusted
            if not pass_adjusted:
                break

        x1 = int(np.clip(x1, x_min, x_max))
        y1 = int(np.clip(y1, y_min, y_max))
        x2 = x1 + crop_w
        y2 = y1 + crop_h

        if adjusted:
            box = (x1, y1, x2, y2)
            score, breakdown = self._score_candidate(
                box, analysis, img_w, img_h, target_ratio)
            best = CropCandidate(box=box, score=score, breakdown=breakdown)
            best.breakdown.setdefault("_warnings", []).append(
                "boundary_protected")
        return best, adjusted

    def _enforce_subject_visibility(self, best: CropCandidate,
                                    analysis: FocalAnalysis,
                                    img_w: int, img_h: int,
                                    target_ratio: float):
        """
        Ensure every important subject is at least _MIN_SUBJECT_VISIBILITY
        visible. If the best crop violates this for any subject, shift the box
        to the position (among a small set of compromises) that maximises the
        least-visible subject, rather than fixating on a single main subject.
        """
        subjects: List[Tuple[float, float, float, float]] = []
        if analysis.main_subject is not None:
            subjects.append(analysis.main_subject)
        subjects.extend(analysis.secondary_subjects[:3])
        for det in analysis.faces:
            subjects.append(det.bbox)
        if not subjects:
            return best, None

        box_norm = _to_norm_box(best.box, img_w, img_h)
        visibilities = [_coverage(box_norm, s) for s in subjects]
        if min(visibilities) >= _MIN_SUBJECT_VISIBILITY:
            return best, None

        crop_w = best.box[2] - best.box[0]
        crop_h = best.box[3] - best.box[1]
        best_box = best.box
        best_min_vis = min(visibilities)

        # Candidate compromise centres: each subject's centre, plus the group
        # centre and the image centre.
        centres: List[Tuple[float, float]] = []
        for s in subjects:
            centres.append(((s[0] + s[2]) / 2 * img_w,
                            (s[1] + s[3]) / 2 * img_h))
        if subjects:
            gx1 = min(s[0] for s in subjects); gy1 = min(s[1] for s in subjects)
            gx2 = max(s[2] for s in subjects); gy2 = max(s[3] for s in subjects)
            centres.append(((gx1 + gx2) / 2 * img_w, (gy1 + gy2) / 2 * img_h))
        centres.append((img_w / 2, img_h / 2))

        if orig_wider(img_w, img_h, target_ratio):
            x_min, x_max = 0, img_w - crop_w
            for cx, cy in centres:
                x1 = int(np.clip(int(round(cx - crop_w / 2)), x_min, x_max))
                y1 = best.box[1]
                box = (x1, y1, x1 + crop_w, y1 + crop_h)
                bn = _to_norm_box(box, img_w, img_h)
                min_vis = min(_coverage(bn, s) for s in subjects)
                if min_vis > best_min_vis:
                    best_min_vis = min_vis
                    best_box = box
        else:
            y_min, y_max = 0, img_h - crop_h
            for cx, cy in centres:
                x1 = best.box[0]
                y1 = int(np.clip(int(round(cy - crop_h / 2)), y_min, y_max))
                box = (x1, y1, x1 + crop_w, y1 + crop_h)
                bn = _to_norm_box(box, img_w, img_h)
                min_vis = min(_coverage(bn, s) for s in subjects)
                if min_vis > best_min_vis:
                    best_min_vis = min_vis
                    best_box = box

        if best_box != best.box:
            score, breakdown = self._score_candidate(
                best_box, analysis, img_w, img_h, target_ratio)
            best = CropCandidate(box=best_box, score=score,
                                 breakdown=breakdown)
            best.breakdown.setdefault("_warnings", []).append(
                "subject_visibility_forced")
            return best, (
                "One or more subjects below target visibility; "
                "least-destructive compromise crop selected"
            )
        return best, (
            "One or more subjects below target visibility; "
            "no better crop position available"
        )

    # ── Helpers ────────────────────────────────────────────────────────────

    def _faces_in_box(self, box: Tuple[int, int, int, int],
                      analysis: FocalAnalysis) -> int:
        box_norm = _to_norm_box(box, analysis.width, analysis.height)
        count = 0
        for det in analysis.faces:
            if _coverage(box_norm, det.bbox) >= 0.9:
                count += 1
        return count

    def _subjects_in_box(self, box: Tuple[int, int, int, int],
                         analysis: FocalAnalysis,
                         img_w: int, img_h: int) -> List[str]:
        box_norm = _to_norm_box(box, img_w, img_h)
        names: List[str] = []
        if (analysis.main_subject is not None
                and _coverage(box_norm, analysis.main_subject) >= 0.5):
            names.append("main_subject")
        for i, sub in enumerate(analysis.secondary_subjects):
            if _coverage(box_norm, sub) >= 0.5:
                names.append(f"secondary_subject_{i}")
        for det in analysis.faces:
            if _coverage(box_norm, det.bbox) >= 0.5:
                names.append(f"face_{det.label}")
        return names

    def _empty_result(self, analysis: FocalAnalysis, target_w: int, target_h: int,
                      warnings: List[str]) -> CropResult:
        return CropResult(
            image_path=analysis.image_path, target_w=target_w, target_h=target_h,
            target_ratio=target_w / target_h, source_w=analysis.width,
            source_h=analysis.height, crop_box=(0, 0, target_w, target_h),
            crop_box_norm=(0.0, 0.0, 1.0, 1.0), crop_w=target_w, crop_h=target_h,
            composition_score=0.0, warnings=warnings,
        )


def _iou(a: Tuple[float, float, float, float],
         b: Tuple[float, float, float, float]) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter_w = max(0.0, x2 - x1)
    inter_h = max(0.0, y2 - y1)
    inter = inter_w * inter_h
    if inter <= 0:
        return 0.0
    area_a = max(0.0, (a[2] - a[0])) * max(0.0, (a[3] - a[1]))
    area_b = max(0.0, (b[2] - b[0])) * max(0.0, (b[3] - b[1]))
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _coverage(crop_norm: Tuple[float, float, float, float],
              subject_norm: Tuple[float, float, float, float]) -> float:
    """
    Fraction of ``subject_norm`` lying inside ``crop_norm``.

    This is ``intersection / subject_area`` (a value of 1.0 means the subject
    is fully contained in the crop). Unlike IoU it is not penalised when the
    crop is much larger than the subject, which is exactly what we need for
    face/subject preservation checks.
    """
    ix = max(0.0, min(crop_norm[2], subject_norm[2]) - max(crop_norm[0], subject_norm[0]))
    iy = max(0.0, min(crop_norm[3], subject_norm[3]) - max(crop_norm[1], subject_norm[1]))
    inter = ix * iy
    sa = max(0.0, (subject_norm[2] - subject_norm[0])) * max(0.0, (subject_norm[3] - subject_norm[1]))
    return inter / sa if sa > 0 else 0.0


def _box_area(box: Tuple[float, float, float, float]) -> float:
    return max(0.0, (box[2] - box[0])) * max(0.0, (box[3] - box[1]))


def _to_norm_box(box: Tuple[int, int, int, int],
                 img_w: int, img_h: int) -> Tuple[float, float, float, float]:
    return (
        box[0] / img_w,
        box[1] / img_h,
        box[2] / img_w,
        box[3] / img_h,
    )


def orig_wider(img_w: int, img_h: int, target_ratio: float) -> bool:
    """True when the source is wider than the target ratio (crop width)."""
    return (img_w / img_h) > target_ratio


# ── Manual crop-override store ───────────────────────────────────────────────
# Persists user-adjusted focal points / crop boxes scoped to (image_path,
# format_key). Loaded lazily from a JSON file so adjustments survive backend
# restarts and can be fed back into the rendering pipeline.
class CropOverrideStore:
    def __init__(self, path: Optional[str] = None):
        self._path = Path(path) if path else None
        self._overrides: Dict[str, Dict] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._overrides = {}
        if self._path is not None and self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._overrides = data
            except Exception:
                self._overrides = {}

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._overrides, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    def _key(self, image_path: str, format_key: str) -> str:
        return f"{format_key}::{Path(image_path).name}"

    def get(self, image_path: str, format_key: str) -> Optional[Dict]:
        """Return the stored override for (image_path, format_key), if any."""
        self._ensure_loaded()
        return self._overrides.get(self._key(image_path, format_key))

    def set(
        self,
        image_path: str,
        format_key: str,
        focal_point: Tuple[float, float],
        crop_box_norm: Tuple[float, float, float, float],
    ) -> None:
        """Persist a manual focal-point / crop-box adjustment."""
        self._ensure_loaded()
        self._overrides[self._key(image_path, format_key)] = {
            "focal_point": [float(focal_point[0]), float(focal_point[1])],
            "crop_box_norm": [float(v) for v in crop_box_norm],
        }
        self._save()

    def clear(self, image_path: str, format_key: str) -> None:
        self._ensure_loaded()
        self._overrides.pop(self._key(image_path, format_key), None)
        self._save()


# Global override store, pointed at output/crop_overrides.json by default.
_override_store: Optional[CropOverrideStore] = None


def get_override_store(path: Optional[str] = None) -> CropOverrideStore:
    global _override_store
    if _override_store is None or path is not None:
        _override_store = CropOverrideStore(path)
    return _override_store



def _touches_boundary(box_norm, sub_norm) -> bool:
    """True when a subject box touches the crop boundary."""
    eps = 0.005
    return (sub_norm[0] <= box_norm[0] + eps
            or sub_norm[2] >= box_norm[2] - eps
            or sub_norm[1] <= box_norm[1] + eps
            or sub_norm[3] >= box_norm[3] - eps)


def _box_intersects_edge(box_norm, sub_norm) -> bool:
    """True when a subject box intersects the crop edge (partial overlap)."""
    return _iou(box_norm, sub_norm) > 0 and not (
        sub_norm[0] >= box_norm[0] and sub_norm[2] <= box_norm[2]
        and sub_norm[1] >= box_norm[1] and sub_norm[3] <= box_norm[3])
