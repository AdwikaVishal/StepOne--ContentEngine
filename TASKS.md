# Content & Design Engine — Task Tracker

> Last verified: all 29 feature checks ✅ | 0 syntax errors | 0 print() statements | 28 tests passing
> Status: ✅ Done | 🔄 In Progress | ❌ Not Done | ⚠️ Partial

---

## 🔴 CRITICAL

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 1 | Async job processing (APScheduler in-memory + Celery fallback) | `api/scheduler.py`, `api/worker.py`, `api/tasks.py`, `api/main.py` | ✅ Done |
| 2 | File validation — real MIME via python-magic + 200MB size cap | `api/main.py` → `validate_upload()` | ✅ Done |
| 3 | Upload cleanup — APScheduler daily job at 03:00, no cron/Docker | `cleanup.py`, `api/main.py` → `start_scheduler()` | ✅ Done |
| 4 | Environment config — all values from `.env`, zero hardcoded paths | `config.py`, `.env`, `.env.example` | ✅ Done |

---

## 🟠 HIGH

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 5 | Face bounding box canvas overlay in UI | `ml_test_ui/src/tabs/FaceTab.tsx` | ✅ Done |
| 6 | Video player with clickable highlight timeline | `ml_test_ui/src/tabs/VideoTab.tsx` | ✅ Done |
| 7 | Result export — JSON download + jsPDF report | `ml_test_ui/src/tabs/PipelineTab.tsx` | ✅ Done |
| 8 | Semantic concept matching — CLIP cosine similarity replaces substring | `content_engine/models/content_understanding.py` | ✅ Done |
| 9 | Concept-driven copy — event type detection (award/keynote/networking/workshop) | `content_engine/copy_generator.py` | ✅ Done |
| 10 | Full generation UI tab with async job polling | `ml_test_ui/src/tabs/GenerateTab.tsx` | ✅ Done |
| 11 | One-command startup script (no Docker) | `start.sh` | ✅ Done |
| 12 | Unit tests — 6 test files, 28+ tests passing | `tests/` | ✅ Done |
| 13 | Face size weighting — small faces 0.4×, large faces 1.0× | `content_engine/models/face_detection.py` | ✅ Done |

---

## 🟡 MEDIUM

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 14 | Reel crossfade transitions — ffmpeg xfade filter | `content_engine/layout_assembler.py` | ✅ Done |
| 15 | Story text burn-in — PIL ImageDraw with shadow | `content_engine/layout_assembler.py` | ✅ Done |
| 16 | Watermark/branding support — logo overlay at any corner | `content_engine/layout_assembler.py` | ✅ Done |
| 17 | Configurable concept weights — `config/concept_weights.json` + API override | `config/concept_weights.json`, `content_engine/models/content_understanding.py` | ✅ Done |
| 18 | Adaptive quality thresholds — auto-calibrate on first 20 images | `content_engine/models/quality.py` | ✅ Done |
| 19 | Caption A/B variants — `generate_variants(n=3)` per platform | `content_engine/copy_generator.py` | ✅ Done |
| 20 | Mobile responsive UI — hamburger menu, CSS Grid, breakpoints | `ml_test_ui/src/App.tsx`, `ml_test_ui/src/styles/responsive.css` | ✅ Done |
| 21 | Result history in LocalStorage — last 10 runs, restore on click | `ml_test_ui/src/tabs/PipelineTab.tsx` | ✅ Done |

---

## 🟢 LOW

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 22 | Structured logging — structlog JSON, request_id middleware, zero print() | `api/logger.py`, `content_engine/pipeline.py`, `content_engine/orchestrator.py` | ✅ Done |
| 23 | CORS locked to env — `CORS_ORIGINS` from `.env`, not hardcoded `["*"]` | `api/main.py`, `config.py` | ✅ Done |

---

## 📋 ASSIGNMENT REQUIREMENTS

| # | Requirement | Status |
|---|-------------|--------|
| 24 | Asset selection explanations — human-readable reason per asset | ✅ Done |
| 25 | Low-confidence flagging — `< 0.5` flagged, never silently dropped | ✅ Done |
| 26 | Cross-platform copy distinction — LinkedIn ≠ Instagram ≠ Stories | ✅ Done |
| 27 | Case study template — 7-section structured Markdown | ✅ Done |
| 28 | Real-time processing — new dataset via API/UI, no reconfiguration | ✅ Done |

