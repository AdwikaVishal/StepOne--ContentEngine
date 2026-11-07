"""
Groq LLM caption provider adapter.
"""

import os
from typing import List, Optional

from .base import CaptionProvider, CaptionProviderError
from ..schema import CaptionGenerationContext, HistoricalPost


class GroqProvider(CaptionProvider):
    """Groq API-based caption generation adapter."""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "")
        self._generator = None
    
    def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            import groq
            return True
        except ImportError:
            return False
    
    def get_name(self) -> str:
        return "groq"
    
    def get_capabilities(self) -> dict:
        return {
            "local": False,
            "requires_api_key": True,
            "supports_retrieval": False,
            "platforms": ["linkedin", "instagram", "reel", "stories"]
        }
    
    def _get_generator(self):
        if self._generator is None:
            try:
                from config import settings
                from content_engine.copy_generator import _GroqGenerator
                self._generator = _GroqGenerator(
                    api_key=self.api_key,
                    model=settings.groq_model,
                    service_tier=settings.groq_service_tier,
                    temperature=settings.groq_temperature,
                )
            except Exception as e:
                raise CaptionProviderError(f"Failed to initialize Groq: {e}")
        return self._generator
    
    def _build_ctx(self, ctx: CaptionGenerationContext):
        from content_engine.copy_generator import _EventContext
        return _EventContext(
            event_name=ctx.event_name,
            event_description=ctx.event_description or ctx.event_name,
            event_type=ctx.event_type,
            detected_concepts=ctx.detected_concepts,
            scene_labels=ctx.scene_labels,
            total_faces=ctx.total_faces,
            video_highlight_count=0,
            top_asset_scores=[],
            hashtag="#" + ctx.event_name.replace(" ", "")[:20],
        )
    
    def generate_linkedin(self, ctx: CaptionGenerationContext, 
                         examples: Optional[List[HistoricalPost]] = None) -> str:
        gen = self._get_generator()
        return gen.linkedin(self._build_ctx(ctx))
    
    def generate_instagram(self, ctx: CaptionGenerationContext,
                          examples: Optional[List[HistoricalPost]] = None) -> str:
        gen = self._get_generator()
        return gen.instagram(self._build_ctx(ctx))
    
    def generate_reel(self, ctx: CaptionGenerationContext,
                     examples: Optional[List[HistoricalPost]] = None) -> str:
        gen = self._get_generator()
        return gen.reel(self._build_ctx(ctx))
    
    def generate_stories(self, ctx: CaptionGenerationContext,
                        num_slides: int = 4,
                        examples: Optional[List[HistoricalPost]] = None) -> List[str]:
        gen = self._get_generator()
        return gen.stories(self._build_ctx(ctx), num_slides)
