# Content & Design Engine

Automates social media content creation from event photos and videos.
Takes 50–150 mixed assets as input and produces LinkedIn posts, Instagram carousels, Reels, Stories, and a case study — with zero manual intervention.

---

## What it produces

| Output | Format | Details |
|--------|--------|---------|
| LinkedIn Post | 1080×1080 JPEG + caption | 4–6 image collage, professional copy |
| Instagram Carousel | 1080×1350 JPEG × N + caption | Up to 10 slides, 4:5 ratio |
| Instagram Reel | 1080×1920 MP4 + caption | 30–60s highlight reel with crossfades |
| Instagram Stories | 1080×1920 JPEG × 4 + captions | Sequential narrative, text burned in |
| Case Study | Markdown | Selection logic, scores, QA flags |
| Selection Report | JSON | Full metadata for every selected asset |

---

## GFF 2025 Brand Challenge

This engine supports the GFF 2025 challenge: **Brand Photo Segregation**.

### What it does
1. **Brand Segregation** — Identifies and extracts photos belonging to each brand using CLIP visual similarity to render references
2. **Brand-aware Content** — Generates carousel, reel, and stories per brand with StepOne's brand voice
3. **Per-brand Output** — One folder per brand, clearly organized

### Usage

```bash
python generate_gff.py \
  --assets path/to/GFF_photos/ \
  --brands "Brand A:path/to/render1.jpg,path/to/render2.jpg" \
           "Brand B:path/to/render3.jpg" \
           "Brand C:path/to/render4.jpg" \
           "Brand D:path/to/render5.jpg" \
  --event "GFF 2025" \
  --output ./output
```

### Selection Logic

| Step | Action |
|------|--------|
| 1 | Load brand render images, compute CLIP embeddings |
| 2 | For each photo: compute cosine similarity to each brand |
| 3 | Assign to brand with highest similarity IF ≥ threshold (0.60) |
| 4 | Unmatched photos → saved for manual review |
| 5 | Within brand: quality (30%) + aesthetic (20%) + faces (30%) + concepts (20%) |

### Output Structure

```
output/GFF_2025/
├── selection_report.json      # Full segregation data
├── selection_logic.md         # Documented decision process
├── unmatched/                 # Unassigned assets
├── Brand_A/
│   ├── carousel_1.jpg … _N.jpg
│   ├── instagram_caption.txt
│   ├── reel.mp4
│   ├── reel_caption.txt
│   ├── stories/story_1.jpg … _4.jpg
│   └── case_study.md
├── Brand_B/  ...
└── Brand_C/  ...
```

### Brand Voice

All copy follows StepOne's tone of voice:
- **Clear over clever** — we earn trust with precision, not wordplay
- **Active over passive** — we act, we deliver, we create
- **Specific over vague** — concrete examples and numbers beat abstract claims
- **Confident over tentative** — we say "we do" and "we deliver"
- **Human over corporate** — contractions are fine; humanity is a feature

---

## Quick start

### 1. Prerequisites

```bash
# macOS
brew install python@3.11 node ffmpeg redis

# Ubuntu/Debian
sudo apt install python3.11 nodejs npm ffmpeg redis-server
```

### 2. Setup

```bash
git clone <repo>
cd content-engine

# Copy and configure environment
cp .env.example .env
# Edit .env if needed (defaults work for local dev)

# Create virtual environment (Python 3.9+ supported; 3.11 recommended)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Install frontend dependencies
npm install --prefix ml_test_ui
```

### 3. Start everything

```bash
bash start.sh
```

This starts:
- **FastAPI backend** → http://localhost:8000
- **ML Test UI** → http://localhost:5173
- **Celery worker** (if Redis is running) → async job processing
- **Daily cleanup** → scheduled via APScheduler inside the API

### 4. Run the pipeline

**Via CLI** (fastest for batch processing):
```bash
source .venv/bin/activate
python generate.py \
  --assets path/to/event/photos/ \
  --event "Tech Summit 2024" \
  --output ./output
```

**Via UI**: Open http://localhost:5173 → tab ⑥ Generate

