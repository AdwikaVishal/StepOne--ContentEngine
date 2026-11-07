"""Captioning module - Local ML caption generation with provider abstraction."""

__version__ = "1.0.0"

from .factory import get_caption_provider, CaptionProviderFactory
from .schema import HistoricalPost, CaptionGenerationContext
from .providers.base import CaptionProvider, CaptionProviderError

__all__ = [
    'get_caption_provider', 
    'CaptionProviderFactory',
    'HistoricalPost', 
    'CaptionGenerationContext',
    'CaptionProvider', 
    'CaptionProviderError'
]
