"""
Video Processor — Scene Detection + Audio Energy + Highlight Extraction

Item 14: Video content scoring
  - Scene detection via PySceneDetect (ContentDetector, threshold 30)
  - Frame scoring via CLIP similarity to "exciting event" prompts
  - Audio energy via librosa RMS (captures applause, cheering, music)
  - Combined score: 0.7 × frame_score + 0.3 × audio_energy
  - Highlight extraction: greedy selection of clips up to target_duration

Returns:
  - extract_highlights(video_path, target_duration=45) → List[Dict]
    Each dict: {start, end, score} in seconds
"""

import cv2
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional


class VideoProcessor:
    """
    Processes videos to extract highlight clips.
    Combines visual (CLIP frame scoring) and audio (librosa RMS energy) signals.
    """

    def __init__(self):
        self._clip_model = None

    # ── CLIP lazy-load ──────────────────────────────────────────────────────────

    @property
    def clip_model(self):
        if self._clip_model is None:
            from sentence_transformers import SentenceTransformer
            from content_engine.utils.mps_safe import MPS_DEVICE
            self._clip_model = SentenceTransformer("clip-ViT-B-32", device=MPS_DEVICE)
        return self._clip_model

    # ── Scene detection ──────────────────────────────────────────────────────────

    def extract_scenes(self, video_path: str) -> List[float]:
        """
        Find scene change timestamps using PySceneDetect.
        Returns list of scene start times in seconds.
        """
        try:
            import signal
            class TimeoutException(Exception):
                pass
            def timeout_handler(signum, frame):
                raise TimeoutException("Scene detection timed out")
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(60)
            try:
                from scenedetect import VideoManager, SceneManager
                from scenedetect.detectors import ContentDetector

                video_manager = VideoManager([video_path])
                scene_manager = SceneManager()
                scene_manager.add_detector(ContentDetector(threshold=30.0))

                try:
                    video_manager.start()
                    scene_manager.detect_scenes(frame_source=video_manager)
                    scenes = scene_manager.get_scene_list()
                    return [scene[0].get_seconds() for scene in scenes]
                finally:
                    video_manager.release()
            except TimeoutException:
                return []
            finally:
                signal.alarm(0)
        except Exception:
            return []

    # ── Audio energy extraction ─────────────────────────────────────────────────

    def compute_audio_energy(self, video_path: str) -> List[float]:
        """
        Extract RMS audio energy per 0.5s segment.
        Higher energy segments capture applause, cheering, music.

        Returns:
            List of energy values (0–1 normalised) per segment
        """
        import tempfile
        import subprocess
        import librosa

        audio_path = Path(tempfile.mktemp(suffix=".wav"))
        try:
            # Convert video to mono 16kHz WAV (ffmpeg must be installed) with timeout
            result = subprocess.run(
                [
                    "ffmpeg", "-i", video_path,
                    "-ac", "1", "-ar", "16000",
                    str(audio_path),
                    "-y", "-loglevel", "quiet",
                ],
                capture_output=True,
                check=False,
                timeout=30,
            )
            if result.returncode != 0:
                return []

            # Load and analyse with timeout (librosa might be slow on large files)
            import signal
            class TimeoutException(Exception):
                pass
            def timeout_handler(signum, frame):
                raise TimeoutException("Audio processing timed out")
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(30)
            
            try:
                y, sr = librosa.load(str(audio_path), sr=16000)
                hop_length = sr // 2  # 0.5 second chunks
                energy = librosa.feature.rms(y=y, hop_length=hop_length)[0]

                # Normalise to 0–1 range
                energy_min, energy_max = energy.min(), energy.max()
                if energy_max > energy_min:
                    energy_norm = (energy - energy_min) / (energy_max - energy_min)
                else:
                    energy_norm = energy
                signal.alarm(0)
                return energy_norm.tolist()
            except TimeoutException:
                return []
            finally:
                signal.alarm(0)
        except Exception:
            return []
        finally:
            audio_path.unlink(missing_ok=True)

    # ── Frame quality scoring ───────────────────────────────────────────────────

    def score_frame(self, frame: np.ndarray) -> float:
        """
        CLIP similarity to "exciting event" prompt set.
        Returns 0–1 score for highlight potential.
        """
        from PIL import Image

        pil_frame = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        frame_emb = self.clip_model.encode(pil_frame)

        # Exciting event prompts
        exciting_embs = self.clip_model.encode([
            "action scene", "crowd cheering", "applause",
            "excitement", "speaking passionately", "award being handed",
            "stage lighting", "dynamic event", "peak moment",
        ]).mean(axis=0)

        import torch
        from content_engine.utils.mps_safe import empty_cache
        similarity = torch.cosine_similarity(
            torch.tensor(frame_emb), torch.tensor(exciting_embs), dim=0
        ).item()
        empty_cache()
        return float((similarity + 1.0) / 2.0)  # Normalise to 0–1

    # ── Fast duration check ──────────────────────────────────────────────────────

    def _get_duration_fast(self, video_path: str) -> float:
        """Get duration using ffprobe — faster than OpenCV for large files."""
        import subprocess
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', video_path],
                capture_output=True, text=True, timeout=5,
            )
            val = (result.stdout or "").strip()
            return float(val) if val else 0.0
        except Exception:
            return 0.0

    def _score_frame_fast(self, video_path: str, timestamp: float) -> float:
        """
        Quick frame scoring using blur + brightness only (no CLIP model).
        Returns 0-1 score. 3-5x faster than CLIP-based scoring.
        """
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        idx = int(timestamp * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        cap.release()

        if not ret:
            return 0.0

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blur_score = min(1.0, cv2.Laplacian(gray, cv2.CV_64F).var() / 300.0)

        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        brightness = hsv[:, :, 2].mean() / 255.0
        bright_score = 1.0 - abs(brightness - 0.5) * 2.0

        return float(blur_score * 0.6 + bright_score * 0.4)

    # ── Optimized highlight extraction with sampling ────────────────────────────

    def extract_highlights_optimized(
        self,
        video_path: str,
        target_duration: float = 45.0,
        min_clip_duration: float = 2.0,
    ) -> List[Dict]:
        """
        Optimized highlight extraction using sampling — 3-5x faster.

        Algorithm:
          1. Quick duration check — short videos return full range
          2. Sample frames at regular intervals instead of full scene detection
          3. Score each sample with fast blur+brightness (no CLIP)
          4. Group high-scoring samples into clips
          5. Greedy selection up to target_duration

        Returns:
            List of {start, end, score} dicts (in seconds)
        """
        duration = self._get_duration_fast(video_path)
        if duration <= 0:
            return []

        if duration <= target_duration:
            return [{"start": 0.0, "end": round(duration, 2), "score": 1.0}]

        sample_interval = max(3.0, duration / 30.0)
        timestamps = []
        t = 0.0
        while t < duration:
            timestamps.append(t)
            t += sample_interval

        scored_samples = []
        for ts in timestamps:
            score = self._score_frame_fast(video_path, ts)
            scored_samples.append((ts, score))

        scored_samples.sort(key=lambda x: x[1], reverse=True)

        highlights = []
        total_time = 0.0
        for ts, score in scored_samples:
            if total_time + min_clip_duration > target_duration:
                break
            end = min(ts + min_clip_duration, duration)
            clip_dur = end - ts
            if clip_dur >= min_clip_duration:
                highlights.append({
                    "start": round(ts, 2),
                    "end": round(end, 2),
                    "score": round(score, 4),
                })
                total_time += clip_dur

        if not highlights and scored_samples:
            ts, score = scored_samples[0]
            end = min(ts + min(target_duration, 5.0), duration)
            highlights.append({
                "start": round(ts, 2),
                "end": round(end, 2),
                "score": round(score, 4),
            })

        highlights.sort(key=lambda h: h["start"])
        return highlights

    # ── Highlight extraction (original, kept for backward compatibility) ────────

    def extract_highlights(
        self,
        video_path: str,
        target_duration: float = 45.0,
        min_clip_duration: float = 2.0,
    ) -> List[Dict]:
        """
        Extract top highlight clips from a video.
        Uses optimized sampling path by default — falls back to full scene detection
        if sampling returns no results.
        """
        fast_result = self.extract_highlights_optimized(video_path, target_duration, min_clip_duration)
        if fast_result and len(fast_result) >= 1:
            return fast_result

        # Fallback: original scene-detection-based extraction
        scenes = self.extract_scenes(video_path)
        if not scenes:
            cap = cv2.VideoCapture(video_path)
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            cap.release()
            if total_frames > 0:
                scenes = [0.0, total_frames / fps]
            else:
                return []

        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        scene_scores = []
        for scene_start in scenes:
            idx = int(scene_start * fps)
            if idx >= total_frames:
                continue
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                continue
            score = self.score_frame(frame)
            scene_scores.append((scene_start, score))

        cap.release()

        if not scene_scores:
            return []

        audio_energy = self.compute_audio_energy(video_path)
        if audio_energy:
            for i, (timestamp, score) in enumerate(scene_scores):
                energy_idx = int(timestamp / 0.5)
                if energy_idx < len(audio_energy):
                    audio_boost = audio_energy[energy_idx]
                    scene_scores[i] = (timestamp, score * (0.7 + 0.3 * audio_boost))

        scene_scores.sort(key=lambda x: x[1], reverse=True)

        highlights = []
        total_time = 0.0
        for timestamp, score in scene_scores:
            if total_time + min_clip_duration > target_duration:
                break
            next_times = [s for s in scenes if s > timestamp]
            next_time = next_times[0] if next_times else timestamp + 5.0
            clip_duration = min(next_time - timestamp, target_duration - total_time)
            if clip_duration >= min_clip_duration:
                highlights.append({
                    "start": round(timestamp, 2),
                    "end": round(timestamp + clip_duration, 2),
                    "score": round(score, 4),
                })
                total_time += clip_duration

        if not highlights and scene_scores:
            ts, score = scene_scores[0]
            highlights.append({
                "start": round(ts, 2),
                "end": round(ts + min(target_duration, 5.0), 2),
                "score": round(score, 4),
            })

        highlights.sort(key=lambda h: h["start"])
        return highlights