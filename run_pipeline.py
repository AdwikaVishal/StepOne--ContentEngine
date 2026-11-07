"""
run_pipeline.py — Entry point for the Content & Design Engine ML pipeline.

Usage:
    python run_pipeline.py --assets path/to/dataset1/ path/to/dataset2/
    python run_pipeline.py --assets event_photos/ --event "Product Launch 2024"

The script:
  1. Discovers all supported image/video files in the provided paths
  2. Runs the full ML pipeline (quality, faces, content understanding, video highlights)
  3. Prints a structured selection report with per-asset explanations
  4. Flags any low-confidence outputs for manual review
  5. Saves a JSON report to ./output/selection_report.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List

from content_engine import ContentEngine, SelectionResult


# Supported file extensions
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
ALL_EXTS = IMAGE_EXTS | VIDEO_EXTS

LOW_CONFIDENCE_THRESHOLD = 0.50


def discover_assets(paths: List[str]) -> List[str]:
    """Recursively find all supported image/video files in the given paths."""
    assets: List[str] = []
    for raw_path in paths:
        p = Path(raw_path)
        if p.is_file() and p.suffix.lower() in ALL_EXTS:
            assets.append(str(p))
        elif p.is_dir():
            for ext in ALL_EXTS:
                assets.extend(str(f) for f in p.rglob(f"*{ext}"))
        else:
            print(f"⚠️  Skipping unrecognised path: {raw_path}")
    return sorted(set(assets))


def print_report(selections: List[SelectionResult]) -> None:
    """Print a structured, human-readable selection report to stdout."""
    if not selections:
        print("No assets were selected.")
        return

    # Group by platform
    by_platform: dict = {}
    for s in selections:
        by_platform.setdefault(s.intended_use, []).append(s)

    platform_order = ["collage", "reel", "story", "case_study"]
    platform_labels = {
        "collage": "LinkedIn Collage (4–6 images)",
        "reel": "Instagram Reel (video)",
        "story": "Instagram Stories (3–4 frames)",
        "case_study": "Case Study Assets",
    }

    print("\n" + "=" * 65)
    print("  CONTENT ENGINE — ASSET SELECTION REPORT")
    print("=" * 65)

    for platform in platform_order:
        if platform not in by_platform:
            continue
        print(f"\n▶  {platform_labels[platform]}")
        print("-" * 65)
        for s in by_platform[platform]:
            name = Path(s.asset.path).name
            conf_indicator = "⚠️ " if s.confidence < LOW_CONFIDENCE_THRESHOLD else "✅"
            print(f"\n  {conf_indicator} {name}")
            print(f"     Confidence : {s.confidence:.2f}")
            print(f"     Reason     : {s.selection_reason}")
            print(f"     Faces      : {s.asset.face_count}")
            print(f"     Quality    : {s.asset.quality_score:.2f}  "
                  f"Aesthetic: {s.asset.aesthetic_score:.2f}")
            if s.asset.asset_type == "video":
                print(f"     Duration   : {s.asset.duration:.1f}s")
                if s.asset.highlight_clips:
                    total = sum(c["end"] - c["start"] for c in s.asset.highlight_clips)
                    print(f"     Highlights : {len(s.asset.highlight_clips)} clips, "
                          f"{total:.1f}s total")
            if s.asset.scene_concepts:
                print(f"     Concepts   : {', '.join(s.asset.scene_concepts[:5])}")

    # Low-confidence summary
    low_conf = [s for s in selections if s.confidence < LOW_CONFIDENCE_THRESHOLD]
    if low_conf:
        print("\n" + "=" * 65)
        print("  ⚠️  LOW-CONFIDENCE OUTPUTS — RECOMMEND MANUAL REVIEW")
        print("=" * 65)
        for s in low_conf:
            print(f"  • {Path(s.asset.path).name}  "
                  f"(confidence={s.confidence:.2f}, use={s.intended_use})")

    print("\n" + "=" * 65)
    print(f"  Total selected: {len(selections)} assets")
    print("=" * 65 + "\n")


def save_json_report(selections: List[SelectionResult], output_path: str) -> None:
    """Serialise the selection results to JSON for downstream use."""
    report = []
    for s in selections:
        report.append({
            "file": s.asset.path,
            "asset_type": s.asset.asset_type,
            "intended_use": s.intended_use,
            "confidence": round(s.confidence, 4),
            "low_confidence": s.confidence < LOW_CONFIDENCE_THRESHOLD,
            "selection_reason": s.selection_reason,
            "scores": {
                "quality": round(s.asset.quality_score, 4),
                "aesthetic": round(s.asset.aesthetic_score, 4),
                "face_count": s.asset.face_count,
                "final": round(s.asset.final_score, 4),
            },
            "scene_concepts": s.asset.scene_concepts[:10],
            "highlight_clips": s.asset.highlight_clips or [],
        })

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(f"JSON report saved → {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Content & Design Engine — ML Asset Selection Pipeline"
    )
    parser.add_argument(
        "--assets",
        nargs="+",
        required=True,
        help="One or more file paths or directories containing event assets.",
    )
    parser.add_argument(
        "--event",
        default="Event",
        help='Description of the event, e.g. "Tech Conference 2024".',
    )
    parser.add_argument(
        "--output",
        default="output/selection_report.json",
        help="Path for the JSON output report.",
    )
    args = parser.parse_args()

    # Discover assets
    asset_list = discover_assets(args.assets)
    if not asset_list:
        print("No supported assets found. Exiting.")
        sys.exit(1)

    print(f"Found {len(asset_list)} assets for event: '{args.event}'\n")

    # Run pipeline
    engine = ContentEngine(event_description=args.event)
    selections = engine.select_assets(asset_list)

    # Report
    print_report(selections)
    save_json_report(selections, args.output)


if __name__ == "__main__":
    main()
