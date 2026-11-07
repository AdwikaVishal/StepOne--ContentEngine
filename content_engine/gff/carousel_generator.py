"""
GFF Carousel generator.
Reuses LayoutAssembler.smart_crop — no duplicate logic.
Adds sharpness re-ranking and enforces 4–6 slides.
"""

import cv2
import numpy as np
from pathlib import Path
from typing import List, Tuple
from PIL import Image

try:
    from api.logger import get_logger
    _log = get_logger("content_engine.gff.carousel")
except Exception:
    import logging
    _log = logging.getLogger("content_engine.gff.carousel")

CAROUSEL_SIZE = (1080, 1350)   # 4:5


def _sharpness(path: str) -> float:
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        return 0.0
    return float(cv2.Laplacian(img, cv2.CV_64F).var())


def generate_carousel(image_paths: List[str]) -> Tuple[List[Image.Image], List[str]]:
    """
    Generate 4–6 carousel slides from image_paths.
    Re-ranks by sharpness, enforces minimum 4 slides.
    Returns (slides, ordered_paths).
    """
    from content_engine.layout_assembler import LayoutAssembler
    assembler = LayoutAssembler()

    if not image_paths:
        return [], []

    # Rank by sharpness descending
    ranked = sorted(image_paths, key=_sharpness, reverse=True)

    # Enforce min 4 by repeating best image
    while len(ranked) < 4:
        ranked.append(ranked[0])

    ranked = ranked[:6]

    slides = []
    for path in ranked:
        try:
            slide = assembler.smart_crop(path, *CAROUSEL_SIZE)
            slides.append(slide)
        except Exception as e:
            _log.warning("carousel_slide_failed", path=Path(path).name, error=str(e))

    _log.info("carousel_done", slides=len(slides))
    return slides, ranked
