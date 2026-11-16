"""
Face Detector — YOLOv11n with Size-Aware Weighting

Item 13: Weighted face scoring (foreground faces > background crowds)
  - Faces covering < 2% of image area → weight 0.4 (background)
  - Faces covering > 10% of image area → weight 1.0 (foreground)
  - Linear interpolation between

Returns:
  - detect_faces(): (face_count, confidences) — backward compatible
  - detect_faces_detailed(): full dict with bboxes, weights, weighted_score
"""

import numpy as np
import threading
import time
from pathlib import Path
from typing import Dict, List, Tuple, Optional

try:
    from config import settings as _cfg, YOLOV11_FACE_MODEL_PATH
    from content_engine.utils.device_manager import get_device_manager
    from content_engine.utils.mps_safe import register_model, MPS_DEVICE, recommend_device
    _DEFAULT_FACE_CONF = _cfg.face_confidence_threshold
    _SIZE_WEIGHT_THRESH = _cfg.face_size_weight_threshold
except Exception:
    _DEFAULT_FACE_CONF = 0.35
    _SIZE_WEIGHT_THRESH = 0.05
    YOLOV11_FACE_MODEL_PATH = "models/yolov11-face/model.pt"  # type: ignore

    def get_device_manager():  # type: ignore
        return None

    def register_model(*args, **kwargs):  # type: ignore
        pass

    MPS_DEVICE = "cpu"  # type: ignore

    def recommend_device(*args, **kwargs):  # type: ignore
        return "cpu"

# Size-weight thresholds (item 13)
_SIZE_WEIGHT_MIN_PCT = 0.02   # <2% of image → 0.4 weight
_SIZE_WEIGHT_MAX_PCT = 0.10   # >10% of image → 1.0 weight


