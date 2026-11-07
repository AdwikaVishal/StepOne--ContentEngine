"""
Base caption provider interface.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

from ..schema import CaptionGenerationContext, HistoricalPost


class CaptionProviderError(Exception):
    """Exception raised by caption providers."""
    pass


class CaptionProvider(ABC):
    """Abstract base class for caption generation providers."""
    
    @abstractmethod
    def generate_linkedin(self, ctx: CaptionGenerationContext, 
                         examples: Optional[List[HistoricalPost]] = None) -> str:
        """Generate LinkedIn caption."""
        pass
    
    @abstractmethod
    def generate_instagram(self, ctx: CaptionGenerationContext,
                          examples: Optional[List[HistoricalPost]] = None) -> str:
        """Generate Instagram caption."""
        pass
    
    @abstractmethod
    def generate_reel(self, ctx: CaptionGenerationContext,
                     examples: Optional[List[HistoricalPost]] = None) -> str:
        """Generate Reel caption."""
        pass
    
    @abstractmethod
    def generate_stories(self, ctx: CaptionGenerationContext,
                        num_slides: int = 4,
                        examples: Optional[List[HistoricalPost]] = None) -> List[str]:
        """Generate Story captions."""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider is available."""
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """Get provider name."""
        pass
    
    @abstractmethod
    def get_capabilities(self) -> Dict[str, Any]:
        """Get provider capabilities."""
        pass
