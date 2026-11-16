"""
Focal-point analysis engine for subject-aware image cropping.

Produces a structured :class:`FocalAnalysis` for every image:

* original dimensions & orientation
* detected faces (YOLOv11-face via the shared :class:`FaceDetector`) with
  bounding boxes, confidences and size-aware weights
* detected people & objects (YOLOv8) with bounding boxes, labels & confidences
* salient visual regions (DINOv2 feature-variance saliency; deterministic
  edge/color saliency fallback when DINOv2 is unavailable)
* main subject + secondary subject bounding boxes
* focal point & focal region (normalised 0-1 coordinates)
* scene-type classification (portrait / group / architecture / product /
  event_stage / screen / general)
* overall confidence score

All inference is local. Models are loaded lazily and shared — no model weight is
loaded twice, there are no cloud calls and no runtime downloads. CUDA is used
when available, otherwise CPU.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from config import (
    YOLOV8_MODEL_PATH,
    YOLOV11_FACE_MODEL_PATH,
    DINOV2_MODEL_PATH,
    CLIP_MODEL_PATH,
)
from content_engine.utils.device_manager import get_device_manager
from content_engine.utils.mps_safe import empty_cache
from content_engine.utils.model_registry import get_clip, get_clip_device
from content_engine.models.face_detection import FaceDetector

try:
    from api.logger import get_logger
    _log = get_logger(__name__)
except Exception:  # pragma: no cover - logging unavailable
    import logging
    _log = logging.getLogger(__name__)

# ── COCO class names for YOLOv8 (index -> label). Only a subset is listed;
#    unknown indices fall back to "object". ──────────────────────────────────
_COCO_NAMES = {
    0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 4: "airplane",
    5: "bus", 6: "train", 7: "truck", 8: "boat", 9: "traffic light",
    10: "fire hydrant", 11: "stop sign", 13: "bench", 14: "bird",
    15: "cat", 16: "dog", 17: "horse", 18: "sheep", 19: "cow",
    20: "elephant", 21: "bear", 22: "zebra", 23: "giraffe", 24: "backpack",
    25: "umbrella", 27: "handbag", 28: "tie", 31: "suitcase", 32: "frisbee",
    33: "skis", 34: "snowboard", 36: "kite", 37: "surfboard", 39: "bottle",
    41: "cup", 42: "fork", 43: "knife", 44: "spoon", 47: "bowl",
    48: "banana", 49: "apple", 50: "sandwich", 51: "orange", 52: "broccoli",
    53: "carrot", 56: "chair", 57: "couch", 58: "potted plant", 59: "bed",
    62: "tv", 63: "laptop", 64: "mouse", 65: "remote", 67: "keyboard",
    68: "cell phone", 70: "toilet", 72: "book", 73: "clock", 74: "vase",
}

# Scene-type keywords used by the heuristic classifier (matched against
# Florence-2 / CLIP concept labels and YOLO object labels).
_STAGE_KEYWORDS = {"stage", "presentation", "podium", "speaker", "keynote",
                   "lecture", "talk", "screen", "projector", "laptop",
                   "microphone", "tv"}
_SCREEN_KEYWORDS = {"screen", "tv", "monitor", "projector", "laptop",
                    "cell phone", "tablet"}
_ARCH_KEYWORDS = {"building", "architecture", "skyscraper", "house",
                  "monument", "bridge"}
_PRODUCT_KEYWORDS = {"bottle", "cup", "cell phone", "laptop", "book", "vase",
                     "bowl", "cake", "donut", "product"}


def _norm_box(x1: float, y1: float, x2: float, y2: float,
              img_w: float, img_h: float) -> Tuple[float, float, float, float]:
    """Convert a pixel box to normalised (0-1) coordinates, clamped."""
    if img_w <= 0 or img_h <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        float(np.clip(x1 / img_w, 0.0, 1.0)),
        float(np.clip(y1 / img_h, 0.0, 1.0)),
        float(np.clip(x2 / img_w, 0.0, 1.0)),
        float(np.clip(y2 / img_h, 0.0, 1.0)),
    )


def _iou(a: Tuple[float, float, float, float],
         b: Tuple[float, float, float, float]) -> float:
    """Intersection-over-union of two normalised boxes."""
    x1 = max(a[0], b[0]); y1 = max(a[1], b[1])
    x2 = min(a[2], b[2]); y2 = min(a[3], b[3])
    inter_w = max(0.0, x2 - x1); inter_h = max(0.0, y2 - y1)
    inter = inter_w * inter_h
    if inter <= 0:
        return 0.0
    area_a = max(0.0, (a[2] - a[0])) * max(0.0, (a[3] - a[1]))
    area_b = max(0.0, (b[2] - b[0])) * max(0.0, (b[3] - b[1]))
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _box_area(box: Tuple[float, float, float, float]) -> float:
    return max(0.0, (box[2] - box[0])) * max(0.0, (box[3] - box[1]))


@dataclass
class Detection:
    """A single detected object / face."""
    label: str
    bbox: Tuple[float, float, float, float]      # normalised (x1,y1,x2,y2)
    bbox_px: Tuple[int, int, int, int]           # original-image pixels
    confidence: float


@dataclass
class FocalAnalysis:
    """
    Complete focal analysis of one image.

    All coordinates that reference the image are either normalised (0-1) or
    expressed in original-image pixels (``bbox_px`` / ``size``).
    """
    image_path: str
    width: int
    height: int
    orientation: str                         # 'landscape' | 'portrait' | 'square'

    # Detections ────────────────────────────────────────────────────────────
    faces: List[Detection] = field(default_factory=list)
    people: List[Detection] = field(default_factory=list)
    objects: List[Detection] = field(default_factory=list)

    # Saliency ──────────────────────────────────────────────────────────────
    salient_regions: List[Tuple[float, float, float, float]] = field(default_factory=list)

    # Subjects ──────────────────────────────────────────────────────────────
    main_subject: Optional[Tuple[float, float, float, float]] = None
    secondary_subjects: List[Tuple[float, float, float, float]] = field(default_factory=list)

    # Focal point / region (normalised) ─────────────────────────────────────
    focal_point: Tuple[float, float] = (0.5, 0.5)      # (x, y)
    focal_region: Tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)

    # Scene classification ──────────────────────────────────────────────────
    scene_type: str = "general"                        # portrait | group | architecture | product | event_stage | screen | general
    scene_type_confidence: float = 0.0

    # Metadata ──────────────────────────────────────────────────────────────
    confidence: float = 0.0                            # overall analysis confidence 0-1
    models_used: List[str] = field(default_factory=list)

    # ── convenience ────────────────────────────────────────────────────────
    @property
    def size(self) -> Tuple[int, int]:
        return (self.width, self.height)

    @property
    def face_count(self) -> int:
        return len(self.faces)

    @property
    def subject_count(self) -> int:
        return (1 if self.main_subject is not None else 0) + len(self.secondary_subjects)

    def to_dict(self) -> Dict[str, Any]:
        """JSON-serialisable representation (excludes raw arrays)."""
        return {
            "image_path": self.image_path,
            "width": self.width,
            "height": self.height,
            "orientation": self.orientation,
            "face_count": self.face_count,
            "faces": [{"label": d.label, "bbox": d.bbox,
                       "bbox_px": d.bbox_px, "confidence": d.confidence}
                      for d in self.faces],
            "people": [{"label": d.label, "bbox": d.bbox,
                        "bbox_px": d.bbox_px, "confidence": d.confidence}
                       for d in self.people],
            "objects": [{"label": d.label, "bbox": d.bbox,
                         "bbox_px": d.bbox_px, "confidence": d.confidence}
                        for d in self.objects],
            "salient_regions": self.salient_regions,
            "main_subject": self.main_subject,
            "secondary_subjects": self.secondary_subjects,
            "focal_point": self.focal_point,
            "focal_region": self.focal_region,
            "scene_type": self.scene_type,
            "scene_type_confidence": self.scene_type_confidence,
            "confidence": self.confidence,
            "models_used": self.models_used,
        }


class FocalAnalyzer:
    """
    Analyses a photograph to locate its important visual content.

    Runs each detector at most once per image (results are cached by path) and
    degrades gracefully: if any model is unavailable, a deterministic
    image-analysis fallback is used instead of failing.
    """

    def __init__(
        self,
        face_detector: Optional[FaceDetector] = None,
        yolo_conf: float = 0.25,
        face_conf: float = 0.35,
        max_image_side: int = 1200,
        cache_size: int = 64,
    ):
        self._face_detector = face_detector or FaceDetector(confidence=face_conf)
        self._yolo_conf = yolo_conf
        self._max_image_side = max_image_side

        # Lazy model handles
        self._yolo_model = None
        self._dino_model = None
        self._dino_available = False

        # Per-image analysis cache: path -> FocalAnalysis
        self._cache: Dict[str, FocalAnalysis] = {}
        self._cache_order: List[str] = []
        self._cache_size = cache_size

    # ── Public API ─────────────────────────────────────────────────────────

    def analyze(self, image_path: str) -> FocalAnalysis:
        """Return the cached (or freshly computed) focal analysis for an image."""
        if image_path in self._cache:
            return self._cache[image_path]

        analysis = self._compute_analysis(image_path)

        # Cache with simple eviction
        self._cache[image_path] = analysis
        self._cache_order.append(image_path)
        if len(self._cache_order) > self._cache_size:
            evict = self._cache_order.pop(0)
            self._cache.pop(evict, None)

        return analysis

    def clear_cache(self) -> None:
        self._cache.clear()
        self._cache_order.clear()

    # ── Internal: full analysis ────────────────────────────────────────────

    def _compute_analysis(self, image_path: str) -> FocalAnalysis:
        t0 = time.perf_counter()

        try:
            img = Image.open(image_path).convert("RGB")
        except Exception as exc:
            _log.warning("focal_open_failed", image=image_path, error=str(exc))
            return FocalAnalysis(
                image_path=image_path, width=0, height=0, orientation="general",
                confidence=0.0,
            )

        width, height = img.size
        orientation = ("portrait" if height > width else
                       "landscape" if width > height else "square")

        models_used: List[str] = []

        # ── Detections ─────────────────────────────────────────────────────
        faces = self._detect_faces(image_path, width, height)
        if faces:
            models_used.append("yolov11-face")

        people, objects = self._detect_objects(image_path, width, height)
        if people or objects:
            models_used.append("yolov8")

        # ── Saliency ───────────────────────────────────────────────────────
        saliency_map, salient_regions = self._compute_saliency(img, width, height)
        if self._dino_available:
            models_used.append("dinov2")
        else:
            models_used.append("saliency-fallback")

        # ── Subjects & focal point ─────────────────────────────────────────
        main_subject, secondary_subjects = self._select_subjects(
            faces, people, objects, salient_regions, width, height)
        focal_point, focal_region = self._compute_focal(
            faces, people, objects, main_subject, salient_regions, width, height)

        # ── Scene classification ───────────────────────────────────────────
        scene_type, scene_conf = self._classify_scene(
            faces, people, objects, salient_regions, width, height)

        # ── Confidence ─────────────────────────────────────────────────────
        confidence = self._compute_confidence(
            faces, people, objects, main_subject, saliency_map, scene_conf)

        load_time = time.perf_counter() - t0
        _log.debug(
            "focal_analysis_done",
            image=Path(image_path).name, size=f"{width}x{height}",
            orientation=orientation, scene=scene_type,
            faces=len(faces), people=len(people), objects=len(objects),
            confidence=round(confidence, 3), elapsed_s=round(load_time, 3),
        )

        empty_cache()
        return FocalAnalysis(
            image_path=image_path,
            width=width, height=height, orientation=orientation,
            faces=faces, people=people, objects=objects,
            salient_regions=salient_regions,
            main_subject=main_subject,
            secondary_subjects=secondary_subjects,
            focal_point=focal_point,
            focal_region=focal_region,
            scene_type=scene_type,
            scene_type_confidence=scene_conf,
            confidence=confidence,
            models_used=models_used,
        )

    # ── Detection: faces (reuse existing FaceDetector / YOLOv11-face) ──────

    def _detect_faces(self, image_path: str, img_w: int, img_h: int) -> List[Detection]:
        try:
            result = self._face_detector.detect_faces_detailed(image_path)
        except Exception as exc:
            _log.debug("face_detection_failed", image=image_path, error=str(exc))
            return []

        detections: List[Detection] = []
        bboxes = result.get("bboxes", [])
        confs = result.get("confidences", [])
        weights = result.get("weights", [])
        for i, bbox in enumerate(bboxes):
            x1, y1, x2, y2 = [float(v) for v in bbox]
            conf = float(confs[i]) if i < len(confs) else 0.5
            weight = float(weights[i]) if i < len(weights) else 0.5
            detections.append(Detection(
                label="face",
                bbox=_norm_box(x1, y1, x2, y2, img_w, img_h),
                bbox_px=(int(round(x1)), int(round(y1)),
                         int(round(x2)), int(round(y2))),
                confidence=conf,
            ))
            # Stash the size-aware weight on the object for later use.
            detections[-1]._weight = weight  # type: ignore[attr-defined]
        return detections

    # ── Detection: people & objects (YOLOv8) ───────────────────────────────

    @property
    def _yolo(self):
        """Lazy-load YOLOv8 (shared, loaded once)."""
        if self._yolo_model is None:
            from ultralytics import YOLO
            from content_engine.utils.mps_safe import MPS_DEVICE as _dev
            self._yolo_model = YOLO(YOLOV8_MODEL_PATH)
            try:
                self._yolo_model.to(_dev)
            except Exception:
                pass
        return self._yolo_model

    def _detect_objects(self, image_path: str, img_w: int, img_h: int):
        """Return (people, objects) lists of Detection."""
        people: List[Detection] = []
        objects: List[Detection] = []
        try:
            results = self._yolo.predict(image_path, conf=self._yolo_conf, verbose=False)
        except Exception as exc:
            _log.debug("yolo_detection_failed", image=image_path, error=str(exc))
            return people, objects

        try:
            boxes = results[0].boxes
            if boxes is None or len(boxes) == 0:
                return people, objects
            xyxy = boxes.xyxy.cpu().numpy()
            confs = boxes.conf.cpu().numpy()
            cls = boxes.cls.cpu().numpy().astype(int)
        except Exception:
            return people, objects

        for box, conf, label_id in zip(xyxy, confs, cls):
            x1, y1, x2, y2 = [float(v) for v in box]
            c = float(conf)
            label = _COCO_NAMES.get(int(label_id), "object")
            det = Detection(
                label=label,
                bbox=_norm_box(x1, y1, x2, y2, img_w, img_h),
                bbox_px=(int(round(x1)), int(round(y1)),
                         int(round(x2)), int(round(y2))),
                confidence=c,
            )
            if label == "person":
                people.append(det)
            else:
                objects.append(det)
        return people, objects

    # ── Saliency ───────────────────────────────────────────────────────────

    @property
    def _dino(self):
        """Lazy-load DINOv2 for feature-based saliency (loaded once)."""
        if self._dino_model is None and not self._dino_available:
            try:
                import torch
                from transformers import AutoModel
                self._dino_model = AutoModel.from_pretrained(
                    DINOV2_MODEL_PATH, local_files_only=True,
                )
                device = "cuda" if torch.cuda.is_available() else "cpu"
                self._dino_model = self._dino_model.to(device).eval()
                self._dino_device = device
                self._dino_available = True
            except Exception as exc:
                _log.debug("dinov2_load_failed", error=str(exc))
                self._dino_model = None
                self._dino_available = False
        return self._dino_model

    def _compute_saliency(self, img: Image.Image, img_w: int, img_h: int):
        """
        Compute a saliency map and salient regions.

        Preferred: DINOv2 patch-feature variance (high-variance patches are
        visually informative). Fallback: deterministic edge/colour saliency.
        Returns (saliency_map_hw [0-1], salient_regions [normalised boxes]).
        """
        dino = self._dino
        saliency_map = None
        if dino is not None:
            try:
                import torch
                import torchvision.transforms as T
                transform = T.Compose([
                    T.Resize(256, interpolation=T.InterpolationMode.BICUBIC),
                    T.CenterCrop(224),
                    T.ToTensor(),
                    T.Normalize(mean=[0.485, 0.456, 0.406],
                                std=[0.229, 0.224, 0.225]),
                ])
                input_tensor = transform(img).unsqueeze(0).to(self._dino_device)
                with torch.no_grad():
                    outputs = dino(input_tensor)
                # last_hidden_state: (1, num_tokens, embed_dim); token 0 = CLS
                last_hidden = outputs.last_hidden_state
                if last_hidden is None or last_hidden.ndim != 3:
                    raise ValueError("unexpected DINOv2 output shape")
                patch_tokens = last_hidden[0, 1:, :]          # (num_patches, dim)
                patch_var = patch_tokens.var(dim=1)           # (num_patches,)
                grid = int(round(patch_var.shape[0] ** 0.5))
                if grid * grid == patch_var.shape[0]:
                    saliency = patch_var.reshape(grid, grid)
                    saliency = (saliency - saliency.min()) / (saliency.max() - saliency.min() + 1e-6)
                    saliency_np = saliency.cpu().numpy()
                    # Upscale to image size
                    saliency_map = cv2.resize(
                        saliency_np, (img_w, img_h),
                        interpolation=cv2.INTER_CUBIC,
                    )
                    saliency_map = (saliency_map - saliency_map.min()) / (saliency_map.max() - saliency_map.min() + 1e-6)
            except Exception as exc:
                _log.debug("dinov2_saliency_failed", error=str(exc))
                saliency_map = None

        if saliency_map is None:
            saliency_map = self._deterministic_saliency(img, img_w, img_h)

        # Derive salient regions by thresholding + connected components.
        salient_regions = self._saliency_to_regions(saliency_map, img_w, img_h)
        return saliency_map, salient_regions

    @staticmethod
    def _deterministic_saliency(img: Image.Image, img_w: int, img_h: int) -> np.ndarray:
        """Deterministic saliency: edges + colour contrast + saturation."""
        arr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
        # Edge magnitude
        sobelx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        sobely = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        edges = cv2.magnitude(sobelx, sobely)
        # Saturation (colourfulness)
        hsv = cv2.cvtColor(arr, cv2.COLOR_BGR2HSV)
        saturation = hsv[:, :, 2].astype(np.float32) / 255.0
        # Local contrast via standard deviation in a window
        mean = cv2.blur(gray.astype(np.float32), (15, 15))
        meansq = cv2.blur((gray.astype(np.float32) ** 2), (15, 15))
        contrast = np.sqrt(np.maximum(meansq - mean ** 2, 0))
        # Combine (normalised)
        edges_n = (edges - edges.min()) / (edges.max() - edges.min() + 1e-6)
        contrast_n = (contrast - contrast.min()) / (contrast.max() - contrast.min() + 1e-6)
        sal = 0.5 * edges_n + 0.25 * contrast_n + 0.25 * saturation
        sal = cv2.GaussianBlur(sal, (31, 31), 0)
        sal = (sal - sal.min()) / (sal.max() - sal.min() + 1e-6)
        return sal

    def _saliency_to_regions(self, sal: np.ndarray, img_w: int, img_h: int,
                             max_regions: int = 4) -> List[Tuple[float, float, float, float]]:
        """Threshold the saliency map and return the top connected regions."""
        if sal is None or sal.size == 0:
            return []
        thresh = max(0.55, float(np.mean(sal) + 0.5 * sal.std()))
        binary = (sal >= thresh).astype(np.uint8)
        num, labels, stats, cents = cv2.connectedComponentsWithStats(binary, 8)
        regions = []
        for i in range(1, num):
            x, y, w, h, area = stats[i]
            if area < (img_w * img_h) * 0.005:  # ignore tiny specks
                continue
            regions.append(_norm_box(x, y, x + w, y + h, img_w, img_h))
        regions.sort(key=lambda b: -_box_area(b))
        return regions[:max_regions]

    # ── Subject selection ──────────────────────────────────────────────────

    def _select_subjects(self, faces, people, objects, salient_regions, img_w, img_h):
        """Choose the main subject + secondary subjects (normalised boxes)."""
        # Candidate subject boxes, each with a priority score.
        candidates: List[Tuple[Tuple[float, float, float, float], float]] = []

        # Faces are the strongest subjects (size-weighted).
        for det in faces:
            weight = getattr(det, "_weight", 0.5)
            score = det.confidence * weight
            candidates.append((det.bbox, score))

        # People detections (only if not already covered by a face).
        for det in people:
            covered = any(_iou(det.bbox, f.bbox) > 0.5 for f in faces)
            if covered:
                continue
            candidates.append((det.bbox, det.confidence * 0.9))

        # Prominent objects (large, confident).
        for det in objects:
            area = _box_area(det.bbox)
            if area < 0.02:  # ignore tiny objects as subjects
                continue
            candidates.append((det.bbox, det.confidence * 0.6 * (1.0 + area)))

        if not candidates:
            # Fall back to the strongest salient region or centre.
            if salient_regions:
                return salient_regions[0], salient_regions[1:]
            return (0.35, 0.35, 0.65, 0.65), []

        candidates.sort(key=lambda c: -c[1])
        main_subject = candidates[0][0]
        secondary = [c[0] for c in candidates[1:4]]  # up to 3 secondary
        return main_subject, secondary

    def _compute_focal(self, faces, people, objects, main_subject,
                       salient_regions, img_w, img_h):
        """
        Compute the focal point (normalised) and focal region (normalised box).

        The focal point is a weighted blend of:
          * face centroids (weighted by size/confidence)
          * the main subject centre
          * the saliency-map peak
        Clamped to lie inside the focal region.
        """
        pts: List[Tuple[float, float]] = []
        wts: List[float] = []

        # Faces pull the focal point strongly.
        for det in faces:
            cx = (det.bbox[0] + det.bbox[2]) / 2.0
            cy = (det.bbox[1] + det.bbox[3]) / 2.0
            weight = getattr(det, "_weight", 0.5) * det.confidence
            pts.append((cx, cy)); wts.append(weight * 1.5)

        # Main subject.
        if main_subject is not None:
            cx = (main_subject[0] + main_subject[2]) / 2.0
            cy = (main_subject[1] + main_subject[3]) / 2.0
            pts.append((cx, cy)); wts.append(1.0)

        # Saliency peak (use the top salient region centre).
        if salient_regions:
            top = salient_regions[0]
            cx = (top[0] + top[2]) / 2.0
            cy = (top[1] + top[3]) / 2.0
            pts.append((cx, cy)); wts.append(0.7)

        if pts:
            total_w = sum(wts) if sum(wts) > 0 else 1.0
            fx = sum(p[0] * w for p, w in zip(pts, wts)) / total_w
            fy = sum(p[1] * w for p, w in zip(pts, wts)) / total_w
        else:
            fx, fy = 0.5, 0.5

        fx = float(np.clip(fx, 0.0, 1.0))
        fy = float(np.clip(fy, 0.0, 1.0))

        # Focal region: box around the main subject, expanded by a margin.
        # ``main_subject`` and ``salient_regions`` are already normalised
        # (0-1), so clamp directly rather than re-running _norm_box.
        if main_subject is not None:
            margin = 0.18
            x1 = main_subject[0] - margin
            y1 = main_subject[1] - margin
            x2 = main_subject[2] + margin
            y2 = main_subject[3] + margin
            focal_region = (
                float(np.clip(x1, 0.0, 1.0)),
                float(np.clip(y1, 0.0, 1.0)),
                float(np.clip(x2, 0.0, 1.0)),
                float(np.clip(y2, 0.0, 1.0)),
            )
        elif salient_regions:
            focal_region = salient_regions[0]
        else:
            focal_region = (0.0, 0.0, 1.0, 1.0)

        # Clamp focal point inside the focal region.
        fx = float(np.clip(fx, focal_region[0], focal_region[2]))
        fy = float(np.clip(fy, focal_region[1], focal_region[3]))

        return (fx, fy), focal_region

    # ── Scene classification ───────────────────────────────────────────────

    def _classify_scene(self, faces, people, objects, salient_regions,
                        img_w, img_h):
        """Classify the scene type heuristically (deterministic fallback)."""
        face_count = len(faces)
        people_count = len(people)

        # Gather labels for keyword matching.
        labels = [d.label for d in faces] + [d.label for d in people] + \
                 [d.label for d in objects]

        # Group: 3+ faces or 2+ people
        if face_count >= 3 or people_count >= 2:
            return "group", 0.8
        # Portrait: single strong face
        if face_count == 1:
            return "portrait", 0.85

        label_set = set(labels)
        # Event stage / presentation
        if label_set & _STAGE_KEYWORDS:
            if label_set & _SCREEN_KEYWORDS:
                return "screen", 0.6
            return "event_stage", 0.65
        # Product: prominent object(s), no people/faces
        if (label_set & _PRODUCT_KEYWORDS) and face_count == 0 and people_count == 0:
            return "product", 0.6
        # Architecture: scene dominated by structures, no people
        if (label_set & _ARCH_KEYWORDS) and face_count == 0 and people_count == 0:
            return "architecture", 0.6
        # Single person -> portrait
        if people_count == 1 and face_count == 0:
            return "portrait", 0.5
        return "general", 0.4

    # ── Confidence ─────────────────────────────────────────────────────────

    def _compute_confidence(self, faces, people, objects, main_subject,
                            saliency_map, scene_conf):
        score = 0.0
        if faces:
            score += 0.35
        if people:
            score += 0.2
        if objects:
            score += 0.15
        if main_subject is not None:
            score += 0.2
        if saliency_map is not None and saliency_map.size:
            score += 0.1 * min(1.0, float(saliency_map.max()))
        score += 0.1 * scene_conf
        return float(np.clip(score, 0.0, 1.0))
