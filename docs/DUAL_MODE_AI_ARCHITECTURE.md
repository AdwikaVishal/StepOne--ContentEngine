# Dual-Mode AI Architecture — Content & Design Engine

**Project:** `/Users/admin/Downloads/contentfinal5 copy 2`  
**Final production architecture:** Local inference (MLX + CLIP + Florence-2 + YOLOv11n + BLIP)  
**Development workaround:** Cloud API testing mode (Groq + Gemini) for 8GB RAM constraint  
**Hardware:** MacBook Air M2, 8GB RAM

---

## Core Principle

`local` is the **final production architecture**. `cloud_testing` is strictly a **temporary development workaround** for the 8GB RAM limitation. Both modes return **identical application-level response schemas**. Local models are never removed.

---

## Execution Modes

| Mode | `AI_EXECUTION_MODE` | Text Generation | Image/Video Understanding | Local Models Loaded? |
|------|--------------------|-----------------|--------------------------|---------------------|
| Local (production) | `local` | MLX Qwen2.5-0.5B-4bit | Florence-2 + CLIP + BLIP | Yes (lazy, on demand) |
| Cloud testing | `cloud_testing` | Groq API | Gemini API | **No** — mock adapters for face/quality/brand |

---

## Provider Abstraction

### New Layer: `content_engine/providers/`

```
content_engine/providers/
├── __init__.py
├── base.py              # Abstract base classes: LLMProvider, VisionProvider
├── factory.py           # Mode-aware provider selection (no cross-mode caching)
├── llm/
│   ├── __init__.py
│   ├── mlx.py           # Wraps existing mlx_client.MLXClient (local only)
│   └── groq.py          # Groq SDK wrapper (cloud_testing only)
└── vision/
    ├── __init__.py
    ├── local.py         # Florence-2 + CLIP + BLIP (local only)
    ├── gemini.py        # google-genai multimodal wrapper (cloud_testing only)
    ├── caption.py       # Caption-focused adapter (routes BLIP↔Gemini)
    └── mock.py          # Mock face/quality/brand adapters (cloud_testing only)
```

### Base Interfaces

**`LLMProvider`** — `generate(system, user, max_tokens, temperature) → str`
- `MLXProvider` (local): wraps `mlx_client.MLXClient`, subprocess worker
- `GroqProvider` (cloud): `groq.Client.chat.completions.create`

**`VisionProvider`** — `understand_image(path) → Dict`, `caption_image(path) → str`
- `LocalVisionProvider` (local): Florence-2 `<OD>` + CLIP cosine + BLIP captioning
- `GeminiVisionProvider` (cloud): `google-genai` `generateContent` with file upload/process/wait/cleanup

**`CaptionVisionProvider`** — Thin adapter used by `StudioIntelligence`, routes BLIP (local) or Gemini (cloud) captioning.

---

## Model Loading Matrix

| Model | Local Mode | Cloud Testing Mode | Notes |
|-------|-----------|-------------------|-------|
| MLX Qwen2.5-0.5B-4bit | Loaded on caption gen | **Never loaded** | Groq replaces text generation |
| CLIP ViT-B/32 | Quality, content, brand matching | **Never loaded** | Mock adapter returns test data |
| Florence-2-base | Content understanding | **Never loaded** | Gemini replaces image understanding |
| YOLOv11n-face | Face detection, layout smart crop | **Never loaded** | Mock adapter returns empty face data |
| BLIP base | Photo intelligence captioning | **Never loaded** | Gemini replaces captioning |
| ffmpeg / Pillow | Video assembly, layout | Same (both modes) | Deterministic, non-AI |

---

## Provider Selection Logic

`content_engine/providers/factory.py` selects providers based on `AI_EXECUTION_MODE`:

1. `get_llm_provider()` → `MLXProvider` (local) or `GroqProvider` (cloud_testing)
2. `get_vision_provider()` → `LocalVisionProvider` (local) or `GeminiVisionProvider` (cloud_testing)
3. `get_caption_provider()` → delegates to `get_vision_provider()`

**Fail-closed:** Cloud mode raises `ConfigurationError` if `GROQ_API_KEY` or `GEMINI_API_KEY` is missing. No silent fallback to local inference.

**No cross-mode caching:** Providers are not cached across mode switches, preventing cache leakage.

---

## Integration Points

