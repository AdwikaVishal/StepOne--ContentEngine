# Cloud Testing Mode — Content & Design Engine

**Purpose:** Temporary development workaround for 8GB RAM constraint on MacBook Air M2.  
**Final architecture:** Local inference (see `docs/LOCAL_MODE_DEPLOYMENT.md`).  
**Not a permanent cloud migration.**

---

## When to Use

Use `cloud_testing` mode **only** when developing on memory-constrained hardware (8GB RAM) where loading all local vision models simultaneously causes OOM. Do not use for production.

---

## Activation

Set in `.env` or environment:

```bash
AI_EXECUTION_MODE=cloud_testing
CLOUD_LLM_PROVIDER=groq
CLOUD_VISION_PROVIDER=gemini
GROQ_API_KEY=<your-groq-key>
GEMINI_API_KEY=<your-gemini-key>
```

**Default:** `AI_EXECUTION_MODE=local` — always falls back to local if not explicitly set to `cloud_testing`.

---

## What Cloud Mode Replaces (API → Local)

| Feature | Local Implementation | Cloud Testing Replacement |
|---------|---------------------|--------------------------|
| Text generation (captions) | MLX Qwen2.5-0.5B-4bit | Groq API (`llama-3.3-70b-versatile`) |
| Image understanding | Florence-2 `<OD>` + CLIP | Gemini multimodal `generateContent` |
| Image captioning | BLIP base | Gemini image captioning |
| Video analysis | CLIP frame scoring + librosa | **Deferred** — Gemini video support not verified against installed SDK |
| Brand matching (numerical) | CLIP cosine similarity | `MockBrandMatcher` (test data) |
| Brand matching (semantic) | Not available | `SemanticBrandMatcher` (Groq text) |
| Face detection | YOLOv11n-face | `MockFaceDetector` (test data) |
| Quality assessment | OpenCV + CLIP | `MockQualityAssessor` (test data) |

---

## What Stays Local in Both Modes

These features have no faithful cloud API equivalent for their specialized numerical outputs:

| Feature | Local Implementation | Cloud Mode Treatment |
|---------|---------------------|---------------------|
| Face detection (bboxes, weights) | YOLOv11n-face | `MockFaceDetector` — empty face data, `mock: true` |
| Quality assessment (blur, brightness, aesthetic) | OpenCV + CLIP | `MockQualityAssessor` — default scores, `mock: true` |
| Brand matching (CLIP cosine) | CLIP ViT-B/32 | `MockBrandMatcher` — mock scores, `mock: true` |
| Reel assembly | ffmpeg concat/xfade | Local ffmpeg (unchanged) |
| Layout assembly | Pillow smart crop | Local Pillow (unchanged) |
| Social Studio storage | Local JSON filesystem | Local JSON filesystem (unchanged) |
| Case study generation | Template markdown | Template (unchanged) |

---

## Semantic Differences (Important)

Cloud mode outputs are **not numerically equivalent** to local mode:

| Aspect | Local | Cloud Testing |
|--------|-------|---------------|
| Scene concepts | Florence-2 object detection labels | Gemini free-text description parsed into concept-like labels |
| Quality score | Laplacian blur + HSV brightness + CLIP aesthetic | Mock value (0.5), flagged `mock: true` |
| Face count/bboxes | YOLOv11n detection with size weighting | Mock data (0 faces), flagged `mock: true` |
| Brand similarity | CLIP cosine similarity (0–1) | Mock similarity, flagged `mock: true` |
| Caption text | MLX Qwen generation | Groq text completion |

**All mock numerical outputs carry explicit `mock: true` and `source: "mock_adapter"` fields.** They are never represented as actual model predictions.

---

## Gemini Video Workflow

`GeminiVisionProvider.understand_video()` implements:

1. **Upload:** `client.files.upload(file=local_path)`
2. **Wait:** Poll `client.files.get(name)` until `state == "ACTIVE"` (timeout: 120s)
3. **Generate:** `client.models.generate_content(model=..., contents=[file, prompt])`
4. **Cleanup:** `client.files.delete(name)` in `finally` block

Local filesystem paths are **never** passed as Gemini URIs.

---

## Fail-Closed Behavior

| Scenario | Result |
|----------|--------|
| `cloud_testing` + missing `GROQ_API_KEY` | `ConfigurationError` at provider init |
| `cloud_testing` + missing `GEMINI_API_KEY` | `ConfigurationError` for vision features |
| Cloud provider timeout | `ProviderTimeoutError` |
| Cloud provider rate limit | `ProviderRateLimitError` |
| Cloud provider failure | Error propagated, **no silent fallback** to local inference |

---

## Testing

All tests are mocked — no real API calls:

```bash
# Run provider tests
.venv311/bin/python -m pytest tests/test_ai_providers.py -v

# Run integration tests
.venv311/bin/python -m pytest tests/test_dual_mode_integration.py -v

# Run full regression suite
.venv311/bin/python -m pytest tests/ --ignore=tests/test_mlx_infrastructure.py
```

**Do not run actual cloud API calls during development.** Credentials are only needed if you explicitly opt into billable testing.

---

## Switching Back to Local

```bash
AI_EXECUTION_MODE=local
```

No code changes needed. Local models (MLX, CLIP, Florence-2, YOLOv11n, BLIP) are used as before.
