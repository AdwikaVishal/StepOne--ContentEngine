"""
Real-photo visual acceptance: before/after comparisons on actual event
photographs from uploads/.

For each selected photograph, generates:
  - Original image
  - Previous centre-crop result (old behaviour)
  - New intelligent crop result (SmartCropper)
  - at 1:1, 4:5, 9:16, 16:9

Produces side-by-side comparison images and a crop-quality report measuring:
  - face visibility / clipping
  - subject visibility
  - composition score
  - output dimensions & aspect ratio
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from content_engine.composition import FocalAnalyzer, SmartCropper
from content_engine.composition.smart_crop import _iou, _to_norm_box

OUT = ROOT / "real_photo_acceptance"
COMPARE = OUT / "compare"
CROPS_AFTER = OUT / "crops" / "after"
CROPS_BEFORE = OUT / "crops" / "before"
ORIGINALS = OUT / "originals"
REPORT_PATH = OUT / "crop_quality_report.json"
for d in (OUT, COMPARE, CROPS_AFTER, CROPS_BEFORE, ORIGINALS):
    d.mkdir(parents=True, exist_ok=True)

# Validation set: diverse real event photographs (file -> short label).
# Selected from the uploads/ audit manifest to cover all required categories.
VALIDATION_SET = [
    # Single-person portraits (face position varies)
    ("00219d4e7ee44a4ab2e191ff52d20477.jpg", "single_portrait_face_right"),
    ("5b1a1be834f44be395ff956cd5ab0366.jpg", "single_portrait_face_near_right_edge"),
    ("1824eb3c4dae42e6b055941acb57187c.jpg", "single_portrait_face_bottom_right"),
    # Two or more people
    ("234c4d933cec4e5fbe21d7190b3207c6.jpg", "two_people_centered"),
    ("337fffa77d2441ea85cf82622ae983ed.jpg", "two_people_right_of_center"),
    # Groups distributed across the frame
    ("1a21ef12381143c285dc506c70383f60.jpg", "large_group_14_faces"),
    ("09398c5cb81c4f87a814cb92a55b4edd.jpg", "group_10_faces_centered"),
    # People near image boundaries
    ("0b1e7942548a458a9e7568d33e74f78f.jpg", "subject_top_right_corner"),
    ("07a720c2281d462887e4ef15ede9a4fc.jpg", "subject_right_edge_no_faces"),
    # Event stages / presentations / screens
    ("3d18c865b37d460e851a42895224c052.jpg", "screen_presentation_no_faces"),
    # Products / banners
    ("70ced33e7e3c4bfa9d998354f315d9d4.jpg", "product_no_faces"),
    # Images without detectable faces (people detected, no faces)
    ("f61c9b8817bc41c6be3f49e247c98759.jpg", "group_people_no_faces_detected"),
]

FORMATS = [
    ("linkedin_1_1", 1080, 1080),
    ("carousel_4_5", 1080, 1350),
    ("story_9_16", 1080, 1920),
    ("landscape_16_9", 1920, 1080),
]


def centre_crop(img: Image.Image, tw: int, th: int) -> Image.Image:
    """Previous behaviour: pure centre crop then resize (no upscaling beyond 2x
    logic replicated approximately — we just resize to exact target)."""
    ow, oh = img.size
    tr = tw / th
    or_ = ow / oh
    if or_ > tr:
        nw = max(1, int(oh * tr)); nh = oh
        x1 = (ow - nw) // 2; y1 = 0
    else:
        nw = ow; nh = max(1, int(ow / tr))
        x1 = 0; y1 = (oh - nh) // 2
    crop = img.crop((x1, y1, x1 + nw, y1 + nh))
    return crop.resize((tw, th), Image.Resampling.LANCZOS)


def box_visibility(crop_norm, subject_norm):
    """Fraction of subject_norm inside crop_norm (both 0-1 boxes)."""
    ix = max(0, min(crop_norm[2], subject_norm[2]) - max(crop_norm[0], subject_norm[0]))
    iy = max(0, min(crop_norm[3], subject_norm[3]) - max(crop_norm[1], subject_norm[1]))
    sa = max(0.0, (subject_norm[2] - subject_norm[0])) * max(0.0, (subject_norm[3] - subject_norm[1]))
    return (ix * iy / sa) if sa > 0 else 0.0


def face_clipped(crop_norm, face_norm, eps=0.005):
    """True if a face is cut by the crop boundary."""
    return (face_norm[0] <= crop_norm[0] + eps or face_norm[2] >= crop_norm[2] - eps or
            face_norm[1] <= crop_norm[1] + eps or face_norm[3] >= crop_norm[3] - eps)


def main():
    manifest_path = OUT / "audit_manifest.json"
    manifest = json.load(open(manifest_path))
    lookup = {e["file"]: e for e in manifest["entries"]}

    analyzer = FocalAnalyzer()
    cropper = SmartCropper(analyzer=analyzer)

    report = {
        "generated_at": datetime.now().isoformat(),
        "source": "uploads/ (real event photographs)",
        "total_tested": len(VALIDATION_SET),
        "formats": [f[0] for f in FORMATS],
        "results": [],
    }

    for filename, label in VALIDATION_SET:
        src = Path("uploads") / filename
        if not src.exists():
            print(f"SKIP (missing): {filename}")
            continue
        entry = lookup[filename]
        print(f"\n=== {label} ({filename}) {entry['width']}x{entry['height']} "
              f"scene={entry['scene_type']} faces={entry['faces']} ===")

        img = Image.open(src).convert("RGB")
        # Save a downscaled original copy for the report package.
        orig_copy = ORIGINALS / f"{label}.jpg"
        img.save(orig_copy, quality=90)

        analysis = analyzer.analyze(str(src))
        face_boxes = [d.bbox for d in analysis.faces]  # normalised 0-1
        person_boxes = [d.bbox for d in analysis.people]
        main_subject = analysis.main_subject

        result_entry = {
            "file": filename,
            "label": label,
            "width": entry["width"],
            "height": entry["height"],
            "orientation": entry["orientation"],
            "scene_type": entry["scene_type"],
            "scene_type_confidence": entry["scene_type_confidence"],
            "confidence": entry["confidence"],
            "faces_detected": entry["faces"],
            "people_detected": entry["people"],
            "objects_detected": entry["objects"],
            "focal_point": analysis.focal_point,
            "focal_region": analysis.focal_region,
            "main_subject": main_subject,
            "face_boxes": face_boxes,
            "formats": [],
        }

        for fmt, tw, th in FORMATS:
            # BEFORE: centre crop
            before_img = centre_crop(img, tw, th)
            before_path = CROPS_BEFORE / f"{label}_{fmt}.jpg"
            before_img.save(before_path, quality=92)

            # AFTER: intelligent crop
            result = cropper.compute_crop(str(src), tw, th, analysis=analysis)
            after_img, _ = cropper.crop_image(str(src), tw, th, analysis=analysis)
            after_path = CROPS_AFTER / f"{label}_{fmt}.jpg"
            after_img.save(after_path, quality=92)

            # Side-by-side comparison
            comp = Image.new("RGB", (tw * 2 + 24, th + 72), (230, 230, 230))
            cd = ImageDraw.Draw(comp)
            comp.paste(before_img, (12, 40))
            comp.paste(after_img, (tw + 12, 40))
            cd.text((12, 8), f"{label}  {fmt}  ·  BEFORE (centre)", fill=(0, 0, 0))
            score_txt = f"AFTER · score={result.composition_score:.2f}"
            cd.text((tw + 12, 8), score_txt, fill=(0, 0, 0))
            comp.save(COMPARE / f"{label}_{fmt}.png")

            # Metrics
            before_norm = _to_norm_box(
                _centre_box(img.size, tw, th), entry["width"], entry["height"])
            after_norm = result.crop_box_norm

            face_vis_before = [box_visibility(before_norm, fb) for fb in face_boxes]
            face_vis_after = [box_visibility(after_norm, fb) for fb in face_boxes]
            faces_clipped_before = sum(face_clipped(before_norm, fb) for fb in face_boxes)
            faces_clipped_after = sum(face_clipped(after_norm, fb) for fb in face_boxes)

            main_vis_before = box_visibility(before_norm, main_subject) if main_subject else None
            main_vis_after = box_visibility(after_norm, main_subject) if main_subject else None

            fmt_entry = {
                "format": fmt,
                "target_w": tw,
                "target_h": th,
                "target_ratio": round(tw / th, 4),
                "before_crop": str(before_path),
                "after_crop": str(after_path),
                "compare": str(COMPARE / f"{label}_{fmt}.png"),
                "composition_score": round(result.composition_score, 4),
                "breakdown": {k: round(v, 4) for k, v in result.breakdown.items()},
                "crop_box_after": result.crop_box,
                "crop_box_norm_after": result.crop_box_norm,
                "main_subject_visibility_before": (round(main_vis_before, 4)
                                                   if main_vis_before is not None else None),
                "main_subject_visibility_after": (round(main_vis_after, 4)
                                                  if main_vis_after is not None else None),
                "face_visibility_before": [round(v, 4) for v in face_vis_before],
                "face_visibility_after": [round(v, 4) for v in face_vis_after],
                "faces_clipped_before": faces_clipped_before,
                "faces_clipped_after": faces_clipped_after,
                "faces_total": len(face_boxes),
                "warnings": result.warnings,
                "trade_off": result.trade_off,
            }
            result_entry["formats"].append(fmt_entry)

            print(f"  {fmt:14s} score={result.composition_score:.2f} "
                  f"subj_vis_before={main_vis_before if main_vis_before is None else round(main_vis_before,2)} "
                  f"subj_vis_after={round(main_vis_after,2) if main_vis_after is not None else None} "
                  f"faces_clipped_before={faces_clipped_before} faces_clipped_after={faces_clipped_after} "
                  f"warn={result.warnings}")

        report["results"].append(result_entry)

    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport written to {REPORT_PATH}")
    print(f"Comparisons in {COMPARE}")


def _centre_box(img_size, tw, th):
    """Return the centre-crop box (x1,y1,x2,y2) in source pixels."""
    ow, oh = img_size
    tr = tw / th
    or_ = ow / oh
    if or_ > tr:
        nw = max(1, int(oh * tr)); nh = oh
        x1 = (ow - nw) // 2; y1 = 0
    else:
        nw = ow; nh = max(1, int(ow / tr))
        x1 = 0; y1 = (oh - nh) // 2
    return (x1, y1, x1 + nw, y1 + nh)


if __name__ == "__main__":
    main()
