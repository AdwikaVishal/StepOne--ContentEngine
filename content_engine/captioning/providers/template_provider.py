"""
Template-based caption provider (fallback).
"""

from typing import List, Optional
import re

from .base import CaptionProvider
from ..schema import CaptionGenerationContext, HistoricalPost


class TemplateProvider(CaptionProvider):
    """Template-based caption generation - always available."""
    
    def __init__(self):
        pass
    
    def is_available(self) -> bool:
        return True
    
    def get_name(self) -> str:
        return "template"
    
    def get_capabilities(self) -> dict:
        return {
            "local": True,
            "requires_api_key": False,
            "supports_retrieval": False,
            "platforms": ["linkedin", "instagram", "reel", "stories"]
        }
    
    def _hashtag(self, text: str) -> str:
        return "#" + re.sub(r"[^a-zA-Z0-9]", "", text.title())
    
    def generate_linkedin(self, ctx: CaptionGenerationContext, 
                         examples: Optional[List[HistoricalPost]] = None) -> str:
        hashtag = self._hashtag(ctx.event_name)
        concepts = ", ".join(ctx.detected_concepts[:3]) if ctx.detected_concepts else "networking and insights"
        
        return f"""What stood out at {ctx.event_name}: {concepts}.

The conversations, the energy, and the ideas exchanged reinforced why these moments matter.

{hashtag} #EventInsights #Networking"""
    
    def generate_instagram(self, ctx: CaptionGenerationContext,
                          examples: Optional[List[HistoricalPost]] = None) -> str:
        hashtag = self._hashtag(ctx.event_name)
        return f"""moments from {ctx.event_name} ✨

the energy said it all

swipe for the highlights →

{hashtag} #EventLife #Highlights"""
    
    def generate_reel(self, ctx: CaptionGenerationContext,
                     examples: Optional[List[HistoricalPost]] = None) -> str:
        hashtag = self._hashtag(ctx.event_name)
        return f"""{ctx.event_name} in motion 🎬

the best moments, caught on camera

watch till the end 👀

{hashtag} #EventHighlights #BehindTheScenes"""
    
    def generate_stories(self, ctx: CaptionGenerationContext,
                        num_slides: int = 4,
                        examples: Optional[List[HistoricalPost]] = None) -> List[str]:
        templates = [
            f"moments from {ctx.event_name}...",
            "the energy was real",
            "conversations that matter",
            "swipe to see more →"
        ]
        return templates[:num_slides]
