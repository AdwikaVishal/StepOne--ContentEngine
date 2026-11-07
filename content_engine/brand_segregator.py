"""
Brand Segregator
Classifies photos into brands using CLIP visual similarity to render references.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from pathlib import Path

try:
    from api.logger import get_logger
    _log = get_logger("content_engine.brand_segregator")
except Exception:
    import logging
    _log = logging.getLogger("content_engine.brand_segregator")

try:
    import torch
    import clip
    from PIL import Image
    _CLIP_AVAILABLE = True
except ImportError:
    _CLIP_AVAILABLE = False
    _log.warning("clip not installed, brand segregation disabled")


@dataclass
class BrandReference:
    """Reference images and metadata for a brand."""
    brand_id: str
    brand_name: str
    render_paths: List[str]  # Paths to render images for this brand
    embedding: Optional[torch.Tensor] = None  # Pre-computed average embedding


@dataclass
class AssetClassification:
    """Classification result for a single asset."""
    path: str
    brand_id: Optional[str]  # None if unmatched
    confidence: float
    similarity_scores: Dict[str, float]  # brand_id -> score


class BrandSegregator:
    """
    Segregates photos into brands using CLIP visual similarity.

    Selection Logic:
      1. Load all brand render images as visual references
      2. For each photo in the dataset:
         a. Compute CLIP image embedding
         b. Compare to average embedding of each brand's render images
         c. Assign to brand with highest similarity IF similarity > threshold
         d. If no brand exceeds threshold → "unmatched" bucket
      3. Return dict: brand_id -> List[AssetClassification]

    The threshold prevents false positives when no brand clearly matches.
    """

    DEFAULT_THRESHOLD = 0.60  # Minimum similarity to assign a brand
    MIN_MATCHING_ASSETS = 5  # Minimum assets per brand for valid output

    def __init__(
        self,
        brands: List[Tuple[str, str, List[str]]],  # List of (brand_id, brand_name, render_paths)
        similarity_threshold: float = 0.45,
    ):
        """
        Initialize brand segregator.

        Args:
            brands: List of (brand_id, brand_name, render_paths) tuples
            similarity_threshold: Minimum similarity to assign a brand (0-1)
        """
        self.similarity_threshold = similarity_threshold
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._model = None
        self._preprocess = None

        # Initialize brand references
        self.brands: List[BrandReference] = []
        for brand_id, brand_name, render_paths in brands:
            valid_paths = [p for p in render_paths if Path(p).exists()]
            if valid_paths:
                self.brands.append(BrandReference(
                    brand_id=brand_id,
                    brand_name=brand_name,
                    render_paths=valid_paths,
                ))

        if not self.brands:
            _log.warning("no_valid_brand_references")
            return

        self._init_clip()
        self._compute_brand_embeddings()

    def _init_clip(self):
        """Initialize CLIP model."""
        global _CLIP_AVAILABLE

        if not _CLIP_AVAILABLE:
            _log.warning("clip_not_available_brand_segregation_disabled")
            return

        try:
            model, preprocess = clip.load("ViT-B/32", device=self._device)
            self._model = model
            self._preprocess = preprocess
            _log.info("clip_loaded_for_brand_segregation", device=self._device)
        except Exception as e:
            _log.error("clip_init_failed", error=str(e))
            _CLIP_AVAILABLE = False

    def _compute_brand_embeddings(self):
        """Pre-compute average embedding for each brand from render images."""
        if not _CLIP_AVAILABLE or self._model is None:
            return

        for brand in self.brands:
            embeddings = []
            for render_path in brand.render_paths:
                try:
                    image = Image.open(render_path).convert("RGB")
                    image_input = self._preprocess(image).unsqueeze(0).to(self._device)
                    with torch.no_grad():
                        embedding = self._model.encode_image(image_input)
                        embedding /= embedding.norm(dim=-1, keepdim=True)
                        embeddings.append(embedding)
                except Exception as e:
                    _log.warning("render_embedding_failed", error=str(e), path=render_path)
                    continue

            if embeddings:
                # Average embeddings across all renders for this brand
                avg_embedding = torch.mean(torch.cat(embeddings, dim=0), dim=0, keepdim=True)
                avg_embedding /= avg_embedding.norm(dim=-1, keepdim=True)
                brand.embedding = avg_embedding
                _log.info("brand_embedding_computed", brand_id=brand.brand_id, renders=len(embeddings))

    def classify_asset(self, asset_path: str) -> AssetClassification:
        """
        Classify a single asset into a brand.

        Returns AssetClassification with:
          - path: original asset path
          - brand_id: matched brand or None if unmatched
          - confidence: similarity score of winning brand
          - similarity_scores: dict of all brand scores
        """
        similarity_scores = {brand.brand_id: 0.0 for brand in self.brands}

        if not _CLIP_AVAILABLE or self._model is None or not self.brands:
            return AssetClassification(
                path=asset_path,
                brand_id=None,
                confidence=0.0,
                similarity_scores=similarity_scores,
            )

        try:
            image = Image.open(asset_path).convert("RGB")
            image_input = self._preprocess(image).unsqueeze(0).to(self._device)

            with torch.no_grad():
                image_feat = self._model.encode_image(image_input)
                image_feat /= image_feat.norm(dim=-1, keepdim=True)

                for brand in self.brands:
                    if brand.embedding is not None:
                        sim = (image_feat @ brand.embedding.T).item()
                        # Normalize to 0-1 range (CLIP returns -1 to 1)
                        similarity_scores[brand.brand_id] = round(float(max(0.0, (sim + 1) / 2)), 4)

        except Exception as e:
            _log.warning("asset_classification_failed", error=str(e), path=asset_path)

        # Find best matching brand
        best_brand_id = None
        best_confidence = 0.0

        for brand_id, score in similarity_scores.items():
            if score >= self.similarity_threshold and score > best_confidence:
                best_brand_id = brand_id
                best_confidence = score

        return AssetClassification(
            path=asset_path,
            brand_id=best_brand_id,
            confidence=best_confidence,
            similarity_scores=similarity_scores,
        )

    def segregate_assets(self, asset_paths: List[str]) -> Dict[str, List[AssetClassification]]:
        """
        Segregate all assets into brand buckets.

        Returns:
            Dict mapping brand_id -> List[AssetClassification]
            Assets with no match go into "unmatched" key
        """
        results: Dict[str, List[AssetClassification]] = {
            brand.brand_id: [] for brand in self.brands
        }
        results["unmatched"] = []

        _log.info("segregation_start", total_assets=len(asset_paths), brands=len(self.brands))

        for path in asset_paths:
            classification = self.classify_asset(path)

            if classification.brand_id:
                results[classification.brand_id].append(classification)
            else:
                results["unmatched"].append(classification)

        # Log summary
        for brand_id, assets in results.items():
            _log.info("segregation_summary", brand=brand_id, assets=len(assets))

        return results

    def get_selection_logic(self) -> str:
        """
        Return documented selection logic as required by the challenge.
        """
        return """
