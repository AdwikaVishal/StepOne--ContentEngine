"""
Data types for Photo Intelligence module.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class AssetAnalysis:
    """Analysis results for a single asset."""
    asset_id: str
    original_filename: str
    path: str
    asset_type: str = "image"
    
    # Quality signals (heuristics)
    sharpness: float = 0.0  # Laplacian variance
    exposure: float = 0.0   # brightness/exposure score
    resolution_score: float = 0.0
    width: int = 0
    height: int = 0
    file_size_bytes: int = 0
    
    # Similarity
    phash: Optional[str] = None
    similarity_group_id: Optional[str] = None
    
    # Semantic (from existing models if available)
    description: str = ""
    scene_concepts: List[str] = field(default_factory=list)
    embeddings_available: bool = False
    
    # Ranking
    component_scores: Dict[str, float] = field(default_factory=dict)
    overall_score: float = 0.0
    confidence: float = 0.0
    reasons: List[str] = field(default_factory=list)
    is_recommended: bool = False
    
    # User state
    user_accepted: Optional[bool] = None
    user_rejected: Optional[bool] = None
    user_order: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "original_filename": self.original_filename,
            "path": self.path,
            "asset_type": self.asset_type,
            "sharpness": round(self.sharpness, 4),
            "exposure": round(self.exposure, 4),
            "resolution_score": round(self.resolution_score, 4),
            "width": self.width,
            "height": self.height,
            "file_size_bytes": self.file_size_bytes,
            "phash": self.phash,
            "similarity_group_id": self.similarity_group_id,
            "description": self.description,
            "scene_concepts": self.scene_concepts,
            "embeddings_available": self.embeddings_available,
            "component_scores": {k: round(v, 4) for k, v in self.component_scores.items()},
            "overall_score": round(self.overall_score, 4),
            "confidence": round(self.confidence, 4),
            "reasons": self.reasons,
            "is_recommended": self.is_recommended,
            "user_accepted": self.user_accepted,
            "user_rejected": self.user_rejected,
            "user_order": self.user_order,
        }


@dataclass
class RankedGroup:
    """Group of near-duplicate/similar images with recommendation."""
    group_id: str
    assets: List[AssetAnalysis]
    recommended_asset_id: str
    group_reason: str
    similarity_threshold: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_id": self.group_id,
            "assets": [a.to_dict() for a in self.assets],
            "recommended_asset_id": self.recommended_asset_id,
            "group_reason": self.group_reason,
            "similarity_threshold": round(self.similarity_threshold, 4),
        }


@dataclass
class CarouselRecommendation:
    """Recommended sequence for carousel/campaign."""
    sequence: List[str]  # asset_ids in order
    rationale: str
    diversity_score: float = 0.0
    coverage_score: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "sequence": self.sequence,
            "rationale": self.rationale,
            "diversity_score": round(self.diversity_score, 4),
            "coverage_score": round(self.coverage_score, 4),
        }


@dataclass
class PhotoIntelligenceResult:
    """Complete result from photo intelligence analysis."""
    assets: List[AssetAnalysis]
    groups: List[RankedGroup]
    carousel_recommendation: CarouselRecommendation
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "assets": [a.to_dict() for a in self.assets],
            "groups": [g.to_dict() for g in self.groups],
            "carousel_recommendation": self.carousel_recommendation.to_dict(),
            "warnings": self.warnings,
            "metadata": self.metadata,
        }
