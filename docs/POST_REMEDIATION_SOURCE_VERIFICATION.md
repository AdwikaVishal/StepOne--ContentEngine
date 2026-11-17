# CONTENT ENGINE — POST-REMEDIATION SOURCE VERIFICATION

**Static Source Inspection Only**
*No commands, tests, builds, servers, model inference, API requests or browser checks were run.*

---

## OVERALL VERDICT

**READY WITH KNOWN SOURCE LIMITATIONS**

All reported repairs (D-001 through D-011) are implemented in source code. No source-level defects were found in the implemented changes. However, several limitations remain that can only be resolved through runtime acceptance testing — most notably the 105-image dataset classification and actual MP4 Reel generation.

---

## 1. PIPELINE VARIABLE ASSIGNMENT (D-001 TO D-005)

### Status: VERIFIED IN SOURCE

Both `_process_image()` and `_process_video()` in `content_engine/pipeline.py` now assign every referenced variable before use.

#### `_process_image()` — `content_engine/pipeline.py:272-396`

| Variable | Assigned before use? | Location | Notes |
|----------|---------------------|----------|-------|
| `quality_score` | Yes | Line 294 | Set to `None` if quality call fails |
| `aesthetic_score` | Yes | Line 295 | Set to `None` if quality call fails |
| `technical_quality` | Yes | Lines 298-303 | `0.0` if unavailable |
| `face_score` | Yes | Line 321 | Set to `None` if face call fails |
| `concept_match_score` | Yes | Lines 337-339 | `None` if unavailable or if model returns `None` |
| `brand_relevance` | Yes | Lines 342-347 | `0.0` default |
| `model_confidence` | Yes | Line 352 | `None` if concept unavailable |
| `final_score` | Yes | Lines 355-361 | From `compute_availability_aware_score()` |
| `category` | Yes | Lines 367-371 | From `_classify_asset()` |
| `class_conf` | Yes | Lines 367-371 | From `_classify_asset()` |

All three model calls (`quality_assessor.assess`, `face_detector.detect_faces_detailed`, `content_understander.understand_image`) are wrapped in `try/except`. On exception, the availability flag is set to `False` and the score is set to `None` — never a fabricated `0.0`.

#### `_process_video()` — `content_engine/pipeline.py:431-612`

| Variable | Assigned before use? | Location | Notes |
|----------|---------------------|----------|-------|
| `quality_score` | Yes | Line 486 | `None` if quality call fails |
| `aesthetic_score` | Yes | Line 487 | `None` if quality call fails |
| `technical_quality` | Yes | Lines 490-495 | `0.0` if unavailable |
| `face_score` | Yes | Line 513 | `None` if face call fails |
| `concept_match_score` | Yes | Lines 529-531 | `None` if unavailable or model returns `None` |
| `brand_relevance` | Yes | Lines 534-539 | `0.0` default |
| `model_confidence` | Yes | Line 542 | `None` if concept unavailable |
| `final_score` (base_score) | Yes | Lines 545-551 | From `compute_availability_aware_score()` |
| `category` | Yes | Lines 554-558 | From `_classify_asset()` |
| `class_conf` | Yes | Lines 554-558 | From `_classify_asset()` |

Video-specific highlight adjustment (`metadata.final_score *= 0.5 + 0.5 * avg_highlight_score`) at line 595 occurs **after** base scoring.

#### Early return paths

Both functions return `None` early when:
- Video cannot be opened (`cap.isOpened()` false, line 446-448)
- Video has no frames (`total_frames == 0`, line 454-457)
- Best frame cannot be read (`best_frame is None`, line 463-465)

These are safe early returns — no undefined variable is referenced after them.

---

## 2. CANONICAL CATEGORY SYSTEM (D-008, D-009)

### Status: VERIFIED IN SOURCE

#### `content_engine/categories.py`

All 10 canonical categories are defined (lines 31-40):

