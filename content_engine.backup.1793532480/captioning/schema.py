"""
Canonical schema for historical social media posts.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional


@dataclass
class HistoricalPost:
    """Canonical representation of a historical social media post."""
    # Identifiers
    post_id: str
    brand: str
    platform: str  # linkedin, instagram, youtube
    content_type: str  # carousel, reel, story, photo, video
    
    # Content
    caption: str
    hashtags: List[str] = field(default_factory=list)
    assets: List[Dict[str, Any]] = field(default_factory=list)
    
    # Engagement metrics
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    saves: Optional[int] = None
    views: Optional[int] = None
    impressions: Optional[int] = None
    engagement_rate: Optional[float] = None
    
    # Context
    campaign_id: Optional[str] = None
    campaign_name: Optional[str] = None
    posted_at: Optional[datetime] = None
    language: str = "en"
    
    # Metadata
    source: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "post_id": self.post_id,
            "brand": self.brand,
            "platform": self.platform,
            "content_type": self.content_type,
            "caption": self.caption,
            "hashtags": self.hashtags,
            "assets": self.assets,
            "likes": self.likes,
            "comments": self.comments,
            "shares": self.shares,
            "saves": self.saves,
            "views": self.views,
            "impressions": self.impressions,
            "engagement_rate": self.engagement_rate,
            "campaign_id": self.campaign_id,
            "campaign_name": self.campaign_name,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "language": self.language,
            "source": self.source,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'HistoricalPost':
        posted_at = None
        if data.get('posted_at'):
            try:
                if isinstance(data['posted_at'], str):
                    posted_at = datetime.fromisoformat(data['posted_at'].replace('Z', '+00:00'))
                elif isinstance(data['posted_at'], datetime):
                    posted_at = data['posted_at']
            except Exception:
                pass
        
        return cls(
            post_id=str(data.get('post_id') or data.get('id') or ''),
            brand=str(data.get('brand') or ''),
            platform=str(data.get('platform') or '').lower(),
            content_type=str(data.get('content_type') or data.get('type') or 'photo').lower(),
            caption=str(data.get('caption') or ''),
            hashtags=data.get('hashtags') or [],
            assets=data.get('assets') or [],
            likes=data.get('likes'),
            comments=data.get('comments'),
            shares=data.get('shares'),
            saves=data.get('saves'),
            views=data.get('views'),
            impressions=data.get('impressions'),
            engagement_rate=data.get('engagement_rate'),
            campaign_id=data.get('campaign_id'),
            campaign_name=data.get('campaign_name'),
            posted_at=posted_at,
            language=str(data.get('language') or 'en').lower(),
            source=data.get('source'),
            raw_data=data,
        )


@dataclass
class CaptionGenerationContext:
    """Context for caption generation."""
    event_name: str
    event_description: str = ""
    brand: Optional[str] = None
    platform: str = "linkedin"
    event_type: str = "default"
    detected_concepts: List[str] = field(default_factory=list)
    scene_labels: List[str] = field(default_factory=list)
    total_faces: int = 0
    asset_count: int = 0
    campaign_id: Optional[str] = None
    campaign_name: Optional[str] = None
    use_retrieval: bool = True
    retrieval_k: int = 5
