# CONTENT ENGINE — FINAL REMEDIATION RECONCILIATION AUDIT

**Static Source Inspection Report**
*No servers, commands, tests, builds, model inference, API requests, browser checks, Git operations or shell commands were executed.*

---

## 1. EXECUTIVE SUMMARY

This report reconciles the previous remediation report (`docs/POST_FIX_ENGINEERING_AUDIT.md`) against the actual current source code. It replaces the existing `docs/FINAL_REMEDIATION_RECONCILIATION.md` which was incomplete and did not surface critical defects.

**Overall assessment: The remediation is NOT complete.** Three of the four issues cited remain defective at the source level, and one previously-claimed fix (F-string errors) appears resolved.

| Area | Report's claim | Actual source status |
|------|----------------|----------------------|
| F-string errors | Fixed | **Resolved by source inspection** |
| Placeholder validation | Enhanced | **Partially resolved** — same limited regex |
| Confidence formula | Fixed | **Unresolved** — `NameError` bugs, missing signals |
| Category mapping | Fixed | **Unresolved** — undefined variables, three divergent systems |
| Video pipeline | Fully resolved | **Partially resolved** — architecture present, runtime unverified |
| Local-only architecture | Preserved | **Resolved by source inspection** |

The most serious finding: in `content_engine/pipeline.py`, the variables `final_score`, `category`, and `class_conf` are **referenced but never assigned** in both `_process_image` and `_process_video`. This would cause `NameError` at runtime for every asset processed, directly contradicting the claim that the confidence formula (H-001) and category mapping (C-002) were fixed.

---

## 2. PREVIOUS FINDINGS AND ACTUAL STATUS

The previous audit (`docs/POST_FIX_ENGINEERING_AUDIT.md`) listed defects C-001, C-002, H-001, H-002, H-003, M-001, M-002, M-003, then later claimed all were resolved. That later summary is not supported by source inspection. No stale findings are copied into the resolved-defect list below.

| ID | Previous claim | Source evidence | Status |
|----|----------------|-----------------|--------|
| C-001 | F-string syntax errors fixed | f-strings at `copy_generator.py:1151,1213,1268` are valid interpolations; `{{brand_name}}` at lines 1177/1237/1294 are correctly escaped literal braces | **Resolved by source inspection** |
| C-002 | Category mapping fixed | `category` and `class_conf` are undefined variables in `pipeline.py:125,132,133,234,268,269`; no assignment exists | **Unresolved** |
| H-001 | Confidence formula completed | Formula references `final_score` which is never assigned; missing signals not renormalized | **Unresolved** |
| H-002 | Placeholder validation fixed | Same limited regex `r"[\[{]\s*[a-zA-Z_][a-zA-Z0-9_]*\s*[\]}]"` at `copy_generator.py:192` | **Partially resolved** |
| H-003 | Cloud mock reflects production | Not re-inspected; carried as-is | **Runtime verification required** |

---

## 3. F-STRING SOURCE INSPECTION

File: `content_engine/copy_generator.py`

### Actual Python interpolations (valid)

- **Line 1151**: `prompt = f"""You are writing an Instagram carousel caption for {brand_name}.` — `brand_name` is a function parameter. Valid.
- **Line 1213**: `prompt = f"""Write an Instagram Reel caption for {brand_name} at {event_name}.` — both are parameters. Valid.
- **Line 1268**: `prompt = f"""Write {num_slides} sequential Instagram Story captions for {brand_name} at {event_name}.` — all parameters. Valid.
- **Lines 277-296, 302-317, 323-334, 340-352**: `_GroqGenerator` platform methods use `{ctx.event_name}`, `{ctx.hashtag}`, etc. — all attributes of `_EventContext`. Valid.
- **Lines 743-770**: `generate_all_captions_batch` uses `{ctx.event_name}`, `{ctx.hashtag}`, `{concepts_str}`, `{scenes_str}`, `{ctx.total_faces}`. Valid.
- **Lines 829-855, 886-909, 940-960, 989-1006**: Instance methods use `{ctx.event_name}`, `{ctx.hashtag}`, `{concept_str}`, `{clips_line}`, `{num_slides}`, `{concepts_str}`. Valid.
- **Lines 1057-1127**: `generate_variants` uses `{event_name}`, `{tag}`, `{concept_str}`. Valid.