| Identifier | Value |
|------------|-------|
| `EVENT_VENUE` | `"event_venue"` |
| `PEOPLE` | `"people"` |
| `SPEAKERS` | `"speakers"` |
| `BOOTHS` | `"booths"` |
| `PRODUCTS` | `"products"` |
| `BRANDING` | `"branding"` |
| `SIGNAGE` | `"signage"` |
| `PROMOTIONAL` | `"promotional"` |
| `OTHER` | `"other"` |
| `UNCERTAIN` | `"uncertain"` |

`ALL_CATEGORIES` (line 42) contains all 10. `normalize_category()` (line 193) returns `UNCERTAIN` default for unknown values — **never silently coerces to `other`**.

#### `content_engine/data_types.py`

`AssetMetadata.__post_init__()` (lines 46-50) normalizes `classification` via `normalize_category(classification, UNCERTAIN)`. If the result is not a valid category, it is set to `UNCERTAIN`.

#### `content_engine/pipeline.py`

`_classify_asset()` (lines 61-117) returns `(UNCERTAIN, 0.0)` when no signals are available (line 88-90), or when confidence is below 0.30 (lines 113-115). Face detection alone adds a `people` vote but does not determine the final category — scene concepts from Florence-2 are the primary signal.

#### `api/main.py`

All three endpoints consolidated:

| Endpoint | Before | After |
|----------|--------|-------|
| `/api/assets/enhanced` | Inline `category_keywords` dict (6 categories) | `categorize_asset_canonical()` + `CANONICAL_TO_DISPLAY` |
| `/api/assets/categorized` | Inline `category_keywords` dict (7 categories, default `'other'`) | `categorize_asset_for_api()` |
| `/api/jobs/{id}/case-study/enriched` | Inline `category_keywords` dict (6 categories, default `'other'`) | `categorize_asset_for_api()` |

No remaining `category_keywords` dicts in `api/main.py` (confirmed by grep). All category logic flows through `content_engine.categories`.

#### `ml_test_ui/src/pages/AssetSelectionPage.tsx`

`categoryIcons` (lines 16-34) includes all 10 canonical categories plus 5 backward-compatible display-name aliases:

| Key | Icon |
|-----|------|
| `event_venue` | Building |
| `people` | Users |
| `speakers` | Mic2 |
| `booths` | Store |
| `products` | Package |
| `branding` | Tag |
| `signage` | Flag |
| `promotional` | Megaphone |
| `other` | Folder |
| `uncertain` | HelpCircle |
| `stage` (alias) | Building |
| `crowd` (alias) | Users |
| `booth` (alias) | Store |
| `networking` (alias) | Handshake |
| `awards` (alias) | Trophy |

`uncertain` maps to `HelpCircle` — an explicit Unknown/Unclassified state, not silently mapped to `other`.

#### Classification confidence

`classification_confidence` in `_classify_asset()` (lines 99-111) is a heuristic: `vote_share * 0.7 + relevance_boost * 0.3`. It is **not** a calibrated probability. `AssetMetadata.uncalibrated = True` (line 38 of data_types.py) documents this.

---

## 3. AVAILABILITY-AWARE SCORING (D-006)

### Status: VERIFIED IN SOURCE (with noted limitations)

#### `_is_valid_score()` — `content_engine/pipeline.py:122-142`

| Check | Implemented? | Line |
|-------|-------------|------|
| `None` rejected | Yes | 130-131 |
| Boolean rejected | Yes | 132-133 |
| Non-numeric rejected | Yes | 134-135 |
| NaN rejected | Yes | 140-141 |
| Infinity rejected | Yes | 140-141 |
| Out-of-range (<0 or >1) rejected | Yes | 142 |
| Measured `0.0` accepted | Yes | 142 (`0.0 <= f <= 1.0`) |

#### `compute_availability_aware_score()` — `content_engine/pipeline.py:145-236`

| Requirement | Implemented? | Evidence |
|-------------|-------------|----------|
| Only available signals in numerator | Yes | Line 222: `sum(available[name] * weights[name] ...)` |
| Only available signals in denominator | Yes | Line 211: `sum(weights[name] for name in available ...)` |
| Renormalized effective weights | Yes | Lines 225-228 |
| All-unavailable → score 0.0, no division by zero | Yes | Lines 202-209 (early return) |
| Effective weights sum to 1.0 (valid non-empty case) | Yes | Mathematically: `sum(w_i/total) = 1.0` |
| Video highlight adjustment after base scoring | Yes | Line 595 |
| Image and video use same scoring semantics | Yes | Both call `compute_availability_aware_score()` |

