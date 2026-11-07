"""
GFF 2025 Orchestrator.
Brand segregation → carousel → reel → stories → StepOne copy.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from api.logger import get_logger
    _log = get_logger("content_engine.gff.orchestrator")
except Exception:
    import logging
    _log = logging.getLogger("content_engine.gff.orchestrator")

try:
    from config import settings as _settings
    _IMAGE_EXTS = set(_settings.allowed_image_extensions)
    _VIDEO_EXTS = set(_settings.allowed_video_extensions)
except Exception:
    _IMAGE_EXTS = {
        ".jpg", ".jpeg", ".jpe", ".png", ".webp", ".bmp", ".dib", ".tif",
        ".tiff", ".gif", ".heic", ".heif", ".avif", ".jfif",
    }
    _VIDEO_EXTS = {
        ".mp4", ".mov", ".qt", ".avi", ".mkv", ".webm", ".m4v", ".wmv",
        ".flv", ".f4v", ".mpg", ".mpeg", ".mpe", ".m2v", ".m2ts", ".mts",
        ".ts", ".3gp", ".3g2", ".ogv", ".asf", ".divx", ".dv", ".vob",
    }


def _safe_name(name: str) -> str:
    import re
    return re.sub(r"[^\w\-]", "_", name).strip("_")


def _discover(folder: str) -> Tuple[List[str], List[str]]:
    images, videos = [], []
    for f in Path(folder).rglob("*"):
        if "render_images" in f.parts:
            continue
        if f.suffix.lower() in _IMAGE_EXTS:
            images.append(str(f))
        elif f.suffix.lower() in _VIDEO_EXTS:
            videos.append(str(f))
    return sorted(images), sorted(videos)


class GFFOrchestrator:
    """
    Complete GFF 2025 pipeline.

    brands: List of (brand_id, brand_name, [render_paths])
    """

    def __init__(
        self,
        event_name: str,
        brands: List[Tuple[str, str, List[str]]],
        similarity_threshold: float = 0.45,
        use_llm: bool = False,
    ):
        self.event_name = event_name
        self.use_llm = use_llm
        self._brand_names: Dict[str, str] = {bid: bname for bid, bname, _ in brands}

        from content_engine.brand.brand_matcher import BrandMatcher
        self._matcher = BrandMatcher(brands, similarity_threshold=similarity_threshold)
        if not self._matcher.brands:
            raise ValueError(
                "No valid brand reference images found. Add render/logo images under "
                "render_images/<brand_id>/ or provide render_paths for each brand."
            )

    def run(
        self,
        asset_folder: str,
        output_root: str = "output",
        event_date: str = "",
    ) -> Path:
        """
        Full pipeline. Returns output directory path.
        """
        _log.info("gff_pipeline_start", event_name=self.event_name)

        images, videos = _discover(asset_folder)
        _log.info("assets_found", images=len(images), videos=len(videos))

        # ── Step 1: Segregate ──────────────────────────────────────────────────
        segregation = self._matcher.segregate(images)

        # ── Step 2: Output directory ───────────────────────────────────────────
        out_dir = Path(output_root) / _safe_name(self.event_name)
        out_dir.mkdir(parents=True, exist_ok=True)

        # ── Step 3: Per-brand content ──────────────────────────────────────────
        brand_results = {}

        for brand_id, brand_photos in segregation.items():
            if brand_id == "unmatched":
                self._save_unmatched(brand_photos, out_dir)
                continue

            brand_name = self._brand_names.get(brand_id, brand_id)
            brand_dir = out_dir / _safe_name(brand_id)
            brand_dir.mkdir(exist_ok=True)

            _log.info("processing_brand", brand=brand_id, photos=len(brand_photos))
            brand_results[brand_id] = self._process_brand(
                brand_id, brand_name, brand_photos, videos, brand_dir, event_date
            )

        # ── Step 4: Reports ────────────────────────────────────────────────────
        self._save_report(segregation, brand_results, out_dir)

        _log.info("gff_pipeline_complete", output=str(out_dir))
        return out_dir

    def _process_brand(
        self,
        brand_id: str,
        brand_name: str,
        photos: List[str],
        videos: List[str],
        brand_dir: Path,
        event_date: str,
    ) -> Dict:
        from content_engine.gff.carousel_generator import generate_carousel
        from content_engine.gff.stories_generator import generate_stories
        from content_engine.gff.reel_generator import generate_reel
        from content_engine.gff import stepone_voice as voice

        result: Dict = {"brand_id": brand_id, "brand_name": brand_name}

        # ── Carousel ───────────────────────────────────────────────────────────
        carousel_paths = []
        if photos:
            slides, ordered = generate_carousel(photos[:10])
            for i, slide in enumerate(slides, 1):
                p = brand_dir / f"carousel_{i}.jpg"
                slide.save(p, quality=95)
                carousel_paths.append(str(p))

            caption = voice.generate_carousel_caption(brand_name, self.event_name, len(slides))
            (brand_dir / "instagram_caption.txt").write_text(caption, encoding="utf-8")
            result["carousel_slides"] = len(carousel_paths)
            result["carousel_caption"] = caption

        # ── Stories ────────────────────────────────────────────────────────────
        story_paths = []
        if photos:
            story_caps = voice.generate_story_captions(brand_name, self.event_name, 4)
            frames = generate_stories(photos[:6], story_caps, num_frames=4)
            stories_dir = brand_dir / "stories"
            stories_dir.mkdir(exist_ok=True)
            for i, frame in enumerate(frames, 1):
                p = stories_dir / f"story_{i}.jpg"
                frame.save(p, quality=95)
                story_paths.append(str(p))
            (stories_dir / "story_captions.txt").write_text(
                "\n".join(f"Story {i}: {c}" for i, c in enumerate(story_caps, 1)),
                encoding="utf-8",
            )
            result["story_frames"] = len(story_paths)
            result["story_captions"] = story_caps

        # ── Reel ───────────────────────────────────────────────────────────────
        reel_ok = False
        reel_duration = 0.0
        if videos:
            # Use existing ContentEngine to get highlight clips for first video
            try:
                from content_engine.models.video_processing import VideoProcessor
                vp = VideoProcessor()
                clips = vp.extract_highlights(videos[0], target_duration=45)
                if clips:
                    reel_path = str(brand_dir / "reel.mp4")
                    reel_ok, reel_duration = generate_reel(videos[0], clips, reel_path)
                    if reel_ok:
                        reel_cap = voice.generate_reel_caption(brand_name, self.event_name, int(reel_duration))
                        (brand_dir / "reel_caption.txt").write_text(reel_cap, encoding="utf-8")
                        result["reel_duration"] = reel_duration
                        result["reel_caption"] = reel_cap
            except Exception as e:
                _log.warning("reel_failed", brand=brand_id, error=str(e))

        result["has_reel"] = reel_ok

        # ── Case study ─────────────────────────────────────────────────────────
        try:
            from content_engine.pipeline import ContentEngine
            from content_engine.case_study_generator import generate_case_study

            engine = ContentEngine(event_description=f"{brand_name} @ {self.event_name}")
            selections = engine.select_assets(photos[:20])
            if selections:
                md = generate_case_study(
                    selections=selections,
                    event_name=f"{brand_name} @ {self.event_name}",
                    event_date=event_date or datetime.now().strftime("%B %d, %Y"),
                    total_assets_processed=len(photos),
                )
                (brand_dir / "case_study.md").write_text(md, encoding="utf-8")
        except Exception as e:
            _log.warning("case_study_failed", brand=brand_id, error=str(e))

        return result

    def _save_unmatched(self, paths: List[str], out_dir: Path) -> None:
        if not paths:
            return
        unmatched_dir = out_dir / "unmatched"
        unmatched_dir.mkdir(exist_ok=True)
        (unmatched_dir / "unmatched_report.json").write_text(
            json.dumps({"count": len(paths), "paths": paths}, indent=2),
            encoding="utf-8",
        )

    def _save_report(
        self,
        segregation: Dict[str, List[str]],
        brand_results: Dict,
        out_dir: Path,
    ) -> None:
        from content_engine.brand.selection_logic import SELECTION_LOGIC

        report = {
            "event_name": self.event_name,
            "timestamp": datetime.now().isoformat(),
            "brands": {}
        }
        for brand_id, assets in segregation.items():
            report["brands"][brand_id] = {
                "photo_count": len(assets),
                "count": len(assets),
                "assets": [str(a) for a in assets],
                "result": brand_results.get(brand_id, {})
            }
        (out_dir / "selection_report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        (out_dir / "selection_logic.md").write_text(SELECTION_LOGIC, encoding="utf-8")
