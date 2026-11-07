"""
generate_gff.py — Entry point for GFF 2025 Brand Content Challenge.

Usage:
    python generate_gff.py \
        --assets path/to/GFF_photos/ \
        --brands "Brand A:path/to/render1.jpg,path/to/render2.jpg" \
                 "Brand B:path/to/render3.jpg" \
                 "Brand C:path/to/render4.jpg" \
                 "Brand D:path/to/render5.jpg" \
        --event "GFF 2025" \
        --output ./output

This script:
  1. Discovers all photos/videos in the asset folder
  2. Segregates them into brands using CLIP similarity
  3. Generates Instagram carousel, reel, and stories per brand
  4. Produces brand-aware copy following StepOne's voice
  5. Writes selection logic documentation
  6. Creates per-brand output folders
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Tuple

try:
    from content_engine import BrandOrchestrator
    from api.logger import get_logger
    _log = get_logger("generate_gff")
except Exception:
    # Fallback for standalone usage
    from content_engine.brand_orchestrator import BrandOrchestrator


def parse_brand_arg(brand_str: str) -> Tuple[str, str, List[str]]:
    """
    Parse a brand argument in the format:
        "BrandName:path/to/render1.jpg,path/to/render2.jpg"
    
    Returns:
        (brand_id, brand_name, render_paths)
    """
    parts = brand_str.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid brand format: '{brand_str}'. Use 'BrandName:path1.jpg,path2.jpg'")
    
    brand_name = parts[0].strip()
    # Convert to safe ID: "Brand A" → "brand_a"
    brand_id = brand_name.lower().replace(" ", "_").replace("-", "_")
    
    render_paths = [p.strip() for p in parts[1].split(",")]
    render_paths = [p for p in render_paths if p]  # Filter empty
    
    if not render_paths:
        raise ValueError(f"No render paths provided for brand: '{brand_name}'")
    
    # Validate paths exist
    missing = [p for p in render_paths if not Path(p).exists()]
    if missing:
        print(f"⚠️  Warning: Render files not found for '{brand_name}': {missing}")
    
    return brand_id, brand_name, render_paths


def main():
    parser = argparse.ArgumentParser(
        description="GFF 2025 — Brand Content Generation Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # GFF 2025 with 4 brands
  python generate_gff.py \
      --assets ./GFF2025_photos/ \
      --brands "Brand A:/renders/brand_a_1.jpg,/renders/brand_a_2.jpg" \
               "Brand B:/renders/brand_b.jpg" \
               "Brand C:/renders/brand_c.jpg" \
               "Brand D:/renders/brand_d.jpg" \
      --event "GFF 2025" \
      --output ./output

  # With custom similarity threshold
  python generate_gff.py \
      --assets ./photos/ \
      --brands "StepOne:/renders/stepone.jpg" \
      --event "GFF 2025" \
      --threshold 0.65

  # Use LLM for copy generation
  python generate_gff.py \
      --assets ./photos/ \
      --brands "Brand:/renders/brand.jpg" \
      --llm
        """,
    )
    
    parser.add_argument(
        "--assets",
        required=True,
        help="Path to folder containing event photos/videos.",
    )
    parser.add_argument(
        "--brands",
        nargs="+",
        required=True,
        help="Brand definitions in format: 'BrandName:render1.jpg,render2.jpg'. "
             "At least one render image per brand required.",
    )
    parser.add_argument(
        "--event",
        default="GFF 2025",
        help='Event name (default: "GFF 2025").',
    )
    parser.add_argument(
        "--output",
        default="output",
        help="Root output directory (default: ./output).",
    )
    parser.add_argument(
        "--event-date",
        default="",
        help="Event date for case studies (default: today).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.60,
        help="Minimum CLIP similarity to assign a brand (0-1, default: 0.60).",
    )
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Use Groq LLM for copy generation (requires GROQ_API_KEY in .env).",
    )
    
    args = parser.parse_args()
    
    # Validate asset folder
    asset_folder = Path(args.assets)
    if not asset_folder.exists():
        print(f"❌ Error: Asset folder not found: {asset_folder}")
        sys.exit(1)
    
    # Parse brand definitions
    brands = []
    for brand_str in args.brands:
        try:
            brand_id, brand_name, render_paths = parse_brand_arg(brand_str)
            brands.append((brand_id, brand_name, render_paths))
        except ValueError as e:
            print(f"❌ Error: {e}")
            sys.exit(1)
    
    if len(brands) < 1:
        print("❌ Error: At least one brand required.")
        sys.exit(1)
    
    print("\n" + "=" * 60)
    print("  GFF 2025 — Brand Content Generation")
    print("=" * 60)
    print(f"\n  Event     : {args.event}")
    print(f"  Assets    : {asset_folder}")
    print(f"  Brands    : {len(brands)}")
    for brand_id, brand_name, renders in brands:
        print(f"              - {brand_name} ({len(renders)} renders)")
    print(f"  Threshold : {args.threshold}")
    print(f"  LLM       : {'Yes' if args.llm else 'No (template fallback)'}")
    print(f"  Output    : {args.output}")
    print("\n" + "-" * 60)
    
    # Run pipeline
    try:
        orchestrator = BrandOrchestrator(
            event_name=args.event,
            brands=brands,
            similarity_threshold=args.threshold,
            use_llm=args.llm,
        )
        
        output_dir = orchestrator.run(
            asset_folder=str(asset_folder),
            output_root=args.output,
            event_date=args.event_date,
        )
        
        # Print summary
        print("\n" + "=" * 60)
        print("  ✅ Generation Complete")
        print("=" * 60)
        print(f"\n  Output directory: {output_dir}")
        print("\n  Generated content:")
        
        for brand_id, brand_name, _ in brands:
            brand_dir = output_dir / brand_id.lower().replace(" ", "_")
            if brand_dir.exists():
                carousel_count = len(list(brand_dir.glob("carousel_*.jpg")))
                has_reel = (brand_dir / "reel.mp4").exists()
                has_stories = (brand_dir / "stories").exists()
                
                print(f"\n    📁 {brand_name}/")
                print(f"       Carousel : {carousel_count} slides")
                print(f"       Reel     : {'✅' if has_reel else '❌'}")
                print(f"       Stories  : {'✅' if has_stories else '❌'}")
        
        # Check for unmatched
        unmatched_dir = output_dir / "unmatched"
        if unmatched_dir.exists():
            unmatched_count = len(list(unmatched_dir.glob("*.jpg"))) if unmatched_dir.exists() else 0
            if unmatched_count > 0:
                print(f"\n    📁 unmatched/ ({unmatched_count} assets)")
        
        print("\n" + "-" * 60)
        print(f"  Selection report: {output_dir / 'selection_report.json'}")
        print(f"  Selection logic : {output_dir / 'selection_logic.md'}")
        print("=" * 60 + "\n")
        
    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()