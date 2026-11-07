# CONTENT ENGINE AUDIT

## Architecture Overview

The Content Engine follows a pipeline architecture:
```
Assets (images/videos) → ContentEngine (ML Selection) → ContentOrchestrator → LayoutAssembler + CopyGenerator → Outputs
```

## Content Generation Workflow Trace

### Trace: User uploads via UI → Final output
1. **UI** (`StudioPage.tsx`): User uploads files via dropzone, configures event in wizard, clicks generate
2. **API Call**: `generateAsync()` or `generateFast()` (brand mode) → POST to `/api/generate/async` or `/api/generate/fast`
3. **API** (`api/main.py:711-903`): Validates files, saves to uploads/, starts async job
4. **Job Backend**: Celery task (`api/tasks.py`) or in-process worker processes job
5. **Orchestrator** (`content_engine/orchestrator.py`): 
   - Discovers assets recursively
   - Creates output directory `output/{safe_event_name}/`
   - Calls `ContentEngine.select_assets()` 
   - Routes selections by `intended_use` (collage/reel/story/case_study)
   - Calls LayoutAssembler for each output type
   - Calls CopyGenerator for captions
   - Calls `generate_case_study()` for case study
   - Writes all files to output dir
6. **Job Complete**: Frontend polls status, fetches result via `getJobResult()`, displays in ResultsPage

## ML Selection Pipeline

**ContentEngine** (`content_engine/pipeline.py`) coordinates:
- **QualityAssessor**: 
  - Blur detection via Laplacian variance
  - Brightness via HSV
  - Aesthetic scoring via CLIP (comparing to quality prompt sets)
  - Adaptive thresholds calibrated from first 20 images
- **FaceDetector** (YOLOv11):
  - Face detection with confidence threshold (default 0.35)
  - Face size weighting - faces < 2% score 0.4x, > 10% score 1.0x
- **ContentUnderstander** (Florence-2 + CLIP):
  - Scene concept detection
  - Event-type concept weights from `config/concept_weights.json`
  - Relevance scoring
- **VideoProcessor**:
  - Scene detection with PySceneDetect
  - Audio energy analysis with librosa
  - Highlight extraction

**Scoring weights:** 30% technical quality + 20% aesthetic + 30% faces + 20% concepts (as per README)

## Content Capabilities

| Capability | Status | Implementation | Notes |
|------------|--------|----------------|-------|
| **Content Creation** | IMPLEMENTED | Orchestrator pipeline | Full automated generation |
| **Content Editing** | PARTIAL | Caption regeneration exists; no general content editor UI | Can regenerate captions via API/UI |
| **Content Revision/Regeneration** | IMPLEMENTED | `/api/captions/regenerate` with Groq | Platform-specific regeneration |
| **Content Templates** | PARTIAL | Layout templates in LayoutAssembler | Layout presets, not content templates |
| **Structured Outputs** | IMPLEMENTED | All outputs follow defined schemas | LinkedIn, carousel, reel, stories, case study, selection report |
| **Content Briefs** | PARTIAL | Event name/description passed through | No structured brief builder in UI visible |
| **Prompt Construction** | IMPLEMENTED | CopyGenerator builds prompts, brand voice integrated | Groq prompts constructed in API/tasks |
| **Model Selection** | IMPLEMENTED | Configurable via env (GROQ_MODEL), multiple models used | Quality/aesthetic/face/concept use different models |
| **AI Provider Integration** | IMPLEMENTED | Groq for LLM, HuggingFace for models | Local models + Groq API |
| **Retries/Error Handling** | PARTIAL | Some retry logic exists | Need to verify throughout |
| **Streaming** | NOT FOUND | - | No streaming responses visible |
| **Token Limits** | UNKNOWN | Groq has limits but not obvious in code | May be handled by SDK |
| **Content Persistence** | IMPLEMENTED | Files saved to output/, uploads/ tracked | Local filesystem only |
| **Drafts/Autosave** | NOT FOUND | - | No draft system visible |
| **Version History** | NOT FOUND | - | No versioning |
| **Publishing** | NOT FOUND | - | No direct publishing to social platforms |
| **Exporting** | IMPLEMENTED | All outputs saved as files | JPEG, MP4, TXT, MD, JSON |
| **Importing** | IMPLEMENTED | File upload | |
| **Scheduling** | NOT FOUND | - | Only cleanup scheduled, not content scheduling |
| **Content Organization/Search/Tagging** | PARTIAL | Files organized by event/brand in folders | No search/tagging UI |
| **Collaboration** | NOT FOUND | - | Single-user system |
| **Validation/Quality Checks** | IMPLEMENTED | Low-confidence flagging, QA in case study | |
| **Guardrails** | UNKNOWN | - | Not obvious |

## Failure Modes & Issues

- **Model download on first run**: Florence-2, CLIP models are large - will download from HuggingFace, may fail offline or with slow connection
- **ffmpeg dependency**: Required for video/reels - if missing, reel generation will fail
- **Redis optional**: Async jobs work in-memory but may not persist across restarts
- **GPU required for reasonable performance?**: PyTorch will use CPU if no CUDA/MPS, very slow for large batches
- **Python version**: requirements say <3.12 but venv is 3.14 - potential compatibility issues with some packages
- **Memory intensive**: Multiple large models loaded simultaneously
