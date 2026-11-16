"""
Real-photo audit: deduplicate uploads and run FocalAnalyzer on each unique
event photograph. Outputs a JSON manifest used to select a diverse validation
set and to generate before/after comparisons.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from content_engine.composition import FocalAnalyzer, SmartCropper

UPLOADS = ROOT / "uploads"
OUT = ROOT / "real_photo_acceptance"
MANIFEST = OUT / "audit_manifest.json"

for d in (OUT,):
    d.mkdir(parents=True, exist_ok=True)


def unique_photos(folder: Path):
    """Return one representative path per unique (w,h,size) signature."""
    files = [p for p in folder.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
    seen = {}
    for p in sorted(files):
        try:
            with Image.open(p) as im:
                key = (im.size[0], im.size[1], p.stat().st_size)
        except Exception:
            continue
        if key not in seen:
            seen[key] = p
    return list(seen.values())


def main():
    photos = unique_photos(UPLOADS)
    print(f"Found {len(photos)} unique photographs (deduplicated from uploads/)")

    analyzer = FocalAnalyzer()
    entries = []
    for i, p in enumerate(photos, 1):
        try:
            analysis = analyzer.analyze(str(p))
            entry = {
                "file": p.name,
                "path": str(p),
                "width": analysis.width,
                "height": analysis.height,
                "orientation": analysis.orientation,
                "scene_type": analysis.scene_type,
                "scene_type_confidence": round(analysis.scene_type_confidence, 3),
                "confidence": round(analysis.confidence, 3),
                "faces": analysis.face_count,
                "people": len(analysis.people),
                "objects": len(analysis.objects),
                "focal_point": analysis.focal_point,
                "focal_region": analysis.focal_region,
                "main_subject": analysis.main_subject,
                "secondary_subjects": analysis.secondary_subjects,
                "models_used": analysis.models_used,
                "face_boxes": [{"bbox": d.bbox, "confidence": round(d.confidence, 2),
                                "weight": round(getattr(d, "_weight", 0.5), 2)}
                               for d in analysis.faces],
                "person_boxes": [{"bbox": d.bbox, "label": d.label,
                                  "confidence": round(d.confidence, 2)}
                                 for d in analysis.people],
                "salient_regions": analysis.salient_regions,
            }
            entries.append(entry)
            print(f"[{i:2d}/{len(photos)}] {p.name:45s} "
                  f"{analysis.width}x{analysis.height} {analysis.orientation:9s} "
                  f"scene={analysis.scene_type:14s} conf={analysis.confidence:.2f} "
                  f"faces={analysis.face_count} people={len(analysis.people)} "
                  f"obj={len(analysis.objects)} focal=({analysis.focal_point[0]:.2f},{analysis.focal_point[1]:.2f})")
        except Exception as exc:
            print(f"[{i:2d}/{len(photos)}] {p.name:45s} ERROR {exc}")

    # Sort: faces desc, then confidence desc, so interesting images bubble up.
    entries.sort(key=lambda e: (-e["faces"], -e["confidence"], e["file"]))
    manifest = {
        "generated_at": datetime.now().isoformat(),
        "source": "uploads/ (deduplicated by dimensions+file size)",
        "total_unique": len(entries),
        "entries": entries,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nManifest written to {MANIFEST} ({len(entries)} entries)")


if __name__ == "__main__":
    main()
