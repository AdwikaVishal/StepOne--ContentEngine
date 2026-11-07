"""
Local vision provider — Florence-2 + CLIP + BLIP.

Used in local mode only. Wraps the existing local model implementations
without adding new inference logic.
"""

from typing import Any, Dict, List, Optional

from content_engine.photo_intelligence.blip_captioner import get_blip_captioner
from content_engine.utils.mps_safe import FLORENCE_DEVICE, FLORENCE_DTYPE, MPS_DEVICE


class LocalVisionProvider:
    """Local vision provider using Florence-2, CLIP, and BLIP."""

    def __init__(self):
        self._florence_model = None
        self._florence_processor = None
        self._clip_model = None
        self._blip_captioner = None

    # ── Florence-2 + CLIP: understand_image ──────────────────────────

    def _load_florence(self):
        if self._florence_model is None:
            import torch
            from transformers import AutoModelForCausalLM, AutoProcessor

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

    def _load_clip(self):
        if self._clip_model is None:
            from sentence_transformers import SentenceTransformer

            self._clip_model = SentenceTransformer("clip-ViT-B-32", device=MPS_DEVICE)
        return self._clip_model

    def understand_image(self, image_path: str) -> Dict[str, Any]:
        """Return scene understanding using Florence-2 + CLIP.

        Schema:
          {
            "scene_concepts": List[str],
            "relevance_scores": Dict[str, float],
            "concept_match_score": float,
            "provider": "local_vision",
          }
        """
        from pathlib import Path

        if not Path(image_path).exists():
            return {
                "scene_concepts": [],
                "relevance_scores": {},
                "concept_match_score": 0.0,
                "provider": "local_vision",
            }

        try:
            model, processor = self._load_florence()
            from PIL import Image

            image = Image.open(image_path).convert("RGB")
            prompt = "<OD>"
            inputs = processor(text=prompt, images=image, return_tensors="pt")
            device = next(model.parameters()).device
            inputs = {k: v.to(device) for k, v in inputs.items()}

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

            labels: List[str] = []
            if parsed and "<OD>" in parsed:
                raw = parsed["<OD>"]
                for part in raw.replace("|", ",").split(","):
                    label = part.strip().strip('"').strip()
                    if label and len(label) > 1:
                        labels.append(label.lower())

            # CLIP relevance scoring
            clip_model = self._load_clip()
            event_concepts = [
                "speech", "audience", "networking", "award", "presentation",
                "crowd", "stage", "logo", "handshake", "applause", "dinner",
                "panel discussion", "keynote", "workshop", "exhibition",
            ]

            relevance_scores: Dict[str, float] = {}
            if labels:
                all_labels = labels + event_concepts
                all_embeddings = clip_model.encode(all_labels)
                label_embs = all_embeddings[: len(labels)]
                concept_embs = all_embeddings[len(labels):]

                import torch as _torch
                label_tensor = _torch.tensor(label_embs)
                concept_tensor = _torch.tensor(concept_embs)
                similarities = _torch.mm(concept_tensor, label_tensor.T)

                for i, concept in enumerate(event_concepts):
                    max_sim = similarities[i].max().item()
                    relevance_scores[concept] = min(1.0, max_sim)

            concept_match_score = (
                max(relevance_scores.values()) if relevance_scores else 0.0
            )

            return {
                "scene_concepts": labels[:20],
                "relevance_scores": relevance_scores,
                "concept_match_score": round(concept_match_score, 4),
                "provider": "local_vision",
            }
        except Exception:
            return {
                "scene_concepts": [],
                "relevance_scores": {},
                "concept_match_score": 0.0,
                "provider": "local_vision",
            }

    # ── BLIP: caption_image ──────────────────────────────────────────

    def caption_image(self, image_path: str) -> str:
        """Return an image caption using BLIP."""
        try:
            captioner = get_blip_captioner()
            result = captioner.caption(image_path, asset_id="local_vision")
            return result.get("caption", "") or ""
        except Exception:
            return ""

    @property
    def name(self) -> str:
        return "local_vision"

    @property
    def requires_api_key(self) -> bool:
        return False

    def is_available(self) -> bool:
        """Local vision is available if transformers and torch are installed."""
        try:
            import transformers  # noqa: F401
            import sentence_transformers  # noqa: F401
            return True
        except ImportError:
            return False
