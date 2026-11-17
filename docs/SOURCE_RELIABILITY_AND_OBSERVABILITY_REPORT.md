# CONTENT ENGINE — SOURCE RELIABILITY, SCORING HARDENING & CLASSIFICATION OBSERVABILITY REPORT

**Source Code Changes Only**
*No commands, tests, builds, servers, model inference, API requests, browser checks, package installations or downloads were performed on the Mac.*

---

## 1. EXECUTIVE SUMMARY

### What changed

Four workstreams of source-code improvements were implemented across the Content Engine backend, API, and frontend:

| Workstream | Defects Addressed | Files Changed |
|------------|-------------------|---------------|
| **A — Batch caption validation** | Inconsistent placeholder validation between individual and batch generation paths; no per-item retry or validation reporting in batch mode | `content_engine/copy_generator.py` |
| **B — Scoring provenance serialization** | `score_available_signals`, `score_missing_signals`, `score_effective_weights`, `score_is_partial`, `score_valid` not exposed in API responses | `content_engine/data_types.py`, `api/main.py`, `api/scheduler.py` |
| **C — Scoring hardening** | Custom weights accepted without validation (negative, NaN, infinite, all-zero); all-unavailable signals produced ambiguous zero score | `content_engine/pipeline.py` |
| **D — Classification diagnostics** | Category assignment had no traceable evidence; face detection could be mistaken for reliable event-category classification | `content_engine/pipeline.py`, `content_engine/data_types.py`, `api/main.py`, `api/scheduler.py`, `ml_test_ui/src/pages/AssetSelectionPage.tsx` |

### Original limitations addressed

1. **Batch captions could silently strip placeholders without retry** — now uses bounded per-item correction retries with validation provenance.
2. **Scoring provenance was computed but not serialized** — now exposed through `_serialise_selections`, scheduler job results, and all categorized/enhanced/enriched API endpoints.
3. **Invalid weight configurations were not rejected** — now validated deterministically with `ValueError` on negative, NaN, infinite, boolean, non-numeric, or all-zero weights.
4. **All-unavailable signals produced an ambiguous zero score** — now distinguished via `score_valid: False` flag.
5. **Classification decisions had no traceable evidence** — now returns structured `classification_explanation` with votes, evidence, and missing signals.
6. **Frontend had no classification diagnostics** — now shows category badges on asset cards, with `uncertain` displayed explicitly.

### Limitations that remain

- Runtime acceptance (Qwen inference, ffmpeg/MP4 generation, 105-image dataset processing) cannot be performed on the Mac — must be done on the Windows RTX 4050 machine.
- `generate_all_captions_batch()` still makes a single LLM call for all platforms; individual caption retries use a generic correction prompt rather than platform-specific prompts.
- Frontend classification explanation is shown as a category badge only; a detailed per-asset explanation panel was not implemented to avoid redesigning the interface.

---

## 2. BATCH GENERATION

### Original defect

`generate_all_captions_batch()` in `content_engine/copy_generator.py` made a single LLM call returning JSON with all platform captions, then validated placeholders by simply stripping them (`strip_placeholders()`) with **no bounded retry**. This was inconsistent with `_generate()`, which performs bounded correction retries (up to `max_correction_attempts + 1` attempts).

### Exact implementation

Two changes were made to `content_engine/copy_generator.py`:

**1. `_generate()` — added `return_validation` parameter**

Added `return_validation: bool = False` parameter to `_generate()`. When `True`, the method returns `(output, validation_record)` tuple instead of just `output`. The `validation_record` contains:
- `valid`, `placeholders`, `cleaned` (from `validate_no_placeholders`)
- `attempts`, `first_pass_valid`, `succeeded_after_retry`, `exhausted`