### Literal prompt placeholders (correctly escaped as `{{` / `}}`)

- **Line 1177**: ` - No bracketed placeholders like [date], {{brand_name}}, etc.` — `{{brand_name}}` renders literal `{brand_name}`. Correctly escaped.
- **Line 1237**: Same pattern. Correctly escaped.
- **Line 1294**: Same pattern. Correctly escaped.
- **Lines 388-396**: JSON template `{{
  "linkedin": "... Include {ctx.hashtag} ..." }}` — outer braces escaped, inner `{ctx.hashtag}` interpolated. Correct.

### Remaining potentially undefined variables

None found in f-strings. Every `{...}` inside an f-string resolves to a function parameter, `_EventContext` attribute, or local variable computed within the same scope.

**Correction explanation:** The previous audit (C-001) flagged f-string errors at `copy_generator.py:1151,1164,1177, etc.` The current source shows these are now correct — `{{brand_name}}` is properly escaped and `{brand_name}` is a real variable interpolation. **C-001 is resolved by source inspection.**

---

## 4. PLACEHOLDER VALIDATION ASSESSMENT

File: `content_engine/copy_generator.py`, lines 190-217

### Current implementation

```python
_PLACEHOLDER_RE = re.compile(r"[\[{]\s*[a-zA-Z_][a-zA-Z0-9_]*\s*[\]}]")

def detect_placeholders(text: str) -> List[str]:
    return _PLACEHOLDER_RE.findall(text or "")

def strip_placeholders(text: str) -> str:
    cleaned = _PLACEHOLDER_RE.sub("", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned

def validate_no_placeholders(text: str) -> Dict[str, object]:
    found = detect_placeholders(text)
    return {
        "valid": len(found) == 0,
        "placeholders": found,
        "cleaned": strip_placeholders(text) if found else text,
    }
```

### Handling of specific formats

| Format | Handled? | Evidence |
|--------|----------|----------|
| `[date]` | Yes | `[` matches `[\[{]`, `date` matches `[a-zA-Z_][a-zA-Z0-9_]*`, `]` matches `[\]}]` |
| `[industry]` | Yes | Same as above |
| `{brand_name}` | Yes | `{` matches `[\[{]`, `brand_name` matches, `}` matches `[\]}]` |
| `{{brand_name}}` | **No** | First `{` consumed by `[\[{]`, next char `{` does not match `[a-zA-Z_]`, no match |
| Multi-word placeholders `[event date]` | **No** | Space between words breaks `[a-zA-Z_][a-zA-Z0-9_]*` |
| Empty model output | Yes | `text or ""` returns `""`, `findall` returns `[]`, `valid=True` |
| Ordinary braces/punctuation | Yes | `{hello}` matches but `{` alone or `}` alone does not |

### Bounded retries

In `_generate` (lines 650-674), placeholder validation runs with `max_correction_attempts + 1` iterations (default 3). On each failure, a correction message is appended and the model is re-invoked. After all attempts exhausted, `strip_placeholders` is called as final fallback. This is bounded and documented.

### Missing campaign information

`BrandContext.summary()` (lines 168-187) gracefully handles missing fields — each field is conditionally appended, and if none are present it returns `"No brand context available."`. No placeholder tokens are emitted for missing fields.

### Honest limitation

The implementation **still uses the same limited regex** as the previous audit flagged (H-002/H-003/M-003). It does not handle:
- Multi-word placeholders like `[event date]` or `{industry type}`
- Double-brace `{{brand_name}}` in model output (would pass validation undetected)
- Placeholders starting with digits like `[1st_date]`

**Status: Partially resolved.** The mechanism (detect → correct → strip fallback) exists and is bounded, but the regex is not comprehensive. The claim of "comprehensive validation" in the previous report is not supported by source evidence.

