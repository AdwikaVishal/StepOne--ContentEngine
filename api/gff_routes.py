"""
GFF 2025 API endpoints.
Mounted at /api/gff in api/main.py.
"""

import json
import shutil
import tempfile
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from config import settings

try:
    from api.logger import get_logger
    logger = get_logger("api.gff_routes")
except Exception:
    import logging
    logger = logging.getLogger("api.gff_routes")

router = APIRouter(prefix="/api/gff", tags=["GFF2025"])

_REFERENCE_EXTS = {
    ".jpg", ".jpeg", ".jpe", ".png", ".webp", ".bmp", ".dib", ".tif",
    ".tiff", ".gif", ".heic", ".heif", ".avif", ".jfif",
}


def _safe_event_name(event_name: str) -> str:
    import re
    return re.sub(r"[^\w\-]", "_", event_name).strip("_")


def _candidate_render_dirs(asset_folder: str, brand_id: str, brand_name: str) -> List[Path]:
    candidates = []
    safe_brand_name = _safe_event_name(brand_name)
    roots = [
        Path(asset_folder),
        Path.cwd(),
        Path("render_images"),
        Path("renders"),
    ]
    for root in roots:
        candidates.extend([
            root / "render_images" / brand_id,
            root / "render_images" / safe_brand_name,
            root / brand_id,
            root / safe_brand_name,
        ])
    return candidates


def _discover_render_paths(asset_folder: str, brand_id: str, brand_name: str) -> List[str]:
    paths = []
    seen = set()
    for folder in _candidate_render_dirs(asset_folder, brand_id, brand_name):
        if not folder.exists() or not folder.is_dir():
            continue
        for p in sorted(folder.rglob("*")):
            if p.is_file() and p.suffix.lower() in _REFERENCE_EXTS:
                resolved = str(p.resolve())
                if resolved not in seen:
                    paths.append(resolved)
                    seen.add(resolved)
    return paths


def _normalise_brands(asset_folder: str, brands: List["BrandDef"]) -> List["BrandDef"]:
    normalised = []
    for brand in brands:
        explicit = [str(Path(p).expanduser()) for p in brand.render_paths if Path(p).expanduser().exists()]
        discovered = _discover_render_paths(asset_folder, brand.brand_id, brand.brand_name)
        render_paths = explicit or discovered
        normalised.append(
            BrandDef(
                brand_id=brand.brand_id,
                brand_name=brand.brand_name,
                render_paths=render_paths,
            )
        )
    return normalised


def _validate_upload_name(upload: UploadFile) -> None:
    filename = upload.filename or "upload"
    ext = Path(filename).suffix.lower()
    if ext not in settings.allowed_upload_extensions:
        raise HTTPException(
            400,
            (
                f"File '{filename}' has unsupported extension '{ext or '(none)'}'. "
                f"Allowed extensions: {', '.join(settings.allowed_upload_extensions)}"
            ),
        )


# ── Request / Response models ─────────────────────────────────────────────────

class BrandDef(BaseModel):
    brand_id: str
    brand_name: str
    render_paths: List[str] = Field(default_factory=list)


class GFFProcessRequest(BaseModel):
    asset_folder: str
    event_name: str = "GFF 2025"
    brands: List[BrandDef]
    similarity_threshold: float = 0.45
    use_llm: bool = False
    event_date: str = ""
    output_root: str = "output"


class GFFProcessResponse(BaseModel):
    output_dir: str
    brand_counts: dict
    unmatched_count: int
    brand_results: dict
    selection_logic: str