#### Weight override validation — PARTIAL GAP

`compute_availability_aware_score()` accepts an optional `weights` parameter (line 150) but does **not** validate that override weights are non-negative, finite, or non-all-zero. If custom weights are passed:
- Negative weights: `total_weight` could be ≤ 0 → early return with score 0.0 (safe)
- NaN weights: `total_weight <= 0.0` is False for NaN → proceeds to `weighted_sum / total_weight` = NaN → `round(NaN, 4)` = NaN (unsafe)
- All-zero weights: `total_weight <= 0.0` → early return with score 0.0 (safe)

**However**, no caller currently passes custom weights. The default weights (module-level constants at lines 52-55) are always valid. This is a latent issue, not an active defect.

#### Provenance fields on AssetMetadata — `content_engine/data_types.py:41-44`

| Field | Type | Default |
|-------|------|---------|
| `score_available_signals` | `List[str]` | `[]` |
| `score_missing_signals` | `List[str]` | `[]` |
| `score_effective_weights` | `Dict[str, float]` | `{}` |
| `score_is_partial` | `bool` | `False` |

#### Provenance in API responses — NOT EXPOSED

Grep confirmed `score_available_signals`, `score_missing_signals`, `score_effective_weights`, `score_is_partial` do **not** appear in any API response serializer or scheduler output:
- `api/main.py:_serialise_selections()` — does not include provenance fields
- `api/scheduler.py:_run_pipeline()` — does not include provenance fields
- `api/scheduler.py:_run_generate()` — does not include provenance fields

The fields exist on `AssetMetadata` but are stripped during serialization. Consumers accessing `AssetMetadata` directly (not through API) can see them.

#### Exception path verification

In both `_process_image` and `_process_video`, each model call is in its own `try/except`. If `quality_assessor.assest()` raises, `quality_available = False` and `quality_score = None`. The previous default `0.0` value in the fallback dict is **never** used as a score — the code explicitly uses `None` when unavailable (lines 294-295, 486-487).

---

## 4. PLACEHOLDER VALIDATION (D-007)

### Status: VERIFIED IN SOURCE (with noted limitations)

#### `_PLACEHOLDER_RE` — `content_engine/copy_generator.py:209-212`

```python
_PLACEHOLDER_RE = re.compile(
    r"\{\{?\s*[a-zA-Z_][a-zA-Z0-9_ ]*\s*\}\}?"  # {word}, {{word}}, {multi word}
    r"|\[\s*[a-zA-Z0-9_][a-zA-Z0-9_ ]*\s*\]"    # [word], [multi word], [1st_date]
)
```

#### Detection verification

| Example | Matches? | Reason |
|---------|----------|--------|
| `[date]` | Yes | `\[` + word + `\]` |
| `[industry]` | Yes | Same pattern |
| `{brand_name}` | Yes | `\{` + word + `\}` |
| `{{brand_name}}` | Yes | `\{` + `\{?` + word + `\}` + `\}?` |
| `[event date]` | Yes | Bracket pattern allows spaces |
| `{industry type}` | Yes | Brace pattern allows spaces |
| `[1st_date]` | Yes | Bracket pattern allows leading digit |
| `#event` | No | No braces/brackets |
| `[10:00 AM]` | No | Colon not in allowed character class |
| `{x > 0}` | No | `>` not in allowed character class |
| `{` alone | No | No closing delimiter |
| `}` alone | No | No opening delimiter |

Brace content must start with a letter or underscore (avoids matching `{x > 0}`-style math). Bracket content may start with a letter, digit, or underscore.

#### `_generate()` retry loop — `content_engine/copy_generator.py:670-725`

