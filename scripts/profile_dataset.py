#!/usr/bin/env python3
"""
Dataset Profiling Script - Historical Posts Dataset Audit
Reproducible profiling for privacy-conscious data quality assessment.
"""

import json
import csv
import sys
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime
from typing import Optional


class DatasetProfiler:
    def __init__(self, data_path: str):
        self.data_path = Path(data_path)
        self.posts = []
        self.stats = {
            "row_count": 0,
            "file_info": {},
            "duplicates": {},
            "missing_fields": {},
            "platform_distribution": {},
            "brand_distribution": {},
            "language_distribution": {},
            "metric_availability": {},
            "timestamp_coverage": {},
            "content_type_distribution": {},
        }
    
    def load_data(self):
        """Load dataset from various formats."""
        if not self.data_path.exists():
            print(f"ERROR: Path does not exist: {self.data_path}")
            return False
        
        if self.data_path.is_file():
            ext = self.data_path.suffix.lower()
            if ext == '.json':
                with open(self.data_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.posts = data if isinstance(data, list) else data.get('posts', [])
            elif ext == '.jsonl':
                with open(self.data_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            self.posts.append(json.loads(line))
            elif ext == '.csv':
                with open(self.data_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    self.posts = list(reader)
            else:
                print(f"ERROR: Unsupported file format: {ext}")
                return False
        elif self.data_path.is_dir():
            print("Directory mode - searching for dataset files...")
            found = False
            for pattern in ['*.json', '*.jsonl', '*.csv']:
                for f in self.data_path.glob(pattern):
                    print(f"  Found: {f}")
                    found = True
            if not found:
                print("No dataset files found in directory")
            return False
        
        self.stats["row_count"] = len(self.posts)
        self.stats["file_info"] = {
            "path": str(self.data_path),
            "size_bytes": self.data_path.stat().st_size if self.data_path.is_file() else None,
            "format": self.data_path.suffix.lower() if self.data_path.is_file() else "directory"
        }
        return True
    
    def check_duplicates(self):
        seen_captions = Counter()
        seen_ids = Counter()
        for post in self.posts:
            caption = str(post.get('caption', '')).strip().lower()
            if caption:
                seen_captions[caption] += 1
            post_id = post.get('post_id') or post.get('id')
            if post_id:
                seen_ids[str(post_id)] += 1
        self.stats["duplicates"] = {
            "caption_duplicates": sum(1 for k, v in seen_captions.items() if v > 1),
            "caption_duplicate_rows": sum(v - 1 for v in seen_captions.values() if v > 1),
            "id_duplicates": sum(1 for k, v in seen_ids.items() if v > 1),
            "id_duplicate_rows": sum(v - 1 for v in seen_ids.values() if v > 1),
        }
    
    def check_missing_fields(self):
        required_fields = ['caption', 'platform', 'brand']
        optional_fields = ['likes', 'comments', 'shares', 'saves', 'views', 'posted_at', 'created_at']
        missing = defaultdict(int)
        for post in self.posts:
            for field in required_fields:
                if field not in post or not post.get(field) or str(post.get(field)).strip() == '':
                    missing[f"required.{field}"] += 1
            for field in optional_fields:
                if field not in post or post.get(field) in [None, '', 'null']:
                    missing[f"optional.{field}"] += 1
        self.stats["missing_fields"] = dict(missing)
    
    def analyze_distributions(self):
        platforms = Counter()
        brands = Counter()
        languages = Counter()
        content_types = Counter()
        for post in self.posts:
            if post.get('platform'):
                platforms[str(post['platform']).lower()] += 1
            if post.get('brand'):
                brands[str(post['brand'])] += 1
            if post.get('language') or post.get('lang'):
                lang = post.get('language') or post.get('lang')
                languages[str(lang).lower()] += 1
            if post.get('content_type') or post.get('type'):
                ct = post.get('content_type') or post.get('type')
                content_types[str(ct).lower()] += 1
        self.stats["platform_distribution"] = dict(platforms)
        self.stats["brand_distribution"] = dict(brands)
        self.stats["language_distribution"] = dict(languages)
        self.stats["content_type_distribution"] = dict(content_types)
    
    def check_metrics(self):
        metrics = ['likes', 'comments', 'shares', 'saves', 'views', 'impressions', 'engagement_rate']
        availability = {}
        for metric in metrics:
            count = 0
            non_null = 0
            for post in self.posts:
                if metric in post:
                    count += 1
                    if post[metric] not in [None, '', 'null']:
                        non_null += 1
            availability[metric] = {
                "present": count,
                "non_null": non_null,
                "coverage": round(non_null / len(self.posts) * 100, 2) if self.posts else 0
            }
        self.stats["metric_availability"] = availability
    
    def check_timestamps(self):
        timestamp_fields = ['posted_at', 'created_at', 'timestamp', 'date', 'published_at']
        coverage = {}
        for field in timestamp_fields:
            count = 0
            valid = 0
            for post in self.posts:
                if field in post and post[field] not in [None, '', 'null']:
                    count += 1
                    try:
                        ts = post[field]
                        if isinstance(ts, str) and len(ts) >= 10:
                            valid += 1
                        elif isinstance(ts, (int, float)):
                            valid += 1
                    except:
                        pass
            if count > 0:
                coverage[field] = {"present": count, "valid": valid, "coverage": round(valid / len(self.posts) * 100, 2)}
        self.stats["timestamp_coverage"] = coverage
    
    def generate_report(self, output_path: Optional[str] = None):
        report = {
            "audit_date": datetime.now().isoformat(),
            "summary": {"total_rows": self.stats["row_count"], "has_data": len(self.posts) > 0},
            "file_info": self.stats["file_info"],
            "data_quality": {"duplicates": self.stats["duplicates"], "missing_fields": self.stats["missing_fields"]},
            "distributions": {"platform": self.stats["platform_distribution"], "brand": self.stats["brand_distribution"],
                             "language": self.stats["language_distribution"], "content_type": self.stats["content_type_distribution"]},
            "engagement_metrics": self.stats["metric_availability"],
            "temporal_coverage": self.stats["timestamp_coverage"],
        }
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2)
            print(f"Report saved to: {output_path}")
        return report
    
    def print_report(self):
        print("=" * 60)
        print("DATASET AUDIT REPORT")
        print("=" * 60)
        print(f"Audit Date: {datetime.now().isoformat()}")
        print(f"Total Rows: {self.stats['row_count']}")
        print()
        print("FILE INFO:")
        for k, v in self.stats["file_info"].items():
            print(f"  {k}: {v}")
        print()
        print("DUPLICATES:")
        for k, v in self.stats["duplicates"].items():
            print(f"  {k}: {v}")
        print()
        print("PLATFORM DISTRIBUTION:")
        for k, v in self.stats["platform_distribution"].items():
            print(f"  {k}: {v}")
        print()
        print("BRAND DISTRIBUTION:")
        for k, v in self.stats["brand_distribution"].items():
            print(f"  {k}: {v}")
        print()
        print("METRIC AVAILABILITY:")
        for k, v in self.stats["metric_availability"].items():
            print(f"  {k}: {v}")
        print()
        print("=" * 60)


def main():
    if len(sys.argv) < 2:
        print("Usage: python profile_dataset.py <path_to_dataset>")
        sys.exit(1)
    profiler = DatasetProfiler(sys.argv[1])
    if not profiler.load_data():
        sys.exit(1)
    profiler.check_duplicates()
    profiler.check_missing_fields()
    profiler.analyze_distributions()
    profiler.check_metrics()
    profiler.check_timestamps()
    profiler.print_report()
    output_dir = Path("docs/ml")
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"dataset_profile_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    profiler.generate_report(str(report_path))


if __name__ == "__main__":
    main()
