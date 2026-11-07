from __future__ import annotations

from typing import Any


def safe_jsonify(obj: Any) -> Any:
    """Recursively convert common non-JSON-friendly objects into JSON-safe types.

    Rules:
      - numpy.bool_ -> bool
      - numpy.integer -> int
      - numpy.floating -> float
      - numpy.ndarray -> list
      - objects with __dict__ -> dict(obj.__dict__)
      - fallback -> str(obj)

    This is intentionally defensive: it should never raise during serialization.
    """
    try:
        # Fast paths
        if obj is None:
            return None
        if isinstance(obj, (str, int, float, bool)):
            return obj

        # Numpy handling (optional import)
        try:
            import numpy as np  # type: ignore

            # bool_ is a scalar subclass of np.generic
            if isinstance(obj, np.bool_):
                return bool(obj)
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.floating):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return safe_jsonify(obj.tolist())
        except Exception:
            # numpy not installed or conversion failed
            pass

        # Common containers
        if isinstance(obj, dict):
            return {str(k): safe_jsonify(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)):
            return [safe_jsonify(v) for v in obj]

        # Torch tensors (optional) sometimes appear in ML metadata
        try:
            import torch  # type: ignore

            if isinstance(obj, torch.Tensor):
                # Avoid huge payloads; best-effort conversion
                if obj.numel() == 1:
                    return safe_jsonify(obj.item())
                return safe_jsonify(obj.detach().cpu().tolist())
        except Exception:
            pass

        # Pydantic models / dataclasses / generic objects
        if hasattr(obj, "__dict__"):
            return safe_jsonify(vars(obj))

        # Iterables as last resort
        try:
            return safe_jsonify(list(obj))
        except Exception:
            pass

        # Handle scalar-like objects with .item()
        if hasattr(obj, "item"):
            try:
                return safe_jsonify(obj.item())
            except Exception:
                pass

        return str(obj)
    except Exception:
        # Absolute last-resort
        try:
            return str(obj)
        except Exception:
            return None

