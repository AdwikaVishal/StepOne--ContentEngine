"""
Main Pipeline Orchestrator — ContentEngine
Coordinates all four ML models, scores every asset, and produces
platform-specific selections with human-readable explanations.
"""

import cv2
import numpy as np
from pathlib import Path
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from .data_types import AssetMetadata, SelectionResult
from .models.quality import QualityAssessor
from .models.face_detection import FaceDetector
from .models.content_understanding import ContentUnderstander
from .models.video_processing import VideoProcessor

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
        """Score a single image through all four models."""
        quality = self.quality_assessor.assess(asset_path)

        if quality["quality_score"] < _QUALITY_FLOOR:
            _log.info('asset_rejected', reason='quality_floor', quality=round(quality['quality_score'],2), asset=Path(asset_path).name)
            return None

        face_result = self.face_detector.detect_faces_detailed(asset_path)
        content = self.content_understander.understand_image(asset_path)

        # Item 13: use weighted_score (size-aware) instead of raw count
        face_score = face_result["weighted_score"]
        # concept_match_score may be None when cloud provider cannot
        # compute CLIP-equivalent similarity; treat as 0.0 for scoring
        concept_match_score = content["concept_match_score"]
        if concept_match_score is None:
            concept_match_score = 0.0
        final_score = (
            quality["quality_score"] * _WEIGHT_QUALITY
            + quality["aesthetic_score"] * _WEIGHT_AESTHETIC
            + face_score * _WEIGHT_FACES
            + concept_match_score * _WEIGHT_CONCEPTS
        )

        return AssetMetadata(
            path=asset_path,
            asset_type="image",
            quality_score=quality["quality_score"],
            aesthetic_score=quality["aesthetic_score"],
            face_count=face_result["face_count"],
            face_confidences=face_result["confidences"],
            relevance_scores=content["relevance_scores"],
            scene_concepts=content["scene_concepts"],
            final_score=final_score,
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

        try:
            quality = self.quality_assessor.assess(temp_frame_path)
            face_result = self.face_detector.detect_faces_detailed(temp_frame_path)
            content = self.content_understander.understand_image(temp_frame_path)
        finally:
            Path(temp_frame_path).unlink(missing_ok=True)

        face_score = face_result["weighted_score"]
        final_score = (
            quality["quality_score"] * _WEIGHT_QUALITY
            + quality["aesthetic_score"] * _WEIGHT_AESTHETIC
            + face_score * _WEIGHT_FACES
            + content["concept_match_score"] * _WEIGHT_CONCEPTS
        )

        metadata = AssetMetadata(
            path=asset_path,
            asset_type="video",
            quality_score=quality["quality_score"],
            aesthetic_score=quality["aesthetic_score"],
            face_count=face_result["face_count"],
            face_confidences=face_result["confidences"],
            relevance_scores=content["relevance_scores"],
            scene_concepts=content["scene_concepts"],
            duration=duration,
            final_score=final_score,
        )

        # Extract highlights and adjust score by highlight quality (with timeout)
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

        return metadata

    def process_asset(self, asset_path: str) -> Optional[AssetMetadata]:
        """Route a single asset to the correct processing path."""
        suffix = Path(asset_path).suffix.lower()
        _log.info("processing_asset", asset=Path(asset_path).name)

        if suffix in _VIDEO_EXTENSIONS:
            return self._process_video(asset_path)
        return self._process_image(asset_path)

    def process_assets_parallel(self, asset_paths: List[str], max_workers: int = 8) -> List[AssetMetadata]:
        """Process assets in parallel using ThreadPoolExecutor for 3-4x speedup."""
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