**Via API**:
```bash
curl -X POST http://localhost:8000/api/generate \
  -F "files=@photo1.jpg" \
  -F "files=@photo2.jpg" \
  -F "files=@video.mp4" \
  -F "event_name=Tech Summit 2024"
```

---

## Architecture

```
content_engine/
├── models/
│   ├── quality.py          # Blur + brightness + CLIP aesthetic (adaptive thresholds)
│   ├── face_detection.py   # YOLOv11 face detection with size weighting
│   ├── content_understanding.py  # Florence-2 + CLIP semantic concept matching
│   └── video_processing.py # Scene detection + audio energy highlight extraction
├── pipeline.py             # ContentEngine — coordinates all 4 models
├── layout_assembler.py     # Smart crop, collage, carousel, stories, reel
├── copy_generator.py       # Event-type-aware captions + A/B variants
├── case_study_generator.py # Structured Markdown case study
└── orchestrator.py         # End-to-end: assets → all outputs

api/
├── main.py     # FastAPI endpoints + file validation + scheduled cleanup
├── worker.py   # Celery app configuration
├── tasks.py    # Background ML tasks
└── logger.py   # Structured JSON logging

ml_test_ui/     # React + TypeScript testing UI
config/
└── concept_weights.json  # Per-event-type concept importance weights
```

---

## Scoring logic

Every asset is scored on four axes:

| Weight | Axis | Method |
|--------|------|--------|
| 30% | Technical quality | Laplacian blur + HSV brightness (adaptive thresholds) |
| 20% | Aesthetic quality | CLIP similarity to quality prompt sets |
| 30% | Face presence | YOLOv11 detection with size weighting |
| 20% | Concept relevance | Florence-2 + CLIP semantic matching with configurable weights |

**Face size weighting**: Faces < 2% of image area score 0.4×. Faces > 10% score 1.0×. Prevents background crowds from outscoring foreground portraits.

**Adaptive thresholds**: The first 20 images in each batch are analysed to calibrate blur and brightness thresholds for the event's lighting conditions.

**Low-confidence flagging**: Assets with composite score < 0.5 are flagged for manual review but still included in output.

---

## Configuration

All settings in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_FILE_SIZE_MB` | 200 | Maximum upload size |
| `FACE_CONFIDENCE_THRESHOLD` | 0.35 | YOLOv11 detection threshold |
| `QUALITY_MIN_SCORE` | 0.30 | Minimum quality to keep an image |
| `UPLOAD_RETENTION_DAYS` | 7 | Auto-delete uploads after N days |
| `OUTPUT_RETENTION_DAYS` | 30 | Auto-delete outputs after N days |
| `CORS_ORIGINS` | localhost:5173 | Allowed frontend origins |

**Concept weights** in `config/concept_weights.json` — adjust per event type (award_ceremony, tech_conference, networking_event, product_launch).

---

## Running tests

```bash
source .venv/bin/activate

# Fast tests (no ML models needed)
pytest tests/test_pipeline.py tests/test_copy_generator.py -v

# All tests (requires ML models loaded)
pytest tests/ -v --cov=content_engine --cov-report=term-missing
```

---

## Startup options

```bash
bash start.sh                # Start everything
bash start.sh --no-worker    # Skip Celery (sync mode, no Redis needed)
bash start.sh --no-ui        # Backend only
bash start.sh --prod         # Production mode (no auto-reload)

# Manual cleanup
python cleanup.py --dry-run  # Preview what would be deleted
python cleanup.py            # Delete old uploads and outputs
```

---

## API reference

Full interactive docs at http://localhost:8000/docs

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/api/model-status` | GET | Which ML packages are installed |
| `/api/quality` | POST | Score single image |
| `/api/faces` | POST | Detect faces + bounding boxes |
| `/api/content` | POST | Florence-2 scene understanding |
| `/api/highlights` | POST | Extract video highlight clips |
| `/api/pipeline` | POST | Full asset selection (sync) |
| `/api/pipeline/async` | POST | Full asset selection (async, returns job_id) |
| `/api/generate` | POST | Full content generation (sync) |
| `/api/generate/async` | POST | Full content generation (async) |
| `/api/jobs/{id}/status` | GET | Poll async job status |
| `/api/jobs/{id}/result` | GET | Get async job result |
