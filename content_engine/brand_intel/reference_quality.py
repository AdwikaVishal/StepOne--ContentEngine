"""
Reference library quality and diversity analysis (Brand Intelligence, Phase 1).

Pure local computation over uploaded reference photographs and logos — no
model inference, no network. Used to warn users when a brand's reference
library is too small, too repetitive or too narrow to support reliable
image-based brand identification.

Metrics are heuristics and are reported as such:
- diversity: mean pairwise 64-bit difference-hash Hamming distance
- near-duplicates: hash distance <= NEAR_DUPLICATE_MAX_DISTANCE
- sharpness: variance of a 5-point Laplacian (low = possibly blurry)

No accuracy claims are made anywhere — the output is evidence for a human.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from api.logger import get_logger
    logger = get_logger("content_engine.brand_intel.reference_quality")
except Exception:
    import logging
    logger = logging.getLogger("content_engine.brand_intel.reference_quality")

# Thresholds (documented, adjustable in code review — not model outputs).
MIN_REFERENCE_PHOTOS = 3      # below → "few references" warning
NEAR_DUPLICATE_MAX_DISTANCE = 6   # of 64 hash bits
NEAR_DUPLICATE_RATIO = 0.3    # ≥30% of pairs near-duplicate → "many near-duplicates"
LOW_DIVERSITY_THRESHOLD = 0.15  # mean pairwise distance below → "low diversity"
MIN_EDGE_SIZE = 256           # below → "low resolution"
LOW_SHARPNESS_THRESHOLD = 20.0  # Laplacian variance below → "possibly blurry"

# Readiness deductions per warning code (documented, additive, clamped 0-100).
WARNING_PENALTIES = {
    "no_references": 40,
    "few_references": 20,
    "no_logo": 20,
    "low_diversity": 15,
    "many_near_duplicates": 10,
    "low_resolution": 10,
    "narrow_category_coverage": 5,
}


def _dhash(path: Path) -> Optional[int]:
    """64-bit difference hash of a raster image; None when unreadable."""
    try:
        from PIL import Image
        with Image.open(path) as img:
            gray = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
            pixels = gray.tobytes()  # mode "L" → 72 raw bytes
    except Exception:
        return None
    bits = 0
    for row in range(8):
        for col in range(8):
            left = pixels[row * 9 + col]
            right = pixels[row * 9 + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def _hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _sharpness(path: Path) -> Optional[float]:
    """Variance of a 5-point Laplacian on the grayscale image (0-255 scale)."""
    try:
        import numpy as np
        from PIL import Image
        with Image.open(path) as img:
            gray = np.asarray(img.convert("L"), dtype=np.float64)
    except Exception:
        return None
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return None
    lap = (
        4 * gray[1:-1, 1:-1]
        - gray[:-2, 1:-1] - gray[2:, 1:-1]
        - gray[1:-1, :-2] - gray[1:-1, 2:]
    )
    return float(lap.var())


def analyze_reference_quality(
    profile: Dict[str, Any],
    assets: List[Dict[str, Any]],
    asset_dir: Path,
) -> Dict[str, Any]:
    """Build the reference-quality report for one brand.

    Args:
        profile: stored brand profile (45+ field flat schema).
        assets:  merged manifest entries from StudioStorage.list_brand_assets.
        asset_dir: the profile's asset directory (for resolving stored_name).

    Returns:
        {
          counts: {logos, references, total},
          categories: {category: count},          # references only
          diversity: {score, pairs, near_duplicate_pairs} | None,
          assets: [{asset_id, kind, category, width, height, sharpness,
                    near_duplicate_of, status}],
          warnings: [{code, severity, message}],
          readiness: int (0-100),
        }
    """
    logos = [a for a in assets if a.get("kind") == "logo"]
    references = [a for a in assets if a.get("kind") == "reference"]

    categories: Dict[str, int] = {}
    for ref in references:
        cat = ref.get("category") or "other"
        categories[cat] = categories.get(cat, 0) + 1

    # ── per-asset metrics ──────────────────────────────────────────────────
    asset_rows: List[Dict[str, Any]] = []
    hashes: Dict[str, int] = {}
    for entry in assets:
        file_path = asset_dir / entry.get("stored_name", "")
        width = entry.get("width")
        height = entry.get("height")
        sharpness = _sharpness(file_path) if file_path.exists() else None
        row = {
            "asset_id": entry.get("asset_id"),
            "kind": entry.get("kind"),
            "category": entry.get("category") or ("logo" if entry.get("kind") == "logo" else "other"),
            "width": width,
            "height": height,
            "sharpness": round(sharpness, 1) if sharpness is not None else None,
            "near_duplicate_of": None,
            "status": "ok",
        }
        if entry.get("kind") == "reference" and file_path.exists():
            h = _dhash(file_path)
            if h is not None:
                hashes[str(entry.get("asset_id"))] = h
        asset_rows.append(row)

    # ── diversity across reference photographs ─────────────────────────────
    diversity: Optional[Dict[str, Any]] = None
    ref_ids = [r["asset_id"] for r in asset_rows
               if r["kind"] == "reference" and r["asset_id"] in hashes]
    if len(ref_ids) >= 2:
        distances: List[int] = []
        near_dup_pairs: List[List[str]] = []
        for i in range(len(ref_ids)):
            for j in range(i + 1, len(ref_ids)):
                d = _hamming(hashes[ref_ids[i]], hashes[ref_ids[j]])
                distances.append(d)
                if d <= NEAR_DUPLICATE_MAX_DISTANCE:
                    near_dup_pairs.append([ref_ids[i], ref_ids[j]])
        mean_distance = (sum(distances) / len(distances)) / 64.0
        diversity = {
            "score": round(mean_distance, 3),
            "pairs": len(distances),
            "near_duplicate_pairs": near_dup_pairs,
        }
        # Annotate rows with their nearest near-duplicate partner.
        flagged = {pair[0]: pair[1] for pair in near_dup_pairs}
        for row in asset_rows:
            if row["asset_id"] in flagged:
                row["near_duplicate_of"] = flagged[row["asset_id"]]
                row["status"] = "near-duplicate"

    # ── warnings ───────────────────────────────────────────────────────────
    warnings: List[Dict[str, Any]] = []

    def warn(code: str, severity: str, message: str) -> None:
        warnings.append({"code": code, "severity": severity, "message": message})

    if not references:
        warn("no_references", "error",
             "No reference photographs yet. Upload photos showing products, "
             "packaging, signage or other brand appearances — logos alone are "
             "not enough to identify a brand in real photographs.")
    elif len(references) < MIN_REFERENCE_PHOTOS:
        warn("few_references", "warning",
             f"Only {len(references)} reference photograph"
             f"{'s' if len(references) != 1 else ''} — "
             f"{MIN_REFERENCE_PHOTOS} or more diverse photos are recommended.")
    if not logos:
        warn("no_logo", "warning",
             "No logo uploaded. Text-free brand marks cannot be matched "
             "without at least one logo reference.")

    if diversity is not None:
        if diversity["score"] < LOW_DIVERSITY_THRESHOLD:
            warn("low_diversity", "warning",
                 f"Reference photos look very similar to each other "
                 f"(diversity {diversity['score']:.2f} of 1.0). Add photos from "
                 f"different contexts — packaging, signage, storefronts.")
        pair_count = diversity["pairs"] or 1
        if len(diversity["near_duplicate_pairs"]) / pair_count >= NEAR_DUPLICATE_RATIO:
            warn("many_near_duplicates", "warning",
                 f"{len(diversity['near_duplicate_pairs'])} near-duplicate pairs "
                 f"found — many of your reference photos appear to be the same image.")

    low_res = [r for r in asset_rows
               if (r["width"] or 0) < MIN_EDGE_SIZE or (r["height"] or 0) < MIN_EDGE_SIZE]
    if low_res:
        warn("low_resolution", "info",
             f"{len(low_res)} reference image"
             f"{'s are' if len(low_res) != 1 else ' is'} smaller than "
             f"{MIN_EDGE_SIZE}px on an edge — small images carry little matching detail.")

    ref_categories = {r["category"] for r in asset_rows if r["kind"] == "reference"}
    if len(references) >= MIN_REFERENCE_PHOTOS and len(ref_categories) <= 1:
        warn("narrow_category_coverage", "info",
             "All reference photos share one category. Categorizing photos "
             "across packaging, signage, storefronts and placements improves matching.")

    possible_blurry = [r for r in asset_rows
                       if r["sharpness"] is not None
                       and r["sharpness"] < LOW_SHARPNESS_THRESHOLD]
    if possible_blurry:
        warn("possibly_blurry", "info",
             f"{len(possible_blurry)} image"
             f"{'s may be blurry' if len(possible_blurry) != 1 else ' may be blurry'} "
             f"(low sharpness) — consider replacing them with sharper photos.")

    readiness = 100
    for warning in warnings:
        readiness -= WARNING_PENALTIES.get(warning["code"], 0)
    readiness = max(0, min(100, readiness))

    return {
        "counts": {
            "logos": len(logos),
            "references": len(references),
            "total": len(assets),
        },
        "categories": categories,
        "diversity": diversity,
        "assets": asset_rows,
        "warnings": warnings,
        "readiness": readiness,
    }


def get_reference_quality(storage: Any, profile_id: str) -> Optional[Dict[str, Any]]:
    """Convenience wrapper: load profile + assets and analyze."""
    profile = storage.get_brand_profile(profile_id)
    if profile is None:
        return None
    try:
        assets = storage.list_brand_assets(profile_id)
        asset_dir = storage._brand_asset_dir(profile_id)
    except ValueError:
        return None
    report = analyze_reference_quality(profile, assets, asset_dir)
    report["profile_id"] = profile_id
    report["brand_name"] = profile.get("name", "")
    return report
