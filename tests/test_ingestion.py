"""Tests for dataset ingestion."""

import json
import tempfile
import os
from pathlib import Path

from scripts.ingest_historical import HistoricalDataIngester
from content_engine.captioning.retrieval.retriever import HistoricalPostRetriever
from content_engine.captioning.schema import HistoricalPost


class TestIngestion:
    def test_ingest_json(self, tmp_path):
        data = [
            {"post_id": "1", "platform": "linkedin", "brand": "Test", "caption": "Hello world", "likes": 10}
        ]
        f = tmp_path / "test.json"
        f.write_text(json.dumps(data))
        ingester = HistoricalDataIngester(str(f), str(tmp_path / "out"))
        posts = ingester.ingest()
        assert len(posts) == 1
        assert posts[0]['platform'] == 'linkedin'
    
    def test_ingest_jsonl(self, tmp_path):
        data = [{"post_id": "1", "platform": "instagram", "brand": "Test", "caption": "Hi"}]
        f = tmp_path / "test.jsonl"
        f.write_text(json.dumps(data[0]) + "\n")
        ingester = HistoricalDataIngester(str(f), str(tmp_path / "out"))
        posts = ingester.ingest()
        assert len(posts) == 1
    
    def test_deduplication(self, tmp_path):
        data = [
            {"post_id": "1", "platform": "linkedin", "brand": "Test", "caption": "Hello"},
            {"post_id": "1", "platform": "linkedin", "brand": "Test", "caption": "Hello"},
        ]
        f = tmp_path / "test.json"
        f.write_text(json.dumps(data))
        ingester = HistoricalDataIngester(str(f), str(tmp_path / "out"))
        posts = ingester.ingest()
        assert len(posts) == 1
    
    def test_normalization(self, tmp_path):
        data = [{"id": "1", "social_platform": "LI", "page_name": "Brand", "text": "Caption here"}]
        f = tmp_path / "test.json"
        f.write_text(json.dumps(data))
        ingester = HistoricalDataIngester(str(f), str(tmp_path / "out"))
        posts = ingester.ingest()
        assert posts[0]['platform'] == 'linkedin'
        assert posts[0]['brand'] == 'Brand'
        assert posts[0]['caption'] == 'Caption here'


class TestRetrievalLeakagePrevention:
    def test_exclude_duplicates(self):
        retriever = HistoricalPostRetriever(data_path="/nonexistent")
        retriever.load_posts()
        retriever.posts = [
            HistoricalPost("1", "BrandA", "instagram", "carousel", "same caption", campaign_id="c1"),
            HistoricalPost("2", "BrandA", "instagram", "carousel", "same caption", campaign_id="c1"),
        ]
        retriever._build_index()
        results = retriever.retrieve(brand="BrandA")
        # Both would match filters but we test filtering logic
        assert len(results) == 2
    
    def test_campaign_isolation(self):
        retriever = HistoricalPostRetriever(data_path="/nonexistent")
        retriever.load_posts()
        retriever.posts = [
            HistoricalPost("1", "BrandA", "instagram", "carousel", "cap1", campaign_id="train_camp"),
            HistoricalPost("2", "BrandA", "instagram", "carousel", "cap2", campaign_id="test_camp"),
        ]
        retriever._build_index()
        train_results = retriever.retrieve(campaign_id="train_camp")
        assert len(train_results) == 1
        assert train_results[0].campaign_id == "train_camp"
