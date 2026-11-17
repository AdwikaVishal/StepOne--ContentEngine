# CONTENT ENGINE — RUNTIME ACCEPTANCE REPORT

**Status: BLOCKED at Phase 0 (Environment & Safety Preflight)**

*No model inference, no test execution, no server startup performed beyond read-only inspection.*

---

## 1. ENVIRONMENT AND HARDWARE DETAILS

| Item | Value |
|------|-------|
| Project root | `/Users/admin/StepOne--ContentEngine` |
| OS | macOS (darwin), Apple Silicon |
| Python | 3.15.0 (`/opt/homebrew/bin/python3`) |
| Node | v26.12.1 |
| npm | 11.20.0 |
| torch | 2.14.1 |
| transformers | 5.21.0 |
| cv2 | 5.0.0 |
| numpy | 2.5.4 |
| pytest | 9.1.1 |
| CUDA available | False |
| MPS available | True (Apple Silicon) |
| Disk free (project volume) | ~25 GiB (88% used) |
| .venv | None (system/homebrew Python) |
| .env file | None (config uses defaults) |
| redis-server | Running on `localhost:6379` |
| Backend/frontend servers | None running |
| ffmpeg / ffprobe | **Not installed** |

---

## 2. OFFLINE ENFORCEMENT

Not yet applied — no inference was attempted. Required env vars for when testing becomes possible:

```
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:HF_HUB_DISABLE_TELEMETRY = "1"
```

---

## 3. PHASE 0 PREFLIGHT FINDINGS

### BLOCKER 1 — Qwen model missing locally

- `QWEN_MODEL_PATH` defaults to `models/qwen/` (see `config.py:185`)
- `models/` directory contains only `yolov8/yolov8n.pt`
- **No Qwen model files exist anywhere in the project** (no `.bin`, `.safetensors`, `.pt`, `.gguf`)
- `scripts/download_qwen_real.py` exists but downloading is **forbidden** by the acceptance protocol
- Without the Qwen model, no local LLM inference, no caption generation, no placeholder-validation end-to-end test can run

### BLOCKER 2 — ffmpeg/ffprobe not installed

- `which ffmpeg ffprobe` → not found
- Video processing, highlight extraction, and MP4 Reel generation (`content_engine/layout_assembler.py`) require ffmpeg
- No Reel acceptance testing can run without ffmpeg

### BLOCKER 3 — No 105-image dataset on this machine

The original user-facing problem references a 105-image dataset, but no such dataset exists here:

| Directory | JPG count |
|-----------|-----------|
| `e2e_test_assets/` | 8 |
| `e2e_full_assets/` | 6 |
| `visual_acceptance/photos/` | 8 |
| `visual_acceptance/originals/` | 0 JPGs (directory exists but no `.jpg` files) |
| `real_photo_acceptance/originals/` | empty |
| `test_photos/` | 1 (`download.jpg`) |

Total discoverable images on this machine: ~23, none matching the described 105-image dataset.

### OBSERVATIONS (non-blocking)

| Item | Finding |
|------|---------|
| Git working tree | 5 modified files + 1 new file (`content_engine/categories.py`) + 1 backup (`content_engine/pipeline.py.backup`) |
| Modified files | `api/main.py`, `content_engine/copy_generator.py`, `content_engine/data_types.py`, `content_engine/pipeline.py`, `ml_test_ui/src/pages/AssetSelectionPage.tsx` |
| Test suite | `tests/` exists with 34 test files including `test_copy_generator.py`, `test_pipeline.py`, `test_qwen_only.py`, `test_local_qwen_only.py` |
| ML dependencies | torch, transformers, cv2, numpy, fastapi, PIL all import successfully |
| redis | Running on localhost:6379 (APScheduler/Celery backend available) |

---

## 4. STOP CONDITIONS TRIGGERED

Per the acceptance protocol, stop and report if:

- [x] **A required local model is missing.** → Qwen2.5-1.5B-Instruct not present at `models/qwen/`
- [x] **Offline execution cannot be guaranteed.** → Even with `HF_HUB_OFFLINE=1`, there is no model to load
- [x] **The 105-image inventory differs from the expected dataset.** → No 105-image dataset exists; largest set is 8 images
- [x] **Video processing cannot start.** → ffmpeg/ffprobe not installed

The system would attempt remote inference or model downloads only if a model path pointed elsewhere — it does not; `QWEN_MODEL_PATH` points to the missing local `models/qwen/`.

---

## 5. PRESERVATION CONFIRMATION

No files were modified, moved, deleted, or overwritten during preflight. Git working tree shows only the pre-existing remediation changes (5 modified source files, 1 new `content_engine/categories.py`, 1 `pipeline.py.backup`). No user assets, model weights, or generated outputs were touched.

---

## 6. ACCEPTANCE VERDICT

**BLOCKED** — Environment and safety preflight cannot be satisfied:

1. Qwen model is required for all content generation and placeholder-validation acceptance (Phase 4) and is missing locally. Downloading is forbidden.
2. ffmpeg is required for video/Reel acceptance (Phase 3) and is not installed.
3. The 105-image dataset required for asset-intelligence acceptance (Phase 2) does not exist on this machine; largest available set is 8 images.

### Required to unblock

| Blocker | Required action | Who |
|---------|----------------|-----|
| Qwen model | Place `Qwen2.5-1.5B-Instruct` weights at `models/qwen/` (offline copy, no download from this machine) | User / environment admin |
| ffmpeg | Install ffmpeg + ffprobe on this machine | User / environment admin |
| 105-image dataset | Provide the 105-image dataset directory | User / environment admin |

Once these are in place, runtime acceptance can proceed starting at Phase 0 (re-run preflight), then Phase 1 (unit tests), Phase 2 (105-image processing), Phase 3 (video/Reel), Phase 4 (Qwen generation), Phase 5 (frontend).

---

**NO COMMANDS, TESTS, BUILDS, SERVERS, MODEL INFERENCE, API REQUESTS OR BROWSER CHECKS WERE RUN BEYOND READ-ONLY INSPECTION.**