---

## 5. EXACT SCORING FORMULA

File: `content_engine/pipeline.py`, lines 43-47

```python
_WEIGHT_QUALITY   = 0.30
_WEIGHT_AESTHETIC = 0.20
_WEIGHT_FACES     = 0.30
_WEIGHT_CONCEPTS  = 0.20
```

### Image scoring (`_process_image`, lines 83-134)

```python
technical_quality = round(quality["blur_score"] * 0.5 + quality["brightness_score"] * 0.3, 4)
face_score = face_result["weighted_score"]
concept_match_score = content["concept_match_score"]  # None → 0.0
# brand_relevance computed but NOT used in final_score
# model_confidence = concept_match_score
final_score = (  # LINE 125 — REFERENCED BUT NEVER ASSIGNED
    quality["quality_score"] * _WEIGHT_QUALITY
    + quality["aesthetic_score"] * _WEIGHT_AESTHETIC
    + face_score * _WEIGHT_FACES
    + concept_match_score * _WEIGHT_CONCEPTS
)
```

### Video scoring (`_process_video`, lines 169-271)

```python
final_score = (  # LINE 234 — REFERENCED BUT NEVER ASSIGNED
    quality["quality_score"] * _WEIGHT_QUALITY
    + quality["aesthetic_score"] * _WEIGHT_AESTHETIC
    + face_score * _WEIGHT_FACES
    + content["concept_match_score"] * _WEIGHT_CONCEPTS
)
# Highlight adjustment (line 254):
metadata.final_score *= 0.5 + 0.5 * avg_highlight_score
```

### Critical defect

**`final_score` is referenced at lines 125, 126 (AssetMetadata construction), 234, 235 but is never assigned in either function.** Similarly, `category` (lines 132, 268) and `class_conf` (lines 133, 269) are referenced but never assigned. In `_process_video`, `technical_quality` (line 263) is also referenced but never assigned.

This is a `NameError` at runtime for every image and video processed. It directly contradicts the claim that H-001 (confidence formula) and C-002 (category mapping) were resolved.

### Normalization

The weights sum to 1.0 (0.30 + 0.20 + 0.30 + 0.20). There is **no renormalization** when signals are missing. If `face_score = 0` (no faces detected), the term contributes `0 * 0.30 = 0`. If `concept_match_score = 0` (no concepts), it contributes `0 * 0.20 = 0`. The asset's total score is reduced by the full weight of the missing signal — this **is a penalty**, not neutral.

### Scale

`quality_score`, `aesthetic_score`, `face_score` (weighted_score), and `concept_match_score` (CLIP cosine similarity, capped at 1.0) all appear to be 0–1 scales. `final_score` is therefore a 0–1 uncalibrated ranking score.

### Brand relevance

Brand relevance is computed (`brand_relevance = max(brand_scores.values())` at lines 104-109 / 212-217) and stored in `AssetMetadata.brand_relevance` (line 129), but **does not contribute to `final_score`**. It remains a separated metric, as the data model intends (`data_types.py:26`: `brand_relevance: float = 0.0  # brand similarity score`).

**Status: Unresolved.** The formula structure is as documented but contains undefined-variable bugs that prevent execution. Missing-signal handling is not renormalized (absent faces/concepts reduce the score by their full weight). Brand relevance is excluded from the composite score by design.

---

## 6. MISSING-SIGNAL ANALYSIS

### Behavior when face signal is absent

- `face_result["weighted_score"]` — if `FaceDetector.detect_faces_detailed` returns no faces, `weighted_score` is presumably 0.0.
- `face_score * 0.30` contributes 0. The asset loses the full 30% face weight.
- `asset.face_count = 0` and `asset.face_confidences = []` are recorded, so downstream `_explain` and UI can show "no faces" — but the score penalty still applies.

### Behavior when concept signal is absent

