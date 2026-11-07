"""
GFF Reel generator.
Reuses LayoutAssembler.create_reel — adds 30–60s duration clamping.
"""

import subprocess
from pathlib import Path
from typing import List, Dict, Tuple

try:
    from api.logger import get_logger
    _log = get_logger("content_engine.gff.reel")
except Exception:
    import logging
    _log = logging.getLogger("content_engine.gff.reel")

MIN_DURATION = 30
MAX_DURATION = 60


def _video_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=10,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _clamp_clips(clips: List[Dict], target: float) -> List[Dict]:
    """Scale clip durations so total fits within MIN–MAX range."""
    total = sum(c["end"] - c["start"] for c in clips)
    if total == 0:
        return clips

    if total > MAX_DURATION:
        scale = MAX_DURATION / total
        clamped = []
        for c in clips:
            dur = (c["end"] - c["start"]) * scale
            clamped.append({"start": c["start"], "end": c["start"] + dur, "score": c["score"]})
        return clamped

    if total < MIN_DURATION:
        # Extend last clip
        deficit = MIN_DURATION - total
        clips = list(clips)
        clips[-1] = {**clips[-1], "end": clips[-1]["end"] + deficit}

    return clips


def generate_reel(
    video_path: str,
    highlight_clips: List[Dict],
    output_path: str,
) -> Tuple[bool, float]:
    """
    Generate a 30–60s reel from highlight clips.
    Returns (success, actual_duration).
    """
    from content_engine.layout_assembler import LayoutAssembler
    assembler = LayoutAssembler()

    if not highlight_clips:
        _log.warning("reel_no_clips")
        return False, 0.0

    clamped = _clamp_clips(highlight_clips, target=45.0)
    ok = assembler.create_reel(video_path, clamped, output_path, transition="crossfade")

    duration = _video_duration(output_path) if ok else 0.0
    _log.info("reel_done", ok=ok, duration=round(duration, 1))
    return ok, duration
