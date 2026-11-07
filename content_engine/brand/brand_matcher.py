"""
Brand matcher — CLIP cosine similarity (primary) + HSV histogram (fallback) + DINOv2 + YOLO + LLM fallback.
Uses sentence-transformers/clip-ViT-B-32 which is already installed in the venv.
"""

import gc
import numpy as np
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import json
import os

try:
    from api.logger import get_logger
    _log = get_logger("content_engine.brand.brand_matcher")
except Exception:
    import logging
    _log = logging.getLogger("content_engine.brand.brand_matcher")

try:
    from content_engine.ai_mode import is_cloud_testing
except ImportError:
    is_cloud_testing = lambda: False

try:
    import cv2
    _CV2 = True
except ImportError:
    _CV2 = False

# In cloud_testing mode, defer heavy model package imports to keep the
# process lightweight (no CLIP, DINOv2, YOLO, or Groq SDK loaded).
if not is_cloud_testing():
    try:
        import torch
        from sentence_transformers import SentenceTransformer
        from PIL import Image as _PILImage
        _CLIP_AVAILABLE = True
    except ImportError:
        _CLIP_AVAILABLE = False
        _log.warning("sentence-transformers not available — CLIP disabled")

    try:
        from transformers import AutoImageProcessor, AutoModel
        from ultralytics import YOLO
        from groq import Groq
        from sklearn.metrics.pairwise import cosine_similarity
        _DINO_YOLO_GROQ_AVAILABLE = True
    except ImportError as e:
        _DINO_YOLO_GROQ_AVAILABLE = False
        _log.warning(f"DINOv2/YOLO/Groq not available — advanced features disabled: {e}")
else:
    _CLIP_AVAILABLE = False
    _DINO_YOLO_GROQ_AVAILABLE = False

try:
    from content_engine.ai_mode import is_cloud_testing
except ImportError:
    is_cloud_testing = lambda: False


@dataclass
class BrandMatch:
    brand_id: str
    brand_name: str
    confidence: float          # 0–1
    orb_score: float
    clip_score: float
    hist_score: float
    dino_score: float = 0.0
    yolo_score: float = 0.0
    decision_log: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BrandReference:
    brand_id: str
    brand_name: str
    render_paths: List[str]
    embedding: Optional[np.ndarray] = field(default=None, repr=False)
    dino_embedding: Optional[np.ndarray] = field(default=None, repr=False)


