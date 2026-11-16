"""
Content Engine — Intelligent Cropping: Visual Acceptance (PHASE 8).

Demonstrates that the subject-aware crop engine preserves important content
that the previous centre-crop behaviour would cut off.

Since the repo contains no real PyCon 22 photographs (only synthetic 800×600
e2e fixtures), this generates clear synthetic event photographs with the
subject at known positions and drives the crop engine with a controlled
FocalAnalysis (subject box placed exactly where a human sees the subject).
This makes the before/after comparison deterministic and easy to verify:
  • BEFORE = centre crop (previous behaviour)
  • AFTER  = intelligent subject-aware crop (new engine)

Outputs:
  visual_acceptance/photos/*.jpg   source photographs (subject drawn at known box)
  visual_acceptance/compare/*.png  before/after side-by-sides
  visual_acceptance/crops/after/*.jpg   new intelligent crops
  visual_acceptance/crops/before/*.jpg  old centre crops
  visual_acceptance/crop_quality_report.json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from content_engine.composition import FocalAnalyzer, SmartCropper, FocalAnalysis

OUT = Path(__file__).resolve().parent.parent / "visual_acceptance"
PHOTOS = OUT / "photos"
COMPARE = OUT / "compare"
CROPS_AFTER = OUT / "crops" / "after"
CROPS_BEFORE = OUT / "crops" / "before"
for d in (OUT, PHOTOS, COMPARE, CROPS_AFTER, CROPS_BEFORE):
    d.mkdir(parents=True, exist_ok=True)

# (name, target_w, target_h)
FORMATS = [
    ("linkedin_1_1", 1080, 1080),
    ("carousel_4_5", 1080, 1350),
    ("story_9_16", 1080, 1920),
    ("landscape_16_9", 1920, 1080),
]


def draw_subject(draw, box_px, fill, label=None):
    x1, y1, x2, y2 = box_px
    draw.rectangle(box_px, fill=fill, outline=(255, 255, 255), width=4)
    # inner detail so it looks like "content", not just a blob
    draw.ellipse([x1 + 10, y1 + 10, x2 - 10, y2 - 10], outline=(255, 255, 255), width=2)
    if label:
        draw.text((x1 + 8, y1 + 8), label, fill=(255, 255, 255))


def make_photo(name, size, subjects, bg=(30, 40, 55)):
    """subjects: list of (box_normalised, fill_rgb, label)."""
    w, h = size
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    # subtle backdrop texture so DINOv2/saliency has something to read
    for i in range(0, h, 6):
        d.line([(0, i), (w, i)], fill=tuple(min(255, c + i // 8) for c in bg), width=1)
    for box_n, fill, label in subjects:
        box_px = (int(box_n[0] * w), int(box_n[1] * h), int(box_n[2] * w), int(box_n[3] * h))
        draw_subject(d, box_px, fill, label)
    path = PHOTOS / f"{name}.jpg"
    img.save(path, quality=92)
    return path, subjects


def centre_crop(img, tw, th):
    """Previous behaviour: pure centre crop then resize."""
    ow, oh = img.size
    tr = tw / th
    or_ = ow / oh
    if or_ > tr:
        nw = int(oh * tr); nh = oh
        x1 = (ow - nw) // 2; y1 = 0
    else:
        nw = ow; nh = int(ow / tr)
        x1 = 0; y1 = (oh - nh) // 2
    crop = img.crop((x1, y1, x1 + nw, y1 + nh))
    return crop.resize((tw, th), Image.Resampling.LANCZOS)


def subject_visibility_in_crop(crop_norm, subject_norm):
    """Fraction of subject_norm inside crop_norm (both 0-1 boxes)."""
    ix = max(0, min(crop_norm[2], subject_norm[2]) - max(crop_norm[0], subject_norm[0]))
    iy = max(0, min(crop_norm[3], subject_norm[3]) - max(crop_norm[1], subject_norm[1]))
    sa = (subject_norm[2] - subject_norm[0]) * (subject_norm[3] - subject_norm[1])
    return (ix * iy / sa) if sa > 0 else 0.0


def main():
    analyzer = FocalAnalyzer()
    cropper = SmartCropper(analyzer=analyzer)

    # Each photo: subject drawn at a known normalised box.
    # The crop engine is driven with main_subject = that same box so the
    # comparison isolates cropping behaviour (not detection quality).
    specs = [
        ("subject_left", (1200, 800), [((0.00, 0.28, 0.22, 0.72), (200, 60, 60), "SUBJECT")]),
        ("subject_right", (1200, 800), [((0.78, 0.28, 1.00, 0.72), (60, 160, 90), "SUBJECT")]),
        ("subject_top", (1200, 800), [((0.30, 0.00, 0.70, 0.24), (200, 180, 40), "SUBJECT")]),
        ("group_two", (1200, 800), [
            ((0.04, 0.30, 0.18, 0.70), (200, 60, 60), "A"),
            ((0.82, 0.30, 0.96, 0.70), (60, 160, 90), "B"),
        ]),
    ]

    report = {
        "generated_at": datetime.now().isoformat(),
        "note": "Synthetic event photographs with subjects at known positions. "
                "BEFORE = centre crop (previous behaviour). AFTER = intelligent "
                "subject-aware crop (new engine). Engine driven with controlled "
                "FocalAnalysis so subject positions are exact.",
        "photos": [],
    }

    for name, size, subjects in specs:
        src, _ = make_photo(name, size, subjects)
        print(f"\n=== {name} ({size[0]}x{size[1]}) ===")

        # Real analyzer output (for transparency / report).
        analysis = analyzer.analyze(src)
        print(f"  real-analyzer: scene={analysis.scene_type} conf={analysis.confidence:.2f} "
              f"faces={analysis.face_count} focal={tuple(round(v,2) for v in analysis.focal_point)}")

        main_subject = subjects[0][0]
        secondary = [s[0] for s in subjects[1:]]
        fa = FocalAnalysis(
            image_path=str(src), width=size[0], height=size[1],
            orientation="portrait" if size[1] > size[0] else "landscape",
            faces=[], people=[], objects=[], salient_regions=[],
            main_subject=main_subject, secondary_subjects=secondary,
            focal_point=(
                (main_subject[0] + main_subject[2]) / 2,
                (main_subject[1] + main_subject[3]) / 2,
            ),
            focal_region=main_subject,
            scene_type="group" if len(subjects) > 1 else "portrait",
            scene_type_confidence=0.9, confidence=0.9, models_used=["controlled"],
        )

        img = Image.open(src).convert("RGB")
        entry = {"photo": name, "size": size, "subjects": subjects, "formats": []}

        for fmt, tw, th in FORMATS:
            result = cropper.compute_crop(src, tw, th, analysis=fa)
            after_img, _ = cropper.crop_image(src, tw, th, analysis=fa)
            after_path = CROPS_AFTER / f"{name}_{fmt}.jpg"
            after_img.save(after_path, quality=92)

            before_img = centre_crop(img, tw, th)
            before_path = CROPS_BEFORE / f"{name}_{fmt}.jpg"
            before_img.save(before_path, quality=92)

            comp = Image.new("RGB", (tw * 2 + 20, th + 56), (240, 240, 240))
            cd = ImageDraw.Draw(comp)
            comp.paste(before_img, (10, 40))
            comp.paste(after_img, (tw + 10, 40))
            cd.text((10, 8), f"{name} · {fmt}  ·  BEFORE (centre)", fill=(0, 0, 0))
            cd.text((tw + 10, 8), f"AFTER · score={result.composition_score:.2f}", fill=(0, 0, 0))
            comp.save(COMPARE / f"{name}_{fmt}.png")

            # Visibility of each subject in before vs after
            cn_before = (10 / tw, 40 / th, (10 + tw) / tw, (40 + th) / th)  # not used; compute properly below
            # before crop normalised (it's centre crop of source):
            ow, oh = size
            tr = tw / th; or_ = ow / oh
            if or_ > tr:
                nw = int(oh * tr); nh = oh
                bx1 = (ow - nw) / 2 / ow; by1 = 0; bx2 = bx1 + nw / ow; by2 = 1.0
            else:
                nw = ow; nh = int(ow / tr)
                bx1 = 0; by1 = (oh - nh) / 2 / oh; bx2 = 1.0; by2 = by1 + nh / oh
            before_norm = (bx1, by1, bx2, by2)
            after_norm = result.crop_box_norm

            vis_before = subject_visibility_in_crop(before_norm, main_subject)
            vis_after = subject_visibility_in_crop(after_norm, main_subject)

            entry["formats"].append({
                "format": fmt, "target_w": tw, "target_h": th,
                "before_crop": str(before_path), "after_crop": str(after_path),
                "compare": str(COMPARE / f"{name}_{fmt}.png"),
                "composition_score": result.composition_score,
                "before_subject_visibility": round(vis_before, 3),
                "after_subject_visibility": round(vis_after, 3),
                "crop_box": result.crop_box,
                "crop_box_norm": result.crop_box_norm,
                "faces_preserved": result.faces_preserved,
                "faces_total": result.faces_total,
                "subjects_preserved": result.subjects_preserved,
                "warnings": result.warnings,
                "trade_off": result.trade_off,
            })
            print(f"  {fmt}: before_vis={vis_before:.2f} after_vis={vis_after:.2f} "
                  f"score={result.composition_score:.2f} "
                  f"subjects={result.subjects_preserved} warn={result.warnings}")

        report["photos"].append(entry)

    (OUT / "crop_quality_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport: {OUT / 'crop_quality_report.json'}")
    print(f"Outputs: {OUT}")


if __name__ == "__main__":
    main()