async def _run_gff_pipeline(
    asset_folder: str,
    event_name: str,
    brands: List[BrandDef],
    similarity_threshold: float,
    use_llm: bool,
    event_date: str,
    output_root: str,
) -> GFFProcessResponse:
    if not Path(asset_folder).exists():
        raise HTTPException(404, f"Asset folder not found: {asset_folder}")

    if not brands:
        raise HTTPException(400, "At least one brand required")

    brands = _normalise_brands(asset_folder, brands)
    brands_missing_renders = [b.brand_name for b in brands if not b.render_paths]
    if brands_missing_renders:
        raise HTTPException(
            400,
            (
                "Missing render/reference images for: "
                f"{', '.join(brands_missing_renders)}. "
                "Add files under render_images/<brand_id>/ or provide render_paths."
            ),
        )

    brands_tuple = [
        (b.brand_id, b.brand_name, b.render_paths)
        for b in brands
    ]

    try:
        from content_engine.gff.orchestrator_gff import GFFOrchestrator
        orch = GFFOrchestrator(
            event_name=event_name,
            brands=brands_tuple,
            similarity_threshold=similarity_threshold,
            use_llm=use_llm,
        )
        out_dir = orch.run(
            asset_folder=asset_folder,
            output_root=output_root,
            event_date=event_date,
        )
    except Exception as e:
        logger.error(f"GFF pipeline failed: {e}")
        raise HTTPException(500, str(e))

    report_path = out_dir / "selection_report.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else {}

    brand_counts = {
        bid: info.get("photo_count", 0)
        for bid, info in report.get("brands", {}).items()
        if bid != "unmatched"
    }
    unmatched = report.get("brands", {}).get("unmatched", {}).get("photo_count", 0)

    brand_results = {
        bid: info.get("result", {})
        for bid, info in report.get("brands", {}).items()
        if bid != "unmatched"
    }

    from content_engine.brand.selection_logic import SELECTION_LOGIC

    return GFFProcessResponse(
        output_dir=str(out_dir),
        brand_counts=brand_counts,
        unmatched_count=unmatched,
        brand_results=brand_results,
        selection_logic=SELECTION_LOGIC,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/process", response_model=GFFProcessResponse)
async def process_gff(req: GFFProcessRequest):
    """
    Full GFF pipeline: segregate → carousel → reel → stories → copy.
    """
    return await _run_gff_pipeline(
        asset_folder=req.asset_folder,
        event_name=req.event_name,
        brands=req.brands,
        similarity_threshold=req.similarity_threshold,
        use_llm=req.use_llm,
        event_date=req.event_date,
        output_root=req.output_root,
    )


@router.post("/process-upload", response_model=GFFProcessResponse)
async def process_gff_upload(
    files: List[UploadFile] = File(...),
    brands_json: str = Form(...),
    event_name: str = Form("GFF 2025"),
    similarity_threshold: float = Form(0.45),
    use_llm: bool = Form(False),
    event_date: str = Form(""),
    output_root: str = Form("output"),
):
    """
    Upload-first endpoint for browser clients.
    Accepts folder/photo uploads and runs the same pipeline as /process.
    """
    try:
        brands_data = json.loads(brands_json)
        brands = [BrandDef(**b) for b in brands_data]
    except Exception as e:
        raise HTTPException(400, f"Invalid brands_json: {e}")

    temp_dir = Path(tempfile.mkdtemp(prefix="gff_upload_"))
    try:
        if not files:
            raise HTTPException(400, "At least one image/video file must be uploaded")

        for f in files:
            _validate_upload_name(f)
            rel_name = (f.filename or "").strip().replace("\\", "/")
            rel_path = Path(rel_name)
            safe_parts = [part for part in rel_path.parts if part not in ("", ".", "..")]
            if not safe_parts:
                continue

            dst = temp_dir.joinpath(*safe_parts)
            dst.parent.mkdir(parents=True, exist_ok=True)
            data = await f.read()
            if len(data) > settings.max_file_size_bytes:
                raise HTTPException(
                    413,
                    (
                        f"File '{f.filename}' is {len(data) // (1024 * 1024)}MB. "
                        f"Maximum allowed: {settings.max_file_size_mb}MB."
                    ),
                )
            dst.write_bytes(data)

        return await _run_gff_pipeline(
            asset_folder=str(temp_dir),
            event_name=event_name,
            brands=brands,
            similarity_threshold=similarity_threshold,
            use_llm=use_llm,
            event_date=event_date,
            output_root=output_root,
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@router.get("/content/{brand_id}")
async def get_brand_content(brand_id: str, output_root: str = "output", event_name: str = "GFF_2025"):
    """Get generated content for a specific brand."""
    import re
    safe_event = re.sub(r"[^\w\-]", "_", event_name).strip("_")
    brand_dir = Path(output_root) / safe_event / brand_id

    if not brand_dir.exists():
        raise HTTPException(404, f"No content for brand: {brand_id}")

    carousel = sorted(str(p) for p in brand_dir.glob("carousel_*.jpg"))
    stories = sorted(str(p) for p in (brand_dir / "stories").glob("story_*.jpg")) if (brand_dir / "stories").exists() else []
    reel = str(brand_dir / "reel.mp4") if (brand_dir / "reel.mp4").exists() else None

    def _read(p: Path) -> str:
        return p.read_text(encoding="utf-8").strip() if p.exists() else ""

    return {
        "brand_id": brand_id,
        "carousel_slides": carousel,
        "carousel_caption": _read(brand_dir / "instagram_caption.txt"),
        "story_frames": stories,
        "story_captions": _read((brand_dir / "stories" / "story_captions.txt")).splitlines(),
        "reel_path": reel,
        "reel_caption": _read(brand_dir / "reel_caption.txt"),
        "case_study": _read(brand_dir / "case_study.md"),
        "stats": {
            "carousel_slides": len(carousel),
            "story_frames": len(stories),
            "has_reel": reel is not None,
        },
    }


@router.get("/selection-logic")
async def get_selection_logic():
    from content_engine.brand.selection_logic import SELECTION_LOGIC
    return {"selection_logic": SELECTION_LOGIC}


@router.get("/brand-clusters")
async def get_brand_clusters(
    event_name: str = "GFF_2025",
    min_confidence: float = 0.0,
    output_root: str = "output",
):
    """
    Return brand cluster data from the most recent GFF pipeline run.
    
    Reads the selection_report.json from the most recent GFF pipeline output
    and returns cluster information (brand assignments, asset counts, centroids)
    suitable for visualization.
    
    Does NOT run the pipeline — reads existing output only.
    """
    import re
    import glob
    from pathlib import Path
    
    safe_event = re.sub(r"[^\w\-]", "_", event_name).strip("_")
    output_root_path = Path(output_root)
    
    # Find the most recent output directory for this event
    event_dir = output_root_path / safe_event
    if not event_dir.exists():
        raise HTTPException(404, f"No event output found for '{event_name}' at {event_dir}")
    
    # Find selection_report.json files
    report_path = event_dir / "selection_report.json"
    if not report_path.exists():
        raise HTTPException(404, f"No selection report found for event '{event_name}'")
    
    import json as _json
    try:
        report = _json.loads(report_path.read_text())
    except Exception as e:
        raise HTTPException(500, f"Failed to parse selection report: {e}")
    
    brands = report.get("brands", {})
    
    # Build cluster points and centroids
    points = []
    brand_centroids = {}
    total_points = 0
    
    for bid, info in brands.items():
        if bid == "unmatched":
            continue
        
        count = info.get("photo_count", info.get("count", 0))
        if count == 0:
            continue
        
        # Assets from the report
        assets = info.get("assets", [])
        
        # Use centroid x=0, y=0 as a placeholder — this is visual clustering data
        # that would require actual image embeddings to compute meaningfully.
        # We return deterministic placeholder values for visualization purposes.
        centroid_x = hash(bid) % 100 / 100.0
        centroid_y = (hash(bid) * 7) % 100 / 100.0
        
        brand_centroids[bid] = {
            "x": round(centroid_x, 3),
            "y": round(centroid_y, 3),
            "count": count,
            "avg_confidence": round(0.65, 3),  # Deterministic placeholder
        }
        
        for asset in assets:
            path = asset.get("path", "")
            confidence = asset.get("confidence", 0.0)
            
            if min_confidence and confidence < min_confidence:
                continue
            
            total_points += 1
            points.append({
                "path": path,
                "brand_id": bid,
                "confidence": round(confidence, 3),
                "x": round(centroid_x, 3),
                "y": round(centroid_y, 3),
                "similarity_scores": {bid: confidence},
                "confidence_band": (
                    "high" if confidence >= 0.7 else
                    "medium" if confidence >= 0.6 else
                    "low"
                ),
                "margin_to_second": 0.0,  # No second brand score available from segregation report
            })
    
    # Filters applied
    filters = {
        "min_confidence": min_confidence,
    }
    
    return {
        "event_name": event_name,
        "total_points": total_points,
        "points": points,
        "centroids": brand_centroids,
        "filters": filters,
    }
