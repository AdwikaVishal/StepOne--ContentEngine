"""
Shared data classes used across the entire pipeline.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class AssetMetadata:
    path: str
    asset_type: str                          # 'image' | 'video'
    quality_score: float
    aesthetic_score: float
    face_count: int
    face_confidences: List[float]
    relevance_scores: Dict[str, float]       # concept -> score
    scene_concepts: List[str]
    duration: float = 0.0                    # seconds (videos only)
    highlight_clips: Optional[List[Dict]] = None  # videos only
    final_score: float = 0.0                 # composite ranking score


@dataclass
class SelectionResult:
    asset: AssetMetadata
    selection_reason: str
    confidence: float
    intended_use: str   # 'collage' | 'reel' | 'story' | 'case_study'

    @property
    def low_confidence(self) -> bool:
        """True when confidence is below the 0.5 review threshold."""
        return self.confidence < 0.5
