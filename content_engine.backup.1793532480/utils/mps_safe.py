"""
MPS (Metal Performance Shaders) memory management for Apple Silicon.
Prevents the MTLCompilerConnectionQueue SIGABRT crash caused by
GPU memory accumulation across inferences.
"""

import gc
import torch

# True only on Apple Silicon with MPS support
MPS_AVAILABLE: bool = torch.backends.mps.is_available()

# Best device for models that are MPS-stable (YOLO, CLIP, SentenceTransformer)
MPS_DEVICE: str = "mps" if MPS_AVAILABLE else "cpu"

# Florence-2 crashes on MPS with float16 — always CPU
FLORENCE_DEVICE: str = "cpu"
FLORENCE_DTYPE = torch.float32


def empty_cache() -> None:
    """Clear MPS GPU cache + Python GC. Call after every inference."""
    if MPS_AVAILABLE:
        torch.mps.empty_cache()
    gc.collect()


def set_memory_fraction(fraction: float = 0.0) -> None:
    """No-op — PYTORCH_MPS_HIGH_WATERMARK_RATIO causes invalid watermark errors."""
    pass
