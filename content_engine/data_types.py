"""
Shared data classes used across the entire pipeline.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class AssetMetadata:
    path: str
    asset_type: str                          # 'image' | 'video'
    quality_score: float                     # Technical quality (blur + brightness + aesthetic)
    aesthetic_score: float
    face_count: int
    face_confidences: List[float]
    relevance_scores: Dict[str, float]       # concept -> score (semantic relevance)
    scene_concepts: List[str]
    duration: float = 0.0                    # seconds (videos only)
    highlight_clips: Optional[List[Dict]] = None  # videos only
    final_score: float = 0.0                 # composite ranking score

    # ── Separated metrics (Item 3: do not conflate) ─────────────────────────
    technical_quality: float = 0.0           # blur + brightness only
    semantic_relevance: float = 0.0          # concept match score (uncalibrated)
    brand_relevance: float = 0.0             # brand similarity score
    model_confidence: float = 0.0            # model's own confidence (not calibrated probability)
    human_verified: bool = False             # human review status
    selection_reason: Optional[str] = None   # why included/excluded
    classification: str = "uncertain"        # semantic category
    classification_confidence: float = 0.0   # confidence in category assignment
    uncalibrated: bool = True                # true when scores are ranking scores, not probabilities


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
