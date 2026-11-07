"""
BrandOrchestrator
End-to-end pipeline for GFF 2025 challenge:
1. Segregate photos into brands using CLIP similarity
2. Generate brand-specific content (carousel, reel, stories)
3. Output organized per brand folder

Output structure:
  output/<EventName>/
    ├── selection_report.json      # Full segregation results
    ├── selection_logic.md         # Documented decision process
    ├── unmatched/                 # Photos not assigned to any brand
    ├── brand_A/
    │   ├── carousel_1.jpg … _N.jpg
    │   ├── instagram_caption.txt
    │   ├── reel.mp4 (if video assets present)
    │   ├── reel_caption.txt
    │   ├── stories/
    │   │   ├── story_1.jpg … _4.jpg
    │   │   └── story_captions.txt
    │   └── case_study.md
    ├── brand_B/  ...
    └── brand_C/  ...

Usage:
    from content_engine.brand_orchestrator import BrandOrchestrator

    orch = BrandOrchestrator(
        event_name="GFF 2025",
        brands=[
            ("brand_a", "Brand A Name", ["/path/to/render1.jpg", "/path/to/render2.jpg"]),
            ("brand_b", "Brand B Name", ["/path/to/render3.jpg"]),
            # ... more brands
        ],
        similarity_threshold=0.60,
    )
    output_dir = orch.run(
        asset_folder="path/to/event/photos/",
        output_root="output",
    )
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Tuple

from content_engine.brand_segregator import BrandSegregator, AssetClassification
from content_engine.pipeline import ContentEngine
from content_engine.layout_assembler import LayoutAssembler
from content_engine.copy_generator import CopyGenerator
from content_engine.case_study_generator import generate_case_study
from content_engine.data_types import AssetMetadata, SelectionResult

try:
    from api.logger import get_logger
    _log = get_logger("content_engine.brand_orchestrator")
except Exception:
    import logging
    _log = logging.getLogger("content_engine.brand_orchestrator")


# Supported file extensions
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
_ALL_EXTS = _IMAGE_EXTS | _VIDEO_EXTS

# Image quality threshold for content generation
_QUALITY_THRESHOLD = 0.30


def _safe_dirname(name: str) -> str:
    """Convert name to a safe directory name."""
    return re.sub(r"[^\w\-]", "_", name).strip("_")


def _discover_assets(folder: str) -> List[str]:
    """Recursively find all supported image/video files."""
    assets = []
    for ext in _ALL_EXTS:
        assets.extend(str(p) for p in Path(folder).rglob(f"*{ext}"))
    return sorted(set(assets))


class BrandOrchestrator:
    """
    Orchestrates brand-specific content generation.

    Flow:
      1. BrandSegregator classifies all photos into brands
      2. For each brand:
         a. Run ML pipeline to score and select best assets
         b. Generate carousel, reel, stories
         c. Generate brand-aware copy
         d. Write case study
      3. Write overall selection report

    Selection Logic:
      - Brand classification: CLIP cosine similarity > threshold (default 0.60)
      - Within brand: Quality (30%) + Aesthetic (20%) + Faces (30%) + Concepts (20%)
      - Minimum 5 assets per brand for valid output
      - Unmatched photos collected separately for manual review
    """

    # Carousel configuration
    CAROUSEL_MIN_SLIDES = 4
    CAROUSEL_MAX_SLIDES = 6

    # Reel configuration
    REEL_MIN_DURATION = 30  # seconds
    REEL_MAX_DURATION = 60  # seconds

    # Story configuration
    STORY_FRAME_COUNT = 4

    def __init__(
        self,
        event_name: str,
        brands: List[Tuple[str, str, List[str]]],  # (brand_id, brand_name, render_paths)
        similarity_threshold: float = 0.60,
        use_llm: bool = False,
    ):
        """
        Initialize BrandOrchestrator.

        Args:
            event_name: Name of the event
            brands: List of (brand_id, brand_name, render_paths) tuples
            similarity_threshold: Minimum CLIP similarity to assign a brand
            use_llm: Whether to use LLM for copy generation
        """
        self.event_name = event_name
        self.similarity_threshold = similarity_threshold

        _log.info("brand_orchestrator_init", event_name=event_name, num_brands=len(brands))

        # Initialize brand segregator
        self._segregator = BrandSegregator(
            brands=brands,
            similarity_threshold=similarity_threshold,
        )

        # Shared ML pipeline (loaded once)
        self._ml = ContentEngine(
            event_description=event_name,
        )

        # Layout assembler
        self._layout = LayoutAssembler()

        # Copy generator
        self._copy = CopyGenerator(use_llm=use_llm)

        # Store brand names for output
        self._brand_names: Dict[str, str] = {
            brand_id: brand_name for brand_id, brand_name, _ in brands
        }

    def run(
        self,
        asset_folder: str,
        output_root: str = "output",
        event_date: str = "",
    ) -> Path:
        """
        Process all assets and generate brand-specific content.

        Args:
            asset_folder: Path to folder containing event photos/videos
            output_root: Root directory for outputs
            event_date: Optional date string for case studies

        Returns:
            Path to the output directory.
        """
        _log.info("brand_pipeline_start", event_name=self.event_name, assets=asset_folder)

        # ── Step 1: Discover assets ─────────────────────────────────────────────
        assets = _discover_assets(asset_folder)
        image_assets = [a for a in assets if Path(a).suffix.lower() in _IMAGE_EXTS]
        video_assets = [a for a in assets if Path(a).suffix.lower() in _VIDEO_EXTS]

        _log.info("assets_discovered", total=len(assets), images=len(image_assets), videos=len(video_assets))

        if not assets:
            _log.warning("no_assets_found")
            return Path(output_root)

        # ── Step 2: Segregate assets into brands ────────────────────────────────
        _log.info("brand_segregation_start")
        segregation_results = self._segregator.segregate_assets(assets)

        # Log segregation summary
        for brand_id, classifications in segregation_results.items():
            if brand_id != "unmatched":
                _log.info("brand_assets_found", brand=brand_id, count=len(classifications))

        # ── Step 3: Generate content per brand ─────────────────────────────────
        output_dir = Path(output_root) / _safe_dirname(self.event_name)
        output_dir.mkdir(parents=True, exist_ok=True)

        all_selections: List[Tuple[str, List[SelectionResult]]] = []  # (brand_id, selections)

        for brand_id, classifications in segregation_results.items():
            if brand_id == "unmatched":
                # Save unmatched assets for manual review
                self._save_unmatched(classifications, output_dir)
                continue

            brand_name = self._brand_names.get(brand_id, brand_id)
            brand_dir = output_dir / _safe_dirname(brand_id)
            brand_dir.mkdir(exist_ok=True)

            _log.info("processing_brand", brand_id=brand_id, brand_name=brand_name, assets=len(classifications))

            # Generate content for this brand
            brand_selections = self._process_brand(
                brand_id=brand_id,
                brand_name=brand_name,
                classifications=classifications,
                brand_dir=brand_dir,
                event_date=event_date,
            )
            all_selections.append((brand_id, brand_selections))

        # ── Step 4: Write overall reports ───────────────────────────────────────
        self._save_selection_report(segregation_results, output_dir)
        self._save_selection_logic(output_dir)
        self._save_brand_summary(all_selections, output_dir)

        _log.info("brand_pipeline_complete", output_dir=str(output_dir))
        return output_dir

    def _process_brand(
        self,
        brand_id: str,
        brand_name: str,
        classifications: List[AssetClassification],
        brand_dir: Path,
        event_date: str,
    ) -> List[SelectionResult]:
        """
        Process a single brand's assets and generate all content outputs.
        """
        if len(classifications) < 5:
            _log.warning("insufficient_brand_assets", brand=brand_id, count=len(classifications))
            # Still process but with fewer assets

        # Extract asset paths, prioritizing higher-confidence matches
        sorted_classifications = sorted(
            classifications, key=lambda c: c.confidence, reverse=True
        )
        asset_paths = [c.path for c in sorted_classifications]

        # Run ML pipeline on this brand's assets
        _log.info("ml_pipeline_start", brand=brand_id, assets=len(asset_paths))
        selections = self._ml.select_assets(asset_paths)

        if not selections:
            _log.warning("no_assets_selected", brand=brand_id)
            return []

        # Separate by intended use
        collage_assets = [s.asset for s in selections if s.intended_use == "collage"]
        reel_selections = [s for s in selections if s.intended_use == "reel"]
        story_assets = [s.asset for s in selections if s.intended_use == "story"]

        # ── Generate carousel (4-6 slides) ─────────────────────────────────────
        if collage_assets:
            carousel_assets = collage_assets[:self.CAROUSEL_MAX_SLIDES]
            try:
                slides = self._layout.create_instagram_carousel(
                    [a.path for a in carousel_assets]
                )
                for i, slide in enumerate(slides, 1):
                    slide.save(brand_dir / f"carousel_{i}.jpg", quality=95)
                _log.info("carousel_done", brand=brand_id, slides=len(slides))
            except Exception as e:
                _log.error("carousel_failed", brand=brand_id, error=str(e))

        # ── Generate reel (30-60 seconds) ──────────────────────────────────────
        if reel_selections:
            reel_asset = reel_selections[0].asset
            if reel_asset.highlight_clips:
                reel_path = str(brand_dir / "reel.mp4")
                try:
                    ok = self._layout.create_reel(
                        reel_asset.path,
                        reel_asset.highlight_clips,
                        reel_path,
                        transition="crossfade",
                    )
                    if ok:
                        total_s = sum(
                            c["end"] - c["start"]
                            for c in reel_asset.highlight_clips
                        )
                        _log.info("reel_done", brand=brand_id, duration_s=round(total_s))
                except Exception as e:
                    _log.error("reel_failed", brand=brand_id, error=str(e))

        # ── Generate stories (3-4 frames) ─────────────────────────────────────
        if story_assets:
            story_frames = self._layout.create_instagram_stories(
                [a.path for a in story_assets[:self.STORY_FRAME_COUNT]]
            )
            stories_dir = brand_dir / "stories"
            stories_dir.mkdir(exist_ok=True)
            for i, frame in enumerate(story_frames, 1):
                frame.save(stories_dir / f"story_{i}.jpg", quality=95)
            _log.info("stories_done", brand=brand_id, frames=len(story_frames))

        # ── Generate brand-aware copy ─────────────────────────────────────────
        all_brand_assets = [s.asset for s in selections]

        # Carousel caption
        carousel_caption = self._copy.generate_brand_carousel_caption(
            brand_name=brand_name,
            event_name=self.event_name,
            assets=collage_assets or all_brand_assets,
        )
        (brand_dir / "instagram_caption.txt").write_text(carousel_caption, encoding="utf-8")

        # Reel caption
        reel_caption = self._copy.generate_brand_reel_caption(
            brand_name=brand_name,
            event_name=self.event_name,
            assets=all_brand_assets,
        )
        (brand_dir / "reel_caption.txt").write_text(reel_caption, encoding="utf-8")

        # Story captions (sequential narrative)
        story_captions = self._copy.generate_brand_story_captions(
            brand_name=brand_name,
            event_name=self.event_name,
            num_slides=self.STORY_FRAME_COUNT,
            assets=story_assets or all_brand_assets,
        )
        story_text = "\n".join(f"Story {i}: {cap}" for i, cap in enumerate(story_captions, 1))
        (brand_dir / "stories" / "story_captions.txt").write_text(story_text, encoding="utf-8")

        _log.info("copy_done", brand=brand_id)

        # ── Generate case study ────────────────────────────────────────────────
        case_study = generate_case_study(
            selections=selections,
            event_name=f"{brand_name} @ {self.event_name}",
            event_date=event_date or datetime.now().strftime("%B %d, %Y"),
            total_assets_processed=len(asset_paths),
        )
        (brand_dir / "case_study.md").write_text(case_study, encoding="utf-8")

        _log.info("brand_processing_complete", brand=brand_id)
        return selections

    def _save_unmatched(
        self,
        classifications: List[AssetClassification],
        output_dir: Path,
    ) -> None:
        """Save unmatched assets for manual review."""
        if not classifications:
            return

        unmatched_dir = output_dir / "unmatched"
        unmatched_dir.mkdir(exist_ok=True)

        report = []
        for c in classifications:
            report.append({
                "path": c.path,
                "best_match": max(c.similarity_scores.items(), key=lambda x: x[1]) if c.similarity_scores else (None, 0),
                "confidence": c.confidence,
                "all_scores": c.similarity_scores,
            })

        (unmatched_dir / "unmatched_report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        _log.info("unmatched_saved", count=len(classifications))

    def _save_selection_report(
        self,
        segregation_results: Dict[str, List[AssetClassification]],
        output_dir: Path,
    ) -> None:
        """Save full segregation and selection report."""
        report = {
            "event_name": self.event_name,
            "similarity_threshold": self.similarity_threshold,
            "timestamp": datetime.now().isoformat(),
            "brands": {},
            "total_assets": sum(len(v) for v in segregation_results.values()),
        }

        for brand_id, classifications in segregation_results.items():
            report["brands"][brand_id] = {
                "count": len(classifications),
                "assets": [
                    {
                        "path": c.path,
                        "confidence": c.confidence,
                        "similarity_scores": c.similarity_scores,
                    }
                    for c in classifications
                ],
            }

        (output_dir / "selection_report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        _log.info("selection_report_saved")

    def _save_selection_logic(self, output_dir: Path) -> None:
        """Save documented selection logic as required by the challenge."""
        logic_doc = self._segregator.get_selection_logic()

        full_doc = f"""# Brand Photo Segregation — Selection Logic