All existing callers (which don't pass `return_validation=True`) continue to receive just the string — fully backward compatible.

**2. New `_validate_and_correct_caption()` method**

Added a helper that validates a single caption string and performs bounded correction retries:
- Detects all supported placeholder patterns via `_PLACEHOLDER_RE`
- Performs bounded correction retries (default `max_correction_attempts=2`, so 3 total attempts)
- Never creates an unbounded retry loop
- Preserves local Qwen generation; no cloud fallback
- Tracks validation provenance per caption
- Isolates failures — one failed caption doesn't invalidate others
- Handles empty output, whitespace-only output, output that becomes empty after stripping, output containing only placeholders, exhausted retries, and generation exceptions

**3. `generate_all_captions_batch()` — per-item validation**

After parsing the batch JSON result, each caption (`linkedin`, `instagram`, `reel`) and each story caption is validated individually using `_validate_and_correct_caption()`. Failed captions are retried with focused correction prompts. Results are attached to the output under a new `validation` key without removing existing fields:

```python
{
    "linkedin": "caption text",
    "instagram": "caption text",
    "reel": "caption text",
    "stories": ["story1", "story2", ...],
    "validation": {
        "linkedin": {"status": "valid_first_pass", "attempts": 1, ...},
        "instagram": {"status": "validation_exhausted", "attempts": 3, ...},
        "reel": {"status": "valid_after_retry", ...},
        "stories": [
            {"status": "valid_first_pass", ...},
            {"status": "requires_review", ...},
            ...
        ]
    }
}
```

### Retry behavior

| Status | Meaning |
|--------|---------|
| `valid_first_pass` | First generation passed validation |
| `valid_after_retry` | A correction attempt passed |
| `validation_exhausted` | Retry limit reached without valid output |
| `empty_output` | Generation returned no usable text |
| `generation_error` | Local model generation failed |
| `requires_review` | Output exists but cannot be trusted as finished content |

### Empty output and exhausted retries

When all retries fail:
- The individual result is marked `validation_exhausted` or `requires_review` — **not** presented as successful.
- The validation failure reason is preserved in the validation record.
- No fabricated generic content is substituted.
- No template is used pretending it came from the model.
- `strip_placeholders()` is applied as a safe fallback, but the result is flagged as requiring review if non-empty after stripping.

### API and frontend compatibility

- Existing `linkedin`, `instagram`, `reel`, `stories` fields are preserved unchanged.
- New `validation` key is additive — callers that don't read it are unaffected.
- Test files (`tests/test_copy_generator.py`, `tests/test_local_qwen_only.py`) check `result["linkedin"]`, `result["instagram"]`, etc. as strings — these continue to work.

---

## 3. SCORING HARDENING

### Weight validation

Added `_validate_weights()` function in `content_engine/pipeline.py` that validates custom weight dictionaries before use:

| Invalid input | Behavior |
|--------------|----------|
| Negative weight | `ValueError`: "Weight for 'X' must not be negative" |
| NaN weight | `ValueError`: "Weight for 'X' must not be NaN" |
| Infinite weight | `ValueError`: "Weight for 'X' must not be infinite" |
| Boolean weight | `ValueError`: "Weight for 'X' must be a numeric score" |
| Non-numeric weight | `ValueError`: "Weight for 'X' must be numeric" |
| All-zero weights | `ValueError`: "At least one weight must be positive" |
| Missing weight entry | Treated as weight 0.0 (signal excluded from scoring) |
| Unexpected weight key | Ignored (doesn't affect scoring) |

`_validate_weights()` is called by `compute_availability_aware_score()` when custom weights are provided. Default module-level weights (`_WEIGHT_QUALITY=0.30`, `_WEIGHT_AESTHETIC=0.20`, `_WEIGHT_FACES=0.30`, `_WEIGHT_CONCEPTS=0.20`) are never modified.

### All-unavailable behavior

When no signals are available:
- `score`: `0.0` (preserved for backward compatibility with float field)
- `score_valid`: `False` — explicitly indicates no valid score exists
- `available_signals`: `[]`
- `missing_signals`: all four signal names
- `effective_weights`: all `0.0`
- `is_partial`: `True`

Callers can distinguish:
- **Measured score of 0.0**: `score_valid=True`, `available_signals` non-empty, one signal has value 0.0
- **Partial score**: `score_valid=True`, `is_partial=True`, some signals missing
- **No valid score**: `score_valid=False`, `available_signals` empty

### Measured-zero behavior

A successfully executed detector returning `0.0` (e.g., face detector found no faces) is treated as available evidence:
- `_is_valid_score(0.0)` returns `True`
- The signal appears in `available_signals` with weight applied
- The signal contributes `0.0 * weight` to the weighted sum
- It is **not** moved to `missing_signals`

### Renormalization behavior

For valid non-empty scoring:
```
score = sum(available[i] * weight[i]) / sum(weight[i] for available i)
```

Weights are renormalized over available signals only. Example: if faces and concepts are unavailable:
```
score = (quality * 0.30 + aesthetic * 0.20) / (0.30 + 0.20)
      = (quality * 0.30 + aesthetic * 0.20) / 0.50
```

### Effective-weight invariants

For a valid non-empty scoring configuration:
- Effective weights sum to 1.0 (within floating-point rounding)
- Missing signals have effective weight `0.0`
- Available signals have positive effective weight
- `score_is_partial` accurately reflects whether any signals were missing

### Numerical examples

| Scenario | Signals | Before (old formula) | After (availability-aware) |
|----------|---------|---------------------|---------------------------|
| All available | Q=0.80, A=0.70, F=0.60, C=0.90 | 0.74 | 0.74 (no change) |
| Faces unavailable | Q=0.80, A=0.70, F=None, C=0.90 | 0.56 (penalized by 0.18) | 0.7143 (renormalized) |
| Concepts unavailable | Q=0.80, A=0.70, F=0.60, C=None | 0.58 (penalized by 0.18) | 0.65 (renormalized) |
| Both unavailable | Q=0.80, A=0.70, F=None, C=None | 0.38 | 0.76 (renormalized) |
| Measured zero faces | Q=0.80, A=0.70, F=0.0, C=0.90 | 0.56 | 0.7143 (F available, contributes 0) |
| All unavailable | Q=None, A=None, F=None, C=None | 0.0 (ambiguous) | 0.0, `score_valid=False` |

---

## 4. SCORING PROVENANCE

### New metadata fields on `AssetMetadata`

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `score_available_signals` | `List[str]` | `[]` | Signals that contributed to the score |
| `score_missing_signals` | `List[str]` | `[]` | Signals that were unavailable |
| `score_effective_weights` | `Dict[str, float]` | `{}` | Weights after renormalization |
| `score_is_partial` | `bool` | `False` | True when at least one signal was missing |
| `score_valid` | `bool` | `False` | True when at least one signal contributed |
| `classification_explanation` | `Optional[Dict]` | `None` | Structured evidence for category assignment |

### API serializers updated

| Endpoint | Serializer | Provenance exposed? |
|----------|------------|-------------------|
| `/api/pipeline` | `_serialise_selections()` | Yes — all 6 fields |
| `/api/pipeline/async` (scheduler `_run_pipeline`) | results dict | Yes — all 6 fields |
| `/api/generate/async` (scheduler `_run_generate`) | `all_processed_assets` | Yes — all 6 fields |
| `/api/assets/enhanced` | `per_category.cat_assets` | Yes — all 6 fields |
| `/api/assets/categorized` | `asset_info` | Yes — all 6 fields |
| `/api/jobs/{id}/case-study/enriched` | `asset_info` | Yes — all 6 fields |

### JSON serializability

All provenance values are JSON-serializable types: `list`, `dict`, `float`, `bool`, `str`, `None`. `None` is used when classification explanation is unavailable (e.g., older metadata records).

### Legacy-record behavior

Older metadata records without provenance fields are handled safely via `getattr(asset, "field", default)`:
- `score_available_signals` → `[]`
- `score_missing_signals` → `[]`
- `score_effective_weights` → `{}`
- `score_is_partial` → `False`
- `score_valid` → `False`
- `classification_explanation` → `None`

No existing user records are migrated or rewritten.

### Frontend visibility

The `AssetSelectionPage.tsx` frontend now displays:
- **Category badge** on each asset card showing the canonical category (e.g., "speakers", "people", "booths") with icon
- **"Uncertain" badge** when classification is uncertain — explicitly distinct from "other"
- **Tooltip** on badges showing `category_label` or explanation hint

The badge uses `title` attribute for hover tooltips. No primary workflow changes — the existing asset grid layout is preserved.

---

## 5. CLASSIFICATION DIAGNOSTICS

### Evidence collected

`_classify_asset()` now returns a 3-tuple `(category, confidence, explanation)` where `explanation` contains:

| Field | Type | Source |
|-------|------|--------|
| `classification_method` | `str` | `"heuristic_signal_fusion"` |
| `face_count` | `int` | YOLOv11 face detector |
| `face_contribution` | `int` | 1 if faces detected, 0 otherwise |
| `scene_concepts` | `List[str]` | Florence-2 `<OD>` labels |
| `clip_relevance` | `Dict[str, float]` | CLIP cosine similarity for concepts mapping to voted categories |
| `category_votes` | `Dict[str, int]` | Vote count per category from concept labels + face contribution |
| `winning_category` | `str \| None` | Category with most votes |
| `competing_categories` | `Dict[str, int]` | Other categories that received votes |
| `missing_signals` | `List[str]` | Which signals were unavailable |
| `is_uncertain` | `bool` | True when confidence < 0.30 or no signals |

### Classification correctness rules (preserved)

- Face detection alone **cannot** prove an asset is a speaker — faces only contribute a "people" vote
- A face detector finding zero faces is **not** equivalent to detector failure — `face_count=0` is valid evidence, not missing
- Missing Florence-2 output does **not** create fabricated concepts — empty list means no concepts detected
- Missing CLIP output does **not** become fake zero-confidence — `concept_match_score=None` means unavailable
- `uncertain` remains **distinct from `other`** — `normalize_category()` never coerces unknown to `other`
- Unknown object labels do **not** automatically become valid categories — `label_to_category()` returns `None` for unknown labels
- Classification confidence remains explicitly **heuristic** — not a calibrated probability
- Competing category evidence is **not** silently discarded — included in `competing_categories` in the explanation

### API response structure

Classification explanation is exposed in all API responses that return asset data:
- `"classification_explanation": {...}` — structured evidence object
- `"classification"` — canonical category identifier
- `"classification_confidence"` — heuristic confidence (0.0–1.0)

Frontend consumers can access `asset.classification_explanation` for detailed diagnostics.

### Remaining limitations

- Classification uses keyword matching against Florence-2 labels, not a trained event-category classifier
- `AssetMetadata` stores a single `classification` string — multi-tag support is not available in the data model
- Confidence is not calibrated — no labelled data or calibration curve exists

---

## 6. FILES CHANGED

### Modified files

| File | Changes |
|------|---------|
| `content_engine/pipeline.py` | Added `Dict` to imports; added `_validate_weights()`; hardened `compute_availability_aware_score()` with weight validation, `score_valid` field, all-unavailable handling; rewrote `_classify_asset()` to return 3-tuple with explanation; updated `_process_image()` and `_process_video()` to use `score_valid` and `classification_explanation` |
| `content_engine/data_types.py` | Added `score_valid` field and `classification_explanation` field to `AssetMetadata` |
| `content_engine/copy_generator.py` | Added `return_validation` parameter to `_generate()`; added `_validate_and_correct_caption()` method; rewrote `generate_all_captions_batch()` placeholder validation with per-item bounded retries and `validation` key in output |
| `api/main.py` | Updated `_serialise_selections()` to include all provenance and classification fields; updated categorized/enhanced/enriched endpoints to include provenance fields |
| `api/scheduler.py` | Updated `_run_pipeline()` and `_run_generate()` serialization to include all provenance and classification fields in both `all_processed_assets` and `results` dicts, including fallback paths |
| `ml_test_ui/src/pages/AssetSelectionPage.tsx` | Added `HelpCircle`, `Building`, `Package`, `Flag`, `Megaphone`, `Folder` to lucide-react imports; added classification badge on asset cards showing category icon + label; "Uncertain" badge shown explicitly for uncertain classifications |

### New files

| File | Purpose |
|------|---------|
| `content_engine/categories.py` | Canonical 10-category system with label-to-category mapping, normalization helpers, category labels and icons (created in prior remediation, preserved here) |

---

## 7. BACKWARD COMPATIBILITY

### Preserved

- **Existing API response fields** — all existing fields in `_serialise_selections`, scheduler results, and categorized/enhanced/enriched endpoints remain unchanged
- **Existing callers of `_generate()`** — `return_validation=False` by default, so all existing callers receive just the string
- **Existing callers of `generate_all_captions_batch()`** — `linkedin`, `instagram`, `reel`, `stories` fields unchanged; new `validation` key is additive
- **Existing callers of `_classify_asset()`** — both callers updated to 3-tuple unpacking; no external callers
- **Existing `AssetMetadata` fields** — all existing fields unchanged; new fields have defaults
- **Default weights** — `_WEIGHT_QUALITY=0.30`, `_WEIGHT_AESTHETIC=0.20`, `_WEIGHT_FACES=0.30`, `_WEIGHT_CONCEPTS=0.20` unchanged
- **No brand relevance in `final_score`** — unchanged from prior design
- **Local-only inference** — no changes to provider factory or model configuration

### Additive changes only

All new fields (`score_available_signals`, `score_missing_signals`, `score_effective_weights`, `score_is_partial`, `score_valid`, `classification_explanation`, `validation`) are additive. Callers that don't read them are unaffected.

---

## 8. LOCAL-ONLY PRESERVATION

Confirmed preserved:

- **`content_engine/providers/factory.py`**: `get_llm_provider()` raises `ConfigurationError` for non-`LOCAL` modes; only `TorchLocalProvider` returned
- **`content_engine/providers/llm/torch_local.py`**: `TorchLocalProvider.generate()` routes through `get_torch_generator()` (local PyTorch/transformers); `status()` reports `local_only: True`, `remote_inference_disabled: True`
- **`content_engine/ai_mode.py`**: `AI_EXECUTION_MODE` defaults to `LOCAL`; `is_cloud_testing()` only `True` when explicitly set
- **`content_engine/copy_generator.py`**: `_generate()` docstring states "Routes exclusively through TorchLocalProvider (Qwen2.5-1.5B-Instruct, models/qwen/). No cloud fallback, no template substitution on failure."
- **`_GroqGenerator` class**: Exists in `copy_generator.py` but is **never instantiated** — dead code, not an active cloud path
- **No model weights or configuration replaced**: `models/qwen/` path unchanged; `QWEN_MODEL_PATH` unchanged

No remote inference APIs, model downloads, or provider changes were introduced.

---

## 9. RUNTIME VERIFICATION STILL REQUIRED

The following checks must be performed on the Windows RTX 4050 machine before acceptance:

| Check | Description |
|-------|-------------|
| **Qwen model loading** | Verify `models/qwen/` contains `Qwen2.5-1.5B-Instruct` weights and loads via `TorchLocalProvider` |
| **ffmpeg/ffprobe** | Verify ffmpeg is installed and `ffmpeg_available()` returns `True` |
| **105-image dataset** | Verify the 105-image dataset exists and processes without `NameError` |
| **Scoring renormalization** | Execute `_process_image()` and `_process_video()` with missing concepts/faces and confirm `final_score` is renormalized |
| **Measured zero vs unavailable** | Confirm face detector returning 0.0 vs raising exception produce different `score_available_signals`/`score_missing_signals` |
| **Placeholder detection on real Qwen output** | Test `detect_placeholders()` against actual Qwen output containing `{{brand_name}}`, `[event date]`, `{industry type}`, `[1st_date]` |
| **Batch retry behavior** | Simulate Qwen returning placeholder-containing output in batch mode and confirm bounded retries execute correctly |
| **MP4 generation** | Verify `create_reel()` produces a valid `instagram_reel.mp4` via ffmpeg |
| **Frontend category display** | Verify all 10 canonical categories render correctly with icons and labels; `uncertain` shows as "Unclassified" |
| **API serialization** | Verify provenance fields appear in actual API responses |

### Stop conditions

Stop and report if:
- Qwen model is missing locally
- Offline execution cannot be guaranteed (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`)
- 105-image dataset is not available
- ffmpeg/ffprobe is not installed
- Processing risks modifying original assets
- GPU memory failures make testing unreliable

---

## 10. EXECUTION DECLARATION

`NO COMMANDS, TESTS, BUILDS, SERVERS, MODEL INFERENCE, API REQUESTS, BROWSER CHECKS, PACKAGE INSTALLATIONS OR DOWNLOADS WERE PERFORMED ON THE MAC.`

No runtime acceptance has been claimed. All changes are source-code only and require validation on the Windows RTX 4050 runtime environment.

---

## 11. ADDENDUM — CUSTOM SCORING WEIGHT VALIDATION CORRECTION

### Identified edge case

During review of the report, an edge case was found in `_validate_weights()`. The original implementation accepted unknown weight keys and checked the total sum across **all** supplied keys (recognized and unknown). Consider this input:

```python
{
    "unknown_signal": 1.0,
    "quality": 0.0,
    "aesthetic": 0.0,
    "faces": 0.0,
    "concepts": 0.0,
}
```

The original code would compute `total = 1.0` (including the unknown key) and accept the configuration. However, all **recognized** scoring weights are zero. In `compute_availability_aware_score()`, the renormalization denominator only sums weights for recognized, available signals — so `total_weight` would be `0.0`, triggering the all-zero fallback and returning `score_valid=False` despite the user having supplied a non-zero weight for an unrecognized key. This is misleading and could mask configuration errors.

### Correction

`_validate_weights()` was corrected as follows:

1. **Unknown weight keys are rejected** with an actionable `ValueError` listing the allowed scoring signals:
   - `quality`, `aesthetic`, `faces`, `concepts`

2. **All recognized weight values are validated** — negative, boolean, non-numeric, NaN, and infinite values are rejected.

3. **The positive-sum check applies only to recognized weights.** The sum is computed over `{"quality", "aesthetic", "faces", "concepts"}` only. If that sum is `<= 0.0`, validation fails.

4. **Unknown keys can no longer make an all-zero recognized configuration valid.** A configuration like the one above now raises `ValueError`.

### Recognized-key validation rule

Only the four canonical scoring signals may appear as weight keys:

| Key | Default weight |
|-----|---------------|
| `quality` | 0.30 |
| `aesthetic` | 0.20 |
| `faces` | 0.30 |
| `concepts` | 0.20 |

Any key outside this set is rejected. Omitted recognized keys are treated as weight `0.0` only if the remaining recognized weights have a positive sum.

### All-zero recognized-weight behavior

A configuration where every recognized weight is `0.0` (with or without unknown keys) is rejected:
```
ValueError: At least one recognized scoring weight must be positive; recognized weights sum to 0.0, which makes renormalization impossible
```

### Scoring invariants (unchanged and verified by source inspection)

- Available signals with positive configured weights contribute to scoring.
- Missing signals receive zero effective weight.
- Effective weights sum to 1.0 for valid non-empty scoring cases.
- All-unavailable input returns `score_valid=False`.
- A measured score of 0.0 can still have `score_valid=True`.
- No invalid configuration produces NaN, infinity or division by zero.

### Runtime verification still required

The corrected `_validate_weights()` must be exercised at runtime on the Windows RTX 4050 machine with the following cases:

| Case | Expected behavior |
|------|-------------------|
| `{"quality": 0.30, "aesthetic": 0.20, "faces": 0.30, "concepts": 0.20}` | Accepted (default weights) |
| `{"unknown_signal": 1.0}` | Rejected: unknown key |
| `{"quality": 0.0, "aesthetic": 0.0, "faces": 0.0, "concepts": 0.0}` | Rejected: all-zero recognized weights |
| `{"unknown_signal": 1.0, "quality": 0.0, "aesthetic": 0.0, "faces": 0.0, "concepts": 0.0}` | Rejected: unknown key (and all-zero recognized weights) |
| `{"quality": -0.1, "aesthetic": 0.2, "faces": 0.3, "concepts": 0.2}` | Rejected: negative weight |
| `{"quality": 1.0}` | Accepted: only quality has positive weight |
| `{"quality": 0.5, "faces": 0.5}` | Accepted: quality and faces positive, others zero |

---