class FaceDetector:
    """
    YOLOv11n-based face detection with size-aware scoring.

    Item 13: Prevents background crowds from outscoring foreground portraits.
    A face covering 2% of a 1000×1000 image (20×20 px) is weighted 0.4.
    A face covering 10% (100×100 px) is weighted 1.0.

    An already-loaded :class:`ultralytics.YOLO` model instance may be injected
    (e.g. by :class:`content_engine.layout_assembler.LayoutAssembler`) so that
    the YOLOv11-face weights are loaded exactly once per process and shared
    between components instead of being duplicated.
    """

    def __init__(self, confidence: float = _DEFAULT_FACE_CONF, model=None):
        self._model     = model
        self._confidence = confidence
        # Serialize YOLO inference: Ultralytics' predictor is not thread-safe and
        # concurrent .to(device) / predict calls on CUDA can corrupt device state
        # (meta-tensor "Cannot copy out of meta tensor" errors). One lock guards
        # both lazy loading and every predict call so the model is never touched
        # by two threads at once.
        self._predict_lock = threading.RLock()

    # ── Model lazy-load ─────────────────────────────────────────────────────────

    @property
    def model(self):
        if self._model is None:
            with self._predict_lock:
                # Double-check after acquiring the lock.
                if self._model is None:
                    from ultralytics import YOLO
                    from config import YOLOV11_FACE_MODEL_PATH

                    t0 = time.perf_counter()
                    device = MPS_DEVICE
                    self._model = YOLO(YOLOV11_FACE_MODEL_PATH)

                    # Place the model explicitly on the selected device once, at
                    # load time. Avoids repeated .to(device) calls inside predict
                    # that can fail on meta/empty tensors under concurrency.
                    try:
                        self._model.to(device)
                    except Exception:
                        # If .to() fails on a meta/empty tensor, rebuild on the
                        # target device with to_empty semantics via the YOLO
                        # constructor's device argument.
                        self._model = YOLO(YOLOV11_FACE_MODEL_PATH)
                        self._model.to(device)
                    load_time = time.perf_counter() - t0

                    # Register with DeviceManager
                    estimated_vram = 50.0 if device.startswith("cuda") else 0.0
                    estimated_ram = 3.0
                    dm = get_device_manager()
                    if dm is not None:
                        dm.register_model(
                            "yolov11_face",
                            model=self._model,
                            device=device,
                            vram_mb=estimated_vram,
                            ram_mb=estimated_ram,
                            load_time_seconds=load_time,
                        )
        else:
            # Model was injected (shared copy): place it on the device and
            # register it once so memory tracking stays accurate without
            # loading a duplicate set of weights.
            device = MPS_DEVICE
            try:
                self._model.to(device)
            except Exception:
                pass
            dm = get_device_manager()
            if dm is not None and not dm.is_model_loaded("yolov11_face"):
                dm.register_model(
                    "yolov11_face",
                    model=self._model,
                    device=device,
                    vram_mb=50.0,
                    ram_mb=3.0,
                    load_time_seconds=0.0,
                )
        return self._model

    # ── Item 13: Size-aware weighting ────────────────────────────────────────────

    @staticmethod
    def _face_weight(bbox: List, img_w: float, img_h: float) -> float:
        """
        Compute face weight based on area percentage.

        Args:
            bbox: [x1, y1, x2, y2] in pixels
            img_w, img_h: image dimensions in pixels

        Returns:
            float: weight between 0.4 and 1.0
        """
        x1, y1, x2, y2 = bbox
        face_area   = (x2 - x1) * (y2 - y1)
        image_area  = img_w * img_h
        area_pct    = face_area / image_area if image_area > 0 else 0.0

        if area_pct >= _SIZE_WEIGHT_MAX_PCT:
            return 1.0
        if area_pct <= _SIZE_WEIGHT_MIN_PCT:
            return 0.4

        # Linear interpolation between 0.4 and 1.0
        t = (area_pct - _SIZE_WEIGHT_MIN_PCT) / (_SIZE_WEIGHT_MAX_PCT - _SIZE_WEIGHT_MIN_PCT)
        return 0.4 + 0.6 * t

    # ── Detection ─────────────────────────────────────────────────────────────────

    def detect_faces(self, image_path: str) -> Tuple[int, List[float]]:
        """
        Backward-compatible detection — returns (count, confidences).

        Returns:
            (face_count, confidences)
        """
        result = self.detect_faces_detailed(image_path)
        return result["face_count"], result["confidences"]

    def detect_faces_detailed(self, image_path: str) -> Dict:
        """
        Full detection with size-aware weighted scoring.

        Returns:
            {
                "face_count": int,
                "confidences": [float],
                "bboxes": [[x1, y1, x2, y2], ...],
                "bboxes_norm": [[0–1, 0–1, 0–1, 0–1], ...],
                "weights": [float],
                "weighted_score": float (0–1)
            }
        """
        import cv2

        img = cv2.imread(str(image_path))
        if img is None:
            return {
                "face_count": 0, "confidences": [],
                "bboxes": [], "bboxes_norm": [],
                "weights": [], "weighted_score": 0.0,
            }

        img_h, img_w = img.shape[:2]

        # Run YOLOv11n on the device the model was placed on at load time.
        # Serialized with self._predict_lock so concurrent pipeline workers never
        # drive the shared Ultralytics predictor at the same time (which can
        # corrupt CUDA device state and surface as a meta-tensor error).
        from content_engine.utils.mps_safe import empty_cache
        try:
            with self._predict_lock:
                results = self.model.predict(image_path, conf=self._confidence, verbose=False)
        except Exception:
            # CPU fallback for unsupported CUDA operations.
            try:
                with self._predict_lock:
                    self._model.to("cpu")
                    results = self.model.predict(image_path, conf=self._confidence, verbose=False)
            except Exception:
                return {
                    "face_count": 0, "confidences": [],
                    "bboxes": [], "bboxes_norm": [],
                    "weights": [], "weighted_score": 0.0,
                }
        finally:
            empty_cache()

        if results[0].boxes is None or len(results[0].boxes) == 0:
            return {
                "face_count": 0, "confidences": [],
                "bboxes": [], "bboxes_norm": [],
                "weights": [], "weighted_score": 0.0,
            }

        boxes   = results[0].boxes
        bboxes  = boxes.xyxy.cpu().numpy().tolist()
        confs   = boxes.conf.cpu().tolist()

        # Compute size-aware weights
        weights = [self._face_weight(b, img_w, img_h) for b in bboxes]

        # Weighted score: sum(confidence × weight) / max_faces
        max_faces       = 10
        weighted_scores = [c * w for c, w in zip(confs, weights)]
        weighted_score  = min(1.0, sum(weighted_scores) / max_faces)

        # Normalize bboxes to 0–1
        bboxes_norm = [
            [b[0]/img_w, b[1]/img_h, b[2]/img_w, b[3]/img_h]
            for b in bboxes
        ]

        return {
            "face_count":   len(bboxes),
            "confidences":  confs,
            "bboxes":       bboxes,
            "bboxes_norm":  bboxes_norm,
            "weights":      weights,
            "weighted_score": round(weighted_score, 4),
        }