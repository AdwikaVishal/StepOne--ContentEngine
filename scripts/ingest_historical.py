#!/usr/bin/env python3
"""
Dataset Ingestion Script - Historical Posts
Supports CSV, JSON, JSONL formats. Parquet requires pyarrow/pandas.
"""

import json
import csv
import sys
import os
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter
from typing import List, Dict, Any, Optional


class HistoricalDataIngester:
    CANONICAL_FIELDS = [
        'post_id', 'platform', 'brand', 'content_type', 'caption', 
        'hashtags', 'published_at', 'asset_references', 'campaign_id', 
        'campaign_name', 'likes', 'comments', 'shares', 'saves', 'views'
    ]
    
    PLATFORM_ALIASES = {
        'li': 'linkedin', 'linked_in': 'linkedin',
        'ig': 'instagram', 'insta': 'instagram',
        'yt': 'youtube', 'tube': 'youtube'
    }
    
    def __init__(self, input_path: str, output_dir: str = "data/processed"):
        self.input_path = Path(input_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir = self.output_dir / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.posts = []
        self.issues = []
    
    def ingest(self):
        if not self.input_path.exists():
            raise FileNotFoundError(f"Input not found: {self.input_path}")
        
        # Preserve raw file
        if self.input_path.is_file():
            import shutil
            shutil.copy2(self.input_path, self.raw_dir / self.input_path.name)
        
        ext = self.input_path.suffix.lower()
        if ext == '.csv':
            self._ingest_csv()
        elif ext == '.json':
            self._ingest_json()
        elif ext == '.jsonl':
            self._ingest_jsonl()
        elif ext == '.parquet':
            self._ingest_parquet()
        else:
            raise ValueError(f"Unsupported format: {ext}")
        
        self._normalize()
        self._validate()
        self._deduplicate()
        return self.posts
    
    def _ingest_csv(self):
        with open(self.input_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.posts.append(dict(row))
    
    def _ingest_json(self):
        with open(self.input_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.posts = data if isinstance(data, list) else data.get('posts', [])
    
    def _ingest_jsonl(self):
        with open(self.input_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    self.posts.append(json.loads(line))
    
    def _ingest_parquet(self):
        try:
            import pandas as pd
            df = pd.read_parquet(self.input_path)
            self.posts = df.to_dict('records')
        except ImportError:
            raise ImportError("pandas/pyarrow required for parquet. Install with: pip install pandas pyarrow")
    
    def _normalize(self):
        normalized = []
        for post in self.posts:
            p = {}
            # Map common field variations
            p['post_id'] = post.get('post_id') or post.get('id') or post.get('postId') or ''
            p['platform'] = str(post.get('platform') or post.get('social_platform') or '').lower()
            p['platform'] = self.PLATFORM_ALIASES.get(p['platform'], p['platform'])
            p['brand'] = post.get('brand') or post.get('page_name') or post.get('account') or ''
            p['content_type'] = str(post.get('content_type') or post.get('type') or post.get('media_type') or 'photo').lower()
            p['caption'] = post.get('caption') or post.get('text') or post.get('message') or post.get('description') or ''
            p['hashtags'] = post.get('hashtags') or []
            if isinstance(p['hashtags'], str):
                p['hashtags'] = [h.strip() for h in p['hashtags'].split(',') if h.strip()]
            p['published_at'] = post.get('published_at') or post.get('posted_at') or post.get('date') or post.get('created_at') or post.get('timestamp')
            p['asset_references'] = post.get('asset_references') or post.get('media_urls') or post.get('assets') or []
            p['campaign_id'] = post.get('campaign_id') or post.get('campaign')
            p['campaign_name'] = post.get('campaign_name')
            # Metrics
            for m in ['likes', 'comments', 'shares', 'saves', 'views', 'impressions']:
                val = post.get(m)
                if val is not None and val != '':
                    try:
                        p[m] = int(val)
                    except (ValueError, TypeError):
                        p[m] = val
            p['_source'] = str(self.input_path.name)
            p['_raw'] = post  # keep reference for provenance
            normalized.append(p)
        self.posts = normalized
    
    def _validate(self):
        for i, post in enumerate(self.posts):
            if not post.get('caption'):
                self.issues.append(f"Row {i}: missing caption")
            if not post.get('platform'):
                self.issues.append(f"Row {i}: missing platform")
            if not post.get('brand'):
                self.issues.append(f"Row {i}: missing brand")
    
    def _deduplicate(self):
        seen = set()
        unique = []
        dupes = 0
        for post in self.posts:
            key = (post.get('post_id'), post.get('caption', '')[:100])
            if key in seen and post.get('post_id'):
                dupes += 1
                continue
            seen.add(key)
            unique.append(post)
        self.posts = unique
        if dupes:
            self.issues.append(f"Removed {dupes} duplicate posts")
    
    def save(self, filename: str = None):
        if filename is None:
            filename = f"historical_posts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        out_path = self.output_dir / filename
        # Remove _raw before saving (can be large)
        to_save = []
        for p in self.posts:
            p_copy = {k: v for k, v in p.items() if k != '_raw'}
            to_save.append(p_copy)
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(to_save, f, indent=2)
        print(f"Saved {len(to_save)} posts to {out_path}")
        return out_path
    
    def profile(self):
        stats = {
            "total": len(self.posts),
            "platforms": dict(Counter(p.get('platform') for p in self.posts)),
            "brands": dict(Counter(p.get('brand') for p in self.posts)),
            "content_types": dict(Counter(p.get('content_type') for p in self.posts)),
            "issues": self.issues,
            "metric_coverage": {}
        }
        for m in ['likes', 'comments', 'shares', 'saves', 'views']:
            count = sum(1 for p in self.posts if m in p and p[m] is not None)
            stats["metric_coverage"][m] = {"present": count, "pct": round(count/len(self.posts)*100, 1) if self.posts else 0}
        return stats


def main():
    if len(sys.argv) < 2:
        print("Usage: python ingest_historical.py <input_file> [output_dir]")
        sys.exit(1)
    ingester = HistoricalDataIngester(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "data/processed")
    posts = ingester.ingest()
    print(f"Ingested {len(posts)} posts")
    for issue in ingester.issues:
        print(f"  ISSUE: {issue}")
    stats = ingester.profile()
    print(f"Platforms: {stats['platforms']}")
    print(f"Brands: {stats['brands']}")
    ingester.save()


if __name__ == "__main__":
    main()
