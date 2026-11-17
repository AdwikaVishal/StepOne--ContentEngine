"""
Main Pipeline Orchestrator — ContentEngine
Coordinates all four ML models, scores every asset, and produces
platform-specific selections with human-readable explanations.
"""

import cv2
import math
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from .data_types import AssetMetadata, SelectionResult
from .models.quality import QualityAssessor
from .models.face_detection import FaceDetector
from .models.content_understanding import ContentUnderstander
from .models.video_processing import VideoProcessor
from content_engine.categories import (
    UNCERTAIN,
    OTHER,
    PEOPLE,
    label_to_category,
    labels_to_categories,
    normalize_category,
)

try:
    from api.logger import get_logger
    _log = get_logger("content_engine.pipeline")
except Exception:
    import logging
    _log = logging.getLogger("content_engine.pipeline")

try:
    from content_engine.ai_mode import is_cloud_testing
    from content_engine.providers.vision.mock import MockQualityAssessor, MockFaceDetector
except ImportError:
    is_cloud_testing = lambda: False
    MockQualityAssessor = QualityAssessor  # type: ignore
    MockFaceDetector = FaceDetector  # type: ignore

try:
    from config import settings as _cfg
    _QUALITY_FLOOR = _cfg.quality_min_score
    _FACE_CONF = _cfg.face_confidence_threshold
    _VIDEO_EXTENSIONS = set(_cfg.allowed_video_extensions)
except Exception:
    _QUALITY_FLOOR = 0.30
    _FACE_CONF = 0.35
    _VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
_WEIGHT_QUALITY   = 0.30
_WEIGHT_AESTHETIC = 0.20
_WEIGHT_FACES     = 0.30
_WEIGHT_CONCEPTS  = 0.20
_LOW_CONFIDENCE_THRESHOLD = 0.50


# ── Classification ──────────────────────────────────────────────────────────

def _classify_asset(
    face_count: int,
    scene_concepts: List[str],
    relevance_scores: Dict[str, float],
) -> tuple:
    """
    Classify an asset into a canonical category using genuine available signals.

    Signals used:
      - Face count (YOLOv11): > 0 indicates people are present.
      - Scene concepts (Florence-2 <OD>): mapped to categories via keyword matching.
      - Relevance scores (CLIP): weight the concept-to-category votes.

    Returns (category, confidence, explanation) where:
      - category is a canonical category identifier.
      - confidence is 0.0–1.0 reflecting how strongly the signals support the category.
      - explanation is a dict with structured diagnostic evidence for the assignment.

    When signals are insufficient, returns (UNCERTAIN, 0.0, explanation) — never invents
    a classification or silently coerces to OTHER.

    Face detection alone cannot prove an asset belongs to any specific event category;
    it only contributes a "people" vote when faces are actually detected.
    """
    # Gather category votes from detected scene concepts.
    concept_votes = labels_to_categories(scene_concepts)

    # Face presence adds a people vote when faces are actually detected.
    face_contribution = 0
    if face_count > 0:
        concept_votes[PEOPLE] = concept_votes.get(PEOPLE, 0) + 1
        face_contribution = 1

    # Build CLIP relevance evidence for categories that received votes.
    clip_evidence: Dict[str, float] = {}
    if relevance_scores:
        for concept, score in relevance_scores.items():
            if _is_valid_score(score):
                cat = label_to_category(concept)
                if cat is not None and cat in concept_votes:
                    clip_evidence[concept] = round(float(score), 4)

    if not concept_votes:
        # No detectable signal at all — uncertain, not other.
        explanation = {
            "classification_method": "heuristic_signal_fusion",
            "face_count": face_count,
            "face_contribution": face_contribution,
            "scene_concepts": list(scene_concepts),
            "clip_relevance": clip_evidence,
            "category_votes": {},
            "winning_category": None,
            "competing_categories": {},
            "missing_signals": ["scene_concepts", "clip_relevance"],
            "is_uncertain": True,
        }
        return UNCERTAIN, 0.0, explanation

    # Pick the category with the most votes.
    best_category = max(concept_votes, key=lambda k: concept_votes[k])
    best_votes = concept_votes[best_category]
    total_votes = sum(concept_votes.values())

    # Competing categories (all except the winner).
    competing = {k: v for k, v in concept_votes.items() if k != best_category}

    # Confidence reflects vote concentration: if one category dominates,
    # confidence is higher. If votes are split, confidence is lower.
    vote_share = best_votes / total_votes if total_votes > 0 else 0.0

    # Boost confidence when relevance scores support the winning category.
    relevance_boost = 0.0
    if relevance_scores:
        for concept, score in relevance_scores.items():
            cat = label_to_category(concept)
            if cat == best_category and _is_valid_score(score) and score > 0.5:
                relevance_boost = max(relevance_boost, min(1.0, float(score)))
                break

    confidence = min(1.0, vote_share * 0.7 + relevance_boost * 0.3)

    # Determine missing signals.
    missing_signals: List[str] = []
    if not scene_concepts:
        missing_signals.append("scene_concepts")
    if not relevance_scores:
        missing_signals.append("clip_relevance")
    if face_count == 0:
        missing_signals.append("face_detection")

    # If confidence is too low to be meaningful, return uncertain.
    is_uncertain = confidence < 0.30
    if is_uncertain:
        explanation = {
            "classification_method": "heuristic_signal_fusion",
            "face_count": face_count,
            "face_contribution": face_contribution,
            "scene_concepts": list(scene_concepts),
            "clip_relevance": clip_evidence,
            "category_votes": dict(concept_votes),
            "winning_category": best_category,
            "competing_categories": competing,
            "missing_signals": missing_signals,
            "is_uncertain": True,
        }
        return UNCERTAIN, confidence, explanation

    explanation = {
        "classification_method": "heuristic_signal_fusion",
        "face_count": face_count,
        "face_contribution": face_contribution,
        "scene_concepts": list(scene_concepts),
        "clip_relevance": clip_evidence,
        "category_votes": dict(concept_votes),
        "winning_category": best_category,
        "competing_categories": competing,
        "missing_signals": missing_signals,
        "is_uncertain": False,
    }
    return best_category, confidence, explanation


