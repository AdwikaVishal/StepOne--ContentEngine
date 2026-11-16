"""
Image composition package — focal-point detection + subject-aware cropping.

Public API:
    from content_engine.composition import FocalAnalyzer, SmartCropper
    from content_engine.composition.focal_analyzer import FocalAnalysis
    from content_engine.composition.smart_crop import CropResult

All inference is local. Models are loaded lazily and shared across the process so
no model weight is ever loaded twice. CPU fallback is used when CUDA is unavailable.
"""

from .focal_analyzer import FocalAnalyzer, FocalAnalysis
from .smart_crop import SmartCropper, CropResult, CropCandidate

__all__ = [
    "FocalAnalyzer",
    "FocalAnalysis",
    "SmartCropper",
    "CropResult",
    "CropCandidate",
]
