# ARCHITECTURE

## System Overview

```mermaid
graph TB
    subgraph Frontend["React UI (ml_test_ui)"]
        Studio[StudioPage]
        Results[ResultsPage]
        AssetSel[AssetSelectionPage]
        Analytics[AnalyticsPage]
    end
    
    subgraph API["FastAPI Backend (api/)"]
        Main[main.py - Routes & Middleware]
        GFFRoutes[gff_routes.py]
        Tasks[Celery Tasks]
        Worker[Celery Worker]
        Scheduler[APScheduler]
    end
    
    subgraph Core["Content Engine (content_engine/)"]
        Orch[ContentOrchestrator]
        BOrch[BrandOrchestrator]
        GFFOrch[GFFOrchestrator]
        Pipeline[ContentEngine/ML Pipeline]
        Layout[LayoutAssembler]
        Copy[CopyGenerator]
        Case[CaseStudyGenerator]
    end
    
    subgraph ML["ML Models"]
        Quality[QualityAssessor]
        Face[FaceDetector - YOLOv11]
        Content[ContentUnderstander - Florence-2/CLIP]
        Video[VideoProcessor - PySceneDetect/Librosa]
        BrandSeg[BrandSegregator - CLIP]
    end
    
    subgraph Storage["Storage"]
        Uploads[(uploads/)]
        Output[(output/)]
        Models[(models/)]
    end
    
    Studio --> Main
    Main --> Orch
    Main --> BOrch
    GFFRoutes --> GFFOrch
    Orch --> Pipeline
    Orch --> Layout
    Orch --> Copy
    BOrch --> BrandSeg
    BOrch --> Orch
    Pipeline --> Quality
    Pipeline --> Face
    Pipeline --> Content
    Pipeline --> Video
    Main --> Tasks
    Tasks --> Worker
    Scheduler --> Main
    Layout --> FFmpeg[ffmpeg]
    Main --> Uploads
    Orch --> Output
```

## Content Generation Data Flow

```mermaid
sequenceDiagram
    participant U as User
    participant UI as React UI
    participant API as FastAPI
    participant Job as Job Queue
    participant Orch as ContentOrchestrator
    participant ML as ContentEngine
    participant Layout as LayoutAssembler
    participant Copy as CopyGenerator
    
    U->>UI: Upload assets + configure event
    UI->>API: POST /api/generate/async
    API->>Job: Queue job (Celery or in-memory)
    API-->>UI: Return job_id
    UI->>API: Poll /api/jobs/{id}/status
    Job->>Orch: Process
    Orch->>ML: select_assets()
    ML->>ML: Quality + Faces + Content + Video scoring
    ML-->>Orch: Selections with intended_use
    Orch->>Layout: Create collages/carousels/stories/reels
    Orch->>Copy: Generate captions
    Orch->>Orch: Generate case study
    Orch-->>Job: Save outputs
    Job-->>API: Job complete
    UI->>API: GET /api/jobs/{id}/result
    API-->>UI: Return result with file URLs
    UI-->>U: Display results
```

## Design/Composition Data Flow

```mermaid
sequenceDiagram
    participant ML as ContentEngine
    participant Orch as Orchestrator
    participant Layout as LayoutAssembler
    participant PIL as Pillow
    participant FFmpeg as ffmpeg
    
    ML-->>Orch: Selections (intended_use: collage/story/reel)
    Orch->>Layout: Route by intended_use
    
    alt intended_use = collage
        Layout->>PIL: smart_crop() with face detection
        Layout->>PIL: create_linkedin_collage() - arrange in grid
        PIL-->>Orch: linkedin_collage.jpg
    alt intended_use = story
        Layout->>PIL: create_stories() - adapt horizontal if needed
        Layout->>PIL: Add text overlay
        PIL-->>Orch: instagram_story_*.jpg
    alt intended_use = reel
        Layout->>FFmpeg: Extract highlights from video
        Layout->>FFmpeg: Concatenate with xfade transitions
        FFmpeg-->>Orch: instagram_reel.mp4
    end
```

## Service Boundaries

| Service | Type | Responsibility |
|---------|------|----------------|
| **api/main.py** | FastAPI App | HTTP routing, validation, middleware, job orchestration, file handling |
| **api/gff_routes.py** | Router | GFF 2025 brand segregation endpoints |
| **api/tasks.py** | Celery Tasks | Background job definitions |
| **api/worker.py** | Celery Worker | Worker process |
| **api/scheduler.py** | APScheduler | In-process job scheduling/fallback |
| **content_engine/orchestrator.py** | Orchestrator | Main pipeline coordination |
| **content_engine/brand_orchestrator.py** | Orchestrator | Brand-aware pipeline |
| **content_engine/gff/orchestrator_gff.py** | Orchestrator | GFF full pipeline |
| **content_engine/pipeline.py** | ML Orchestrator | Coordinates all ML models |
| **content_engine/layout_assembler.py** | Service | Image/video composition |
| **content_engine/copy_generator.py** | Service | Caption generation |
| **content_engine/brand_segregator.py** | Service | CLIP-based brand matching |

## API Contracts

Key endpoints:
- `POST /api/generate/async` - Submit async generation job
- `GET /api/jobs/{job_id}/status` - Job status
- `GET /api/jobs/{job_id}/result` - Job results
- `POST /api/generate/fast` - Fast generation with brand mode support
- `POST /api/generate/custom` - Custom generation with layout choices
- `POST /api/layout/preview` - Preview layouts
- `POST /api/gff/process` - GFF pipeline
- `POST /api/gff/process-upload` - GFF upload endpoint
- `POST /api/captions/regenerate` - Regenerate captions with LLM

## Persistence

- **Filesystem only** - No database (Postgres, MongoDB, etc.) found
- **Uploads**: Saved to `settings.upload_dir` (default `uploads/`)
- **Outputs**: Saved to `settings.output_dir` (default `output/`) organized by event/brand
- **Models**: Cached by HuggingFace in standard locations or `MODEL_CACHE_DIR`

## External Integrations

| Integration | Type | Usage | Required |
|-------------|------|-------|----------|
| **HuggingFace Hub** | Model downloads | Florence-2, YOLOv11 face model, CLIP models | Yes for first run |
| **Groq API** | LLM | Caption regeneration | Optional (falls back to templates) |
| **Redis** | Message broker | Celery jobs | Optional (falls back to in-memory) |
| **FFmpeg** | Video processing | Reel creation, video encoding | Required for video features |
| **libmagic** | File validation | MIME type detection | Required by python-magic |

## Configuration Dependencies

All config via environment variables read by `config.py`. Key deps:
- API settings, CORS origins
- Storage paths
- ML thresholds (face confidence, quality, brand similarity)
- Redis/Celery settings
- Groq API key/model
- File type restrictions, size limits
- Cleanup retention
