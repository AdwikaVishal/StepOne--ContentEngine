"""
Photo Intelligence module - AI-assisted image curation for social posts.
Uses existing vision models (CLIP/Florence-2) when available, with
deterministic heuristics as fallbacks. No model training, no labeled datasets.
"""
from .analyzer import PhotoIntelligenceAnalyzer
from .types import AssetAnalysis, RankedGroup, CarouselRecommendation, PhotoIntelligenceResult

__all__ = [
    "PhotoIntelligenceAnalyzer",
    "AssetAnalysis",
    "RankedGroup", 
    "CarouselRecommendation",
    "PhotoIntelligenceResult",
]