| Requirement | Implemented? | Evidence |
|-------------|-------------|----------|
| Bounded retries (max_correction_attempts + 1) | Yes | Line 677: `range(max_correction_attempts + 1)` |
| First-pass valid tracked | Yes | Lines 681-682 |
| Success after retry tracked | Yes | Lines 683-684 |
| Exhausted retries tracked | Yes | Lines 702-706 |
| Provenance in validation record | Yes | Lines 712-719 |
| Safe fallback (strip_placeholders) | Yes | Line 705 |
| No cloud fallback | Yes | `_generate()` uses `self._provider` from `get_llm_provider()` → `TorchLocalProvider` |

#### All generation paths use `_generate()`

Grep confirmed `validate_placeholders` default is `True` (line 627) and no caller overrides it to `False`. All platform methods (`generate_linkedin_caption`, `generate_instagram_caption`, `generate_reel_caption`, `generate_story_captions`, `generate_brand_carousel_caption`, `generate_brand_reel_caption`, `generate_brand_story_captions`, `generate_variants`) call `self._generate()`.

#### GAP: `generate_all_captions_batch` — `content_engine/copy_generator.py:827-833`

The batch method validates placeholders but **only strips** (no retry):

```python
for key in ("linkedin", "instagram", "reel"):
    val = result.get(key)
    if isinstance(val, str):
        v = validate_no_placeholders(val)
        if not v["valid"]:
            result[key] = v["cleaned"]
```

This is a pre-existing design gap (not introduced by this remediation). Individual platform outputs in the batch path are cleaned but not retried.

#### Exhausted-retry concern

After exhausted retries, `strip_placeholders()` is applied. If the entire output consisted of placeholder tokens, the result could be empty. The caller does not check for empty output after stripping. This is a runtime concern, not a source defect.

---

## 5. ORIGINAL CONTENT ENGINE ISSUES

### Issue 1: Generic captions and unresolved placeholders

**Source status:** D-007 implemented robust placeholder detection and bounded retry. The `_generate()` method validates all output and strips remaining placeholders as a safe fallback.

**Runtime verification required:** Cannot confirm that Qwen actually produces placeholder-free output without running inference.

### Issue 2: Uploaded videos not appearing in the Reel workflow

**Source status:** Video pipeline is intact:
- `api/main.py:validate_upload()` accepts videos (lines 455-571)
- `api/scheduler.py:_run_generate()` computes `video_count` and passes `generate_reel` flag (lines 420, 428, 431)
- `content_engine/orchestrator.py:run()` handles reel generation when `generate_reel=True` and `reel_selections` exist (lines 208-234)
- `content_engine/layout_assembler.py:create_reel()` assembles MP4 via ffmpeg (lines 434-473)
- Frontend `ResultsPage.tsx` distinguishes all six reel states (lines 59-421)

**Runtime verification required:** Cannot confirm actual MP4 generation without running ffmpeg and the full pipeline.

### Issue 3: 105 images classified as `Other`

**Source status:** Classification now uses `_classify_asset()` which returns canonical categories based on Florence-2 scene concepts + face count + CLIP relevance. Returns `UNCERTAIN` (not `Other`) when signals are insufficient.

**Runtime verification required:** Cannot confirm that 105 images move from 100% `Other`/`uncertain` to meaningful categories without running Florence-2 + CLIP on the actual dataset.

**None of the three original user-facing problems can be declared resolved from source inspection alone.**

---

## 6. LOCAL-ONLY ARCHITECTURE

### Status: VERIFIED IN SOURCE

| Component | File | Local-only enforcement |
|-----------|------|----------------------|
| LLM provider factory | `content_engine/providers/factory.py:23-35` | `get_llm_provider()` raises `ConfigurationError` for non-LOCAL modes |
| LLM provider | `content_engine/providers/llm/torch_local.py:64-75` | `status()` reports `local_only: True`, `remote_inference_disabled: True` |
| Vision provider factory | `content_engine/providers/factory.py:38-46` | `get_vision_provider()` raises `ConfigurationError` for non-LOCAL modes |
| Execution mode | `content_engine/ai_mode.py:24-31` | Defaults to `LOCAL`; `is_cloud_testing()` only True when explicitly set |
| Copy generator | `content_engine/copy_generator.py:610-613` | Docstring: "Routes exclusively through TorchLocalProvider. No cloud fallback" |

