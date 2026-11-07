"""
Content & Design Engine
Automates asset selection, layout assembly, copy generation,
and case study production for multi-platform social media content.

All heavy ML models are lazily imported — the package can be imported
without any ML dependencies installed (they are only loaded on first use).
"""

# Lightweight data types — always safe to import
from .data_types import AssetMetadata, SelectionResult


def __getattr__(name):
    """
    Lazy-load all heavy classes on first access.
    This prevents import-time failures when ML packages are missing.
    """
    _lazy = {
        "QualityAssessor":    (".models.quality",             "QualityAssessor"),
        "FaceDetector":       (".models.face_detection",      "FaceDetector"),
        "ContentUnderstander":(".models.content_understanding","ContentUnderstander"),
        "VideoProcessor":     (".models.video_processing",    "VideoProcessor"),
        "ContentEngine":      (".pipeline",                   "ContentEngine"),
        "LayoutAssembler":    (".layout_assembler",           "LayoutAssembler"),
        "CopyGenerator":      (".copy_generator",             "CopyGenerator"),
        "generate_case_study":(".case_study_generator",       "generate_case_study"),
        "ContentOrchestrator":(".orchestrator",               "ContentOrchestrator"),
        "BrandSegregator":    (".brand_segregator",           "BrandSegregator"),
        "AssetClassification":(".brand_segregator",           "AssetClassification"),
        "stepone_brand_voice":(".brand_voice",                "stepone_brand_voice"),
        "BrandVoice":         (".brand_voice",                "BrandVoice"),
        "BrandOrchestrator":  (".brand_orchestrator",         "BrandOrchestrator"),
    }
    if name in _lazy:
        module_path, attr = _lazy[name]
        import importlib
        mod = importlib.import_module(module_path, package=__name__)
        return getattr(mod, attr)
    raise AttributeError(f"module 'content_engine' has no attribute {name!r}")

__all__ = [
    # ML Models
    "QualityAssessor",
    "FaceDetector",
    "ContentUnderstander",
    "VideoProcessor",
    # Core pipeline
    "ContentEngine",
    "AssetMetadata",
    "SelectionResult",
    # Layout and copy
    "LayoutAssembler",
    "CopyGenerator",
    "generate_case_study",
    "ContentOrchestrator",
    # Brand segregation (GFF 2025 challenge)
    "BrandSegregator",
    "AssetClassification",
    "BrandOrchestrator",
    # Brand voice
    "stepone_brand_voice",
    "BrandVoice",
]
