# API Integration Audit — Content & Design Engine

**Project:** `/Users/admin/Downloads/contentfinal5 copy 2`  
**Audit type:** Read-only credential & integration audit (no secrets exposed, no code modified)  
**Hardware:** MacBook Air M2, 8GB RAM  
**Python:** 3.11 (`.venv311`), MLX (`.venv-mlx`)

---

## Executive Summary

The application is designed to run end-to-end locally using **MLX local inference** for all AI-powered copy generation. No external API key is required for the core content-generation workflow. The only externally configured credential present is `GROQ_API_KEY`, but Groq is **disabled in code** (the caption factory rejects `groq_only` mode and `CopyGenerator._groq` is always `None`).

All heavy ML models (CLIP, Florence-2, YOLOv11n-face, BLIP) load from the public Hugging Face Hub — no auth token required. Redis/Celery is optional; the app falls back to in-process APScheduler when Redis is unavailable.

**Readiness verdict:** READY WITH MOCKED INTEGRATIONS (core local testing possible without any external credentials).

---

## Phase 1 & 2 — Complete Integration Inventory

| # | Service | Purpose | Env var | Required? | Status | Validation | Local alternative | Cost | Dependent modules |
|---|---------|---------|---------|-----------|--------|------------|-------------------|------|-------------------|
| 1 | **MLX (Apple Silicon)** | Local LLM inference for captions | `MLX_MODEL_ID`, `MLX_MODEL_PATH`, `MLX_MAX_TOKENS`, `MLX_MAX_CONTEXT`, `MLX_TEMPERATURE`, `MLX_TIMEOUT_SECONDS`, `MLX_MIN_AVAILABLE_GB`, `MLX_MAX_SWAP_PERCENT`, `MLX_MAX_MEMORY_PERCENT`, `MLX_WORKER_PYTHON`, `MLX_WORKER_SCRIPT` | **Required** (caption path) | Configured | `content_engine/llm/mlx_config.py:validate()`; `scripts/mlx_worker.py` health check | None (MLX IS the local alternative) | Free (local) | `copy_generator.py`, `captioning/providers/local_provider.py`, `captioning/factory.py`, `llm/mlx_client.py`, `scripts/mlx_worker.py` |
| 2 | **Qwen2.5-0.5B-Instruct-4bit (mlx-community)** | MLX model weights (4-bit quantized) | `MLX_MODEL_ID` | **Required** | Configured (repo id; weights must be cached) | `mlx_lm.load(model_path)` in worker | Qwen2.5-1.5B-4bit (~1.2GB) | Free | `mlx_worker.py` |
| 3 | **CLIP ViT-B/32 (sentence-transformers)** | Aesthetic scoring, concept matching, brand matching | None (HF Hub) | **Required** (ML pipeline) | Package installed; model auto-downloads on first use | `SentenceTransformer("clip-ViT-B-32")` | None | Free (public model) | `models/quality.py`, `models/content_understanding.py`, `models/video_processing.py`, `brand/brand_matcher.py` |
| 4 | **Florence-2-base (microsoft)** | Object detection (`<OD>` task) for scene concepts | None (HF Hub) | **Required** (content understanding) | Package installed; model auto-downloads | `AutoModelForCausalLM.from_pretrained("microsoft/Florence-2-base")` | None | Free | `models/content_understanding.py` |
| 5 | **YOLOv11n-face-detection (AdamCodd)** | Face detection + size-aware weighting + smart crop anchor | None (HF Hub via `hf_hub_download`) | **Required** (quality/scoring/layout) | Package installed; model downloads via `hf_hub_download` | `YOLO(model_path)` | None | Free | `models/face_detection.py`, `layout_assembler.py` |
| 6 | **BLIP (Salesforce/blip-image-captioning-base)** | Image captioning (photo intelligence) | `BLIP_MODEL_ID`, `BLIP_MODEL_PATH`, `BLIP_LOCAL_FILES_ONLY`, `BLIP_MAX_IMAGE_SIDE`, `BLIP_MAX_FILE_SIZE_MB`, `BLIP_MAX_PIXELS`, `BLIP_MAX_BATCH_IMAGES` | Optional | Configured defaults; `BLIP_LOCAL_FILES_ONLY=true` (no auto-download) | `BlipProcessor.from_pretrained(..., local_files_only=True)` | None | Free | `photo_intelligence/blip_captioner.py`, `api/photo_intelligence_routes.py` |
| 7 | **DINOv2 (facebook/dinov2-small)** | Advanced brand matching (optional branch) | None (HF Hub) | Optional | Import wrapped in try/except; may not be installed | `AutoImageProcessor.from_pretrained("facebook/dinov2-small")` | CLIP-only fallback | Free | `brand/brand_matcher.py` |
| 8 | **Groq LLM API** | AI-powered captions (DISABLED in code) | `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_SERVICE_TIER`, `GROQ_TEMPERATURE` | **Optional** (disabled) | **Configured in .env but NOT used** — factory raises `CaptionProviderError` for `groq_only`; `CopyGenerator._groq` is always `None` | `groq.Groq(api_key=...)` client init; `is_available()` checks key + import | MLX local inference | Free tier (no CC required) | `copy_generator.py` (_GroqGenerator), `captioning/providers/groq_provider.py` |
| 9 | **Redis + Celery** | Async job queue / distributed workers | `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `CELERY_WORKER_CONCURRENCY`, ... | Optional | Configured defaults (`redis://localhost:6379/0`); falls back to APScheduler in-memory | `redis.from_url(...).ping()` | APScheduler in-process (dev mode) | Free (self-hosted) | `api/main.py`, `api/tasks.py`, `api/worker.py`, `api/scheduler.py` |
| 10 | **Flower** | Celery monitoring dashboard | `FLOWER_PORT`, `FLOWER_ENABLED`, `FLOWER_USER`, `FLOWER_PASSWORD` | Optional | Configured (`FLOWER_ENABLED=true`) | HTTP to `localhost:5555` | None | Free | `api/worker.py` |
| 11 | **Sentry** | Error tracking | `SENTRY_DSN` | Optional | **Not configured** (commented out in .env) | `sentry_sdk.init(dsn=...)` | None | Free tier | `api/worker.py` |
| 12 | **LinkedIn Publishing** | Social media publishing | `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`, `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_ORGANIZATION_ID` | Optional | **Not configured** | `LinkedInPublisher.is_configured()` → checks `LINKEDIN_ACCESS_TOKEN` | None (mock/publish returns "not configured") | Free (dev) | `studio/publishing.py`, `api/studio_routes.py` |
| 13 | **Instagram Publishing** | Social media publishing | `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_BUSINESS_ACCOUNT_ID`, `INSTAGRAM_APP_ID`, `INSTAGRAM_APP_SECRET` | Optional | **Not configured** | `InstagramPublisher.is_configured()` → checks token + business account ID | None | Free (dev) | `studio/publishing.py`, `api/studio_routes.py` |
| 14 | **ffmpeg** (system binary) | Video validation, reel assembly, audio extraction | None | Required (video features) | System binary; checked via `subprocess.run(["ffprobe", ...])` | `ffprobe` / `ffmpeg` exit code 0 | None | Free | `api/main.py`, `models/video_processing.py`, `layout_assembler.py` |
| 15 | **libmagic** (system lib + python-magic) | MIME type detection for uploads | None | Required (upload validation) | `python-magic>=0.4.27` in requirements; needs `libmagic` system lib | `magic.from_buffer(data, mime=True)` | Fallback to `file.content_type` | Free | `api/main.py` |
| 16 | **Local filesystem storage** | Uploads, outputs, models cache | `UPLOAD_DIR`, `OUTPUT_DIR`, `MODEL_CACHE_DIR`, `LOG_DIR` | Required | Configured (`uploads/`, `output/`, `models/`, `logs/`) | `settings.upload_dir.mkdir(...)` | None | Free | `config.py`, `api/main.py`, `studio/storage.py` |
| 17 | **Historical post data** | Caption style retrieval | `CAPTION_HISTORICAL_DATA_PATH` | Optional | `data/historical/` exists but only contains `.gitkeep` (no posts) | `HistoricalPostRetriever.load_posts()` | None (empty) | Free | `captioning/retrieval/retriever.py` |
| 18 | **Pillow / OpenCV / numpy** | Image processing, layout assembly | None | Required | Installed per requirements.txt | `PIL.Image.open`, `cv2.imread` | None | Free | `layout_assembler.py`, `api/main.py` |