## Document Version
Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Event: {self.event_name}

---

{logic_doc}

---

## Scoring Weights

| Weight | Axis | Method |
|--------|------|--------|
| 30% | Technical quality | Laplacian blur + HSV brightness (adaptive thresholds) |
| 20% | Aesthetic quality | CLIP similarity to quality prompt sets |
| 30% | Face presence | YOLOv11 detection with size weighting |
| 20% | Concept relevance | CLIP semantic matching with configurable weights |

---

## Content Output Specifications

### Instagram Carousel
- Format: 1080×1350 JPEG (4:5 ratio)
- Slides: 4-6 slides per brand
- Layout: Smart crop centered on detected faces
- Caption: Brand-aware, StepOne voice, Instagram native

### Instagram Reel
- Format: 1080×1920 MP4 (9:16 ratio)
- Duration: 30-60 seconds
- Transitions: Crossfade (xfade filter, 0.5s per transition)
- Audio: Extracted from highlight clips
- Caption: Hook-first, tag CTA, 2-3 hashtags

### Instagram Stories
- Format: 1080×1920 JPEG (9:16 ratio)
- Frames: 3-4 per brand
- Narrative: Sequential — each frame leads into the next
- Text: Burned into bottom 15% with gradient overlay
- Captions: Short, conversational, CTA in final frame