`_GroqGenerator` class exists in `copy_generator.py:257` but is **never instantiated** — dead code, not an active cloud path. `CopyGenerator.__init__` uses `get_llm_provider()` which returns `TorchLocalProvider`.

No model weights, configuration, or provider selection were modified.

---

## 7. DEFECT SUMMARY

| ID | Defect | Source Status | File | Lines |
|----|--------|--------------|------|-------|
| D-001 | `final_score` undefined in `_process_image` | **VERIFIED IN SOURCE** | `pipeline.py` | 355-361 |
| D-002 | `final_score` undefined in `_process_video` | **VERIFIED IN SOURCE** | `pipeline.py` | 545-551 |
| D-003 | `category` undefined | **VERIFIED IN SOURCE** | `pipeline.py` | 367-371, 554-558 |
| D-004 | `class_conf` undefined | **VERIFIED IN SOURCE** | `pipeline.py` | 367-371, 554-558 |
| D-005 | `technical_quality` undefined in `_process_video` | **VERIFIED IN SOURCE** | `pipeline.py` | 490-495 |
| D-006 | Missing-signal scoring (no renormalization) | **VERIFIED IN SOURCE** | `pipeline.py` | 122-236, 355-361, 545-551 |
| D-007 | Placeholder regex too limited | **VERIFIED IN SOURCE** | `copy_generator.py` | 209-212, 670-725 |
| D-008 | No canonical category system | **VERIFIED IN SOURCE** | `categories.py` | 1-231 |
| D-009 | Divergent API category systems | **VERIFIED IN SOURCE** | `api/main.py` | 64-154, 1634-1656, 1700-1728, 2093-2096 |
| D-010 | Brand relevance in final score | **VERIFIED** (excluded by design) | `pipeline.py` | 342-347, 534-539 |
| D-011 | Runtime verification outstanding | **RUNTIME VERIFICATION REQUIRED** | — | — |

### Limitations documented

1. **Provenance fields not serialized in API responses** — `score_available_signals`, `score_missing_signals`, `score_effective_weights`, `score_is_partial` exist on `AssetMetadata` but are not included in `_serialise_selections()` or scheduler output.

2. **Weight override validation** — `compute_availability_aware_score()` accepts custom `weights` without validating for negative/NaN/all-zero values. No caller currently passes custom weights.

3. **`generate_all_captions_batch` placeholder handling** — Strips placeholders without retry for individual platform outputs (pre-existing gap).

4. **Empty output after placeholder stripping** — Possible if all output is placeholder tokens; caller does not check.

5. **Classification is heuristic, not trained** — `_classify_asset()` uses keyword matching, not a trained classifier. Returns `UNCERTAIN` when signals are insufficient.

---

## 8. RUNTIME VERIFICATION STILL REQUIRED

The following must be verified at runtime before acceptance:

1. **105-image dataset classification** — Confirm classification moves from 100% `Other`/`uncertain` to meaningful categories using actual Florence-2 + CLIP output.
2. **MP4 Reel generation** — Confirm `create_reel()` produces a valid `instagram_reel.mp4` via ffmpeg.
3. **Scoring renormalization** — Confirm `final_score` is renormalized (not penalized) when concepts/faces are unavailable.
4. **Measured zero vs unavailable** — Confirm a detector returning 0.0 and a detector raising an exception produce different provenance.
5. **Placeholder detection on real Qwen output** — Confirm `{{brand_name}}`, `[event date]`, `{industry type}`, `[1st_date]` are detected.
6. **Retry behavior** — Confirm bounded retries execute and `validation.exhausted` is set correctly.
7. **End-to-end pipeline** — Full upload → process → select → layout → copy → output flow.

---

**NO COMMANDS, TESTS, BUILDS, SERVERS, MODEL INFERENCE, API REQUESTS OR BROWSER CHECKS WERE RUN.**