### Services NOT actually used (present in docs/requirements but no execution path traced)

- None found — every package in `requirements.txt` is imported somewhere in the active codebase.
- `sentry-sdk` is commented out in requirements and not imported.
- The `content_engine.backup.1793532480/` directory contains legacy code (old Groq providers, old caption factory) that is **not imported** by the active application.

---

## Phase 3 — Audit of Existing Credentials

### Variables present in `.env` (names only — values never printed)

| Env var | Present in .env? | Referenced in code? | Integration initializes? | Safe local validation? | Notes |
|---------|-----------------|---------------------|-------------------------|------------------------|-------|
| `API_HOST` | Yes | config.py:33 | N/A (server setting) | Yes | — |
| `API_PORT` | Yes | config.py:34 | N/A | Yes | — |
| `API_WORKERS` | Yes | config.py:35 | N/A | Yes | — |
| `LOG_LEVEL` | Yes | config.py:36 | N/A | Yes | — |
| `CORS_ORIGINS` | Yes | config.py:39 | N/A | Yes | — |
| `UPLOAD_DIR` | Yes | config.py:42 | Yes | Yes | — |
| `OUTPUT_DIR` | Yes | config.py:43 | Yes | Yes | — |
| `MODEL_CACHE_DIR` | Yes | config.py:44 | Yes | Yes | `models/` dir is empty |
| `LOG_DIR` | Yes | config.py:45 | Yes | Yes | — |
| `MAX_FILE_SIZE_MB` | Yes | config.py:46 | N/A | Yes | — |
| `UPLOAD_RETENTION_DAYS` | Yes | config.py:49 | N/A | Yes | — |
| `OUTPUT_RETENTION_DAYS` | Yes | config.py:50 | N/A | Yes | — |
| `FACE_CONFIDENCE_THRESHOLD` | Yes | config.py:53 | Yes | Yes | — |
| `QUALITY_MIN_SCORE` | Yes | config.py:54 | Yes | Yes | — |
| `QUALITY_BLUR_THRESHOLD` | Yes | config.py:55 | Yes | Yes | — |
| `FACE_SIZE_WEIGHT_THRESHOLD` | Yes | config.py:56 | Yes | Yes | — |
| `REDIS_URL` | Yes | config.py:62 | Yes (connect check) | Yes | Redis may not be running; fallback exists |
| `CELERY_BROKER_URL` | Yes | config.py:65 | Yes | Yes | — |
| `CELERY_RESULT_BACKEND` | Yes | config.py:66 | Yes | Yes | — |
| `CELERY_WORKER_CONCURRENCY` | Yes | config.py:67 | Yes | Yes | — |
| `CELERY_WORKER_MAX_TASKS_PER_CHILD` | Yes | config.py:68 | Yes | Yes | — |
| `CELERY_TASK_TIME_LIMIT` | Yes | config.py:69 | Yes | Yes | — |
| `CELERY_TASK_SOFT_TIME_LIMIT` | Yes | config.py:70 | Yes | Yes | — |
| `FLOWER_PORT` | Yes | config.py:73 | Yes | Yes | — |
| `FLOWER_ENABLED` | Yes | config.py:74 | Yes | Yes | — |
| `GROQ_API_KEY` | **Yes** | config.py:82, copy_generator.py, groq_provider.py | **Disabled in code** | N/A (not used) | Key present but Groq integration is disabled; factory rejects groq_only mode |
| `GROQ_MODEL` | Yes | config.py:83 | N/A (unused) | N/A | — |
| `GROQ_SERVICE_TIER` | Yes | config.py:84 | N/A (unused) | N/A | — |
| `GROQ_TEMPERATURE` | Yes | config.py:85 | N/A (unused) | N/A | — |
| `MODEL_PATH` | Yes | .env line 71 | Not referenced in active code | N/A | Local path to Qwen PyTorch model; unused by active MLX path |
| `MLX_MODEL_ID` | Yes | config.py (via .env), mlx_config.py:42 | Yes | Yes | `mlx-community/Qwen2.5-0.5B-Instruct-4bit` |
| `MLX_MAX_TOKENS` | Yes | mlx_config.py:45 | Yes | Yes | — |
| `MLX_MAX_CONTEXT` | Yes | mlx_config.py:46 | Yes | Yes | — |
| `MLX_TIMEOUT_SECONDS` | Yes | mlx_config.py:48 | Yes | Yes | — |