---

## Brand Voice Adherence

All copy follows StepOne's brand voice:
- Clear over clever — we earn trust with precision, not wordplay
- Active over passive — we act, we deliver, we create
- Specific over vague — concrete examples and numbers beat abstract claims
- Confident over tentative — we say "we do" and "we deliver"
- Human over corporate — contractions are fine; humanity is a feature

Language to use: insight-driven, experience-led, measurable impact, experiential intelligence
Language to avoid: creative agency, event management, event solutions, "we work hard to try to"
"""
        (output_dir / "selection_logic.md").write_text(full_doc, encoding="utf-8")
        _log.info("selection_logic_saved")

    def _save_brand_summary(
        self,
        all_selections: List[Tuple[str, List[SelectionResult]]],
        output_dir: Path,
    ) -> None:
        """Save summary of all brands and their content outputs."""
        summary = {
            "event_name": self.event_name,
            "brands_processed": len(all_selections),
            "brand_details": [],
        }

        for brand_id, selections in all_selections:
            brand_name = self._brand_names.get(brand_id, brand_id)
            carousel_count = sum(1 for s in selections if s.intended_use == "collage")
            has_reel = any(s.intended_use == "reel" for s in selections)
            has_stories = any(s.intended_use == "story" for s in selections)

            summary["brand_details"].append({
                "brand_id": brand_id,
                "brand_name": brand_name,
                "total_assets": len(selections),
                "carousel_slides": min(carousel_count, self.CAROUSEL_MAX_SLIDES),
                "has_reel": has_reel,
                "has_stories": has_stories,
                "high_confidence_count": sum(1 for s in selections if s.confidence >= 0.5),
                "low_confidence_count": sum(1 for s in selections if s.confidence < 0.5),
            })

        (output_dir / "brand_summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        _log.info("brand_summary_saved", brands=len(all_selections))


# ── Standalone selection logic documentation ───────────────────────────────────

language_doc = """
## Brand Photo Segregation — Selection Logic (Detailed)

