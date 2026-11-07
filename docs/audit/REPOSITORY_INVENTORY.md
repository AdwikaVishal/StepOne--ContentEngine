# REPOSITORY INVENTORY

## Project Structure
```
contentfinal5 copy 2/
├── api/                    # FastAPI backend (main.py, gff_routes.py, tasks.py, worker.py, scheduler.py)
├── config/                 # Config files (concept_weights.json)
├── content_engine/         # Core ML pipeline
│   ├── brand/             # Brand voice, selection logic
│   ├── gff/               # GFF orchestrator
│   ├── models/            # ML models (quality, face_detection, content_understanding, video_processing)
│   └── utils/             # Utilities
├── docs/                  # Documentation (analysis reports, audit will go here)
├── ml_test_ui/            # React + TypeScript frontend (Vite)
├── models/                # (empty dir)
├── tests/                 # Pytest tests
├── uploads/               # Upload directory (created)
├── output/                # Output directory
├── .env, .env.example     # Environment config
├── config.py              # Central config
├── generate.py            # CLI entry point
├── generate_gff.py        # GFF CLI entry point
├── pyproject.toml         # Python project config
├── requirements.txt       # Dependencies
├── run_pipeline.py        # Pipeline runner
├── start.sh, start_dev.sh # Startup scripts
└── yolov8n.pt            # YOLOv8 weights (6.5MB)
```

## Tech Stack

### Backend (Python)
- **Framework:** FastAPI 0.110.0+, Uvicorn
- **Python:** >=3.9, <3.12 (per pyproject) - but venv has 3.14
- **ML/CV:** PyTorch >=2.0, torchvision, transformers <5.0, ultralytics, opencv-python, Pillow, numpy, scipy, scikit-learn
- **Video/Audio:** scenedetect, librosa
- **CLIP/Florence:** sentence-transformers, huggingface-hub, accelerate, einops, timm
- **Async/Queue:** Celery 5.3+, Redis 5.0+, Kombu, Flower
- **Scheduling:** APScheduler
- **LLM:** Groq >=1.0.0
- **Validation:** python-magic, pydantic (via FastAPI)
- **Logging:** structlog
- **Image Utils:** ImageHash for deduplication

### Frontend (TypeScript/React)
- **Framework:** React 19.2.5, TypeScript ~6.0.2
- **Build:** Vite 8.0.10
- **UI:** Framer Motion, Lucide React icons
- **State/Data:** Axios, idb (IndexedDB), react-hot-toast/sonner
- **Features:** react-dropzone, html2canvas, jspdf, recharts, embla-carousel-react

### Infrastructure
- **OS:** macOS (darwin)
- **Git:** Yes, repo initialized
- **FFmpeg:** Required for video processing (mentioned in README)
- **Redis:** Optional (falls back to in-memory)
- **libmagic:** Required for python-magic

## Entry Points

| File | Purpose |
|------|---------|
| `api/main.py` | FastAPI app, all API routes, startup/shutdown, middleware |
| `content_engine/orchestrator.py` | Main ContentOrchestrator - end-to-end pipeline |
| `content_engine/brand_orchestrator.py` | BrandOrchestrator for GFF mode |
| `content_engine/gff/orchestrator_gff.py` | GFF-specific orchestrator |
| `generate.py` | CLI for standard generation |
| `generate_gff.py` | CLI for GFF brand segregation |
| `run_pipeline.py` | Pipeline runner script |
| `ml_test_ui/src/App.tsx` | React app entry |
| `ml_test_ui/src/main.tsx` | React DOM mount |

## Key Configuration Files
- `config.py` - Central settings class reading from .env
- `.env` / `.env.example` - Environment variables
- `pyproject.toml` - Python build/test config
- `ml_test_ui/package.json` - Frontend deps
- `api/worker.py` - Celery worker config
- `api/beat_schedule.py` - Celery beat schedule

## Dependencies Count
- requirements.txt: ~60 packages
- ml_test_ui/package.json: ~40 deps + ~15 devDeps
