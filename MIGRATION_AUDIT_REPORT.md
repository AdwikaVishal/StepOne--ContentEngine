# PHASE 1 AUDIT REPORT: PyTorch Qwen → MLX Migration

## 1. Existing Architecture Summary

### 1.1 Project Structure
```
/Users/admin/Downloads/contentfinal5 copy 2/
├── .venv311/           # Main FastAPI env (PyTorch 2.15, Transformers 4.57)
├── .venv-mlx/          # Isolated MLX env (MLX 0.32.4, MLX-LM 0.32.2)
├── .venv.retired/      # Rollback env (preserve)
├── .venv.py315/        # Unrelated (do not touch)
├── content_engine/
│   ├── copy_generator.py           # _LocalLLMGenerator + CopyGenerator (PyTorch Qwen)
│   ├── captioning/
│   │   ├── providers/
│   │   │   ├── local_provider.py   # LocalLLMProvider (PyTorch Qwen - SECOND impl)
│   │   │   ├── base.py             # CaptionProvider ABC
│   │   │   ├── template_provider.py
│   │   │   └── groq_provider.py    # Disabled by factory
│   │   ├── factory.py              # CaptionProviderFactory (Qwen-only policy)
│   │   └── schema.py
│   └── studio/
│       ├── content_orchestrator.py # StudioContentOrchestrator (VALIDATION CRITICAL)
│       ├── grounding.py            # unsupported_claim() - strict checks
│       └── facts.py
├── api/
│   ├── main.py         # FastAPI app (preloads VISION models only)
│   └── worker.py       # Celery worker (solo pool, preloads VISION models)
├── start.sh            # Main startup (uses .venv311)
├── start_worker.sh     # Celery worker startup
└── config.py           # Central config with env var mappings
```

### 1.2 Hardware & Memory
- **MacBook Air M2, 8 GB unified memory** (confirmed: 8589934592 bytes)
- **Current Qwen cache**: 4.4 GB at `~/.cache/huggingface/hub/models--Qwen--Qwen2.5-1.5B-Instruct/`
- **Vision models** (BLIP, CLIP, YOLOv11n, Florence-2, DINOv2) preloaded at startup
- **MLX env** has MLX 0.32.4, MLX-LM 0.32.2, MLX-Metal 0.32.4 + Transformers 5.22.1

---

## 2. All Qwen Loading Paths (Two Independent Implementations)

### Path A: `content_engine/copy_generator.py` → `_LocalLLMGenerator`
```python
class _LocalLLMGenerator:
    _MODEL_ID = "Qwen/Qwen2.5-1.5B-Instruct"
    
    def __init__(self):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        # Device: MPS (float16) or CPU (float32)
        # Loads tokenizer + model with local_files_only=True
        # Uses device_map="mps" or "cpu"
```
**Lazy init** via `CopyGenerator._get_qwen()` → caches in `self._llm`
**Generation** via `_generate_qwen()` → uses `tokenizer.apply_chat_template()` + `model.generate()`

**Public methods using this:**
- `generate_linkedin_caption()` - max_new_tokens=72
- `generate_instagram_caption()` - max_new_tokens=40
- `generate_reel_caption()` - max_new_tokens=80
- `generate_story_captions()` - max_new_tokens=max(32, num_slides * 32)
- `generate_brand_carousel_caption()` - max_new_tokens=180
- `generate_brand_reel_caption()` - max_new_tokens=120
- `generate_brand_story_captions()` - max_new_tokens=200
- `generate_variants()` - calls above + Groq variants (disabled)

### Path B: `content_engine/captioning/providers/local_provider.py` → `LocalLLMProvider`
```python
class LocalLLMProvider(CaptionProvider):
    DEFAULT_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"
    
    def load_model(self):
        from transformers import AutoTokenizer, AutoModelForCausalLM
        import torch
        # Loads with torch_dtype=torch.float32 (NOT float16!)
        # local_files_only=True
```
**Lazy init** via `load_model()` → caches in `self._model`, `self._tokenizer`
**Generation** via `_generate()` → manual chat template + `model.generate(temp=0.7, do_sample=True)`

**Public methods:**
- `generate_linkedin()` - max_new_tokens=200
- `generate_instagram()` - max_new_tokens=150
- `generate_reel()` - max_new_tokens=100
- `generate_stories()` - max_new_tokens=150
- `generate_youtube()` - max_new_tokens=150