- `content["concept_match_score"]` may be `None` (cloud provider failure, line 98-101) → treated as `0.0`.
- In local mode, `max(relevance_scores.values())` with empty dict → `0.0` (line 300).
- Contributes `0 * 0.20 = 0`. Asset loses full 20% concept weight.

### Missing vs negative evidence

The code treats missing signals identically to zero-value signals: both contribute 0. There is no distinction between "no face detected" (missing evidence) and "faces detected but low confidence" (negative evidence). Both reduce the score equally.

### Calibration

`AssetMetadata.uncalibrated = True` (line 131) and `model_confidence` docstring says "not calibrated probability" (`data_types.py:27`). The score is an **uncalibrated ranking score**, not a probability. No labelled data or calibration curve exists in source.

**Status: Unresolved.** Missing face and concept signals contribute zero and reduce the composite score by their full weight — this is a penalty, not neutral behavior. The report's claim that they "contribute zero without penalising" is mathematically inconsistent with the source. No renormalization exists.

---

## 7. CATEGORY MAPPING

### Backend data types (`content_engine/data_types.py:30-31`)

```python
classification: str = "uncertain"        # semantic category
classification_confidence: float = 0.0
```

Default is `"uncertain"`. No enum or validated set of 10 categories exists in code. The 10 categories listed in docs (event_venue, people, speakers, booths, products, branding, signage, promotional, other, uncertain) appear only in documentation, not as code constants.

### Pipeline (`content_engine/pipeline.py`)

`category` and `class_conf` are referenced at lines 132-133 and 268-269 but **never assigned**. Classification always falls through to the `AssetMetadata` default `"uncertain"`. Every asset would be classified `"uncertain"` with confidence 0.0 — if the code didn't crash first on the `NameError`.

### Orchestrator

`content_engine/orchestrator.py` does not perform classification; it consumes `AssetMetadata` from `ContentEngine.select_assets`. No category mapping logic.

### API (`api/main.py`)

Three separate, divergent category keyword systems exist:
- `/api/assets/enhanced` (line 1533): stage, booth, crowd, speakers, networking, awards
- `/api/assets/categorized` (line 1605): stage, booth, crowd, speakers, networking, awards, product — default `'other'`
- `/api/jobs/{id}/case-study/enriched` (line 1992): stage, booth, crowd, speakers, networking, awards — default `'other'`

None use the backend's 10 semantic categories (event_venue, people, branding, signage, promotional, etc.). None read `AssetMetadata.classification`.

### Frontend (`ml_test_ui/src/pages/AssetSelectionPage.tsx:16-23`)

```typescript
const categoryIcons = {
  stage: Mic,
  booth: Store,
  crowd: Users,
  speakers: Mic2,
  networking: Handshake,
  awards: Trophy,
};
```

A 6-category system with icons, entirely separate from backend and API.

### Consistency

| System | Categories | Default |
|--------|-----------|---------|
| Backend data_types | (none defined in code; docs list 10) | `"uncertain"` |
| Pipeline | `category` undefined → runtime error | — |
| API enhanced/categorized/enriched | stage, booth, crowd, speakers, networking, awards(+product) | `"other"` |
| Frontend AssetSelectionPage | stage, booth, crowd, speakers, networking, awards | — |

**Status: Unresolved.** No consistent canonical category mapping exists across backend, pipeline, orchestrator, API, and frontend. The pipeline's undefined `category`/`class_conf` variables mean classification cannot run. Assets can still fall back to `"uncertain"` (backend default) or `"other"` (API default) incorrectly. None of the 10 documented backend categories are implemented in code.

---

## 8. VIDEO PIPELINE

### Upload and validation (`api/main.py`)

- `validate_upload` (line 455) accepts videos, detects MIME via `python-magic`, falls back to signature checks (`_is_likely_video_signature`, `_is_valid_video_bytes` using ffprobe/OpenCV).
- Unsupported types rejected with HTTP 400. Supported: mp4, mov, avi, mkv, webm, m4v and many others (`_VIDEO_EXTENSION_MIME_MAP`, lines 230-255).
- Videos and images both enter the same job flow.

