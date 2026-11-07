"""
Image intelligence for multi-image analysis and selection.
"""
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image
import imagehash


class StudioIntelligence:
    def __init__(self):
        self._pipeline = None
        self._blip = None
    
    def _get_pipeline(self):
        if self._pipeline is None:
            try:
                from content_engine.pipeline import ContentEngine
                self._pipeline = ContentEngine(event_description="Social media content")
            except Exception:
                self._pipeline = None
        return self._pipeline

    def _get_blip(self):
        if self._blip is None:
            from content_engine.photo_intelligence.blip_captioner import get_blip_captioner
            self._blip = get_blip_captioner()
        return self._blip
    
    def analyze_assets(self, assets: List[Dict[str, Any]], brief: str = "") -> Dict[str, Any]:
        results = []
        hashes = []
        for asset in assets:
            path = asset.get("path")
            info = {
                "asset_id": asset["id"],
                "filename": asset.get("original_filename"),
                "url": asset.get("url"),
                "path": path,
                "quality": {},
                "description": "",
                "caption": None,
                "caption_status": "not_requested",
                "caption_model": None,
                "caption_error": None,
                "subjects": [],
                "sharpness": 0.0,
                "duplicates": [],
                "relevance": 0.0,
                "suitability": {"linkedin": 0.5, "instagram": 0.5},
                "selected": False,
                "selection_reason": "",
            }
            # Compute perceptual hash for deduplication
            if path and os.path.exists(path) and asset.get("asset_type") == "image":
                try:
                    img = Image.open(path)
                    h = imagehash.phash(img)
                    info["phash"] = str(h)
                    hashes.append((asset["id"], h))
                    # Basic sharpness via PIL/Laplacian approximation
                    try:
                        import cv2
                        import numpy as np
                        arr = np.array(img.convert('L'))
                        info["sharpness"] = float(cv2.Laplacian(arr, cv2.CV_64F).var())
                    except Exception:
                        pass
                except Exception:
                    pass
            # Try to use existing pipeline if available
            try:
                pipe = self._get_pipeline()
                if pipe and path and os.path.exists(path) and asset.get("asset_type") == "image":
                    meta = pipe._process_image(path)
                    if meta:
                        info["quality"] = {
                            "quality_score": meta.quality_score,
                            "aesthetic_score": meta.aesthetic_score,
                            "final_score": meta.final_score,
                        }
                        info["subjects"] = meta.scene_concepts[:10]
                        info["description"] = ", ".join(meta.scene_concepts[:5]) if meta.scene_concepts else ""
                        info["relevance"] = float(meta.final_score)
                        info["suitability"]["linkedin"] = min(1.0, 0.5 + meta.quality_score * 0.3 + meta.aesthetic_score * 0.2)
                        info["suitability"]["instagram"] = min(1.0, 0.5 + meta.aesthetic_score * 0.3 + (meta.face_count * 0.1))
            except Exception:
                pass
            results.append(info)

        # BLIP is loaded lazily here, on explicit asset analysis, and processes
        # one image at a time. Results are associated by asset ID, never index.
        image_assets = [a for a in assets if a.get("asset_type") == "image" and (a.get("path") or a.get("file_path"))]
        try:
            captions = self._get_blip().caption_many([
                {"asset_id": a.get("id") or a.get("asset_id"), "path": a.get("path") or a.get("file_path")}
                for a in image_assets
            ])
            caption_by_id = {c["asset_id"]: c for c in captions}
            for result in results:
                caption = caption_by_id.get(result["asset_id"])
                if caption:
                    result.update(caption=caption["caption"], caption_status=caption["caption_status"],
                                  caption_model=caption["caption_model"], caption_error=caption["caption_error"])
                    if caption["caption_error"]:
                        result["captioning_error"] = caption["caption_error"]
                    result["caption_relevance"] = self._caption_relevance(caption.get("caption") or "", brief)
        except Exception as exc:
            for result in results:
                if result["caption_status"] == "not_requested":
                    result.update(caption_status="error", caption_model=getattr(self._blip, "model_identifier", None), caption_error=str(exc))
        
        # Detect duplicates
        for i, (id1, h1) in enumerate(hashes):
            dups = []
            for j, (id2, h2) in enumerate(hashes):
                if i != j and h1 - h2 < 5:  # Hamming distance threshold
                    dups.append(id2)
            for r in results:
                if r["asset_id"] == id1:
                    r["duplicates"] = dups
                    break
        
        return {
            "analyzed": results,
            "total": len(results),
            "duplicates_found": sum(1 for r in results if r.get("duplicates")),
        }
    
    def select_best_images(self, analyzed: List[Dict[str, Any]], max_count: int = 10) -> Dict[str, Any]:
        def score_item(x):
            base = x.get("relevance") or 0.0
            q = x.get("quality", {}).get("final_score") or 0.0
            sharp = min(1.0, (x.get("sharpness") or 0.0) / 1000.0)
            caption_match = x.get("caption_relevance") or 0.0
            return base * 0.30 + q * 0.35 + sharp * 0.15 + caption_match * 0.20
        
        # Rank first, then retain the best item from each near-duplicate set.
        ranked = sorted(analyzed, key=score_item, reverse=True)
        candidates = []
        seen_ids = set()
        for item in ranked:
            aid = item["asset_id"]
            if aid in seen_ids:
                continue
            candidates.append(item)
            seen_ids.add(aid)
            seen_ids.update(item.get("duplicates") or [])

        selected = candidates[:max_count]
        for i, s in enumerate(selected):
            s["selected"] = True
            s["rank"] = i + 1
            parts = [f"quality {s.get('quality', {}).get('final_score', 0):.2f}", f"visual sharpness {min(1.0, (s.get('sharpness') or 0)/1000):.2f}"]
            if s.get("caption"):
                parts.append(f"uncertain caption relevance {s.get('caption_relevance', 0):.2f}")
            s["selection_reason"] = f"Ranked #{i+1} using " + ", ".join(parts)
            s.pop("_brief", None)
        # Stable sequencing keeps selected quality while preferring distinct
        # caption vocabulary between adjacent story frames.
        selected = self._sequence_for_visual_diversity(selected)
        return {
            "selected": selected,
            "all_analyzed": analyzed,
            "total_candidates": len(candidates),
            "selected_count": len(selected),
        }

    @staticmethod
    def _caption_relevance(caption: str, brief: str) -> float:
        if not caption or not brief:
            return 0.0
        stop = {"the", "and", "with", "from", "that", "this", "into", "for", "are", "was", "about"}
        words = {w.casefold().strip(".,!?;:") for w in brief.split()} - stop
        terms = {w.casefold().strip(".,!?;:") for w in caption.split()} - stop
        return len(words & terms) / max(1, len(words))

    @staticmethod
    def _sequence_for_visual_diversity(items):
        if len(items) < 3:
            return items
        remaining, ordered = list(items), [items[0]]
        while remaining:
            previous = set((ordered[-1].get("caption") or "").lower().split())
            next_item = max(remaining, key=lambda item: (
                len(set((item.get("caption") or "").lower().split()) - previous),
                item.get("quality", {}).get("final_score") or 0,
            ))
            remaining.remove(next_item)
            ordered.append(next_item)
        for index, item in enumerate(ordered):
            item["story_sequence"] = index + 1
            item["sequence_reason"] = "Ordered to reduce overlap between adjacent image-caption vocabulary, with quality as tie-breaker. Captions are uncertain descriptions."
        return ordered
