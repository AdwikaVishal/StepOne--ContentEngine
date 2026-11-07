# Dataset Audit - Historical Content Dataset

**Audit Date:** 2026-10-27  
**Project:** Content & Design Engine  
**Auditor:** AI Assistant  
**Task:** Historical Content Dataset Audit and Local Captioning Baseline

## Executive Summary

This audit was conducted to find historical social media post datasets (10,000+ posts with engagement metrics) as specified in the task. After thorough search of the repository and filesystem, **no historical post dataset with 10,000+ posts and engagement metrics was found in the expected locations or anywhere in the repository**.

## Search Conducted

### Repository Search
Searched for patterns: `historical`, `dataset`, `posts`, `engagement`, `caption*history`
- Checked all files outside node_modules, .venv, .git, dist
- Searched for CSV, JSON, JSONL, Parquet files
- Grepped for "10,000", "10000" references

**Results:** No dataset files found. The word "dataset" appears only in:
- Comments in code (e.g., "asset folder/dataset" used interchangeably)
- Library files in node_modules/.venv
- TASKS.md mentions "new dataset via API/UI" in context of processing assets

### Filesystem Search
Searched in `/Users/admin/Downloads/` and common locations for post datasets
- Found no files matching `*posts*.csv`, `*posts*.json`, `*engagement*`, `*caption*history*`

## Current State Assessment

### Existing Caption Generation (Baseline)
The project has a sophisticated caption generation system in `content_engine/copy_generator.py`:

| Component | Status | Notes |
|-----------|--------|-------|
| `CopyGenerator` class | IMPLEMENTED | Main caption generator with Groq LLM + template fallback |
| `_GroqGenerator` | IMPLEMENTED | Uses Groq API (llama-3.3-70b-versatile) when GROQ_API_KEY set |
| Event type detection | IMPLEMENTED | Detects award_ceremony, keynote, networking, workshop from asset concepts |
| Platform-specific captions | IMPLEMENTED | LinkedIn, Instagram, Reel, Stories with different tones |
| Brand voice integration | IMPLEMENTED | StepOne brand voice with validation |
| Brand-aware captions | IMPLEMENTED | For GFF mode with separate methods |
| A/B variants | IMPLEMENTED | `generate_variants()` method |
| Caption regeneration API | IMPLEMENTED | `/api/captions/regenerate` endpoint uses Groq |

### Groq Integration Points
1. `content_engine/copy_generator.py` - Primary integration, auto-enables if GROQ_API_KEY set
2. `content_engine/brand/brand_matcher.py` - Uses Groq for brand matching fallback
3. `api/main.py` - `/api/captions/regenerate` endpoint
4. `config.py` - Groq settings (api_key, model, service_tier, temperature)

### Asset Metadata Schema
`content_engine/data_types.py` contains:
```python
@dataclass
class AssetMetadata:
    path: str
    asset_type: str
    quality_score: float
    aesthetic_score: float
    face_count: int
    face_confidences: List[float]
    relevance_scores: Dict[str, float]
    scene_concepts: List[str]
    final_score: float
    intended_use: str = "collage"
    selection_reason: str = ""
    highlight_clips: Optional[List[Dict]] = None
    duration: float = 0.0
```

## Data Quality Report

**Status:** CANNOT PERFORM - No historical dataset found.

If a dataset exists elsewhere on the system that wasn't found in searches, it would need to be located. The task states "10,000+ historical social media posts with engagement metrics" - this appears to be describing what needs to be collected/used, not what currently exists in the repo.

## Recommendations

1. **Locate or create dataset**: Search more broadly or ask user for dataset location/path
2. **Define schema first**: Create canonical schema even without data
3. **Build infrastructure**: Create data loading, preprocessing pipeline structure
4. **Plan for local models**: Prepare for when data is available

## Privacy Considerations
- No PII found in current codebase
- .env contains API keys (should not be committed)
- User data (uploads) goes to `uploads/` directory (gitignored likely)
