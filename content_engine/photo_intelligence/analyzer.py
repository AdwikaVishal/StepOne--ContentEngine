"""
Photo Intelligence Analyzer - Production implementation.
"""
import os
import uuid
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict

from PIL import Image
import imagehash
import numpy as np
import cv2

from .types import AssetAnalysis, RankedGroup, CarouselRecommendation, PhotoIntelligenceResult

try:
    from api.logger import get_logger
    _log = get_logger(__name__)
except Exception:
    import logging
    _log = logging.getLogger(__name__)


class PhotoIntelligenceAnalyzer:
    """
    Analyzes batches of images for curation and carousel sequencing.
    Reuses existing models when available, falls back to heuristics.
    Never pretends heuristics are ground-truth AI predictions.
    """
    
    def __init__(self, 
                 duplicate_threshold: int = 5,
                 similarity_threshold: int = 8,
                 use_existing_models: bool = True):
        self.duplicate_threshold = duplicate_threshold
        self.similarity_threshold = similarity_threshold
        self.use_existing_models = use_existing_models
        self._pipeline = None
        self._content_understander = None
    
    def _get_pipeline(self):
        if not self.use_existing_models:
            return None
        if self._pipeline is None:
            try:
                from content_engine.pipeline import ContentEngine
                self._pipeline = ContentEngine(event_description="Photo intelligence analysis")
            except Exception as e:
                _log.warning("pipeline_load_failed", error=str(e))
                self._pipeline = None
        return self._pipeline
    
    def _get_content_understander(self):
        if not self.use_existing_models:
            return None
        if self._content_understander is None:
            try:
                from content_engine.models.content_understanding import ContentUnderstander
                self._content_understander = ContentUnderstander()
            except Exception as e:
                _log.warning("content_understander_load_failed", error=str(e))
                self._content_understander = None
        return self._content_understander
    
    def _generate_asset_id(self, path: str, filename: str) -> str:
        """Generate stable asset ID based on path and filename."""
        key = f"{path}:{filename}".encode('utf-8')
        return hashlib.sha256(key).hexdigest()[:16]
    
    def _compute_sharpness(self, img: Image.Image) -> float:
        """Compute sharpness using Laplacian variance."""
        try:
            arr = np.array(img.convert('L'))
            variance = cv2.Laplacian(arr, cv2.CV_64F).var()
            return float(variance)
        except Exception:
            return 0.0
    
    def _compute_exposure(self, img: Image.Image) -> float:
        """Compute exposure score based on histogram."""
        try:
            arr = np.array(img.convert('RGB'))
            # Compute mean brightness
            gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
            mean_brightness = np.mean(gray) / 255.0
            # Penalize very dark or very overexposed
            if mean_brightness < 0.1 or mean_brightness > 0.9:
                return max(0.0, 1.0 - abs(mean_brightness - 0.5) * 2)
            return 1.0 - abs(mean_brightness - 0.5) * 0.5
        except Exception:
            return 0.5
    
    def _compute_resolution_score(self, width: int, height: int, file_size: int) -> float:
        """Compute resolution quality score."""
        pixels = width * height
        # Normalize to reasonable scale
        if pixels >= 1920 * 1080:
            res_score = 1.0
        elif pixels >= 1280 * 720:
            res_score = 0.8
        elif pixels >= 640 * 480:
            res_score = 0.6
        else:
            res_score = 0.4
        return res_score
    
    def _get_perceptual_hash(self, img: Image.Image) -> Optional[str]:
        """Compute perceptual hash for similarity detection."""
        try:
            h = imagehash.phash(img)
            return str(h)
        except Exception:
            return None
    
    def _extract_semantic_info(self, path: str) -> Tuple[str, List[str], bool]:
        """Try to extract semantic info using existing models."""
        description = ""
        concepts = []
        embeddings_available = False
        
        # Try content understander first
        try:
            cu = self._get_content_understander()
            if cu:
                result = cu.understand_image(path)
                concepts = result.get('scene_concepts', [])[:10]
                if concepts:
                    description = ", ".join(concepts[:5])
                # Check if CLIP is loaded
                if hasattr(cu, 'clip_model') and cu.clip_model is not None:
                    embeddings_available = True
        except Exception:
            pass
        
        # Try pipeline as fallback
        if not concepts:
            try:
                pipe = self._get_pipeline()
                if pipe:
                    meta = pipe._process_image(path)
                    if meta:
                        concepts = meta.scene_concepts[:10]
                        if concepts:
                            description = ", ".join(concepts[:5])
            except Exception:
                pass
        
        return description, concepts, embeddings_available
    
    def analyze_batch(self, 
                     assets: List[Dict[str, Any]],
                     brief: str = "") -> PhotoIntelligenceResult:
        """
        Analyze a batch of images.
        assets: List of dicts with 'path', 'original_filename', 'id' or similar
        """
        results: List[AssetAnalysis] = []
        warnings: List[str] = []
        hashes = []
        
        for asset in assets:
            path = asset.get('path') or asset.get('file_path')
            filename = asset.get('original_filename') or asset.get('filename') or Path(path).name if path else 'unknown'
            asset_id = asset.get('id') or asset.get('asset_id') or self._generate_asset_id(path or '', filename)
            asset_type = asset.get('asset_type') or 'image'
            
            analysis = AssetAnalysis(
                asset_id=asset_id,
                original_filename=filename,
                path=path or '',
                asset_type=asset_type,
            )
            
            # Check file existence and basic properties
            if not path or not os.path.exists(path):
                warnings.append(f"File not found: {filename}")
                analysis.reasons.append("File not found or inaccessible")
                analysis.confidence = 0.0
                results.append(analysis)
                continue
            
            try:
                file_size = os.path.getsize(path)
                analysis.file_size_bytes = file_size
                
                # Check file size (rough check - 200MB default)
                if file_size > 200 * 1024 * 1024:
                    warnings.append(f"File too large: {filename} (>200MB)")
                    analysis.reasons.append("File exceeds size limit (heuristic check)")
            except Exception as e:
                warnings.append(f"Error reading file: {filename} - {e}")
            
            # Process images only
            if asset_type == 'image':
                try:
                    img = Image.open(path)
                    analysis.width, analysis.height = img.size
                    
                    # Compute quality signals (heuristics)
                    analysis.sharpness = self._compute_sharpness(img)
                    analysis.exposure = self._compute_exposure(img)
                    analysis.resolution_score = self._compute_resolution_score(
                        analysis.width, analysis.height, analysis.file_size_bytes
                    )
                    
                    # Perceptual hash
                    analysis.phash = self._get_perceptual_hash(img)
                    if analysis.phash:
                        hashes.append((asset_id, imagehash.hex_to_hash(analysis.phash)))
                    
                    # Semantic info from existing models
                    desc, concepts, emb_avail = self._extract_semantic_info(path)
                    analysis.description = desc
                    analysis.scene_concepts = concepts
                    analysis.embeddings_available = emb_avail
                    
                    img.close()
                except Exception as e:
                    warnings.append(f"Cannot process image: {filename} - {e}")
                    analysis.reasons.append(f"Image processing error: {str(e)[:50]}")
                    analysis.confidence = 0.0
            else:
                analysis.reasons.append("Non-image asset - limited analysis")
            
            results.append(analysis)
        
        # Group duplicates and similar images
        groups = self._group_similar_images(results, hashes)
        
        # Compute rankings
        self._compute_rankings(results, groups)
        
        # Generate carousel recommendation
        carousel_rec = self._generate_carousel_recommendation(results, groups, brief)
        
        return PhotoIntelligenceResult(
            assets=results,
            groups=groups,
            carousel_recommendation=carousel_rec,
            warnings=warnings,
            metadata={
                "total_assets": len(results),
                "groups_found": len(groups),
                "models_used": {
                    "content_understander": self._content_understander is not None,
                    "pipeline": self._pipeline is not None,
                },
                "note": "Heuristic scores are not ground-truth AI predictions"
            }
        )
    
    def _group_similar_images(self, 
                              results: List[AssetAnalysis], 
                              hashes: List[Tuple[str, imagehash.ImageHash]]) -> List[RankedGroup]:
        """Group near-duplicates and visually similar shots."""
        groups = []
        assigned = set()
        group_id_counter = 0
        
        # Build hash map
        hash_map = {aid: h for aid, h in hashes}
        result_map = {r.asset_id: r for r in results}
        
        for i, (aid1, h1) in enumerate(hashes):
            if aid1 in assigned:
                continue
            
            group_members = []
            for j, (aid2, h2) in enumerate(hashes):
                if aid2 in assigned:
                    continue
                distance = h1 - h2
                if distance <= self.similarity_threshold:
                    if aid2 in result_map:
                        group_members.append(result_map[aid2])
                        assigned.add(aid2)
            
            if len(group_members) >= 2:
                # Find best candidate in group (will be refined in ranking)
                best = max(group_members, key=lambda x: x.sharpness + x.exposure + x.resolution_score)
                best.is_recommended = True
                
                for member in group_members:
                    member.similarity_group_id = f"group_{group_id_counter}"
                
                groups.append(RankedGroup(
                    group_id=f"group_{group_id_counter}",
                    assets=group_members,
                    recommended_asset_id=best.asset_id,
                    group_reason=f"Group of {len(group_members)} visually similar images (perceptual hash similarity)",
                    similarity_threshold=float(self.similarity_threshold)
                ))
                group_id_counter += 1
        
        return groups
    
    def _compute_rankings(self, results: List[AssetAnalysis], groups: List[RankedGroup]):
        """Generate explainable ranking with component scores."""
        group_recommendations = {}
        for group in groups:
            group_recommendations[group.recommended_asset_id] = True
        
        for analysis in results:
            if not analysis.path or not os.path.exists(analysis.path):
                analysis.overall_score = 0.0
                analysis.confidence = 0.0
                continue
            
            component_scores = {}
            reasons = []
            
            # Sharpness (normalized)
            sharp_norm = min(1.0, analysis.sharpness / 1000.0)  # rough normalization
            component_scores['sharpness'] = sharp_norm
            if sharp_norm > 0.7:
                reasons.append("Good sharpness/focus")
            elif sharp_norm < 0.3:
                reasons.append("Lower sharpness (may be less crisp)")
            
            # Exposure
            component_scores['exposure'] = analysis.exposure
            if analysis.exposure > 0.7:
                reasons.append("Well-exposed")
            elif analysis.exposure < 0.4:
                reasons.append("Exposure could be improved")
            
            # Resolution
            component_scores['resolution'] = analysis.resolution_score
            if analysis.resolution_score >= 0.8:
                reasons.append("High resolution suitable for most platforms")
            
            # Semantic relevance (if available)
            if analysis.scene_concepts:
                component_scores['semantic'] = min(1.0, len(analysis.scene_concepts) / 10.0)
                reasons.append(f"Contains {', '.join(analysis.scene_concepts[:3])}")
            else:
                component_scores['semantic'] = 0.3  # neutral when no semantic info
            
            # Group recommendation bonus
            if group_recommendations.get(analysis.asset_id):
                component_scores['group_recommendation'] = 0.9
                reasons.append("Recommended as best in similar group")
            else:
                component_scores['group_recommendation'] = 0.5
            
            # Compute overall score (weighted heuristic)
            overall = (
                component_scores['sharpness'] * 0.25 +
                component_scores['exposure'] * 0.15 +
                component_scores['resolution'] * 0.20 +
                component_scores['semantic'] * 0.25 +
                component_scores['group_recommendation'] * 0.15
            )
            analysis.component_scores = component_scores
            analysis.overall_score = overall
            
            # Confidence based on data availability (heuristic, not ground truth)
            confidence_factors = []
            if analysis.sharpness > 0:
                confidence_factors.append(0.2)
            if analysis.width > 0:
                confidence_factors.append(0.2)
            if analysis.phash:
                confidence_factors.append(0.2)
            if analysis.scene_concepts:
                confidence_factors.append(0.2)
            if self._content_understander or self._pipeline:
                confidence_factors.append(0.2)
            analysis.confidence = sum(confidence_factors)
            
            analysis.reasons = reasons if reasons else ["Scored using heuristic quality signals"]
    
    def _generate_carousel_recommendation(self,
                                         results: List[AssetAnalysis],
                                         groups: List[RankedGroup],
                                         brief: str = "") -> CarouselRecommendation:
        """Build coherent recommended sequence for carousel avoiding repetition."""
        # Get candidate pool (prefer recommended from groups, avoid rejected)
        candidates = []
        for r in results:
            if r.user_rejected:
                continue
            if not r.path or not os.path.exists(r.path):
                continue
            # Prefer group recommendations
            in_group = any(r.asset_id == g.recommended_asset_id for g in groups)
            candidates.append((r, in_group))
        
        # Sort by score, prefer group recommendations
        candidates.sort(key=lambda x: (x[1], x[0].overall_score), reverse=True)
        
        sequence = []
        used_concepts = set()
        
        # Build diverse sequence
        for analysis, is_group_rec in candidates:
            if len(sequence) >= 10:  # reasonable carousel length
                break
            # Avoid too much repetition of same concepts
            concepts = set(analysis.scene_concepts)
            overlap = len(concepts & used_concepts)
            if concepts and overlap > len(concepts) * 0.7 and len(sequence) > 0:
                continue  # skip for diversity
            
            sequence.append(analysis.asset_id)
            used_concepts.update(concepts)
            analysis.is_recommended = True
        
        # If sequence too short, add more
        if len(sequence) < 3:
            for analysis, _ in candidates:
                if analysis.asset_id not in sequence and len(sequence) < 5:
                    sequence.append(analysis.asset_id)
        
        # Compute diversity score
        all_concepts_in_seq = []
        for sid in sequence:
            for r in results:
                if r.asset_id == sid:
                    all_concepts_in_seq.extend(r.scene_concepts)
        unique_concepts = len(set(all_concepts_in_seq))
        diversity_score = min(1.0, unique_concepts / max(1, len(sequence) * 2))
        
        rationale = f"Recommended sequence of {len(sequence)} images prioritizing quality, diversity, and best representatives from similar groups. Scores are heuristic-based, not ground-truth predictions."
        if brief:
            rationale += f" Aligned with brief: {brief[:100]}"
        
        return CarouselRecommendation(
            sequence=sequence,
            rationale=rationale,
            diversity_score=diversity_score,
            coverage_score=min(1.0, len(sequence) / 10.0)
        )
    
    def update_user_selection(self,
                            result: PhotoIntelligenceResult,
                            asset_id: str,
                            action: str,
                            order: Optional[int] = None) -> PhotoIntelligenceResult:
        """Update user selection (accept/reject/reorder)."""
        for asset in result.assets:
            if asset.asset_id == asset_id:
                if action == 'accept':
                    asset.user_accepted = True
                    asset.user_rejected = False
                elif action == 'reject':
                    asset.user_rejected = True
                    asset.user_accepted = False
                elif action == 'reorder' and order is not None:
                    asset.user_order = order
                break
        return result
    
    def apply_user_preferences(self, result: PhotoIntelligenceResult) -> List[str]:
        """Get final ordered list based on user preferences."""
        # Start with carousel recommendation
        sequence = list(result.carousel_recommendation.sequence)
        
        # Remove rejected
        rejected = {a.asset_id for a in result.assets if a.user_rejected}
        sequence = [s for s in sequence if s not in rejected]
        
        # Add accepted not in sequence
        accepted = [a.asset_id for a in result.assets if a.user_accepted and a.asset_id not in sequence]
        sequence.extend(accepted)
        
        # Apply custom orders
        ordered = []
        unordered = []
        for sid in sequence:
            for a in result.assets:
                if a.asset_id == sid:
                    if a.user_order is not None:
                        ordered.append((a.user_order, sid))
                    else:
                        unordered.append(sid)
                    break
        ordered.sort(key=lambda x: x[0])
        final = [x[1] for x in ordered] + unordered
        
        return final