class BrandMatcher:
    """Brand matcher using ORB + HSV histogram + CLIP + DINOv2 + YOLO + LLM fallback.

    Weights (per requirement):
      - ORB:   0.20
      - HSV:   0.10
      - CLIP:  0.20 (only if available)
      - DINO:  0.50 (only if available)
      - YOLO:  0.20 (only if available)

    Brands are defined as (brand_id, brand_name, [render_paths]) tuples.

    Public contract (used by backend/frontend):
      - `segregate(asset_paths)` returns Dict[str, List[str]]
      - buckets include `unmatched`.
    """

    def __init__(
        self,
        brands: List[Tuple[str, str, List[str]]],
        similarity_threshold: float = 0.45,
        orb_nfeatures: int = 2000,
        config: Dict = None,
    ):
        self.threshold = similarity_threshold
        self._clip: Optional[SentenceTransformer] = None
        self.brands: List[BrandReference] = []

        # ORB precomputation
        self._orb_nfeatures = orb_nfeatures
        self._orb_matcher = None  # BFMatcher, initialised if cv2 available
        self._brand_orb = {}  # brand_id -> list of (kp, desc) for each render
        self._brand_hist = {}  # brand_id -> list of precomputed hist arrays

        # DINOv2 and YOLO
        self._dino_processor = None
        self._dino_model = None
        self._yolo_model = None
        self._groq_client = None
        self._device = None

        # Cloud testing mode: use mock brand matching, no CLIP/DINO/YOLO loading
        self._use_mock = is_cloud_testing()

        # Ensemble weights
        self.weights = {
            "orb": config.get("orb_weight", 0.2) if config else 0.2,
            "hsv": config.get("hsv_weight", 0.1) if config else 0.1,
            "clip": config.get("clip_weight", 0.2) if config else 0.2,
            "dino": config.get("dino_weight", 0.5) if config else 0.5,
            "yolo": config.get("yolo_weight", 0.2) if config else 0.2,
        }

        for brand_id, brand_name, render_paths in brands:
            valid = [p for p in render_paths if Path(p).exists()]
            if valid:
                self.brands.append(BrandReference(brand_id, brand_name, valid))
            else:
                _log.warning("no_valid_renders", brand=brand_id)

        if _CV2 and not self._use_mock:
            self._orb_matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)

        # Precompute ORB + HSV hist for references (fast scoring later)
        if _CV2 and not self._use_mock:
            self._precompute_orb_and_hist()

        if _CLIP_AVAILABLE and self.brands and not self._use_mock:
            self._load_clip()
            self._compute_embeddings()

        if _DINO_YOLO_GROQ_AVAILABLE and self.brands and not self._use_mock:
            self._load_dino_yolo_groq()
            self._compute_dino_embeddings()

    # ── CLIP ──────────────────────────────────────────────────────────────────

    def _load_clip(self):
        try:
            from content_engine.utils.mps_safe import MPS_DEVICE
            self._clip = SentenceTransformer("clip-ViT-B-32", device=MPS_DEVICE)
            _log.info("clip_loaded_for_brand_matching")
        except Exception as e:
            _log.warning("clip_load_failed", error=str(e))

    def _encode_image(self, path: str) -> Optional[np.ndarray]:
        try:
            img = _PILImage.open(path).convert("RGB")
            emb = self._clip.encode(img, convert_to_numpy=True)
            emb = emb / (np.linalg.norm(emb) + 1e-8)
            return emb
        except Exception as e:
            _log.warning("encode_failed", path=path, error=str(e))
            return None

    def _compute_embeddings(self):
        for brand in self.brands:
            embs = [self._encode_image(p) for p in brand.render_paths]
            embs = [e for e in embs if e is not None]
            if embs:
                avg = np.mean(embs, axis=0)
                brand.embedding = avg / (np.linalg.norm(avg) + 1e-8)
                _log.info("brand_embedding_ready", brand=brand.brand_id, renders=len(embs))

    # ── ORB (precomputed for references) ─────────────────────────────────────

    def _extract_orb(self, bgr: np.ndarray):
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        orb = cv2.ORB_create(nfeatures=self._orb_nfeatures)
        kp, des = orb.detectAndCompute(gray, None)
        return kp, des

    def _orb_similarity(self, query_des: Optional[np.ndarray], ref_des: Optional[np.ndarray]) -> float:
        if query_des is None or ref_des is None:
            return 0.0
        if len(query_des) < 10 or len(ref_des) < 10:
            return 0.0

        try:
            matches = self._orb_matcher.knnMatch(query_des, ref_des, k=2)
            good = 0
            for m_n in matches:
                if len(m_n) != 2:
                    continue
                m, n = m_n
                if m.distance < 0.75 * n.distance:
                    good += 1
            return min(1.0, good / 100.0)
        except Exception:
            return 0.0

    def _precompute_orb_and_hist(self):
        """Precompute ORB descriptors and HSV histograms for all brand renders."""
        if not _CV2:
            return

        for brand in self.brands:
            orb_list = []
            hist_list = []

            for render_path in brand.render_paths:
                bgr = cv2.imread(render_path)
                if bgr is None:
                    continue

                _, des = self._extract_orb(bgr)
                orb_list.append((render_path, des))

                hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
                hist = cv2.calcHist([hsv], [0, 1], None, [90, 128], [0, 180, 0, 256])
                cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
                hist_list.append(hist)

            self._brand_orb[brand.brand_id] = [d for _, d in orb_list]
            self._brand_hist[brand.brand_id] = hist_list

    # ── Histogram (precomputed for references; query computed per asset) ───

    def _hist_from_path(self, path: str):
        try:
            bgr = cv2.imread(path)
            if bgr is None:
                return None
            hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0, 1], None, [90, 128], [0, 180, 0, 256])
            cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
            return hist
        except Exception:
            return None

    def _hist_similarity_from_hists(self, query_hist, ref_hist) -> float:
        if query_hist is None or ref_hist is None:
            return 0.0
        try:
            return float(max(0.0, cv2.compareHist(query_hist, ref_hist, cv2.HISTCMP_CORREL)))
        except Exception:
            return 0.0

    # ── DINOv2 + YOLO + LLM ─────────────────────────────────────────────────

    def _load_dino_yolo_groq(self):
        try:
            from content_engine.utils.mps_safe import MPS_DEVICE
            self._device = MPS_DEVICE

            # Load DINOv2
            self._dino_processor = AutoImageProcessor.from_pretrained("facebook/dinov2-small")
            self._dino_model = AutoModel.from_pretrained("facebook/dinov2-small")
            self._dino_model.eval()
            self._dino_model.to(self._device)

            # Load YOLO
            self._yolo_model = YOLO("yolov8n.pt")

            # Load Groq
            from config import settings
            if settings.groq_api_key:
                self._groq_client = Groq(api_key=settings.groq_api_key)

            _log.info("dino_yolo_groq_loaded")
        except Exception as e:
            _log.warning("dino_yolo_groq_load_failed", error=str(e))

    def _compute_dino_embeddings(self):
        if not _DINO_YOLO_GROQ_AVAILABLE or self._dino_model is None:
            return

        for brand in self.brands:
            embs = []
            for render_path in brand.render_paths:
                emb = self._get_dinov2_embedding(render_path)
                if emb is not None:
                    embs.append(emb)
            if embs:
                avg = np.mean(embs, axis=0)
                brand.dino_embedding = avg / (np.linalg.norm(avg) + 1e-8)
                _log.info("brand_dino_embedding_ready", brand=brand.brand_id, renders=len(embs))

    def _get_dinov2_embedding(self, image_path: str) -> Optional[np.ndarray]:
        if self._dino_processor is None or self._dino_model is None:
            return None
        try:
            if isinstance(image_path, str):
                image = _PILImage.open(image_path).convert("RGB")
            elif isinstance(image_path, np.ndarray):
                image = _PILImage.fromarray(cv2.cvtColor(image_path, cv2.COLOR_BGR2RGB))
            else:
                return None

            inputs = self._dino_processor(images=image, return_tensors="pt")
            inputs = {k: v.to(self._device) for k, v in inputs.items()}

            with torch.no_grad():
                outputs = self._dino_model(**inputs)
                embedding = outputs.last_hidden_state[:, 0, :].cpu().numpy().flatten()

            return embedding
        except Exception as e:
            _log.warning("dino_embedding_failed", path=image_path, error=str(e))
            return None

    def _detect_logo_crop(self, image_path: str) -> np.ndarray:
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"Cannot read image: {image_path}")

        if self._yolo_model is None:
            return img

        results = self._yolo_model(img, verbose=False)[0]
        best_box = None
        best_conf = 0.0
        if results.boxes is not None:
            for box in results.boxes:
                conf = float(box.conf[0])
                if conf > 0.25 and conf > best_conf:
                    best_conf = conf
                    best_box = box.xyxy[0].cpu().numpy().astype(int)

        if best_box is not None:
            x1, y1, x2, y2 = best_box
            h, w = img.shape[:2]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            cropped = img[y1:y2, x1:x2]
            return cropped
        else:
            return img

    def _orb_match_ratio(self, query_img: np.ndarray, ref_img_path: str) -> float:
        ref_img = cv2.imread(ref_img_path)
        if ref_img is None:
            return 0.0

        query_gray = cv2.cvtColor(query_img, cv2.COLOR_BGR2GRAY)
        ref_gray = cv2.cvtColor(ref_img, cv2.COLOR_BGR2GRAY)

        orb = cv2.ORB_create(nfeatures=1000)
        kp1, des1 = orb.detectAndCompute(query_gray, None)
        kp2, des2 = orb.detectAndCompute(ref_gray, None)

        if des1 is None or des2 is None or len(kp1) == 0 or len(kp2) == 0:
            return 0.0

        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        matches = bf.knnMatch(des1, des2, k=2)

        good_matches = []
        for m, n in matches:
            if m.distance < 0.75 * n.distance:
                good_matches.append(m)

        ratio = len(good_matches) / min(len(kp1), len(kp2))
        return min(ratio, 1.0)

    def _hsv_histogram_correlation(self, query_img: np.ndarray, ref_img_path: str) -> float:
        ref_img = cv2.imread(ref_img_path)
        if ref_img is None:
            return 0.0

        h, w = query_img.shape[:2]
        ref_resized = cv2.resize(ref_img, (w, h))

        query_hsv = cv2.cvtColor(query_img, cv2.COLOR_BGR2HSV)
        ref_hsv = cv2.cvtColor(ref_resized, cv2.COLOR_BGR2HSV)

        hist_query_h = cv2.calcHist([query_hsv], [0], None, [180], [0, 180])
        hist_query_s = cv2.calcHist([query_hsv], [1], None, [256], [0, 256])
        hist_ref_h = cv2.calcHist([ref_hsv], [0], None, [180], [0, 180])
        hist_ref_s = cv2.calcHist([ref_hsv], [1], None, [256], [0, 256])

        cv2.normalize(hist_query_h, hist_query_h, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
        cv2.normalize(hist_query_s, hist_query_s, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
        cv2.normalize(hist_ref_h, hist_ref_h, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
        cv2.normalize(hist_ref_s, hist_ref_s, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)

        corr_h = cv2.compareHist(hist_query_h, hist_ref_h, cv2.HISTCMP_CORREL)
        corr_s = cv2.compareHist(hist_query_s, hist_ref_s, cv2.HISTCMP_CORREL)

        corr = (max(0, corr_h) + max(0, corr_s)) / 2
        return min(corr, 1.0)

    def _llm_verify(self, image_path: str, candidate_brands: List[str], top_scores: Dict[str, float]) -> Optional[Dict[str, Any]]:
        if not candidate_brands or self._groq_client is None:
            return None

        brand_list = ", ".join(candidate_brands)
        prompt = f"""You are a logo verification assistant. Look at the provided image and decide which of these brands is most likely visible: [{brand_list}].
Return valid JSON only with the following fields:
{{"brand": "exact brand name from list", "confidence": 0.0-1.0, "reason": "short explanation"}}
If you cannot confidently identify any brand, set brand to null and confidence to 0.
Focus on logos, text marks, or brand colors."""

        import base64
        try:
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()

            response = self._groq_client.chat.completions.create(
                model="llama-3.2-11b-vision-preview",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                        ]
                    }
                ],
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            result = json.loads(response.choices[0].message.content)
            if result.get("brand") in candidate_brands and result.get("confidence", 0) > 0.6:
                return result
        except Exception as e:
            _log.error("llm_verification_failed", error=str(e))
        return None

    # ── Public API ─────────────────────────────────────────────────────────────

    def classify(self, asset_path: str) -> BrandMatch:
        """Classify a single asset. Returns BrandMatch (brand_id='unmatched' if no confident match)."""
        if not self.brands:
            return BrandMatch("unmatched", "Unmatched", 0.0, 0.0, 0.0, 0.0)

        # Cloud testing mode: mock brand matching, no CLIP/DINO/YOLO loading
        if self._use_mock:
            brand_ids = [b.brand_id for b in self.brands]
            scores = {bid: 0.0 for bid in brand_ids}
            if brand_ids:
                scores[brand_ids[0]] = 0.65  # Deterministic mock score
            best_id = brand_ids[0] if brand_ids else "unmatched"
            best_name = next((b.brand_name for b in self.brands if b.brand_id == best_id), "Unmatched")
            best_conf = scores.get(best_id, 0.0)
            return BrandMatch(
                brand_id=best_id if best_conf >= self.threshold else "unmatched",
                brand_name=best_name,
                confidence=best_conf,
                orb_score=0.0,
                clip_score=0.0,
                hist_score=0.0,
                dino_score=0.0,
                yolo_score=0.0,
                decision_log={
                    "image_path": asset_path,
                    "best_brand": best_name,
                    "raw_ensemble_score": best_conf,
                    "individual_scores": {"orb": 0.0, "hsv": 0.0, "clip": 0.0, "dino": 0.0, "yolo": 0.0},
                    "threshold_used": self.threshold,
                    "llm_override": False,
                    "mock": True,
                    "source": "mock_adapter",
                },
            )

        asset_emb = self._encode_image(asset_path) if _CLIP_AVAILABLE else None

        # Precompute query ORB + hist once per asset
        query_des: Optional[np.ndarray] = None
        query_hist = None
        if _CV2:
            try:
                asset_bgr = cv2.imread(asset_path)
                if asset_bgr is not None:
                    _, query_des = self._extract_orb(asset_bgr)
            except Exception:
                query_des = None

            query_hist = self._hist_from_path(asset_path)

        # Advanced features (DINOv2, YOLO, LLM)
        cropped_img = None
        query_dino_emb = None
        if _DINO_YOLO_GROQ_AVAILABLE and _CV2:
            try:
                cropped_img = self._detect_logo_crop(asset_path)
                query_dino_emb = self._get_dinov2_embedding(cropped_img)
            except Exception as e:
                _log.warning("advanced_features_failed", error=str(e))

        best_id, best_name, best_score = "unmatched", "Unmatched", 0.0
        best_orb, best_clip, best_hist, best_dino, best_yolo = 0.0, 0.0, 0.0, 0.0, 0.0
        decision_log = {}

        # weights (renormalized based on available features)
        w_orb, w_hist, w_clip, w_dino, w_yolo = (
            self.weights["orb"],
            self.weights["hsv"],
            self.weights["clip"],
            self.weights["dino"],
            self.weights["yolo"],
        )

        if not (_CLIP_AVAILABLE and asset_emb is not None):
            w_clip = 0.0
        if not (_DINO_YOLO_GROQ_AVAILABLE and query_dino_emb is not None):
            w_dino = 0.0
        if not (_DINO_YOLO_GROQ_AVAILABLE and self._yolo_model is not None):
            w_yolo = 0.0

        total_weight = w_orb + w_hist + w_clip + w_dino + w_yolo
        if total_weight > 0:
            w_orb /= total_weight
            w_hist /= total_weight
            w_clip /= total_weight
            w_dino /= total_weight
            w_yolo /= total_weight

        for brand in self.brands:
            orb_refs = self._brand_orb.get(brand.brand_id, [])
            hist_refs = self._brand_hist.get(brand.brand_id, [])

            # ORB score (avg over reference renders)
            orb_scores = [self._orb_similarity(query_des, ref_des) for ref_des in orb_refs]
            orb_score = float(np.mean(orb_scores)) if orb_scores else 0.0

            # Histogram score (avg over reference renders)
            hist_scores = [self._hist_similarity_from_hists(query_hist, ref_hist) for ref_hist in hist_refs]
            hist_score = float(np.mean(hist_scores)) if hist_scores else 0.0

            # CLIP score (cosine similarity -> [0,1])
            clip_score = 0.0
            if w_clip > 0.0 and brand.embedding is not None and asset_emb is not None:
                clip_raw = float(np.dot(asset_emb, brand.embedding))  # [-1,1]
                clip_score = max(0.0, (clip_raw + 1.0) / 2.0)          # [0,1]

            # DINOv2 score
            dino_score = 0.0
            if w_dino > 0.0 and brand.dino_embedding is not None and query_dino_emb is not None:
                dino_sim = cosine_similarity([query_dino_emb], [brand.dino_embedding])[0][0]
                dino_score = max(0.0, dino_sim)

            # YOLO score
            yolo_score = 0.0
            if w_yolo > 0.0 and self._yolo_model is not None and _CV2:
                if cropped_img is not None:
                    results = self._yolo_model(cropped_img, verbose=False)[0]
                    if results.boxes is not None and len(results.boxes) > 0:
                        yolo_score = max(float(box.conf[0]) for box in results.boxes)

            combined = orb_score * w_orb + hist_score * w_hist + clip_score * w_clip + dino_score * w_dino + yolo_score * w_yolo

            if combined > best_score:
                best_score = combined
                best_id = brand.brand_id
                best_name = brand.brand_name
                best_orb = orb_score
                best_clip = clip_score
                best_hist = hist_score
                best_dino = dino_score
                best_yolo = yolo_score

        decision_log = {
            "image_path": asset_path,
            "best_brand": best_name,
            "raw_ensemble_score": best_score,
            "individual_scores": {
                "orb": best_orb,
                "hsv": best_hist,
                "clip": best_clip,
                "dino": best_dino,
                "yolo": best_yolo
            },
            "threshold_used": self.threshold,
            "llm_override": False
        }

        # LLM fallback
        final_id = best_id
        final_name = best_name
        final_confidence = best_score
        if _DINO_YOLO_GROQ_AVAILABLE and 0.35 < best_score < 0.65:
            _log.info("ambiguous_match", score=best_score, invoking_llm=True)
            top_candidates = sorted(self.brands, key=lambda b: -best_score)[:3]
            top_candidate_ids = [b.brand_id for b in top_candidates]
            llm_result = self._llm_verify(asset_path, top_candidate_ids, {})
            if llm_result:
                decision_log["llm_override"] = True
                decision_log["llm_output"] = llm_result
                if llm_result["confidence"] > 0.6:
                    for brand in self.brands:
                        if brand.brand_id == llm_result["brand"]:
                            final_id = brand.brand_id
                            final_name = brand.brand_name
                            final_confidence = llm_result["confidence"]
                            _log.info("llm_overrode_decision", brand=final_id, confidence=final_confidence)
                            break

        if final_confidence < self.threshold:
            decision_log["final_decision"] = "unmatched"
            decision_log["reason"] = f"Final confidence {final_confidence:.2f} below threshold {self.threshold}"
            return BrandMatch(
                "unmatched",
                "Unmatched",
                round(final_confidence, 4),
                round(best_orb, 4),
                round(best_clip, 4),
                round(best_hist, 4),
                round(best_dino, 4),
                round(best_yolo, 4),
                decision_log
            )

        decision_log["final_decision"] = final_name
        decision_log["reason"] = f"Ensemble score {best_score:.2f} + LLM override={decision_log['llm_override']}"
        return BrandMatch(
            final_id,
            final_name,
            round(final_confidence, 4),
            round(best_orb, 4),
            round(best_clip, 4),
            round(best_hist, 4),
            round(best_dino, 4),
            round(best_yolo, 4),
            decision_log
        )

    def segregate(self, asset_paths: List[str]) -> Dict[str, List[str]]:
        """Segregate all assets into brand buckets. Unmatched go to 'unmatched'."""
        result: Dict[str, List[str]] = {b.brand_id: [] for b in self.brands}
        result["unmatched"] = []

        for path in asset_paths:
            match = self.classify(path)
            bucket = match.brand_id if match.brand_id in result else "unmatched"
            result[bucket].append(path)

        for brand_id, paths in result.items():
            _log.info("segregation_result", brand=brand_id, count=len(paths))

        # Clear cache after batch
        try:
            from content_engine.utils.mps_safe import empty_cache
            empty_cache()
        except Exception:
            gc.collect()

        return result