### Variables in `.env.example` but NOT in `.env`

| Env var | Status | Notes |
|---------|--------|-------|
| `PYTHONPATH` | Missing | Commented out in .env.example |
| `BRAND_USE_LOGO_DETECTION` | Missing | Default `true` in config.py |
| `BRAND_USE_LLM_FALLBACK` | Missing | Default `true` in config.py |
| `SENTRY_DSN` | Missing | Optional error tracking |
| `CAPTION_PROVIDER_MODE` | Missing | Default `local_only` in factory.py |
| `CAPTION_USE_LOCAL` | Missing | Default `false` |
| `CAPTION_FORCE_LOCAL` | Missing | Default `false` |
| `CAPTION_LOCAL_MODEL` | Missing | Default `Qwen/Qwen2.5-1.5B-Instruct` |
| `CAPTION_ALLOW_GROQ_FALLBACK` | Missing | Default `true` |
| `CAPTION_HISTORICAL_DATA_PATH` | Missing | Default `data/historical` |
| `CAPTION_LOCAL_MODEL_PATH` | Missing | Default `""` |
| `CAPTION_MAX_NEW_TOKENS` | Missing | Default `256` |
| `CAPTION_TEMPERATURE` | Missing | Default `0.7` |
| `BLIP_MODEL_ID` | Missing | Default `Salesforce/blip-image-captioning-base` |
| `BLIP_MODEL_PATH` | Missing | Default `""` |
| `BLIP_LOCAL_FILES_ONLY` | Missing | Default `true` |
| `BLIP_MAX_IMAGE_SIDE` | Missing | Default `1024` |
| `BLIP_MAX_FILE_SIZE_MB` | Missing | Default `50` |
| `BLIP_MAX_PIXELS` | Missing | Default `40000000` |
| `BLIP_MAX_BATCH_IMAGES` | Missing | Default `20` |
| `MLX_MODEL_BITS` | Missing | Default `4` |
| `MLX_MODEL_PATH` | Missing | Default `None` |
| `MLX_MIN_AVAILABLE_GB` | Missing | Default `2.0` |
| `MLX_MAX_SWAP_PERCENT` | Missing | Default `50.0` |
| `MLX_MAX_MEMORY_PERCENT` | Missing | Default `85.0` |
| `FLOWER_USER` | Missing | Commented out |
| `FLOWER_PASSWORD` | Missing | Commented out |
| `DEVICE`, `TORCH_DTYPE` | Missing | Commented out |
| `LINKEDIN_*` (4 vars) | Missing | Optional publishing |
| `INSTAGRAM_*` (4 vars) | Missing | Optional publishing |