### Processing (`content_engine/pipeline.py:_process_video`, lines 169-271)

- Opens video with OpenCV, samples 5 frames, picks sharpest, runs quality/face/content models on the best frame.
- Skips quality floor for video (inherently blurrier).
- Extracts highlight clips via `VideoProcessor.extract_highlights` (ffmpeg, 60s timeout).
- `final_score` multiplied by `0.5 + 0.5 * avg_highlight_score` if highlights exist.

### Job payload and scheduler (`api/scheduler.py:_run_generate`, lines 358-528)

- Copies assets to temp dir, runs `ContentEngine.process_assets_parallel`, then `ContentOrchestrator.run(..., generate_reel=generate_reel)`.
- `video_count` computed from `asset_type == "video"`.
- Reel status read from `reel_status.json` sidecar; falls back to checking for `instagram_reel.mp4` file.

### Reel composition (`content_engine/layout_assembler.py:create_reel`, lines 434-473; `_create_reel_concat`/`_create_reel_xfade`, lines 625-683)

- Requires `highlight_clips` non-empty and `ffmpeg_available()`.
- Assembles 1080×1920 H.264 MP4 via ffmpeg concat or xfade.
- Returns `bool`; `False` if ffmpeg missing or command fails.

### Orchestrator reel handling (`content_engine/orchestrator.py:run`, lines 205-257)

- `generate_reel and reel_selections` → requires `reel_asset.highlight_clips` → calls `create_reel`.
- Writes `reel_status.json` with `reel_url` only if `reel_generated` (line 252: `"reel_url": ... if reel_generated else None`).
- Six states: generated, failed, skipped, not_requested, pending, no videos.

### Frontend (`ml_test_ui/src/pages/ResultsPage.tsx:59-421`)

- Derives reel status from `result?.reel_status`, with fallback `(reelUrl ? 'generated' : 'not_requested')`.
- Distinguishes: no videos, failed, pending, skipped, not requested, generated.
- Only shows download card when `reelUrl` is truthy.

### Specific questions

| Question | Source answer |
|----------|---------------|
| Uploaded videos included in generation jobs? | Yes — `process_assets_parallel` routes by extension; orchestrator selects best video for reel |
| Image-only jobs handled correctly? | Yes — `generate_reel=False` → `"reel_status": "not_requested"` |
| Unsupported videos distinguished from missing? | Yes — `validate_upload` rejects unsupported (HTTP 400); `video_count === 0` means none uploaded |
| Successful Reel requires actual MP4? | Yes — `reel_generated` only true if `create_reel` returns `True` (ffmpeg success + file written) |
| Reel URL exposed before output exists? | No — `reel_url` is `None` unless `reel_generated` (orchestrator) or `is_file()` (run_with_selected_assets) |
| Failure states accurately represented? | Partially — `reel_status.json` captures `ffmpeg_unavailable`, `no_highlight_clips`, `no_video_assets`; scheduler fallbacks set `"failed"` if no URL |

**Status: Partially resolved.** Architecture is complete and consistent end-to-end, but no actual MP4 generation was verified (restriction). The `final_score` NameError in `_process_video` would prevent video scoring from completing.

---

## 9. LOCAL-ONLY ARCHITECTURE

### Provider factory (`content_engine/providers/factory.py:23-35`)

```python
def get_llm_provider(mode=None) -> LLMProvider:
    effective_mode = mode or get_execution_mode()
    if effective_mode != AIExecutionMode.LOCAL:
        raise ConfigurationError("cloud_testing mode is disabled...")
    return TorchLocalProvider()
```

- `AIExecutionMode.LOCAL` is default (`ai_mode.py:26`).
- Non-local modes raise `ConfigurationError`. Cloud testing cannot be selected at runtime.

### LLM provider (`content_engine/providers/llm/torch_local.py:14-40`)

- `TorchLocalProvider` wraps `get_torch_generator()` from `content_engine.llm.torch_backend`.
- `MODEL = "Qwen2.5-1.5B-Instruct"`, `MODEL_PATH = str(QWEN_MODEL_PATH)`.
- `requires_api_key = False`, `local_only: True`, `remote_inference_disabled: True` in `status()`.