---

## 3. Production Call Sites

| Call Site | Class Used | Method | Purpose |
|-----------|-----------|--------|---------|
| `StudioContentOrchestrator.generate_post()` | `CopyGenerator` | `generate_linkedin_caption`, `generate_instagram_caption`, `generate_story_captions` | Main Studio pipeline |
| `CaptionProviderFactory.get_provider()` → `LocalLLMProvider` | `LocalLLMProvider` | All `generate_*` | Captioning API (retrieval-augmented) |
| `api/tasks.py` (Celery tasks) | Via `ContentEngine`/`ContentOrchestrator` | Indirect | Async generation jobs |
| `scripts/test_qwen_inference.py` | Direct `_LocalLLMGenerator` | Smoke test | Manual verification |
| `tests/test_copy_generator.py` | `CopyGenerator` (mocked) | All methods | Unit tests |
| `tests/test_local_provider.py` | `LocalLLMProvider` (mocked) | All methods | Unit tests |
| `tests/test_studio.py` | `StudioContentOrchestrator` (mocked) | `generate_post` | Integration test |

---

## 4. Affected Tests

| Test File | Tests | Mocking Strategy |
|-----------|-------|------------------|
| `tests/test_copy_generator.py` | 8 tests | Mocks `_LocalLLMGenerator.generate()` via `gen._llm = MockQwen()` |
| `tests/test_local_provider.py` | 5 tests | Mocks `transformers` module entirely via `monkeypatch` |
| `tests/test_studio.py` | 1 test (`test_studio_content_orchestrator_with_mocked_qwen`) | Mocks `CopyGenerator._llm` |
| `tests/test_captioning_provider.py` | Unknown | Likely uses factory |
| `tests/test_qwen_only.py` | Unknown | Real model tests |

**Critical**: All tests mock the model - no real inference in CI. Must preserve mock compatibility.

---

## 5. Environment Configuration

### Current Env Vars (from `config.py`)
```bash
# Caption provider
CAPTION_PROVIDER_MODE=auto
CAPTION_USE_LOCAL=false
CAPTION_FORCE_LOCAL=false
CAPTION_LOCAL_MODEL=Qwen/Qwen2.5-1.5B-Instruct
CAPTION_LOCAL_MODEL_PATH=          # Optional local path override
CAPTION_MAX_NEW_TOKENS=256
CAPTION_TEMPERATURE=0.7
CAPTION_ALLOW_GROQ_FALLBACK=true   # But factory forces false

# BLIP (vision - keep unchanged)
BLIP_MODEL_ID=Salesforce/blip-image-captioning-base
BLIP_LOCAL_FILES_ONLY=true
```

### Required New MLX Env Vars (per migration prompt)
```bash
MLX_MODEL_ID=              # e.g., "mlx-community/Qwen2.5-0.5B-Instruct-4bit"
MLX_MODEL_PATH=            # Optional local path
MLX_MODEL_BITS=4           # Quantization
MLX_MAX_TOKENS=256         # Conservative default
MLX_MAX_CONTEXT=2048       # Conservative default
MLX_TEMPERATURE=0.0        # Deterministic for factual copy
MLX_TIMEOUT_SECONDS=60     # Worker timeout
```

---

## 6. MLX Isolation Strategy

### Current State
- `.venv311`: PyTorch 2.15, Transformers 4.57, FastAPI, Celery, Redis
- `.venv-mlx`: MLX 0.32.4, MLX-LM 0.32.2, MLX-Metal 0.32.4, Transformers 5.22.1

### Isolation Requirements
1. **Never install MLX in `.venv311`** - would upgrade Transformers and break app
2. **Never install PyTorch in `.venv-mlx`** - not needed, wastes memory
3. **Communication**: JSON-lines over subprocess pipes (simplest, no network)
4. **Worker process**: Single `scripts/mlx_worker.py` launched from `.venv-mlx`
5. **Binding**: If HTTP used, `127.0.0.1` only, dynamic port

### Recommended: JSON-lines Subprocess Protocol
```
FastAPI (.venv311)          MLX Worker (.venv-mlx)
     │                            │
     ├──── stdin: {id, prompt, ...} ──►
     │                            │
     ◄──── stdout: {id, text, tokens, duration, error?} ──┤
     │                            │
     └──── stderr: structured logs (mlx_*) ──► (captured by parent)
```