### Security notes

- The `.env.example` file contains a literal `GROQ_API_KEY` value on line 67. This is a security issue — `.env.example` should not contain real key values. **Do not modify** `.env` per audit rules, but this is flagged as a finding.
- No AWS, Stripe, SendGrid, Twilio, Google Maps, Cloudinary, or other cloud credentials are referenced anywhere in the active codebase.
- No OAuth flows are implemented beyond URL construction in `studio/publishing.py` (prepared boundary, not functional).

---

## Phase 4 — Safe Validation Checks Performed

The following read-only checks were performed (no model downloads, no inference, no external writes, no credential modification):

1. **SDK imports verified statically:** `fastapi`, `celery`, `redis`, `groq`, `torch`, `transformers`, `ultralytics`, `sentence-transformers`, `cv2`, `librosa`, `scenedetect`, `mlx-lm` (in `.venv-mlx`), `python-magic`, `structlog`, `apscheduler`, `flower`, `kombu`, `huggingface-hub`, `accelerate`, `pillow`, `numpy`, `scipy`, `scikit-learn`, `einops`, `timm`, `optree`, `ImageHash`, `pytest`, `httpx` — all present in `requirements.txt`.
2. **Configuration parsing:** `config.py` loads `.env` via `python-dotenv`; all `os.getenv` calls traced; defaults exist for every optional var.
3. **Endpoint configuration:** `api/main.py` routes enumerated (`/health`, `/api/model-status`, `/api/quality`, `/api/faces`, `/api/content`, `/api/highlights`, `/api/pipeline`, `/api/pipeline/async`, `/api/generate/*`, `/api/captions/regenerate`, `/api/gff/*`, `/api/studio/*`, `/api/photo-intelligence/*`, websockets).
4. **MLX worker script:** `scripts/mlx_worker.py` exists; `MLXConfig.validate()` checks worker python/script paths exist.
5. **Local service connectivity:** `api/main.py` health endpoint checks Redis via `r.ping()` with 1s timeout (non-failing).
6. **Database:** No database used — storage is local filesystem + Redis (optional) + in-memory APScheduler + JSON files (`studio/storage.py`).
7. **API authentication:** No read-only provider endpoint was called. Groq key is present but integration is disabled; no external network calls made.
8. **Mocked requests:** Unit tests exist in `tests/` using `unittest.mock.patch` (e.g. `test_captioning_provider.py` patches `os.environ`).