### Step 1: Brand Reference Preparation
For each brand in the event:
1. Load all render images provided as visual references
2. Pre-process each render through CLIP (ViT-B/32)
3. Compute average embedding across all renders for that brand
4. Store as "brand prototype vector"

### Step 2: Asset Classification
For each photo/video in the dataset:
1. Compute CLIP image embedding
2. Calculate cosine similarity to each brand's prototype vector
3. Normalize similarities to 0-1 range ((similarity + 1) / 2)
4. Record all similarity scores in asset metadata

### Step 3: Brand Assignment
Decision rule:
- If max(similarity_scores) >= threshold (default 0.60):
    → Assign asset to brand with highest similarity
- If max(similarity_scores) < threshold:
    → Asset goes to "unmatched" bucket (not deleted, flagged for review)

### Step 4: Quality Filtering (within each brand)
After brand assignment, apply standard quality scoring:
1. Technical Quality (30%): Laplacian blur variance + HSV brightness
2. Aesthetic Quality (20%): CLIP similarity to curated quality prompts
3. Face Presence (30%): YOLOv11 detection with size weighting
   - Small faces (< 2% area): 0.4× multiplier
   - Large faces (> 10% area): 1.0× multiplier
4. Concept Relevance (20%): Semantic matching to event concepts

Assets sorted by composite score, top N selected for content output.

### Step 5: Content Assignment
- Carousel: Top 4-6 collage assets (smart crop to 4:5)
- Reel: Best video with highlight clips (crossfade transitions)
- Stories: Top 4 diverse assets (vertical crop to 9:16)
- Case Study: 2 concept-rich images

### Selection Criteria Summary
| Criteria | Threshold | Action if not met |
|----------|-----------|-------------------|
| Brand similarity | >= 0.60 | → Unmatched bucket |
| Technical quality | >= 0.30 | → Rejected |
| Face confidence | >= 0.35 | → Lower score |
| Composite score | >= 0.50 | → Flagged for review |

### Output Organization
```
output/<EventName>/
├── selection_report.json      # Full segregation data
├── selection_logic.md         # This document
├── brand_summary.json         # Processing summary
├── unmatched/                  # Unassigned assets + report
├── brand_A/                   # One folder per brand
│   ├── carousel_1.jpg … N.jpg
│   ├── instagram_caption.txt
│   ├── reel.mp4
│   ├── reel_caption.txt
│   ├── stories/story_1.jpg … 4.jpg
│   ├── stories/story_captions.txt
│   └── case_study.md
├── brand_B/
│   └── ...
└── brand_C/
    └── ...
```
"""