**Protocol**:
```json
// Request
{"id": "req-123", "system": "...", "user": "...", "max_tokens": 100, "temperature": 0.0, "timeout": 30}

// Response (success)
{"id": "req-123", "text": "...", "prompt_tokens": 45, "completion_tokens": 87, "duration_ms": 1200, "model": "Qwen2.5-0.5B-4bit"}

// Response (error)
{"id": "req-123", "error": "MODEL_UNAVAILABLE", "message": "..."}
```

---

## 7. Recommended Worker Architecture

### File Structure
```
content_engine/llm/
├── __init__.py
├── mlx_config.py       # Pydantic settings from MLX_* env vars
├── mlx_protocol.py     # Request/Response dataclasses + serialization
├── mlx_client.py       # MLXClient (used by CopyGenerator, LocalLLMProvider)
└── mlx_worker.py       # Entry point (runs in .venv-mlx)
```

### Worker Responsibilities (`mlx_worker.py`)
```python
def main():
    # 1. Parse MLX_* env vars
    # 2. Memory guard: check RAM/swap before loading
    # 3. Load MLX model ONCE (mlx_lm.load())
    # 4. Loop: read JSON line from stdin → generate → write JSON line to stdout
    # 5. Handle shutdown signal → cleanup
```

### Client Responsibilities (`mlx_client.py`)
```python
class MLXClient:
    def __init__(self):
        self._proc = None
        self._lock = threading.Lock()  # Serialize requests
    
    def _ensure_worker(self):
        if not self._proc or self._proc.poll() is not None:
            self._spawn_worker()  # subprocess.Popen with pipes
    
    def generate(self, system: str, user: str, max_tokens: int, temperature: float) -> InferenceResult:
        with self._lock:  # Single request at a time
            self._ensure_worker()
            # Send request, read response with timeout
            # Handle worker death, restart once
```

---

## 8. Memory-Safety Strategy (HIGHEST PRIORITY)

### Current Risk
- 8 GB unified memory
- Vision models preloaded (CLIP, YOLO, BLIP) ≈ 2-3 GB
- Qwen 1.5B PyTorch (float16 on MPS) ≈ 3-4 GB
- **Previous runs made Mac unresponsive**

### MLX Memory Plan
| Component | Estimate | Notes |
|-----------|----------|-------|
| macOS base | ~2 GB | System |
| Vision models | ~2.5 GB | CLIP, YOLO, BLIP (preloaded) |
| MLX 0.5B 4-bit | ~0.5 GB | Model weights |
| KV cache (2K ctx) | ~0.3 GB | 28 layers × 1536 hidden × 2 |
| Generation overhead | ~0.5 GB | Buffers, Metal |
| **Total** | **~5.8 GB** | **Leaves ~2 GB margin** |

### Guardrails (implement in `mlx_worker.py` startup)
```python
def check_memory_safety():
    import psutil
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    
    # Abort if:
    if mem.available < 2 * 1024**3:      # < 2 GB free
        raise MemoryError("Insufficient RAM")
    if swap.percent > 50:                  # Swap > 50% used
        raise MemoryError("High swap pressure")
    if mem.percent > 85:                   # System > 85% used
        raise MemoryError("Memory pressure too high")
```

### Inference Guards
- **Single model instance** - loaded once at worker start
- **Single request at a time** - `threading.Lock` in client
- **Max tokens**: 256 default (configurable via `MLX_MAX_TOKENS`)
- **Max context**: 2048 (configurable via `MLX_MAX_CONTEXT`)
- **Timeout**: 60s default (configurable via `MLX_TIMEOUT_SECONDS`)
- **No preload** at FastAPI startup - worker starts on first request
- **No auto-reload** - explicit restart only

---

## 9. Migration File Plan

### New Files (Phase 3)
| File | Purpose |
|------|---------|
| `content_engine/llm/__init__.py` | Package init |
| `content_engine/llm/mlx_config.py` | Settings from MLX_* env vars |
| `content_engine/llm/mlx_protocol.py` | Request/Response types + JSON codec |
| `content_engine/llm/mlx_client.py` | MLXClient for CopyGenerator + LocalLLMProvider |
| `scripts/mlx_worker.py` | Worker entry point (runs in .venv-mlx) |