Checks NOT performed (per audit rules): no model downloads, no ML inference, no FastAPI startup, no Redis ping beyond code inspection, no external API calls, no publishing.

---

## Phase 5 — Local Testing Architecture (MacBook Air M2, 8GB RAM)

### Memory profile of local models

| Model | Approx. size | Simultaneously loadable? | Notes |
|-------|-------------|-------------------------|-------|
| MLX Qwen2.5-0.5B-4bit | ~0.5 GB | Yes (primary) | Confirmed working per user |
| CLIP ViT-B/32 | ~0.3–0.5 GB | Yes (with MLX, sequentially) | Loaded by multiple model classes |
| Florence-2-base | ~0.8–1.2 GB | Only one at a time | Used by ContentUnderstander |
| YOLOv11n-face | ~0.02 GB | Yes | Tiny |
| BLIP base | ~0.4–0.6 GB | Only one at a time | Photo intelligence only |

**Critical constraint:** Do not load Florence-2, CLIP, and BLIP simultaneously on 8GB RAM. The `ContentEngine` loads QualityAssessor (CLIP) + FaceDetector (YOLO) + ContentUnderstander (Florence-2 + CLIP) + VideoProcessor (CLIP) in `__init__`. This is already the designed behavior — models are lazy-loaded per-property, so they only load on first use.

### Safe sequential testing strategy

1. **MLX caption generation** (single model, ~0.5GB) — test first, lowest risk
2. **Image quality + face detection** (YOLO + CLIP) — load sequentially
3. **Content understanding** (Florence-2 + CLIP) — unload other models first if possible
4. **Video highlights** (ffmpeg + librosa + CLIP) — heaviest; test last
5. **BLIP photo intelligence** — test separately, unload other models

**No Docker.** Redis optional (APScheduler fallback). No simultaneous loading of multiple large models.

---

## Phase 6 — API Key Acquisition Checklist

### A. Essential for core local testing

**None.** No external API key is required for the core content-generation workflow. MLX local inference replaces Groq.

### B. Essential only for specific optional features

| Provider | Env var | Dashboard URL (official) | Free tier? | Credit card required? | Necessary for MVP local testing? | Steps to obtain |
|----------|---------|-------------------------|------------|----------------------|----------------------------------|-----------------|
| LinkedIn | `LINKEDIN_ACCESS_TOKEN` (+ CLIENT_ID, CLIENT_SECRET, ORGANIZATION_ID) | https://www.linkedin.com/developers/ | Yes (dev apps) | No | No | Create LinkedIn app → generate OAuth token → set env vars |
| Instagram (Meta) | `INSTAGRAM_ACCESS_TOKEN` (+ APP_ID, APP_SECRET, BUSINESS_ACCOUNT_ID) | https://developers.facebook.com/ | Yes (dev apps) | No | No | Create Meta app → Instagram Business account → generate token |
| Sentry | `SENTRY_DSN` | https://sentry.io/ | Yes (free tier) | No | No | Create Sentry project → copy DSN |