---

## 🔧 INFRASTRUCTURE (No Docker)

| # | Task | File(s) | Status |
|---|------|---------|--------|
| 29 | `useJobPolling` React hook — polls every 2s, handles both backends | `ml_test_ui/src/hooks/useJobPolling.ts` | ✅ Done |
| 30 | `JobStatus` component — live progress bar + step label + backend indicator | `ml_test_ui/src/components/JobStatus.tsx` | ✅ Done |
| 31 | `api/scheduler.py` — in-memory job store, APScheduler thread pool | `api/scheduler.py` | ✅ Done |
| 32 | `README.md` — full deployment guide, architecture, API reference | `README.md` | ✅ Done |
| 33 | `requirements.txt` — all deps including python-magic, apscheduler, structlog | `requirements.txt` | ✅ Done |

---

## ✅ SUCCESS CHECKLIST

- [x] `bash start.sh` starts everything with one command
- [x] API responds in < 100ms (jobs return job_id immediately)
- [x] Files > 200MB rejected with clear 413 error
- [x] Files with wrong MIME type rejected with clear 400 error (python-magic)
- [x] Old uploads auto-deleted after 7 days (APScheduler at 03:00)
- [x] Face boxes visible on images in UI (canvas overlay)
- [x] Video highlights has clickable timeline markers
- [x] Copy changes based on event type (award vs networking vs keynote)
- [x] Stories have text burned into images
- [x] Zero `print()` statements — all structured JSON logs
- [x] `CORS_ORIGINS` restricts to specified domains from `.env`
- [x] 28 unit tests passing
- [x] Second dataset processes without reconfiguration

---

## 📁 Final File Inventory

```
content-engine/
├── api/
│   ├── __init__.py
│   ├── logger.py          ← structlog JSON logging + request_id
│   ├── main.py            ← FastAPI + validation + scheduler + CORS
│   ├── scheduler.py       ← In-memory job store (APScheduler)
│   ├── tasks.py           ← Celery tasks (when Redis available)
│   └── worker.py          ← Celery app config
├── config/
│   └── concept_weights.json  ← Per-event-type concept weights
├── content_engine/
│   ├── models/
│   │   ├── quality.py          ← Blur + brightness + CLIP (adaptive)
│   │   ├── face_detection.py   ← YOLOv11 + size weighting
│   │   ├── content_understanding.py  ← Florence-2 + CLIP semantic
│   │   └── video_processing.py ← Scene detect + audio energy
│   ├── pipeline.py         ← ContentEngine orchestrator
│   ├── layout_assembler.py ← Collage + carousel + stories + reel
│   ├── copy_generator.py   ← Event-type templates + A/B variants
│   ├── case_study_generator.py
│   ├── orchestrator.py     ← End-to-end pipeline
│   └── data_types.py
├── ml_test_ui/src/
│   ├── hooks/
│   │   └── useJobPolling.ts    ← Job status polling hook
│   ├── components/
│   │   ├── JobStatus.tsx       ← Live progress bar component
│   │   ├── Badge.tsx
│   │   ├── Card.tsx
│   │   ├── DropZone.tsx
│   │   ├── ScoreBar.tsx
│   │   └── Spinner.tsx
│   ├── styles/
│   │   └── responsive.css      ← Mobile breakpoints
│   ├── tabs/
│   │   ├── QualityTab.tsx
│   │   ├── FaceTab.tsx         ← Canvas bbox overlay
│   │   ├── ContentTab.tsx
│   │   ├── VideoTab.tsx        ← HTML5 player + timeline
│   │   ├── PipelineTab.tsx     ← Export + history
│   │   └── GenerateTab.tsx     ← Async job polling
│   ├── App.tsx                 ← Mobile responsive sidebar
│   └── api.ts                  ← Typed axios client
├── tests/
│   ├── conftest.py
│   ├── test_quality.py
│   ├── test_face_detection.py
│   ├── test_content_understanding.py
│   ├── test_layout_assembler.py
│   ├── test_pipeline.py
│   └── test_copy_generator.py
├── .env
├── .env.example
├── cleanup.py
├── config.py
├── generate.py
├── README.md
├── requirements.txt
├── run_pipeline.py
├── start.sh
└── TASKS.md
```