### Modified Files (Phase 4-6)
| File | Changes |
|------|---------|
| `content_engine/copy_generator.py` | Replace `_LocalLLMGenerator` with `MLXClient` calls; keep `CopyGenerator` API identical |
| `content_engine/captioning/providers/local_provider.py` | Replace `load_model()`/`_generate()` with `MLXClient`; keep `CaptionProvider` interface |
| `content_engine/captioning/factory.py` | Update error messages to reference MLX backend; keep factory logic |
| `start.sh` | Add MLX worker startup (optional - lazy start preferred) |
| `config.py` | Add MLX_* settings class (optional, can use os.getenv directly) |

### Preserved Files (NO CHANGES)
- `content_engine/studio/content_orchestrator.py` - **VALIDATION LOGIC SACROSANCT**
- `content_engine/studio/grounding.py` - **UNSUPPORTED_CLAIM SACROSANCT**
- `content_engine/studio/facts.py` - Fact record building
- All vision models (`content_engine/models/`, `content_engine/photo_intelligence/`)
- `api/main.py`, `api/worker.py` - No MLX imports here

---

## 10. Risks & Rollback Strategy

### Risks
| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| MLX model conversion fails | Medium | High | Test conversion in Phase 3 before integration |
| 0.5B model quality insufficient | Medium | Medium | Have 1.5B 4-bit as fallback; keep Qwen cache |
| Worker subprocess crashes | Low | High | Client handles restart; log stderr |
| Memory still too high | Low | Critical | Memory guard aborts before load |
| Tests break due to interface changes | Medium | Medium | Preserve ALL public method signatures |

### Rollback Plan
1. **Backup**: `cp -r content_engine content_engine.backup.$(date +%s)`
2. **Git**: `git stash` or `git checkout` to pre-migration commit
3. **Envs**: `.venv311` and `.venv.retired` untouched
4. **Model cache**: 4.4 GB Qwen cache preserved at `~/.cache/huggingface/...`
5. **Rollback time**: < 5 minutes (git checkout + restart)

### Model Conversion Check (Pre-requisite)
```bash
# In .venv-mlx
python -c "
from mlx_lm import convert
convert('Qwen/Qwen2.5-1.5B-Instruct', 
        '/tmp/qwen-mlx', 
        quantization='4bit',
        dtype='float16')
"
# Verify load:
python -c "
from mlx_lm import load
model, tokenizer = load('/tmp/qwen-mlx')
print('Load OK')
"
```

### Recommended Target Model
| Model | Size | Quant | Est. RAM | MLX-LM Support | License |
|-------|------|-------|----------|----------------|---------|
| `mlx-community/Qwen2.5-0.5B-Instruct-4bit` | 0.5B | 4-bit | ~0.5 GB | ✅ Native | Apache 2.0 |
| `mlx-community/Qwen2.5-1.5B-Instruct-4bit` | 1.5B | 4-bit | ~1.2 GB | ✅ Native | Apache 2.0 |

**Recommendation**: Start with **0.5B 4-bit** for maximum safety margin. Upgrade to 1.5B only if quality insufficient AND memory allows.

---

## 11. Next Steps (Awaiting Approval)

**PHASE 2** - Backup & Configuration
1. Create migration backup
2. Add MLX_* env vars to `.env.example`
3. Create `content_engine/llm/mlx_config.py`

**PHASE 3** - Shared MLX Worker
1. Implement `mlx_protocol.py`, `mlx_client.py`, `mlx_worker.py`
2. Test model conversion & worker startup in isolation
3. Verify memory guard works

**PHASE 4** - CopyGenerator Migration
1. Replace `_LocalLLMGenerator` with `MLXClient` delegation
2. Preserve ALL public method signatures
3. Run `tests/test_copy_generator.py` (mocked)

**PHASE 5** - LocalLLMProvider Migration
1. Replace PyTorch load/generate with `MLXClient`
2. Preserve `CaptionProvider` interface
3. Run `tests/test_local_provider.py` (mocked)

**PHASE 6** - Factory & Startup Integration
1. Update factory error messages
2. Optional: integrate worker launch in `start.sh`
3. Run all regression tests

**PHASE 7-9** - Testing & Controlled Inference
- Only proceed to real inference after ALL mocked tests pass
- Explicit approval required before Phase 9

---

**Ready for Phase 2 approval.** The audit is complete. No source files modified.