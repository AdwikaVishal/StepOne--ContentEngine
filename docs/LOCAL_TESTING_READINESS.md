# Local Testing Readiness — Content & Design Engine

**Project:** `/Users/admin/Downloads/contentfinal5 copy 2`  
**Hardware:** MacBook Air M2, 8GB RAM  
**Python:** 3.11 (`.venv311`), MLX (`.venv-mlx`)  
**MLX:** 0.32.4, MLX-LM 0.32.2  
**Model:** Qwen2.5-0.5B-Instruct-4bit (~0.5GB) — confirmed working

---

## Readiness Verdict

**READY WITH MOCKED INTEGRATIONS**

Complete local testing is possible without any external API keys. Groq is disabled in code; MLX local inference handles all caption generation. All computer-vision models load from public Hugging Face Hub. Redis is optional (APScheduler fallback).

---

## What Can Be Tested Locally (Zero Credentials)

| Feature | Local mechanism | Memory impact | Status |
|---------|----------------|---------------|--------|
| MLX caption generation | Qwen2.5-0.5B-4bit via subprocess worker | ~0.5GB model + worker | ✅ Ready |
| Image quality assessment | OpenCV blur/brightness + CLIP ViT-B/32 aesthetic | CLIP ~0.4GB | ✅ Ready |
| Face detection | YOLOv11n-face (AdamCodd) | ~20MB | ✅ Ready |
| Content understanding | Florence-2-base (<OD>) + CLIP concept matching | Florence-2 ~1GB + CLIP | ✅ Ready (load sequentially) |
| Video highlight extraction | ffmpeg + librosa audio energy + CLIP frame scoring | CLIP + ffmpeg subprocess | ✅ Ready (test last) |
| Layout assembly | Pillow smart-crop + collage/carousel/stories | Low | ✅ Ready |
| Reel assembly | ffmpeg concat / xfade | Low (subprocess) | ✅ Ready |
| Case study generation | Template markdown | Negligible | ✅ Ready |
| Brand segregation | CLIP cosine similarity | CLIP ~0.4GB | ✅ Ready |
| Brand-aware copy | MLX Qwen | ~0.5GB | ✅ Ready |
| Studio projects/drafts/brand profiles | Local JSON filesystem storage | Negligible | ✅ Ready |
| GFF brand pipeline | CLIP + MLX + local storage | Moderate | ✅ Ready |
| API health / model-status | FastAPI endpoints | Negligible | ✅ Ready |
| Async jobs (APScheduler fallback) | In-memory thread pool | Negligible | ✅ Ready (no Redis needed) |

## What Requires External Credentials (Blocked Until Connected)

| Feature | Credential(s) | Can test locally without? |
|---------|--------------|--------------------------|
| LinkedIn publishing | `LINKEDIN_ACCESS_TOKEN` (+ client id/secret/org id) | ❌ Returns "not configured" |
| Instagram publishing | `INSTAGRAM_ACCESS_TOKEN` + `INSTAGRAM_BUSINESS_ACCOUNT_ID` | ❌ Returns "not configured" |
| Sentry error tracking | `SENTRY_DSN` | ⚠️ Optional, skipped if missing |
| Groq-based captions | `GROQ_API_KEY` | ⚠️ Disabled in code; MLX used instead |

## Memory Management on 8GB RAM

### Model sizes (approximate)

| Model | Size | Loads simultaneously with MLX? |
|-------|------|-------------------------------|
| MLX Qwen2.5-0.5B-4bit | ~0.5 GB | Primary — loaded alone |
| CLIP ViT-B/32 | ~0.4–0.5 GB | Yes, but only one CV model at a time |
| Florence-2-base | ~0.8–1.2 GB | Only one CV model at a time |
| BLIP base | ~0.4–0.6 GB | Only one CV model at a time |
| YOLOv11n-face | ~0.02 GB | Yes, tiny |

### Critical constraint

The `ContentEngine.__init__` instantiates `QualityAssessor` (CLIP), `FaceDetector` (YOLO), `ContentUnderstander` (Florence-2 + CLIP), and `VideoProcessor` (CLIP). Models are **lazy-loaded per-property** — they only load on first use — but if multiple models are used in sequence without unloading, peak memory can approach 8GB.

**Safe sequential testing strategy:**

```
Step 1: MLX caption generation alone (lowest risk, ~0.5GB)
Step 2: Image quality + face detection (YOLO + CLIP)
Step 3: Content understanding (Florence-2 + CLIP) — unload CLIP/YOLO first if possible
Step 4: Video highlights (ffmpeg + librosa + CLIP) — heaviest, test last
Step 5: BLIP photo intelligence — test separately, unload other models first
```

**Rules:**
- Do not load Florence-2, CLIP, and BLIP simultaneously.
- Do not start multiple MLX workers (single model, serialized requests).
- MLX worker uses `solo` pool (concurrency=1) to prevent OOM.

## System Dependencies (Install Before Testing)

These are NOT Python packages — they are system binaries/libraries:

