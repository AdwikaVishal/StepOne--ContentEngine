"""
StepOne brand voice copy generator for GFF 2025.
Wraps existing CopyGenerator with brand-aware prompts.
"""

from typing import List

try:
    from api.logger import get_logger
    _log = get_logger("content_engine.gff.stepone_voice")
except Exception:
    import logging
    _log = logging.getLogger("content_engine.gff.stepone_voice")


BRAND_VOICE_GUIDELINES = """
## StepOne Brand Voice

| Principle | Do | Don't |
|-----------|-----|-------|
| Clear over clever | "We increased engagement by 45%" | "We blew the roof off" |
| Active over passive | "We designed" | "The design was created" |
| Specific over vague | "47 people engaged" | "Many people showed up" |
| Confident over tentative | "We deliver results" | "We try to deliver" |
| Human over corporate | "We've seen this work" | "It has been observed" |

**Use:** insight-driven, experience-led, measurable impact, experiential intelligence
**Avoid:** creative agency, event management, event solutions, "we work hard to try to"
"""


def generate_carousel_caption(brand_name: str, event_name: str, num_slides: int) -> str:
    """Instagram carousel caption — StepOne voice."""
    try:
        from content_engine.copy_generator import CopyGenerator
        from content_engine.data_types import AssetMetadata

        # Synthetic asset for context
        asset = AssetMetadata(
            path="synthetic", asset_type="image",
            quality_score=0.8, aesthetic_score=0.7,
            face_count=5, face_confidences=[0.9] * 5,
            relevance_scores={"networking": 0.9, "stage": 0.8, "audience": 0.85},
            scene_concepts=["networking", "stage", "audience", "award"],
            final_score=0.82,
        )
        gen = CopyGenerator()
        return gen.generate_brand_carousel_caption(
            brand_name=brand_name,
            event_name=event_name,
            assets=[asset],
        )
    except Exception as e:
        _log.warning("carousel_caption_fallback", error=str(e))
        tag = brand_name.replace(" ", "")
        return (
            f"{brand_name} at {event_name}.\n\n"
            f"The moments that mattered. The people who showed up.\n\n"
            f"Swipe through for the full story →\n\n"
            f"#{tag} #GFF2025 #ExperientialIntelligence"
        )


def generate_reel_caption(brand_name: str, event_name: str, duration: int) -> str:
    """Instagram Reel caption — punchy, energetic."""
    try:
        from content_engine.copy_generator import CopyGenerator
        from content_engine.data_types import AssetMetadata

        asset = AssetMetadata(
            path="synthetic", asset_type="video",
            quality_score=0.8, aesthetic_score=0.7,
            face_count=8, face_confidences=[0.9] * 8,
            relevance_scores={"stage": 0.9, "crowd": 0.85},
            scene_concepts=["stage", "crowd", "applause"],
            final_score=0.85,
        )
        gen = CopyGenerator()
        return gen.generate_brand_reel_caption(
            brand_name=brand_name,
            event_name=event_name,
            assets=[asset],
        )
    except Exception as e:
        _log.warning("reel_caption_fallback", error=str(e))
        tag = brand_name.replace(" ", "")
        return (
            f"{duration}s. One insight. Unlimited possibility.\n\n"
            f"Watch how we brought {brand_name}'s story to life at {event_name}.\n\n"
            f"Experiences that move people.\n\n"
            f"#{tag} #GFF2025 #StepOne"
        )


def generate_story_captions(brand_name: str, event_name: str, num_frames: int = 4) -> List[str]:
    """Sequential story captions — narrative arc."""
    try:
        from content_engine.copy_generator import CopyGenerator
        from content_engine.data_types import AssetMetadata

        asset = AssetMetadata(
            path="synthetic", asset_type="image",
            quality_score=0.8, aesthetic_score=0.7,
            face_count=3, face_confidences=[0.9] * 3,
            relevance_scores={"networking": 0.9},
            scene_concepts=["networking", "stage"],
            final_score=0.8,
        )
        gen = CopyGenerator()
        return gen.generate_brand_story_captions(
            brand_name=brand_name,
            event_name=event_name,
            num_slides=num_frames,
            assets=[asset],
        )
    except Exception as e:
        _log.warning("story_captions_fallback", error=str(e))
        return [
            f"{brand_name} at {event_name} →",
            "The insight that started it all →",
            "The moment it clicked →",
            f"Experiences that move people. #{brand_name.replace(' ', '')}",
        ][:num_frames]
