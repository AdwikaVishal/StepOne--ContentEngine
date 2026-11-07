"""
Historical post retrieval system.
"""

import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from collections import defaultdict

from ..schema import HistoricalPost


class HistoricalPostRetriever:
    """Retrieve relevant historical posts for caption generation."""
    
    def __init__(self, data_path: Optional[str] = None):
        self.data_path = Path(data_path) if data_path else Path("data/historical")
        self.posts: List[HistoricalPost] = []
        self._index = defaultdict(list)
    
    def load_posts(self):
        """Load historical posts from data directory."""
        self.posts = []
        if not self.data_path.exists():
            return
        
        for pattern in ['*.json', '*.jsonl']:
            for f in self.data_path.glob(pattern):
                try:
                    if f.suffix == '.json':
                        with open(f, 'r', encoding='utf-8') as fp:
                            data = json.load(fp)
                        items = data if isinstance(data, list) else data.get('posts', [])
                    else:  # jsonl
                        items = []
                        with open(f, 'r', encoding='utf-8') as fp:
                            for line in fp:
                                if line.strip():
                                    items.append(json.loads(line))
                    
                    for item in items:
                        try:
                            post = HistoricalPost.from_dict(item)
                            if post.caption:
                                self.posts.append(post)
                        except Exception:
                            continue
                except Exception:
                    continue
        
        self._build_index()
    
    def _build_index(self):
        """Build indices for fast retrieval."""
        self._index = defaultdict(list)
        for i, post in enumerate(self.posts):
            self._index[('brand', post.brand.lower())].append(i)
            self._index[('platform', post.platform)].append(i)
            self._index[('content_type', post.content_type)].append(i)
            if post.campaign_id:
                self._index[('campaign', post.campaign_id)].append(i)
    
    def retrieve(self, brand: Optional[str] = None, 
                 platform: Optional[str] = None,
                 content_type: Optional[str] = None,
                 campaign_id: Optional[str] = None,
                 campaign_context: Optional[str] = None,
                 k: int = 5,
                 min_engagement: Optional[float] = None) -> List[HistoricalPost]:
        """
        Retrieve relevant historical posts filtered by criteria.
        """
        if not self.posts:
            return []
        
        # Start with all posts
        candidate_indices = set(range(len(self.posts)))
        
        # Apply filters
        if brand:
            brand_indices = set(self._index.get(('brand', brand.lower()), []))
            if brand_indices:
                candidate_indices &= brand_indices
        
        if platform:
            platform_indices = set(self._index.get(('platform', platform.lower()), []))
            if platform_indices:
                candidate_indices &= platform_indices
        
        if content_type:
            ct_indices = set(self._index.get(('content_type', content_type.lower()), []))
            if ct_indices:
                candidate_indices &= ct_indices
        
        if campaign_id:
            camp_indices = set(self._index.get(('campaign', campaign_id), []))
            if camp_indices:
                candidate_indices &= camp_indices
        
        candidates = [self.posts[i] for i in candidate_indices]
        
        # Filter by engagement if specified
        if min_engagement is not None:
            filtered = []
            for post in candidates:
                if post.engagement_rate is not None and post.engagement_rate >= min_engagement:
                    filtered.append(post)
            candidates = filtered
        
        # Sort by engagement if available
        def sort_key(p):
            if p.engagement_rate is not None:
                return p.engagement_rate
            if p.likes is not None:
                return p.likes
            return 0
        
        candidates.sort(key=sort_key, reverse=True)
        return candidates[:k]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about loaded posts."""
        if not self.posts:
            return {"total": 0}
        
        brands = defaultdict(int)
        platforms = defaultdict(int)
        for p in self.posts:
            brands[p.brand] += 1
            platforms[p.platform] += 1
        
        return {
            "total": len(self.posts),
            "brands": dict(brands),
            "platforms": dict(platforms),
        }