| Dependency | Purpose | Install command (macOS) | Check command |
|------------|---------|------------------------|---------------|
| ffmpeg | Video validation, reel assembly, audio extraction | `brew install ffmpeg` | `which ffmpeg` |
| libmagic | MIME type detection (python-magic backend) | `brew install libmagic` | `python -c "import magic; print('ok')"` |
| Redis | Optional — async job queue (Celery) | `brew install redis && brew services start redis` | `redis-cli ping` |
| Python 3.11 | Main application runtime | Already present (`.venv311`) | `python --version` |
| Python 3.11 (mlx) | MLX worker runtime | Already present (`.venv-mlx`) | `.venv-mlx/bin/python --version` |

## Safe Test Commands (Read-Only)

Run from project root. None of these download models, run inference, modify `.env`, or call external APIs.

### 1. Verify MLX configuration parses (no model load)

```bash
python -c "
from content_engine.llm.mlx_config import MLXConfig
c = MLXConfig.from_env()
issues = c.validate()
print('MLX config issues:', issues if issues else 'none')
print('Model:', c.model_id)
print('Worker python:', c.worker_python, 'exists:', __import__('pathlib').Path(c.worker_python).exists())
print('Worker script:', c.worker_script, 'exists:', __import__('pathlib').Path(c.worker_script).exists())
"
```

### 2. Verify API package imports (no server start)

```bash
python -c "
from api.main import app
print('FastAPI app imported OK')
print('Routes:', len(app.routes))
"
```

### 3. Check optional package availability (imports only)

```bash
python -c "
import importlib
for pkg in ['groq','redis','celery','torch','transformers','ultralytics','sentence_transformers','cv2','librosa','scenedetect','magic','apscheduler','flower','huggingface_hub','accelerate']:
    try:
        importlib.import_import(pkg)
        print(f'{pkg}: available')
    except ImportError:
        print(f'{pkg}: NOT INSTALLED')
"
```

### 4. Check MLX worker script exists and is executable

```bash
ls -la scripts/mlx_worker.py
ls -la .venv-mlx/bin/python
```

### 5. Run existing unit tests (mocked, no external calls)

```bash
python -m pytest tests/ -x -q --timeout=60
```

Note: Some tests may import the full `content_engine` module which triggers lazy model loading. Per `pyproject.toml`, model tests should import directly without going through `__init__.py`.

### 6. API health endpoint (after starting server — optional)

```bash
# Start server (only if you want to test HTTP endpoints)
python start.sh

# Then in another terminal:
curl http://localhost:8000/health
curl http://localhost:8000/api/model-status
```

## Environment Variables Needed for Local Testing

| Env var | Source | Required for local testing? | Default if missing |
|---------|--------|----------------------------|-------------------|
| `MLX_MODEL_ID` | `.env` | Yes | `mlx-community/Qwen2.5-0.5B-Instruct-4bit` |
| `MLX_MAX_TOKENS` | `.env` | No | `64` |
| `MLX_MAX_CONTEXT` | `.env` | No | `2048` |
| `MLX_TIMEOUT_SECONDS` | `.env` | No | `180` |
| `REDIS_URL` | `.env` | No (APScheduler fallback) | `redis://localhost:6379/0` |
| `UPLOAD_DIR`, `OUTPUT_DIR`, `MODEL_CACHE_DIR`, `LOG_DIR` | `.env` | No | `uploads/`, `output/`, `models/`, `logs/` |
| `GROQ_API_KEY` | `.env` | **No** (disabled) | `""` |

All of the above are already configured in `.env`. No new environment variables need to be set for local testing.

## Features Blocked on This Machine

None for core testing. The following are optional and degrade gracefully:

- **Redis/Celery distributed jobs** — if Redis isn't running, APScheduler in-process handles jobs (dev mode only).
- **Social publishing** — returns "not configured" without tokens; doesn't block content generation.
- **Sentry** — errors are logged locally; no external reporting.

## Recommended Testing Order

1. MLX config validation (command 1 above)
2. Package import check (command 2-3 above)
3. MLX worker health check (spawn worker, health check, shutdown — no generation)
4. Single-image pipeline: upload → quality → face → content understanding → selection
5. MLX caption generation on selected assets
6. Full orchestrator run on small batch (2-3 images)
7. Video highlight extraction on a short clip (test last)
8. BLIP photo intelligence (test separately, unload other models first)

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| MLX model weights not cached (~0.5GB download from HF Hub) | Medium | Medium | Download once; no auth needed |
| 8GB RAM exceeded by multiple CV models | Medium | High | Test models sequentially; don't load Florence-2 + BLIP + CLIP together |
| ffmpeg not installed | Low | High | Install via `brew install ffmpeg` |
| libmagic not installed | Low | Medium | Install via `brew install libmagic`; fallback to content-type header |
| `data/historical/` empty | High | Low | Caption retrieval returns empty; not blocking |
| Groq key present but integration disabled | N/A | Low | MLX is the active caption path; no action needed |

## Files Created by This Audit

- `docs/API_INTEGRATION_AUDIT.md` — full integration inventory
- `docs/LOCAL_TESTING_READINESS.md` (this file)
- `docs/API_KEYS_CHECKLIST.md` — credential acquisition checklist

## Recommended Next Steps

1. Install system dependencies: `brew install ffmpeg libmagic`
2. Run the MLX config validation and package import checks above
3. Run the MLX worker health check (spawn → health → shutdown)
4. Run the full content-generation pipeline on a small local asset batch
5. If social publishing is needed later, obtain LinkedIn and Instagram access tokens