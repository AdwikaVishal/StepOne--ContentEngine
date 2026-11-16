import sys
sys.path.insert(0, '.')
from content_engine.composition import FocalAnalyzer, SmartCropper
from content_engine.composition.smart_crop import _to_norm_box, _iou
import numpy as np

src = "uploads/234c4d933cec4e5fbe21d7190b3207c6.jpg"
analyzer = FocalAnalyzer()
analysis = analyzer.analyze(src)
cropper = SmartCropper(analyzer=analyzer)

# Replicate _compute_crop selection manually to inspect
img_w, img_h = analysis.width, analysis.height
target_w, target_h = 1080, 1920
target_ratio = target_w / target_h
orig_ratio = img_w / img_h
crop_w = max(1, int(round(img_h * target_ratio)))
crop_h = img_h
x_min, x_max = 0, img_w - crop_w
y_min, y_max = 0, 0

print(f"img {img_w}x{img_h} crop {crop_w}x{crop_h} x_range [{x_min},{x_max}]")

# Face centres
for i, d in enumerate(analysis.faces):
    cx = (d.bbox[0] + d.bbox[2]) / 2 * img_w
    cy = (d.bbox[1] + d.bbox[3]) / 2 * img_h
    x1 = int(np.clip(round(cx - crop_w / 2), x_min, x_max))
    y1 = int(np.clip(round(cy - crop_h / 2), y_min, y_max))
    box = (x1, y1, x1 + crop_w, y1 + crop_h)
    bn = _to_norm_box(box, img_w, img_h)
    max_iou = max(_iou(bn, f.bbox) for f in analysis.faces)
    print(f"face {i} centre-biased box={box} max_face_iou={max_iou:.3f}")

# What does compute_crop return?
result = cropper.compute_crop(src, target_w, target_h, analysis=analysis)
bn = result.crop_box_norm
print(f"\ncompute_crop result: box={result.crop_box} norm={bn}")
print(f"max face iou in result: {max(_iou(bn, f.bbox) for f in analysis.faces):.3f}")
print(f"score={result.composition_score:.4f} warnings={result.warnings}")
