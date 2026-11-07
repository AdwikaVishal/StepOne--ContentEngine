"""
Mock vision adapters for cloud_testing mode.

These return deterministic TEST_DATA without loading any local model weights.
Used for face detection, quality assessment, and brand matching when
AI_EXECUTION_MODE=cloud_testing.

All results carry an explicit `mock: true` flag and `source: "mock_adapter"`
so they are never mistaken for actual model predictions.
"""

from typing import Any, Dict, List, Optional


class MockFaceDetector:
    """Mock face detection — returns empty face data in cloud_testing mode.

    YOLOv11n bounding boxes have no faithful cloud API replacement.
    This adapter lets the UI be tested without loading YOLO weights.
    """

    def detect_faces_detailed(self, image_path: str) -> Dict[str, Any]:
        """Return mocked face detection result (no model loaded)."""
        return {
            "face_count": 0,
            "confidences": [],
            "bboxes": [],
            "bboxes_norm": [],
            "weights": [],
            "weighted_score": 0.0,
            "mock": True,
            "source": "mock_adapter",
            "provider": "mock_face",
        }

    def detect_faces(self, image_path: str):
        """Backward-compatible (count, confidences)."""
        result = self.detect_faces_detailed(image_path)
        return result["face_count"], result["confidences"]

    @property
    def model(self):
        """No model — raises if anything tries to access it."""
        raise RuntimeError(
            "MockFaceDetector has no model. YOLOv11n is not loaded in cloud_testing mode."
        )


class MockQualityAssessor:
    """Mock quality assessment — returns default scores in cloud_testing mode.

    CLIP aesthetic scoring has no faithful cloud API replacement.
    This adapter lets the pipeline be tested without loading CLIP weights.
    """

    def assess(self, image_path: str) -> Dict[str, float]:
        """Return mocked quality scores (no model loaded)."""
        return {
            "blur_score": 0.5,
            "brightness_score": 0.5,
            "aesthetic_score": 0.5,
            "quality_score": 0.5,
            "mock": True,
            "source": "mock_adapter",
            "provider": "mock_quality",
        }

    def compute_aesthetic_score(self, image) -> float:
        """Return mocked aesthetic score."""
        return 0.5

    @property
    def clip_model(self):
        """No model — raises if anything tries to access it."""
        raise RuntimeError(
            "MockQualityAssessor has no CLIP model. CLIP is not loaded in cloud_testing mode."
        )


class MockBrandMatcher:
    """Mock brand matching — returns deterministic mock similarity scores.

    CLIP cosine similarity has no faithful cloud API replacement.
    Groq semantic descriptions are a separate feature (SemanticBrandMatcher)
    and must never be represented as CLIP scores.

    All scores carry `mock: true` and `source: "mock_adapter"`.
    """

    DEFAULT_THRESHOLD = 0.60

    def __init__(
        self,
        brands: List = None,
        similarity_threshold: float = 0.60,
        **kwargs,
    ):
        self.similarity_threshold = similarity_threshold
        self.brands = brands or []
        self.brand_ids = [b[0] if isinstance(b, (tuple, list)) else getattr(b, "brand_id", str(b)) for b in self.brands]

    def classify_asset(self, asset_path: str) -> Dict[str, Any]:
        """Return mocked brand classification (no CLIP loaded)."""
        scores = {bid: 0.0 for bid in self.brand_ids}
        # Deterministic mock: assign first brand a mid-range mock score
        if self.brand_ids:
            scores[self.brand_ids[0]] = 0.65
        best_brand = self.brand_ids[0] if self.brand_ids else None
        best_conf = scores.get(best_brand, 0.0) if best_brand else 0.0
        return {
            "path": asset_path,
            "brand_id": best_brand if best_conf >= self.similarity_threshold else None,
            "confidence": best_conf,
            "similarity_scores": scores,
            "mock": True,
            "source": "mock_adapter",
            "provider": "mock_brand",
        }

    def segregate_assets(self, asset_paths: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Return mocked segregation results (no CLIP loaded)."""
        results: Dict[str, List[Dict[str, Any]]] = {bid: [] for bid in self.brand_ids}
        results["unmatched"] = []
        for path in asset_paths:
            classification = self.classify_asset(path)
            bid = classification.get("brand_id")
            if bid and bid in results:
                results[bid].append(classification)
            else:
                results["unmatched"].append(classification)
        return results

    def get_selection_logic(self) -> str:
        """Return selection logic documentation."""
        return (
            "BRAND PHOTO SEGREGATION — MOCK (cloud_testing mode)\n"
            "CLIP numerical scoring is disabled in cloud_testing mode.\n"
            "All similarity scores are TEST_DATA from MockBrandMatcher.\n"
        )


class SemanticBrandMatcher:
    """Optional Groq-based semantic brand description (cloud_testing only).

    This is CLEARLY DISTINGUISHED from CLIP numerical similarity.
    It returns free-text rationale, not cosine similarity scores.
    Never mixed into the numerical similarity_scores contract.
    """

    def __init__(self, api_key: Optional[str] = None):
        from content_engine.providers.llm.groq import GroqProvider

        self._groq = GroqProvider(api_key=api_key)

    def describe_brand_fit(
        self,
        image_path: str,
        brand_name: str,
        brand_description: str = "",
    ) -> str:
        """Return a free-text semantic rationale for brand fit.

        NOT a CLIP score. Not numerically comparable to CLIP similarity.
        """
        system = (
            "You are a brand strategist. Given an image and a brand profile, "
            "write a brief rationale for whether the image fits the brand. "
            "Do not provide numerical scores or percentages."
        )
        user = (
            f"Image: {image_path}\n"
            f"Brand: {brand_name}\n"
            f"Brand description: {brand_description}\n"
        )
        return self._groq.generate(
            system=system,
            user=user,
            max_tokens=200,
            temperature=0.3,
        )