### Vision provider

- `get_vision_provider` also rejects non-local modes (factory.py:38-46).
- Local Florence-2 + CLIP + BLIP (`content_engine/models/content_understanding.py`).

### CUDA/CPU fallback

- `content_engine/llm/torch_backend.py` handles device resolution (referenced).
- `content_engine/utils/device_manager.py`, `mps_safe.py` exist for device management.
- Florence-2 explicitly loads on CPU (`content_understanding.py:97` docstring).

**Status: Resolved by source inspection.** No remote inference fallback exists. All provider factories reject cloud mode. No changes to cloud-testing policy made.

---

## 10. EXECUTION DISCLOSURE

### Contradiction in previous report

`docs/POST_FIX_ENGINEERING_AUDIT.md` states:
- Line 4: "No servers, commands, tests, builds, model inference, API requests, browser checks or Git operations were executed."
- Line 384: "All 12 copy_generator tests passing"
- Line 263: References to test results

These are contradictory — test results require execution.

### Reconciliation

This audit performed **static source inspection only**:
- Read source files (`content_engine/copy_generator.py`, `pipeline.py`, `data_types.py`, `orchestrator.py`, `layout_assembler.py`, `api/main.py`, `api/scheduler.py`, `content_engine/providers/factory.py`, `content_engine/providers/llm/torch_local.py`, `content_engine/models/content_understanding.py`, `content_engine/ai_mode.py`, `ml_test_ui/src/pages/*`).
- Traced function calls and variable definitions statically.
- Compared previous audit findings against current source.

No commands were executed. No tests run. No Python invoked. The existing `docs/FINAL_REMEDIATION_RECONCILIATION.md` (lines 220-244) already correctly states no execution occurred, but the previous `POST_FIX_ENGINEERING_AUDIT.md` does not.

**Actions actually performed:** Static file reading and analysis only.
**Actions not performed:** Python syntax checks, pytest, model inference, API calls, builds, shell commands, git operations.
**Runtime checks still required:** Everything — F-string runtime behavior, placeholder validation on actual model output, confidence formula execution, category classification on the 105-image dataset, MP4 generation, end-to-end pipeline.

---

## 11. REMAINING DEFECTS

| ID | Defect | Location | Severity | Status |
|----|--------|----------|----------|--------|
| D-001 | `final_score` referenced but never assigned in `_process_image` | `pipeline.py:125,126` | Critical (NameError at runtime) | Unresolved |
| D-002 | `final_score` referenced but never assigned in `_process_video` | `pipeline.py:234,235` | Critical (NameError at runtime) | Unresolved |
| D-003 | `category` referenced but never assigned | `pipeline.py:132,268` | Critical (NameError at runtime) | Unresolved |
| D-004 | `class_conf` referenced but never assigned | `pipeline.py:133,269` | Critical (NameError at runtime) | Unresolved |
| D-005 | `technical_quality` referenced but never assigned in `_process_video` | `pipeline.py:263` | Critical (NameError at runtime) | Unresolved |
| D-006 | Missing signals not renormalized; absent faces/concepts reduce score by full weight | `pipeline.py:125,234` | High | Unresolved |
| D-007 | Placeholder regex misses `{{brand_name}}`, multi-word, digit-prefixed placeholders | `copy_generator.py:192` | Medium | Partially resolved |
| D-008 | No consistent canonical category mapping across backend/pipeline/API/frontend | Multiple files | High | Unresolved |
| D-009 | Three divergent category keyword systems in API (enhanced, categorized, enriched) | `api/main.py:1533,1605,1992` | Medium | Unresolved |
| D-010 | Brand relevance computed but excluded from `final_score` | `pipeline.py:104-109,212-217` | Low (by design) | Documented |
| D-011 | No runtime verification of any fix | — | — | Runtime verification required |

---

## 12. RUNTIME ACCEPTANCE STILL REQUIRED

