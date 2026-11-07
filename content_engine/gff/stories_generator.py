"""
GFF Stories generator.
Reuses LayoutAssembler.create_instagram_stories — adds horizontal adaptation.
"""

import cv2
import numpy as np
from pathlib import Path
from typing import List
from PIL import Image, ImageFilter

try:
    from api.logger import get_logger
    _log = get_logger("content_engine.gff.stories")
except Exception:
    import logging
    _log = logging.getLogger("content_engine.gff.stories")

STORY_SIZE = (1080, 1920)   # 9:16


def _adapt_horizontal(path: str) -> Image.Image:
    """
    Landscape image → 9:16 story frame.
    Blurred background fill + centred original overlay.
    """
    orig = Image.open(path).convert("RGB")
    ow, oh = orig.size

    if ow <= oh:
        # Already portrait — just smart crop
        from content_engine.layout_assembler import LayoutAssembler
        return LayoutAssembler().smart_crop(path, *STORY_SIZE)

    # Landscape: blur-fill background
    bg = orig.resize(STORY_SIZE, Image.Resampling.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=28))

    # Overlay: scale to fit width
    scale = STORY_SIZE[0] / ow
    fg = orig.resize((STORY_SIZE[0], int(oh * scale)), Image.Resampling.LANCZOS)
    y = (STORY_SIZE[1] - fg.height) // 2
    bg.paste(fg, (0, y))
    return bg


def generate_stories(
    image_paths: List[str],
    captions: List[str],
    num_frames: int = 4,
) -> List[Image.Image]:
    """
    Generate 3–4 story frames with captions burned in.
    Handles horizontal assets via blur-fill adaptation.
    """
    from content_engine.layout_assembler import LayoutAssembler
    assembler = LayoutAssembler()

    num_frames = max(3, min(num_frames, 4, len(image_paths)))
    selected = image_paths[:num_frames]
    captions = (captions or []) + [""] * num_frames

    frames = []
    for i, path in enumerate(selected):
        try:
            frame = _adapt_horizontal(path)
            # Burn caption using existing assembler method
            cap = captions[i] if i < len(captions) else ""
            if cap:
                frame = assembler._burn_text(frame.convert("RGBA"), cap).convert("RGB")
            frames.append(frame)
        except Exception as e:
            _log.warning("story_frame_failed", path=Path(path).name, error=str(e))

    _log.info("stories_done", frames=len(frames))
    return frames
