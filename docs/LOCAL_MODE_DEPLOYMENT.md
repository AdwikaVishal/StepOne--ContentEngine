# Local Mode Deployment — Content & Design Engine

**Purpose:** Final production architecture for the Content & Design Engine.  
**All AI inference runs locally** on Apple Silicon using MLX, PyTorch/MPS, and Hugging Face Hub models.  
**No external API calls for AI inference.**

---

## Architecture

```
Local Mode Stack:
├── Text Generation   → MLX Qwen2.5-0.5B-Instruct-4bit (~0.5GB)
├── Image Understanding → Florence-2-base + CLIP ViT-B/32
├── Image Captioning   → BLIP (Salesforce/blip-image-captioning-base)
├── Face Detection     → YOLOv11n-face (AdamCodd/YOLOv11n-face-detection)
├── Quality Assessment → OpenCV + CLIP aesthetic
├── Brand Matching     → CLIP cosine similarity
├── Video Analysis     → ffmpeg + librosa + CLIP frame scoring
├── Reel Assembly      → ffmpeg concat/xfade
├── Layout Assembly    → Pillow smart crop
└── Storage            → Local filesystem (uploads/, output/, models/)
```

---

## Activation (Default)

```bash
AI_EXECUTION_MODE=local
```

This is the default — no explicit setting required. All other env vars are optional with sensible defaults.

---

## Memory Management (8GB RAM MacBook Air M2)

**Critical:** Do not load Florence-2, CLIP, and BLIP simultaneously.

### Safe Sequential Testing Strategy

1. **MLX caption generation** alone (~0.5GB) — test first, lowest risk
2. **Image quality + face detection** (YOLO + CLIP) — load sequentially
3. **Content understanding** (Florence-2 + CLIP) — unload other models first
4. **Video highlights** (ffmpeg + librosa + CLIP) — heaviest, test last
5. **BLIP photo intelligence** — test separately, unload other models first

### Model Sizes (Approximate)

| Model | Size | Simultaneously Loadable? |
|-------|------|--------------------------|
| MLX Qwen2.5-0.5B-4bit | ~0.5GB | Yes (primary model) |
| CLIP ViT-B/32 | ~0.4–0.5GB | Yes, but only one CV model at a time |
| Florence-2-base | ~0.8–1.2GB | Only one CV model at a time |
| BLIP base | ~0.4–0.6GB | Only one CV model at a time |
| YOLOv11n-face | ~0.02GB | Yes, tiny |

**Never load Florence-2, CLIP, and BLIP simultaneously.**

---

## System Dependencies

Install before running:

```bash
brew install ffmpeg libmagic
```

### Verify Installation

```bash
which ffmpeg
python3 -c "import magic; print('libmagic OK')"
```

---

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `AI_EXECUTION_MODE` | `local` | Must be `local` (default) or `cloud_testing` |
| `MLX_MODEL_ID` | `mlx-community/Qwen2.5-0.5B-Instruct-4bit` | MLX model repo ID |
| `MLX_MAX_TOKENS` | `64` | Max tokens per generation |
| `MLX_MAX_CONTEXT` | `2048` | Max context window |
| `MLX_TIMEOUT_SECONDS` | `180` | Worker request timeout |
| `REDIS_URL` | `redis://localhost:6379/0` | Optional; APScheduler fallback if unavailable |
| `GROQ_API_KEY` | `""` | Only used in `cloud_testing` mode |
| `GEMINI_API_KEY` | `""` | Only used in `cloud_testing` mode |

---

## Running the Application

```bash
# Start the API server
./start.sh

# Start the MLX worker (for local caption generation)
./start_worker.sh

# Start the dev server with auto-reload
./start_dev.sh
```

---

## Memory Guard Thresholds

| Variable | Default | Purpose |
|----------|---------|---------|
| `MLX_MIN_AVAILABLE_GB` | `2.0` | Minimum free RAM before model load |
| `MLX_MAX_SWAP_PERCENT` | `50.0` | Max swap pressure allowed |
| `MLX_MAX_MEMORY_PERCENT` | `85.0` | Max system memory pressure |

**Do not modify these thresholds.** They prevent OOM on 8GB systems.

---

## Testing

```bash
# Full regression suite (excluding MLX infrastructure test requiring psutil)
.venv311/bin/python -m pytest tests/ --ignore=tests/test_mlx_infrastructure.py

# Provider-specific tests
.venv311/bin/python -m pytest tests/test_ai_providers.py tests/test_dual_mode_integration.py -v

# Copy generator tests
.venv311/bin/python -m pytest tests/test_copy_generator.py tests/test_qwen_only.py -v
```

All tests are mocked — no real API calls, no local model inference during test execution.

---

## Production Deployment

1. Set `AI_EXECUTION_MODE=local` (default)
2. Ensure `MLX_MODEL_ID` points to the quantized Qwen model
3. Install system dependencies: `ffmpeg`, `libmagic`
4. Cache MLX model weights once (~0.5GB download from Hugging Face Hub, no auth required)
5. Start with `./start.sh`

No cloud API keys required for production operation.