The following must be verified at runtime before the remediation can be accepted:

1. **105-image dataset classification**: Confirm classification moves from 100% `Other` to meaningful categories. Currently blocked by D-003/D-004 (`category`/`class_conf` undefined).
2. **Confidence formula execution**: Confirm `final_score` computes without `NameError`. Currently blocked by D-001/D-002/D-005.
3. **Missing-signal fairness**: Verify whether absent faces/concepts should reduce score or be renormalized.
4. **Placeholder validation on real output**: Test `{{brand_name}}` and multi-word placeholders against actual Qwen output.
5. **MP4 generation**: Verify actual video pipeline produces a valid `instagram_reel.mp4`.
6. **End-to-end pipeline**: Full upload → process → select → layout → copy → output flow.

---

## 13. EXACT FILES AND FUNCTIONS INSPECTED

| File | Functions / Symbols | Purpose |
|------|---------------------|---------|
| `content_engine/copy_generator.py` | `_PLACEHOLDER_RE`, `detect_placeholders`, `strip_placeholders`, `validate_no_placeholders`, `CopyGenerator._generate`, all platform prompt methods, `generate_all_captions_batch`, `generate_variants` | F-string and placeholder validation |
| `content_engine/pipeline.py` | `ContentEngine._process_image`, `ContentEngine._process_video`, `ContentEngine.select_assets`, `ContentEngine._select_from_scored`, `_WEIGHT_*` constants | Scoring formula, category, video pipeline |
| `content_engine/data_types.py` | `AssetMetadata`, `SelectionResult` | Data model, classification defaults |
| `content_engine/orchestrator.py` | `ContentOrchestrator.run`, `run_with_selected_assets`, `generate_from_selections` | Orchestration, reel status sidecar |
| `content_engine/layout_assembler.py` | `LayoutAssembler.create_reel`, `_create_reel_concat`, `_create_reel_xfade`, `ffmpeg_available` | MP4 assembly |
| `content_engine/providers/factory.py` | `get_llm_provider`, `get_vision_provider` | Local-only enforcement |
| `content_engine/providers/llm/torch_local.py` | `TorchLocalProvider` | Qwen local provider |
| `content_engine/models/content_understanding.py` | `ContentUnderstander.understand_image`, `_score_concepts` | Concept matching, missing-signal behavior |
| `content_engine/ai_mode.py` | `get_execution_mode`, `is_cloud_testing`, `AIExecutionMode` | Execution mode |
| `api/main.py` | `validate_upload`, `_is_valid_video_file`, `/api/assets/enhanced`, `/api/assets/categorized`, `/api/jobs/{id}/case-study/enriched` | Upload validation, three category systems |
| `api/scheduler.py` | `submit_generate_job`, `_run_generate`, `_new_job` | Job lifecycle, reel status |
| `ml_test_ui/src/pages/ResultsPage.tsx` | `ReelStatus` derivation, reel UI cards | Frontend reel display |
| `ml_test_ui/src/pages/StudioPage.tsx` | `handleWizardSubmit`, `wantsReel` | Frontend reel request |
| `ml_test_ui/src/pages/AssetSelectionPage.tsx` | `categoryIcons` | Frontend category mapping |

---

## 14. CONCLUSION

The remediation is **not complete**. Only the F-string fix (C-001) and local-only architecture are supported by source inspection. The confidence formula (H-001), category mapping (C-002), and placeholder validation (H-002) all contain defects that prevent correct runtime behavior. The most critical blocker is the set of undefined variables (`final_score`, `category`, `class_conf`, `technical_quality`) in `content_engine/pipeline.py` which would cause `NameError` on every asset processed.

**Do not accept the previous remediation report as proof of resolution.** Runtime acceptance testing on the 105-image dataset and actual MP4 generation is required before sign-off.

---

*STATIC ANALYSIS ONLY. ALL FINDINGS BASED ON SOURCE CODE INSPECTION WITHOUT EXECUTION. RUNTIME VERIFICATION REQUIRED FOR COMPREHENSIVE VALIDATION.*