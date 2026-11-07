"""
Content Understander — Florence-2 + CLIP Semantic Concept Matching

Item 12: Concept relevance scoring
  - Florence-2 object detection (<OD> task) extracts scene labels
  - CLIP encodes both labels and event concepts
  - Cosine similarity between label embeddings and concept embeddings
  - Concept weights from config/concept_weights.json

Returns:
  - scene_concepts: list of detected labels
  - relevance_scores: {concept: 0-1 score}
  - concept_match_score: max(relevance_scores.values())
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

# Default event concepts (15 total — used if no custom list provided)
DEFAULT_EVENT_CONCEPTS = [
    "speech", "audience", "networking", "award", "presentation",
    "crowd", "stage", "logo", "handshake", "applause", "dinner",
    "panel discussion", "keynote", "workshop", "exhibition",
]

try:
    from content_engine.ai_mode import is_cloud_testing
    from content_engine.providers import get_vision_provider
except ImportError:
    is_cloud_testing = lambda: False
    get_vision_provider = None  # type: ignore


def _load_default_weights() -> Dict[str, float]:
    """Load concept weights from config/concept_weights.json."""
    try:
        path = Path(__file__).parent.parent.parent / "config" / "concept_weights.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


class ContentUnderstander:
    """
    Florence-2 for object detection, CLIP for semantic concept matching.

    In cloud_testing mode, delegates to a Gemini vision provider instead of
    loading local Florence-2/CLIP weights.

    Scoring:
      - scene_concepts: list of detected objects
      - relevance_scores: per-concept CLIP similarity (0–1)
      - concept_match_score: max(relevance_scores.values()) — used in composite scoring
    """

    def __init__(
        self,
        event_concepts: Optional[List[str]] = None,
        concept_weights: Optional[Dict[str, float]] = None,
        vision_provider: Optional[object] = None,
    ):
        self.event_concepts   = event_concepts or DEFAULT_EVENT_CONCEPTS
        self.concept_weights  = concept_weights or _load_default_weights()

        self._florence_model  = None
        self._florence_processor = None
        self._clip_model      = None

        # Provider-based routing (cloud_testing mode)
        self._vision_provider = vision_provider
        if self._vision_provider is None and is_cloud_testing() and get_vision_provider is not None:
            self._vision_provider = get_vision_provider()

    # ── Model lazy-loads ───────────────────────────────────────────────────────

    @property
    def florence(self):
        """Load Florence-2 base model on first use — always CPU (MPS crashes with float16)."""
        if self._florence_model is None:
            import torch
            from transformers import AutoModelForCausalLM, AutoProcessor
            from content_engine.utils.mps_safe import FLORENCE_DEVICE, FLORENCE_DTYPE

            self._florence_model = AutoModelForCausalLM.from_pretrained(
                "microsoft/Florence-2-base",
                torch_dtype=FLORENCE_DTYPE,
                trust_remote_code=True,
                attn_implementation="eager",
            ).to(FLORENCE_DEVICE)

            self._florence_processor = AutoProcessor.from_pretrained(
                "microsoft/Florence-2-base",
                trust_remote_code=True,
            )
        return self._florence_model, self._florence_processor

    @property
    def clip(self):
        """Load CLIP model on first use — MPS when available."""
        if self._clip_model is None:
            from sentence_transformers import SentenceTransformer
            from content_engine.utils.mps_safe import MPS_DEVICE
            self._clip_model = SentenceTransformer("clip-ViT-B-32", device=MPS_DEVICE)
        return self._clip_model

    # ── Object detection ────────────────────────────────────────────────────────

    def _run_object_detection(self, image_path: str) -> List[str]:
        """
        Run Florence-2 <OD> task to extract scene labels.
        Returns list of detected labels (e.g., ["person", "stage", "audience"]).
        """
        from PIL import Image

        model, processor = self.florence
        image = Image.open(image_path).convert("RGB")

        prompt   = "<OD>"
        inputs  = processor(text=prompt, images=image, return_tensors="pt")

        # Move to same device as model
        device  = next(model.parameters()).device
        inputs  = {k: v.to(device) for k, v in inputs.items()}

        with torch.no_grad():
            generated_ids = model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=256,
                do_sample=False,
                num_beams=3,
            )

        generated_text = processor.batch_decode(
            generated_ids, skip_special_tokens=False
        )[0]

        parsed = processor.post_process_generation(
            generated_text,
            task="<OD>",
            image_size=(image.width, image.height),
        )

        # Florence-2 <OD> format: labels separated by "|" or ", "
        labels = []
        if parsed and "<OD>" in parsed:
            raw = parsed["<OD>"]
            # Split on common delimiters
            for part in raw.replace("|", ",").split(","):
                label = part.strip().strip('"').strip()
                if label and len(label) > 1:
                    labels.append(label.lower())

        return labels

    # ── Concept scoring ─────────────────────────────────────────────────────────

    def _score_concepts(
        self,
        detected_labels: List[str],
        concept_weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """
        Score each event concept based on CLIP similarity to detected labels.

        Args:
            detected_labels: labels from Florence-2 object detection
            concept_weights: optional dict {concept: weight} to boost specific concepts

        Returns:
            {concept: similarity_score} for all event_concepts
        """
        if not detected_labels:
            return {c: 0.0 for c in self.event_concepts}

        weights  = concept_weights or self.concept_weights

        # Encode all labels and concepts with CLIP
        all_labels    = detected_labels + self.event_concepts
        all_embeddings = self.clip.encode(all_labels)

        label_embs   = all_embeddings[:len(detected_labels)]
        concept_embs = all_embeddings[len(detected_labels):]

        # Cosine similarity between each label and each concept
        import torch
        label_tensor    = torch.tensor(label_embs)
        concept_tensor  = torch.tensor(concept_embs)

        # Compute all pairwise similarities
        similarities = torch.mm(concept_tensor, label_tensor.T)

        # For each concept, take the max similarity across all labels
        scores = {}
        for i, concept in enumerate(self.event_concepts):
            max_sim = similarities[i].max().item()
            weight  = weights.get(concept, 1.0)
            scores[concept] = min(1.0, max_sim * weight)  # Cap at 1.0

        return scores

    # ── Public API ──────────────────────────────────────────────────────────────

    def understand_image(self, image_path: str) -> Dict:
        """
        Full content understanding of an image.

        In cloud_testing mode, delegates to the configured vision provider
        (Gemini) without loading Florence-2 or CLIP locally.
        In local mode, uses Florence-2 <OD> + CLIP concept matching.

        Returns:
            {
                "scene_concepts": list of detected objects,
                "relevance_scores": {concept: 0-1 score},
                "concept_match_score": max(relevance_scores.values()),
            }
        """
        from pathlib import Path

        # Cloud mode: delegate to vision provider, no local model loading.
        # The provider handles file existence and errors itself.
        if self._vision_provider is not None:
            try:
                result = self._vision_provider.understand_image(image_path)
                # Preserve provider's schema exactly: relevance_scores may be
                # empty when the cloud provider cannot calculate CLIP-equivalent scores.
                return {
                    "scene_concepts": result.get("scene_concepts", []),
                    "relevance_scores": result.get("relevance_scores", {}),
                    "concept_match_score": result.get("concept_match_score", 0.0),
                    "semantic_description": result.get("semantic_description", ""),
                    "provider": result.get("provider", "groq"),
                }
            except Exception:
                return {
                    "scene_concepts": [],
                    "relevance_scores": {},
                    "concept_match_score": None,
                }

        # Guard against missing files (local mode only)
        if not Path(image_path).exists():
            return {
                "scene_concepts": [],
                "relevance_scores": {},
                "concept_match_score": 0.0,
            }

        try:
            detected_labels = self._run_object_detection(image_path)
        except Exception:
            detected_labels = []
        finally:
            from content_engine.utils.mps_safe import empty_cache
            empty_cache()

        relevance_scores   = self._score_concepts(detected_labels)
        concept_match_score = max(relevance_scores.values()) if relevance_scores else 0.0

        return {
            "scene_concepts":     detected_labels[:20],   # Cap at 20 labels
            "relevance_scores":   relevance_scores,
            "concept_match_score": round(concept_match_score, 4),
        }

    # ── Class methods ────────────────────────────────────────────────────────────

    @staticmethod
    def _load_default_weights() -> Dict[str, float]:
        """Load concept weights from config file."""
        return _load_default_weights()