### C. Production-only

- Social publishing (LinkedIn, Instagram) — only needed when publishing to live social accounts.
- Sentry — only needed for production error tracking.
- Redis/Celery persistence — only needed for distributed async jobs; APScheduler suffices for local/dev.

### D. Not required — local alternative exists

| Instead of | Local alternative |
|------------|-------------------|
| Groq LLM API | MLX Qwen2.5-0.5B-4bit (local) |
| Paid image generation | None needed (app doesn't generate images) |
| Paid video generation | None needed (reel uses ffmpeg on local video) |
| Paid image understanding | Florence-2 + BLIP (local) |
| Paid embeddings/vector DB | CLIP + local file storage |
| Cloud object storage | Local filesystem (`uploads/`, `output/`) |

---

## Phase 7 — Findings

### Broken or unused integrations

1. **Groq API integration** — Key is configured in `.env`, but the integration is **disabled in code**:
   - `content_engine/captioning/factory.py:25-26` raises `CaptionProviderError("Groq is disabled...")` for `groq_only` mode.
   - `content_engine/copy_generator.py:473` sets `self._groq = None` always.
   - Status: **Configured but non-functional.** Do not rely on Groq for testing.

2. **`MODEL_PATH` env var** — Set in `.env` (line 71) to a local Qwen PyTorch path, but **not referenced in any active code file**. Only appears in legacy backup code (`content_engine.backup.1793532480/copy_generator.py:469`). Dead configuration.

3. **`data/historical/`** — Contains only `.gitkeep`. Caption retrieval will return empty results. Not blocking.

4. **`models/` directory** — Empty. ML model weights are downloaded on-demand from Hugging Face Hub (public models, no auth).

### Features blocked by missing credentials

| Feature | Blocking credential | Can work without? |
|---------|--------------------|-------------------|
| LinkedIn publishing | `LINKEDIN_ACCESS_TOKEN` | Yes — returns "not configured" status |
| Instagram publishing | `INSTAGRAM_ACCESS_TOKEN` + `INSTAGRAM_BUSINESS_ACCOUNT_ID` | Yes — returns "not configured" status |
| Sentry error tracking | `SENTRY_DSN` | Yes — optional, skipped if missing |
| Groq-based captions | `GROQ_API_KEY` | Yes — MLX is used instead (Groq disabled) |

### Features that work with zero external credentials

- Asset upload + validation (image/video)
- Quality assessment (blur, brightness, CLIP aesthetic)
- Face detection (YOLOv11n)
- Content understanding (Florence-2 + CLIP)
- Video highlight extraction (ffmpeg + librosa)
- Layout assembly (collage, carousel, stories, reel via ffmpeg)
- Caption generation (MLX Qwen2.5-0.5B-4bit)
- Case study generation
- Brand segregation (CLIP)
- Brand-aware copy (MLX)
- Studio project/draft/brand-profile management (local JSON storage)
- GFF brand-specific content pipeline

---

## Recommended Testing Order

1. **MLX health check** — `scripts/mlx_worker.py` + `content_engine/llm/mlx_client.py` health check (no generation, just worker spawn + model load check)
2. **API health endpoint** — `/health` (Redis status, APScheduler fallback)
3. **Package availability** — `api/main.py:569` `/api/model-status` (checks torch, transformers, ultralytics, groq, etc.)
4. **Image quality + face detection** — single image through `ContentEngine.process_asset`
5. **Content understanding** — single image through `ContentUnderstander.understand_image`
6. **MLX caption generation** — `CopyGenerator.generate_linkedin_caption` / `generate_instagram_caption`
7. **Full pipeline** — `ContentOrchestrator.run()` on a small asset batch
8. **Video highlights** — `VideoProcessor.extract_highlights_optimized` (test last, heaviest)

### Safe test commands (read-only, no billing, no publishing)

```bash
# 1. Check MLX config validates (no model load)
python -c "from content_engine.llm.mlx_config import MLXConfig; c = MLXConfig.from_env(); print(c.validate())"

# 2. Check API package status (imports only)
python -c "from api.main import app; print('app imported OK')"

# 3. Check which optional packages import
python -c "import groq; print('groq available')"  # groq SDK present but unused
python -c "import redis; print('redis available')"

# 4. List test files
ls tests/
```

---

## Phase 8 — Final Readiness Verdict

**Status: READY WITH MOCKED INTEGRATIONS**

The application can run complete local testing without obtaining any external API keys. Groq is disabled and replaced by MLX local inference. All ML models load from public Hugging Face Hub. Redis is optional with APScheduler fallback. Social publishing and Sentry are optional and degrade gracefully.

### Feature-by-feature readiness matrix

| Feature | Local MLX/Local model? | External credential needed? | Status |
|---------|----------------------|----------------------------|--------|
| Image upload & validation | Yes (filesystem) | No | ✅ Ready |
| Image quality assessment | Yes (OpenCV + CLIP) | No | ✅ Ready |
| Face detection | Yes (YOLOv11n) | No | ✅ Ready |
| Content understanding | Yes (Florence-2 + CLIP) | No | ✅ Ready |
| Video highlight extraction | Yes (ffmpeg + librosa + CLIP) | No | ✅ Ready |
| Layout assembly (collage/carousel/stories/reel) | Yes (Pillow + ffmpeg) | No | ✅ Ready |
| Caption generation (LinkedIn/IG/Reel/Stories) | Yes (MLX Qwen 0.5B-4bit) | No | ✅ Ready |
| Case study generation | Yes (template) | No | ✅ Ready |
| Brand segregation | Yes (CLIP) | No | ✅ Ready |
| Brand-aware copy | Yes (MLX) | No | ✅ Ready |
| Studio project/draft management | Yes (local JSON) | No | ✅ Ready |
| GFF brand pipeline | Yes (CLIP + MLX) | No | ✅ Ready |
| LinkedIn publishing | No | `LINKEDIN_ACCESS_TOKEN` | ❌ Blocked |
| Instagram publishing | No | `INSTAGRAM_ACCESS_TOKEN` | ❌ Blocked |
| Sentry error tracking | No | `SENTRY_DSN` | ⚠️ Optional |
| Groq-based captions | No (disabled) | `GROQ_API_KEY` | ⚠️ Disabled in code |

### Answers to the four key questions

1. **Can we test the complete content-generation workflow locally?**  
   **Yes.** The full pipeline (asset selection → layout → MLX captions → case study) runs entirely on local models with no external credentials.

2. **Which API keys do we actually need to obtain?**  
   **None for MVP local testing.** Only obtain LinkedIn/Instagram tokens if you need social publishing; Sentry DSN if you want error tracking.

3. **Which features can use MLX/local models instead of paid APIs?**  
   All caption generation (MLX Qwen), all image understanding (CLIP, Florence-2, YOLOv11n, BLIP), all layout/video assembly (Pillow, ffmpeg).

4. **Which features will remain blocked until external services are connected?**  
   LinkedIn publishing, Instagram publishing. Everything else works locally.

### Remaining risks

- **8GB RAM constraint:** Loading Florence-2 + CLIP + BLIP simultaneously may exceed memory. Test models sequentially.
- **MLX model weights not cached:** `mlx-community/Qwen2.5-0.5B-Instruct-4bit` must be downloaded once (~0.5GB) from Hugging Face Hub. No auth needed.
- **ffmpeg/libmagic system libs:** Must be installed (`brew install ffmpeg libmagic`) for video and upload validation.
- **Groq key in `.env.example`:** Security finding — `.env.example` contains a literal key value. Should be removed (outside audit scope to modify).
- **`data/historical/` empty:** Caption style retrieval returns no results; not blocking.

### Files created by this audit

- `docs/API_INTEGRATION_AUDIT.md` (this file)
- `docs/LOCAL_TESTING_READINESS.md`
- `docs/API_KEYS_CHECKLIST.md`

### Recommended next steps

1. Verify ffmpeg and libmagic are installed (`which ffmpeg`, `python -c "import magic"`).
2. Run MLX health check (worker spawn + model load check only — no generation).
3. Run the full pipeline on a small local asset batch to confirm end-to-end local testing.
4. If social publishing is needed later, obtain LinkedIn and Instagram access tokens and add them to `.env`.
5. Remove the literal `GROQ_API_KEY` value from `.env.example` (security hygiene).