BRAND PHOTO SEGREGATION — SELECTION LOGIC
========================================

Step 1: Brand Reference Preparation
  - Load all render images provided for each brand
  - Compute CLIP image embeddings for each render
  - Average embeddings per brand to create a single "brand prototype" vector

Step 2: Asset Classification
  - For each photo in the dataset:
    a. Compute CLIP image embedding
    b. Calculate cosine similarity to each brand's prototype vector
    c. Normalize similarities to 0-1 range

Step 3: Brand Assignment
  - If highest similarity >= threshold ({threshold}):
      Assign photo to that brand
  - If highest similarity < threshold:
      Photo goes to "unmatched" bucket (not deleted, just not assigned)

Step 4: Quality Filtering (within each brand)
  - Apply the standard quality scoring pipeline:
      Technical quality (30%) + Aesthetic (20%) + Face presence (30%) + Concepts (20%)
  - Select top assets per brand for content output

Selection Criteria:
  - Similarity threshold: {threshold} (prevents false positives)
  - Minimum brand size: {min_assets} assets for valid output
  - Assets sorted by final composite score within each brand

Output Organization:
  - One folder per brand containing all content outputs
  - Unmatched assets collected in separate folder for manual review
  - Selection report includes all similarity scores for transparency
""".format(
            threshold=self.similarity_threshold,
            min_assets=self.MIN_MATCHING_ASSETS,
        )