# ── Availability-aware scoring (D-006) ──────────────────────────────────────

def _is_valid_score(value: object) -> bool:
    """
    Return True when value is a genuine, finite score in [0, 1].

    Rejects None, non-numeric types, booleans, NaN, infinity, and out-of-range
    values. A successfully executed detector returning 0.0 is a valid measured
    zero; an unavailable or failed measurement returns None or an invalid value.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    if math.isnan(f) or math.isinf(f):
        return False
    return 0.0 <= f <= 1.0


# Recognized scoring signal names — the only weight keys permitted.
_RECOGNIZED_WEIGHT_KEYS = {"quality", "aesthetic", "faces", "concepts"}


def _validate_weights(weights: Dict[str, float]) -> Dict[str, float]:
    """
    Validate and normalize a weight configuration dict.

    Only the four recognized scoring signals are permitted as weight keys:
    quality, aesthetic, faces, concepts. Unknown keys are rejected with an
    actionable error so they cannot mask an all-zero recognized configuration.

    Rejects negative, NaN, infinite, boolean, and non-numeric values.
    Ensures the sum of recognized weights is positive so renormalization
    is possible. Returns a copy of the validated weights dict containing
    only recognized keys.
    """
    validated: Dict[str, float] = {}
    for name, value in weights.items():
        if name not in _RECOGNIZED_WEIGHT_KEYS:
            raise ValueError(
                f"Unknown weight key '{name}'. "
                f"Allowed scoring signals: {sorted(_RECOGNIZED_WEIGHT_KEYS)}."
            )
        if isinstance(value, bool):
            raise ValueError(
                f"Weight for '{name}' must be a numeric score, got boolean {value!r}"
            )
        if not isinstance(value, (int, float)):
            raise ValueError(
                f"Weight for '{name}' must be numeric, got {type(value).__name__}"
            )
        fval = float(value)
        if math.isnan(fval):
            raise ValueError(f"Weight for '{name}' must not be NaN")
        if math.isinf(fval):
            raise ValueError(f"Weight for '{name}' must not be infinite")
        if fval < 0.0:
            raise ValueError(f"Weight for '{name}' must not be negative ({fval})")
        validated[name] = fval

    total = sum(validated[name] for name in _RECOGNIZED_WEIGHT_KEYS if name in validated)
    if total <= 0.0:
        raise ValueError(
            "At least one recognized scoring weight must be positive; "
            f"recognized weights sum to {total}, which makes renormalization impossible"
        )

    return validated


def compute_availability_aware_score(
    quality_score: Optional[float] = None,
    aesthetic_score: Optional[float] = None,
    face_score: Optional[float] = None,
    concept_score: Optional[float] = None,
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, object]:
    """
    Compute a composite ranking score using only genuinely available signals.

    Signals that are unavailable (None, invalid, or failed model call) are
    excluded and their weights are renormalized over the remaining signals.
    A measured zero (e.g. no faces detected by a working detector) is treated
    as available evidence and contributes 0.0 to the weighted sum.

    Args:
        quality_score: technical quality score (0-1), or None if unavailable.
        aesthetic_score: aesthetic quality score (0-1), or None if unavailable.
        face_score: face presence score (0-1), or None if unavailable.
        concept_score: concept match score (0-1), or None if unavailable.
        weights: optional dict mapping signal name -> raw weight. Defaults to
            the module-level _WEIGHT_* constants. Invalid weights raise
            ValueError.

    Returns:
        dict with keys:
            - score: float (0-1), 0.0 when no signals are available.
            - score_valid: True when at least one signal was available and
              contributed to the score; False when no signals were available.
            - available_signals: list of signal names that contributed.
            - missing_signals: list of signal names that were unavailable.
            - effective_weights: dict mapping signal name -> renormalized weight.
            - is_partial: True when at least one expected signal was missing.
    """
    if weights is None:
        weights = {
            "quality": _WEIGHT_QUALITY,
            "aesthetic": _WEIGHT_AESTHETIC,
            "faces": _WEIGHT_FACES,
            "concepts": _WEIGHT_CONCEPTS,
        }
    else:
        weights = _validate_weights(weights)

    signals = {
        "quality": quality_score,
        "aesthetic": aesthetic_score,
        "faces": face_score,
        "concepts": concept_score,
    }

    available: Dict[str, float] = {}
    missing: List[str] = []

    for name, value in signals.items():
        if _is_valid_score(value):
            available[name] = float(value)
        else:
            missing.append(name)

    # Build effective weights for all four signal names (not just weight keys).
    effective_weights: Dict[str, float] = {
        "quality": 0.0,
        "aesthetic": 0.0,
        "faces": 0.0,
        "concepts": 0.0,
    }

    if not available:
        # No signals available — no fabricated score. score_valid=False lets
        # callers distinguish this from a measured 0.0.
        return {
            "score": 0.0,
            "score_valid": False,
            "available_signals": [],
            "missing_signals": missing,
            "effective_weights": effective_weights,
            "is_partial": True,
        }

    total_weight = sum(weights[name] for name in available if name in weights)

    if total_weight <= 0.0:
        # All available signals have zero weight — cannot renormalize.
        return {
            "score": 0.0,
            "score_valid": False,
            "available_signals": list(available.keys()),
            "missing_signals": missing,
            "effective_weights": effective_weights,
            "is_partial": bool(missing),
        }

    weighted_sum = sum(available[name] * weights[name] for name in available if name in weights)
    score = round(weighted_sum / total_weight, 4)

    for name in effective_weights:
        if name in available and name in weights:
            effective_weights[name] = round(weights[name] / total_weight, 4)

    return {
        "score": score,
        "score_valid": True,
        "available_signals": list(available.keys()),
        "missing_signals": missing,
        "effective_weights": effective_weights,
        "is_partial": bool(missing),
    }


class ContentEngine:
    def __init__(
        self,
        event_description: str,
        event_concepts: Optional[List[str]] = None,
        quality_assessor: Optional[object] = None,
        face_detector: Optional[object] = None,
        content_understander: Optional[object] = None,
        video_processor: Optional[object] = None,
    ):
        self.event_description = event_description

        # Cloud testing mode: use mock adapters, no local model loading
        if is_cloud_testing():
            self.quality_assessor    = quality_assessor or MockQualityAssessor()
            self.face_detector       = face_detector or MockFaceDetector()
            # ContentUnderstander and VideoProcessor handle cloud routing internally
            self.content_understander = content_understander or ContentUnderstander(
                event_concepts=event_concepts,
            )
            self.video_processor     = video_processor or VideoProcessor()
        else:
            self.quality_assessor    = quality_assessor or QualityAssessor()
            self.face_detector       = face_detector or FaceDetector()
            self.content_understander = content_understander or ContentUnderstander(
                event_concepts=event_concepts,
            )
            self.video_processor     = video_processor or VideoProcessor()
        _log.info("models_ready")
    # ------------------------------------------------------------------
    # Asset processing
    # ------------------------------------------------------------------

    def _process_image(self, asset_path: str) -> Optional[AssetMetadata]:
        """Score a single image through all four models.

        Uses availability-aware scoring (D-006): only signals that were
        successfully computed contribute to the final score. Unavailable
        signals are excluded and their weights are renormalized. A measured
        zero (e.g. no faces detected by a working detector) is treated as
        available evidence, not as a missing signal.
        """
        # ── Quality assessment ──────────────────────────────────────────
        quality_available = True
        try:
            quality = self.quality_assessor.assess(asset_path)
        except Exception:
            quality_available = False
            quality = {
                "blur_score": 0.0,
                "brightness_score": 0.0,
                "aesthetic_score": 0.0,
                "quality_score": 0.0,
            }

        quality_score = quality.get("quality_score") if quality_available else None
        aesthetic_score = quality.get("aesthetic_score") if quality_available else None

        # Technical quality = blur + brightness only (exclude aesthetic so metrics stay separated)
        if quality_available:
            technical_quality = round(
                quality["blur_score"] * 0.5 + quality["brightness_score"] * 0.3, 4
            )
        else:
            technical_quality = 0.0

        # ── Face detection ──────────────────────────────────────────────
        face_available = True
        try:
            face_result = self.face_detector.detect_faces_detailed(asset_path)
        except Exception:
            face_available = False
            face_result = {
                "face_count": 0,
                "confidences": [],
                "bboxes": [],
                "bboxes_norm": [],
                "weights": [],
                "weighted_score": 0.0,
            }

        # Item 13: use weighted_score (size-aware) instead of raw count
        face_score = face_result.get("weighted_score") if face_available else None

        # ── Content understanding ───────────────────────────────────────
        concept_available = True
        try:
            content = self.content_understander.understand_image(asset_path)
        except Exception:
            concept_available = False
            content = {
                "scene_concepts": [],
                "relevance_scores": {},
                "concept_match_score": None,
            }

        # concept_match_score may be None when cloud provider cannot
        # compute CLIP-equivalent similarity; None = unavailable, 0.0 = measured zero
        concept_match_score = content.get("concept_match_score")
        if concept_match_score is None:
            concept_available = False

        # ── Brand relevance (brand name similarity) ─────────────────────────────────
        brand_relevance = 0.0
        if hasattr(content, 'brand_scores'):
            brand_scores = content.get('brand_scores', {})
            if brand_scores:
                # Take the maximum brand similarity score
                brand_relevance = max(brand_scores.values())
        
        # ── Model confidence (if available) ─────────────────────────────────────
        # Use the concept_match_score if it's a calibrated confidence,
        # otherwise treat it as semantic relevance
        model_confidence = concept_match_score if concept_available else None

        # ── Final ranking score (availability-aware, D-006) ──────────────────────
        scoring = compute_availability_aware_score(
            quality_score=quality_score,
            aesthetic_score=aesthetic_score,
            face_score=face_score,
            concept_score=concept_match_score,
        )
        final_score = scoring["score"]
        score_valid = scoring["score_valid"]

        # ── Classification ──────────────────────────────────────────────────────
        # Uses genuine signals only: face count + Florence-2 scene concepts +
        # CLIP relevance scores. Returns UNCERTAIN when signals are insufficient
        # — never invents a classification or silently coerces to OTHER.
        category, class_conf, classification_explanation = _classify_asset(
            face_count=face_result.get("face_count", 0),
            scene_concepts=content.get("scene_concepts", []),
            relevance_scores=content.get("relevance_scores", {}),
        )

        return AssetMetadata(
            path=asset_path,
            asset_type="image",
            quality_score=quality.get("quality_score", 0.0),
            aesthetic_score=quality.get("aesthetic_score", 0.0),
            face_count=face_result.get("face_count", 0),
            face_confidences=face_result.get("confidences", []),
            relevance_scores=content.get("relevance_scores", {}),
            scene_concepts=content.get("scene_concepts", []),
            final_score=final_score,
            # Separated metrics (do not conflate)
            technical_quality=technical_quality,
            semantic_relevance=concept_match_score if concept_match_score is not None else 0.0,
            brand_relevance=brand_relevance,
            model_confidence=model_confidence if model_confidence is not None else 0.0,
            uncalibrated=True,
            classification=category,
            classification_confidence=class_conf,
            classification_explanation=classification_explanation,
            # Score provenance (D-006)
            score_available_signals=scoring["available_signals"],
            score_missing_signals=scoring["missing_signals"],
            score_effective_weights=scoring["effective_weights"],
            score_is_partial=scoring["is_partial"],
            score_valid=score_valid,
        )

    def _best_video_frame(self, asset_path: str, cap: cv2.VideoCapture,
                          total_frames: int, fps: float) -> Optional[np.ndarray]:
        """
        Sample up to 5 evenly-spaced frames and return the one with the
        highest quality score. This avoids rejecting a video because the
        single sampled frame happened to be a title card or fade.
        """
        # Sample at 10%, 25%, 40%, 55%, 70% — avoids intros and outros
        sample_positions = [0.10, 0.25, 0.40, 0.55, 0.70]
        best_frame = None
        best_score = -1.0

        temp_path = str(Path(asset_path).with_suffix("._tmp_probe.jpg"))

        for pct in sample_positions:
            idx = max(0, int(total_frames * pct))
            if idx >= total_frames:
                continue
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                continue

            # Quick blur score only — fast, no model needed
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            score = cv2.Laplacian(gray, cv2.CV_64F).var()
            if score > best_score:
                best_score = score
                best_frame = frame

        Path(temp_path).unlink(missing_ok=True)
        return best_frame

    def _process_video(self, asset_path: str) -> Optional[AssetMetadata]:
        """
        Score a video by:
          1. Sampling 5 frames and picking the sharpest one (avoids title cards)
          2. Running image models on that best frame
          3. Skipping the quality floor — video frames are inherently blurrier
             than photos; the floor is only meaningful for still images
          4. Extracting highlight clips and adjusting the final score

        Uses availability-aware scoring (D-006): only signals that were
        successfully computed contribute to the base score. Unavailable
        signals are excluded and their weights are renormalized. Video-specific
        highlight adjustment is applied after the base score is computed.
        """
        cap = cv2.VideoCapture(asset_path)
        if not cap.isOpened():
            _log.warning("video_open_failed", asset=Path(asset_path).name)
            return None

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        duration = total_frames / fps

        if total_frames == 0:
            _log.warning("video_no_frames", asset=Path(asset_path).name)
            cap.release()
            return None

        # Pick the sharpest of 5 sampled frames
        best_frame = self._best_video_frame(asset_path, cap, total_frames, fps)
        cap.release()

        if best_frame is None:
            _log.warning("video_frame_read_failed", asset=Path(asset_path).name)
            return None

        # Write temp frame for image models
        temp_frame_path = str(Path(asset_path).with_suffix("._tmp_frame.jpg"))
        cv2.imwrite(temp_frame_path, best_frame)

        # ── Quality assessment ──────────────────────────────────────────
        quality_available = True
        try:
            quality = self.quality_assessor.assess(temp_frame_path)
        except Exception:
            quality_available = False
            quality = {
                "blur_score": 0.0,
                "brightness_score": 0.0,
                "aesthetic_score": 0.0,
                "quality_score": 0.0,
            }
        finally:
            Path(temp_frame_path).unlink(missing_ok=True)

        quality_score = quality.get("quality_score") if quality_available else None
        aesthetic_score = quality.get("aesthetic_score") if quality_available else None

        # Technical quality = blur + brightness only
        if quality_available:
            technical_quality = round(
                quality["blur_score"] * 0.5 + quality["brightness_score"] * 0.3, 4
            )
        else:
            technical_quality = 0.0

        # ── Face detection ──────────────────────────────────────────────
        face_available = True
        try:
            face_result = self.face_detector.detect_faces_detailed(temp_frame_path)
        except Exception:
            face_available = False
            face_result = {
                "face_count": 0,
                "confidences": [],
                "bboxes": [],
                "bboxes_norm": [],
                "weights": [],
                "weighted_score": 0.0,
            }

        # Item 13: use weighted_score (size-aware) instead of raw count
        face_score = face_result.get("weighted_score") if face_available else None

        # ── Content understanding ───────────────────────────────────────
        concept_available = True
        try:
            content = self.content_understander.understand_image(temp_frame_path)
        except Exception:
            concept_available = False
            content = {
                "scene_concepts": [],
                "relevance_scores": {},
                "concept_match_score": None,
            }

        # concept_match_score may be None when cloud provider cannot
        # compute CLIP-equivalent similarity; None = unavailable, 0.0 = measured zero
        concept_match_score = content.get("concept_match_score")
        if concept_match_score is None:
            concept_available = False

        # ── Brand relevance (brand name similarity) ─────────────────────────────────
        brand_relevance = 0.0
        if hasattr(content, 'brand_scores'):
            brand_scores = content.get('brand_scores', {})
            if brand_scores:
                # Take the maximum brand similarity score
                brand_relevance = max(brand_scores.values())

        # ── Model confidence (if available) ─────────────────────────────────────
        model_confidence = concept_match_score if concept_available else None

        # ── Base ranking score (availability-aware, D-006) ──────────────────────
        scoring = compute_availability_aware_score(
            quality_score=quality_score,
            aesthetic_score=aesthetic_score,
            face_score=face_score,
            concept_score=concept_match_score,
        )
        base_score = scoring["score"]
        score_valid = scoring["score_valid"]

        # ── Classification ──────────────────────────────────────────────────────
        category, class_conf, classification_explanation = _classify_asset(
            face_count=face_result.get("face_count", 0),
            scene_concepts=content.get("scene_concepts", []),
            relevance_scores=content.get("relevance_scores", {}),
        )

        metadata = AssetMetadata(
            path=asset_path,
            asset_type="video",
            quality_score=quality.get("quality_score", 0.0),
            aesthetic_score=quality.get("aesthetic_score", 0.0),
            face_count=face_result.get("face_count", 0),
            face_confidences=face_result.get("confidences", []),
            relevance_scores=content.get("relevance_scores", {}),
            scene_concepts=content.get("scene_concepts", []),
            duration=duration,
            final_score=base_score,
            # Score provenance (D-006) — set before highlight adjustment
            score_available_signals=scoring["available_signals"],
            score_missing_signals=scoring["missing_signals"],
            score_effective_weights=scoring["effective_weights"],
            score_is_partial=scoring["is_partial"],
            score_valid=score_valid,
            # Classification diagnostics (D-008/D-009)
            classification_explanation=classification_explanation,
        )

        # Extract highlights and adjust score by highlight quality (with timeout)
        # Highlight extraction requires ffmpeg/ffprobe; if unavailable, the video
        # is still a valid asset — it just won't have highlight clips for reel
        # assembly.
        try:
            import signal
            class TimeoutException(Exception):
                pass
            def timeout_handler(signum, frame):
                raise TimeoutException("Highlight extraction timed out")
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(60)  # 60 second timeout
            try:
                highlights = self.video_processor.extract_highlights(asset_path, target_duration=45)
                metadata.highlight_clips = highlights
                if highlights:
                    avg_highlight_score = float(np.mean([h["score"] for h in highlights]))
                    metadata.final_score *= 0.5 + 0.5 * avg_highlight_score
            except TimeoutException:
                metadata.highlight_clips = []
            finally:
                signal.alarm(0)
        except Exception:
            metadata.highlight_clips = []

        # Update AssetMetadata with additional metrics
        metadata.technical_quality = technical_quality
        metadata.semantic_relevance = concept_match_score if concept_match_score is not None else 0.0
        metadata.brand_relevance = brand_relevance
        metadata.model_confidence = model_confidence if model_confidence is not None else 0.0
        metadata.uncalibrated = True
        metadata.classification = category
        metadata.classification_confidence = class_conf

        return metadata

    def process_asset(self, asset_path: str) -> Optional[AssetMetadata]:
        """Route a single asset to the correct processing path."""
        suffix = Path(asset_path).suffix.lower()
        _log.info("processing_asset", asset=Path(asset_path).name)

        if suffix in _VIDEO_EXTENSIONS:
            return self._process_video(asset_path)
        return self._process_image(asset_path)

    def process_assets_parallel(self, asset_paths: List[str], max_workers: Optional[int] = None) -> List[AssetMetadata]:
        """Process assets in parallel using ThreadPoolExecutor.

        Concurrency is bounded to protect the RTX 4050's 6 GB VRAM: models are
        shared across workers, so only a small number of concurrent GPU inference
        streams is needed. Defaults to ``settings.pipeline_max_workers``
        (``CE_PIPELINE_MAX_WORKERS`` env var, default 2).
        """
        if max_workers is None:
            max_workers = _cfg.pipeline_max_workers
        results = []
        total = len(asset_paths)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_path = {
                executor.submit(self.process_asset, path): path
                for path in asset_paths
            }

            for idx, future in enumerate(as_completed(future_to_path)):
                try:
                    result = future.result()
                    if result:
                        results.append(result)
                except Exception as e:
                    path = future_to_path.get(future, "unknown")
                    _log.error("parallel_asset_failed", asset=path, error=str(e))

        return results

    def select_assets_parallel(self, asset_list: List[str]) -> List[SelectionResult]:
        """Parallel version of select_assets for 3-4x speedup."""
        _log.info('pipeline_start_parallel', total_assets=len(asset_list))

        image_paths = [p for p in asset_list if Path(p).suffix.lower() not in _VIDEO_EXTENSIONS]
        if image_paths:
            cal = self.quality_assessor.calibrate_batch(image_paths)
            if cal.get("calibrated"):
                _log.info(
                    "thresholds_calibrated",
                    blur_threshold=cal.get("blur_threshold"),
                    brightness_center=cal.get("brightness_center"),
                    brightness_tolerance=cal.get("brightness_tolerance"),
                    sample_size=cal.get("sample_size"),
                )

        all_assets = self.process_assets_parallel(asset_list)

        if not all_assets:
            _log.warning("no_assets_passed_filtering")
            return []

        all_assets.sort(key=lambda a: a.final_score, reverse=True)
        return self._select_from_scored(all_assets)

    # ------------------------------------------------------------------
    # Selection logic
    # ------------------------------------------------------------------

    def select_assets(self, asset_list: List[str]) -> List[SelectionResult]:
        """
        Process all assets and select the best ones per platform.

        Item 18: Auto-calibrates quality thresholds on the first 20 images
        before scoring any assets, so thresholds adapt to the event's lighting.
        """
        _log.info('pipeline_start', total_assets=len(asset_list))

        # Item 18: Calibrate quality thresholds on image sample
        image_paths = [p for p in asset_list if Path(p).suffix.lower() not in _VIDEO_EXTENSIONS]
        if image_paths:
            cal = self.quality_assessor.calibrate_batch(image_paths)
            if cal.get("calibrated"):
                _log.info(
                    "thresholds_calibrated",
                    blur_threshold=cal.get("blur_threshold"),
                    brightness_center=cal.get("brightness_center"),
                    brightness_tolerance=cal.get("brightness_tolerance"),
                    sample_size=cal.get("sample_size"),
                )

        all_assets: List[AssetMetadata] = []
        for path in asset_list:
            metadata = self.process_asset(path)
            if metadata:
                all_assets.append(metadata)

        if not all_assets:
            _log.warning("no_assets_passed_filtering")
            return []

        all_assets.sort(key=lambda a: a.final_score, reverse=True)
        return self._select_from_scored(all_assets)

    def _select_from_scored(self, all_assets: List[AssetMetadata]) -> List[SelectionResult]:
        """Select assets for each platform from already-scored list."""
        images = [a for a in all_assets if a.asset_type == "image"]
        videos = [a for a in all_assets if a.asset_type == "video"]

        selections: List[SelectionResult] = []

        # --- LinkedIn Collage (4–6 images, prefer group shots) ----------
        collage_pool = sorted(
            [a for a in images if a.face_count >= 2],
            key=lambda a: a.final_score,
            reverse=True,
        )
        if len(collage_pool) < 4:
            collage_pool = images

        for asset in collage_pool[:6]:
            selections.append(SelectionResult(
                asset=asset,
                selection_reason=self._explain(asset, "collage"),
                confidence=asset.final_score,
                intended_use="collage",
            ))

        # --- Instagram Reel (best video) --------------------------------
        if videos:
            best_video = videos[0]
            selections.append(SelectionResult(
                asset=best_video,
                selection_reason=self._explain(best_video, "reel"),
                confidence=best_video.final_score,
                intended_use="reel",
            ))

        # --- Instagram Stories (3–4 visually diverse images) -----------
        story_picks: List[AssetMetadata] = []
        used_concepts: set = set()

        for asset in images:
            if len(story_picks) >= 4:
                break
            asset_concepts = set(asset.scene_concepts[:2])
            if not asset_concepts.intersection(used_concepts) or len(story_picks) == 0:
                story_picks.append(asset)
                used_concepts.update(asset_concepts)

        for asset in story_picks:
            selections.append(SelectionResult(
                asset=asset,
                selection_reason=self._explain(asset, "story"),
                confidence=asset.final_score,
                intended_use="story",
            ))

        # --- Case Study (top 2 concept-rich images) --------------------
        case_study_pool = sorted(
            images,
            key=lambda a: max(a.relevance_scores.values()) if a.relevance_scores else 0.0,
            reverse=True,
        )
        for asset in case_study_pool[:2]:
            selections.append(SelectionResult(
                asset=asset,
                selection_reason=self._explain(asset, "case_study"),
                confidence=asset.final_score,
                intended_use="case_study",
            ))

        return selections

    # ------------------------------------------------------------------
    # Explainability
    # ------------------------------------------------------------------

    def _explain(self, asset: AssetMetadata, platform: str) -> str:
        """Generate a plain-English reason for why this asset was selected."""
        reasons: List[str] = []

        # Quality tier
        if asset.quality_score >= 0.8:
            reasons.append("high technical quality")
        elif asset.quality_score >= 0.6:
            reasons.append("good quality")
        else:
            reasons.append("acceptable quality")

        # Face presence
        if asset.face_count > 5:
            reasons.append(f"{asset.face_count} faces (strong group energy)")
        elif asset.face_count > 0:
            reasons.append(f"{asset.face_count} face(s) visible")

        # Top matching concepts
        top_concepts = [
            concept
            for concept, score in sorted(
                asset.relevance_scores.items(), key=lambda x: x[1], reverse=True
            )[:2]
            if score > 0.5
        ]
        if top_concepts:
            reasons.append(f"captures {', '.join(top_concepts)}")

        # Platform-specific additions
        if platform == "reel" and asset.highlight_clips:
            total_secs = sum(c["end"] - c["start"] for c in asset.highlight_clips)
            reasons.append(
                f"{len(asset.highlight_clips)} highlight clips ({total_secs:.0f}s total)"
            )

        reason_str = "; ".join(reasons) if reasons else "best available asset"
        platform_labels = {
            "collage": "LinkedIn collage",
            "reel": "Instagram Reel",
            "story": "Instagram Story",
            "case_study": "case study",
        }
        return f"Selected for {platform_labels.get(platform, platform)}: {reason_str}."
