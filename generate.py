"""
generate.py — CLI entry point for the full content generation pipeline.

Usage:
    python generate.py --assets path/to/event/assets/ --event "Tech Summit 2024"
    python generate.py --assets dataset1/ dataset2/ --event "Product Launch" --output ./out
    python generate.py --assets photos/ --event "Conference" --llm   # use LLM for captions
"""

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Content & Design Engine — full generation pipeline"
    )
    parser.add_argument(
        "--assets", nargs="+", required=True,
        help="One or more folders containing event images/videos.",
    )
    parser.add_argument(
        "--event", required=True,
        help='Event name, e.g. "Tech Summit 2024".',
    )
    parser.add_argument(
        "--description", default="",
        help="Optional longer event description for context.",
    )
    parser.add_argument(
        "--output", default="output",
        help="Root output directory (default: ./output).",
    )
    parser.add_argument(
        "--date", default="",
        help='Event date string for the case study, e.g. "May 2024".',
    )
    parser.add_argument(
        "--llm", action="store_true",
        help="Use Phi-3.5-mini for caption generation (requires extra VRAM).",
    )
    args = parser.parse_args()

    # Validate asset folders
    for folder in args.assets:
        if not Path(folder).exists():
            print(f"Error: asset path not found: {folder}")
            sys.exit(1)

    # If multiple folders, merge them into a single temp directory
    import shutil, tempfile
    if len(args.assets) == 1:
        asset_folder = args.assets[0]
        tmp_dir = None
    else:
        tmp_dir = tempfile.mkdtemp(prefix="ce_assets_")
        for folder in args.assets:
            for f in Path(folder).rglob("*"):
                if f.is_file():
                    shutil.copy(f, Path(tmp_dir) / f.name)
        asset_folder = tmp_dir
        print(f"Merged {len(args.assets)} folders into temporary directory.")

    try:
        from content_engine.orchestrator import ContentOrchestrator

        orch = ContentOrchestrator(
            event_name=args.event,
            event_description=args.description or args.event,
            use_llm=args.llm,
        )
        out_dir = orch.run(
            asset_folder=asset_folder,
            output_root=args.output,
            event_date=args.date,
        )
        print(f"\nAll outputs saved to: {out_dir.resolve()}")
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