| File | Change | Mode-Aware Behavior |
|------|--------|-------------------|
| `config.py` | Added 5 env vars | `ai_execution_mode`, `cloud_llm_provider`, `cloud_vision_provider`, `gemini_api_key` (reuse `GROQ_API_KEY`) |
| `content_engine/ai_mode.py` | NEW | Mode detection + credential validation (fail-closed) |
| `content_engine/copy_generator.py` | Accepts `llm_provider` | Uses provider's `generate()` instead of direct MLX client |
| `content_engine/captioning/factory.py` | Routes through `ai_mode` | MLX (local) or Groq (cloud) via provider factory |
| `content_engine/models/content_understanding.py` | Accepts `vision_provider` | Local Florence-2+CLIP or Gemini vision |
| `content_engine/models/video_processing.py` | Accepts `vision_provider` | Local CLIP+ffmpeg or Gemini video analysis |
| `content_engine/pipeline.py` (`ContentEngine`) | Accepts optional providers | Cloud mode uses `MockQualityAssessor` + `MockFaceDetector` |
| `content_engine/studio/intelligence.py` | Routes via factory | BLIP (local) or Gemini captioning (cloud) |
| `content_engine/studio/content_orchestrator.py` | Provider-agnostic errors | No hard-coded "Qwen" in error messages |
| `content_engine/brand/brand_matcher.py` | Mock in cloud mode | CLIP numerical scoring (local) + `MockBrandMatcher` (cloud) + `SemanticBrandMatcher` (Groq, clearly distinguished) |
| `content_engine/gff/orchestrator_gff.py` | Provider-aware copy | Uses mode-selected providers for caption generation |

---

## Brand Matching Design (Corrected)

**CLIP numerical brand matching** stays local in both modes:
- Returns `similarity_scores: {brand_id: float}` and `confidence`
- Authoritative contract used by `BrandOrchestrator` and `GFFOrchestrator`

**Groq semantic brand description** (`SemanticBrandMatcher`, cloud_testing only):
- Returns free-text rationale, **not** cosine similarity scores
- Clearly distinguished from CLIP scores; never mixed into `similarity_scores`
- Never represented as CLIP-equivalent

**Mock brand matching** (`MockBrandMatcher`, cloud_testing only):
- Returns deterministic mock scores with `mock: true` and `source: "mock_adapter"`
- Used when brand matching numerical scores are needed but CLIP is not loaded

---

## Video Handling (Gemini)

**DEFERRED:** Gemini video understanding is not yet verified against the installed
`google-genai` SDK. `GeminiVisionProvider.understand_video()` raises an
`UnsupportedFeatureError` rather than calling untested SDK interfaces.

Local video processing (`VideoProcessor` with ffmpeg + librosa + CLIP frame
scoring) remains unchanged and available in both modes.

If the video workflow is verified against the SDK in the future, the deferred
implementation can be enabled by replacing the `UnsupportedFeatureError` with
the explicit upload/poll/generate/cleanup workflow.

Local filesystem paths are **never** passed as Gemini URIs.

---

## SDK Specification

- **Google Gen AI SDK:** `google-genai` (current official Python client), **not** `google.generativeai`
- Interface: `genai.Client(api_key=...)`, `client.models.generate_content(...)`, `client.files.upload/delete/get(...)`
- Lazy import inside provider modules — never imported at module top level in `local` mode

---

## Security

- No API keys in logs, exceptions, API responses, or frontend code
- `GROQ_API_KEY` reused from existing `.env`
- `GEMINI_API_KEY` added as proposed setting (not in `.env` without approval)
- No duplicate variables in `.env.example`
- `.env` not modified by this implementation

---

## Preservation Checklist

| Item | Status |
|------|--------|
| MLX not removed | ✅ |
| Existing local model implementations not removed | ✅ |
| `.venv311`, `.venv-mlx`, `.venv.retired` untouched | ✅ |
| Old Qwen checkpoints untouched | ✅ |
| Local models not permanently replaced | ✅ (cloud mode is opt-in via env var) |
| Memory guard thresholds unchanged | ✅ |
| No model downloads | ✅ |
| No unrelated application features changed | ✅ |
| `.env` not modified | ✅ |
| Local mode is default | ✅ |

---

## Test Files

- `tests/test_ai_providers.py` — 31 tests: mode detection, credentials, provider selection, import isolation, schema compatibility, mock adapters
- `tests/test_dual_mode_integration.py` — 18 tests: ContentEngine isolation, StudioIntelligence routing, VideoProcessor routing, BrandMatcher mock, mode switching, import isolation

All tests are mocked — no real API calls, no local model loading, no FastAPI startup.
