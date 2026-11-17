# CONTENT ENGINE — SCORING AND PLACEHOLDER REMEDIATION REPORT

**Static Code Changes Only**
*No commands, tests, builds, servers, model inference, API requests or browser checks were run.*

---

## 1. ROOT CAUSE AND RESOLUTION — D-006 (MISSING-SIGNAL SCORE RENORMALIZATION)

### Root Cause

The original scoring formula in `content_engine/pipeline.py` was:

```python
final_score = (
    quality["quality_score"] * _WEIGHT_QUALITY
    + quality["aesthetic_score"] * _WEIGHT_AESTHETIC
    + face_score * _WEIGHT_FACES
    + concept_match_score * _WEIGHT_CONCEPTS
)
```

Weights: quality 0.30, aesthetic 0.20, faces 0.30, concepts 0.20 (sum = 1.0).

Two defects:

1. **Missing signals treated as zero, reducing the score.** When `concept_match_score` was `None` (cloud provider failure), it was coerced to `0.0`, which subtracted the full 20% concept weight from the score. An asset without detectable concepts was penalized as if it had been evaluated and found conceptually irrelevant.

2. **No distinction between measured zero and unavailable signal.** A face detector that ran successfully and found 0 faces (`weighted_score = 0.0`) and a face detector that failed entirely (exception) both produced `face_score = 0.0`. Both were treated identically, penalizing the asset by the full 30% face weight.

3. **No renormalization.** When one or more signals were unavailable, the remaining weights were not scaled up to sum to 1.0 over the available signals.

### Resolution

Added `compute_availability_aware_score()` in `content_engine/pipeline.py` (after `_classify_asset`, before `ContentEngine` class). The helper:

- Accepts optional signal values (`quality_score`, `aesthetic_score`, `face_score`, `concept_score`) and optional weight overrides.
- Uses `_is_valid_score()` to determine availability: a value is available only if it is a non-`None`, non-boolean, finite `int`/`float` in `[0, 1]`.
- Includes only available signals in the weighted sum.
- Renormalizes weights over available signals: `score = sum(value * weight) / sum(weight for available)`.
- A measured zero (e.g. `face_score = 0.0` from a working detector) is available evidence and contributes `0.0 * weight`.
- An unavailable signal (e.g. `concept_match_score = None`, or a model call that raised) is excluded entirely.
- Returns a dict with `score`, `available_signals`, `missing_signals`, `effective_weights`, and `is_partial`.

Both `_process_image` and `_process_video` were modified to:
- Wrap each model call (`quality_assessor.assess`, `face_detector.detect_faces_detailed`, `content_understander.understand_image`) in `try/except`. On failure, the signal is marked unavailable rather than crashing or substituting a fabricated zero.
- Call `compute_availability_aware_score()` to compute `final_score`.
- Store score provenance in `AssetMetadata` fields: `score_available_signals`, `score_missing_signals`, `score_effective_weights`, `score_is_partial`.
- Preserve the video-specific highlight adjustment: `metadata.final_score *= 0.5 + 0.5 * avg_highlight_score`, applied after the base score.

Brand relevance remains excluded from `final_score` (unchanged from prior design).

---

## 2. ROOT CAUSE AND RESOLUTION — D-007 (ROBUST PLACEHOLDER VALIDATION)

### Root Cause

The original regex in `content_engine/copy_generator.py`:

```python
_PLACEHOLDER_RE = re.compile(r"[\[{]\s*[a-zA-Z_][a-zA-Z0-9_]*\s*[\]}]")
```

Defects:

1. **Missed `{{brand_name}}`** — double braces. The first `{` is consumed by `[\[{]`, but the next char `{` does not match `[a-zA-Z_]`, so no match occurs. Unresolved `{{brand_name}}` in model output passes validation undetected.

2. **Missed multi-word placeholders** — `[event date]`, `{industry type}`. The pattern `[a-zA-Z_][a-zA-Z0-9_]*` does not allow spaces, so multi-word tokens fail.

3. **Missed digit-leading placeholders** — `[1st_date]`. The pattern starts with `[a-zA-Z_]`, excluding digits.

4. **No validation provenance** — the retry loop did not record whether validation passed on first attempt, after retry, or was exhausted.

### Resolution

Replaced `_PLACEHOLDER_RE` with:

```python
_PLACEHOLDER_RE = re.compile(
    r"\{\{?\s*[a-zA-Z_][a-zA-Z0-9_ ]*\s*\}\}?"  # {word}, {{word}}, {multi word}
    r"|\[\s*[a-zA-Z0-9_][a-zA-Z0-9_ ]*\s*\]"    # [word], [multi word], [1st_date]
)
```

Supported syntax:

| Pattern | Example | Matches? |
|---------|---------|----------|
| `[word]` | `[date]`, `[industry]` | Yes |
| `[multi word]` | `[event date]` | Yes |
| `[digit-leading]` | `[1st_date]` | Yes |
| `{word}` | `{brand_name}` | Yes |
| `{{word}}` | `{{brand_name}}` | Yes |
| `{multi word}` | `{industry type}` | Yes |
| Ordinary text | `#event`, `[10:00 AM]`, `{` alone | No |

Brace content must start with a letter or underscore (avoids matching `{x > 0}`-style math). Bracket content may start with a letter, digit, or underscore. Both allow internal spaces but exclude colons and other punctuation, reducing false positives on timestamps and ordinary prose.

The `_generate()` retry loop was enhanced to track and report validation provenance:

| Field | Meaning |
|-------|---------|
| `attempts` | Number of validation attempts made (1 = first pass, 2+ = retries) |
| `first_pass_valid` | True if the initial generation contained no placeholders |
| `succeeded_after_retry` | True if placeholders were cleared after at least one retry |
| `exhausted` | True if all `max_correction_attempts + 1` attempts failed |
| `valid` | True if the final output has no unresolved placeholders |
| `placeholders` | List of unresolved placeholder strings found (empty if valid) |
| `cleaned` | Placeholder-stripped version of the output |

Retry behavior (unchanged bounds, enhanced reporting):
- Up to `max_correction_attempts + 1` total attempts (default 3).
- On each failure, a correction message listing the unresolved placeholders is appended and the model is re-invoked.
- If all retries fail, `strip_placeholders()` is applied as a safe fallback — unresolved template tokens are removed from the returned content.
- The caller can distinguish first-pass valid, success-after-retry, and exhausted-retries via the validation record.

---

## 3. EXACT FILES AND FUNCTIONS MODIFIED

| File | Function / Symbol | Change | Defects |
|------|-------------------|--------|---------|
| `content_engine/data_types.py` | `AssetMetadata` | Added `score_available_signals`, `score_missing_signals`, `score_effective_weights`, `score_is_partial` fields | D-006 |
| `content_engine/pipeline.py` | `_is_valid_score()` | New helper — validates a score is finite, non-None, non-bool, in [0, 1] | D-006 |
| `content_engine/pipeline.py` | `compute_availability_aware_score()` | New helper — renormalizes weights over available signals, returns provenance | D-006 |
| `content_engine/pipeline.py` | `ContentEngine._process_image()` | Wraps model calls in try/except; uses `compute_availability_aware_score`; stores provenance | D-006 |
| `content_engine/pipeline.py` | `ContentEngine._process_video()` | Same as `_process_image`; preserves highlight adjustment | D-006 |
| `content_engine/pipeline.py` | `_classify_asset()` | Uses `.get()` with defaults for robustness (defensive, no behavior change) | D-006 |
| `content_engine/copy_generator.py` | `_PLACEHOLDER_RE` | Replaced limited regex with robust pattern supporting `{{}}`, multi-word, digit-leading | D-007 |
| `content_engine/copy_generator.py` | `detect_placeholders()` | Unchanged logic, new regex | D-007 |
| `content_engine/copy_generator.py` | `strip_placeholders()` | Unchanged logic, new regex | D-007 |
| `content_engine/copy_generator.py` | `validate_no_placeholders()` | Unchanged return shape, new regex | D-007 |
| `content_engine/copy_generator.py` | `CopyGenerator._generate()` | Tracks `validation_attempts`, `first_pass_valid`, `succeeded_after_retry`, `exhausted`; includes in `validation` record passed to `_record_metadata` | D-007 |

---

## 4. BEFORE-AND-AFTER SCORING EXAMPLES

Weights: quality 0.30, aesthetic 0.20, faces 0.30, concepts 0.20.

### All signals available

| Signal | Value |
|--------|-------|
| quality | 0.80 |
| aesthetic | 0.70 |
| faces | 0.60 |
| concepts | 0.90 |

**Before:** `0.80×0.30 + 0.70×0.20 + 0.60×0.30 + 0.90×0.20 = 0.74`  
**After:** same — all signals available, no renormalization needed. Score = **0.74**.  
Provenance: `available_signals = [quality, aesthetic, faces, concepts]`, `missing_signals = []`, `is_partial = False`.

### Faces unavailable (concept matcher failed / never ran)

| Signal | Value |
|--------|-------|
| quality | 0.80 |
| aesthetic | 0.70 |
| faces | None (unavailable) |
| concepts | 0.90 |

**Before:** `0.80×0.30 + 0.70×0.20 + 0.0×0.30 + 0.90×0.20 = 0.56` (faces treated as 0, penalized by 0.18)  
**After:** available = {quality: 0.80, aesthetic: 0.70, concepts: 0.90}; total_weight = 0.30+0.20+0.20 = 0.70; score = `(0.80×0.30 + 0.70×0.20 + 0.90×0.20) / 0.70 = 0.50/0.70 = 0.7143`  
Provenance: `available_signals = [quality, aesthetic, concepts]`, `missing_signals = [faces]`, `effective_weights = {quality: 0.43, aesthetic: 0.29, faces: 0.0, concepts: 0.29}`, `is_partial = True`. Score = **0.7143**.

### Concepts unavailable (CLIP/Florence-2 returned None)

| Signal | Value |
|--------|-------|
| quality | 0.80 |
| aesthetic | 0.70 |
| faces | 0.60 |
| concepts | None (unavailable) |

**Before:** `0.80×0.30 + 0.70×0.20 + 0.60×0.30 + 0.0×0.20 = 0.58` (concepts treated as 0, penalized by 0.18)  
**After:** available = {quality: 0.80, aesthetic: 0.70, faces: 0.60}; total_weight = 0.30+0.20+0.30 = 0.80; score = `(0.80×0.30 + 0.70×0.20 + 0.60×0.30) / 0.80 = 0.52/0.80 = 0.65`  
Provenance: `available_signals = [quality, aesthetic, faces]`, `missing_signals = [concepts]`, `effective_weights = {quality: 0.38, aesthetic: 0.25, faces: 0.38, concepts: 0.0}`, `is_partial = True`. Score = **0.65**.

### Both faces and concepts unavailable

| Signal | Value |
|--------|-------|
| quality | 0.80 |
| aesthetic | 0.70 |
| faces | None (unavailable) |
| concepts | None (unavailable) |

**Before:** `0.80×0.30 + 0.70×0.20 + 0.0×0.30 + 0.0×0.20 = 0.38`  
**After:** available = {quality: 0.80, aesthetic: 0.70}; total_weight = 0.30+0.20 = 0.50; score = `(0.80×0.30 + 0.70×0.20) / 0.50 = 0.38/0.50 = 0.76`  
Provenance: `available_signals = [quality, aesthetic]`, `missing_signals = [faces, concepts]`, `effective_weights = {quality: 0.60, aesthetic: 0.40, faces: 0.0, concepts: 0.0}`, `is_partial = True`. Score = **0.76**.

### Measured zero vs unavailable signal

| Scenario | face_score | concept_score | Before score | After score |
|----------|-----------|---------------|-------------|-------------|
| Detector ran, 0 faces found | 0.0 (measured) | 0.90 | `0.80×0.3 + 0.70×0.2 + 0.0×0.3 + 0.90×0.2 = 0.56` | `0.7143` (faces available, contributes 0) |
| Detector failed, faces unavailable | None (unavailable) | 0.90 | `0.56` (same — bug: treats failure as 0) | `0.7143` (faces missing, weight renormalized) |

The key difference: in the "detector failed" case, the **before** code incorrectly penalized the asset by 30% for a signal that was never measured. The **after** code excludes faces and renormalizes, producing a fairer score.

---

## 5. PLACEHOLDER SYNTAX SUPPORTED

| Example | Detected? | Notes |
|---------|-----------|-------|
| `[date]` | Yes | Single word in brackets |
| `[industry]` | Yes | Single word in brackets |
| `[event date]` | Yes | Multi-word in brackets |
| `[1st_date]` | Yes | Digit-leading + underscore |
| `{brand_name}` | Yes | Single identifier in braces |
| `{{brand_name}}` | Yes | Double-escaped braces |
| `{industry type}` | Yes | Multi-word in braces |
| `{product launch}` | Yes | Multi-word in braces |
| `#event` | No | Hashtag, no braces/brackets |
| `[10:00 AM]` | No | Colon not allowed in content |
| `{x > 0}` | No | Starts with letter but `>` not allowed; also no match due to `>` | Wait, `{x > 0}` — `\{\{?\s*` matches `{`, `[a-zA-Z_]` matches `x`, `[a-zA-Z0-9_ ]*` matches ` ` (stops at `>`), `\}\}?` needs `}` but sees `>` → no match. Correct. |
| `{` alone | No | No closing brace |
| `}` alone | No | No opening brace |

---

## 6. RETRY AND EXHAUSTED-RETRY BEHAVIOR

**Bounded retry (unchanged bounds, enhanced reporting):**

- `max_correction_attempts` defaults to 2, meaning up to 3 total attempts (1 initial + 2 corrections).
- On each failed validation, a correction message listing unresolved placeholders is appended to the prompt and the model is re-invoked.
- If the model returns empty output on a retry, the loop breaks early.
- If all attempts fail, `strip_placeholders()` removes remaining placeholder tokens as a safe fallback. The returned content contains no unresolved template tokens.
- The `validation` record in `GenerationMetadata` reports:
  - `first_pass_valid`: initial output was clean
  - `succeeded_after_retry`: output became clean after ≥1 retry
  - `exhausted`: all attempts failed, fallback applied
  - `attempts`: total number of validation attempts

**Caller responsibility:** The caller should check `validation.exhausted` and `validation.valid` to determine whether the output is trustworthy. If `exhausted` is True, the output was strip-cleaned and may be missing intended content.

---

## 7. REMAINING LIMITATIONS

1. **No multi-tag classification:** `AssetMetadata.classification` stores a single category. If multiple categories receive votes, only the top vote-getter is stored. Callers needing multi-tag analysis must re-inspect `scene_concepts` directly.

2. **Classification confidence is heuristic:** `classification_confidence` combines vote concentration and CLIP relevance boost. It is not a calibrated probability.

3. **Placeholder regex false positives:** Template-like syntax in ordinary prose (e.g. `{The event was great}`) may be flagged. This is an acceptable trade-off — over-detection is safer than under-detection for template tokens.

4. **Placeholder regex false negatives:** Placeholders with unsupported punctuation (e.g. `[10:00 AM]`, `[section 2.1]`) will not be detected. These contain colons/periods outside the allowed character class.

5. **Score provenance not serialized in all paths:** `score_available_signals` etc. are stored on `AssetMetadata` but may not appear in all API response serializers. Consumers should check the field directly on the metadata object.

6. **No brand relevance in final score:** Brand relevance remains a separated metric (`brand_relevance` field) and does not contribute to `final_score`. This is unchanged from the prior design.

---

## 8. LOCAL-ONLY INFERENCE PRESERVATION

Confirmed preserved:

- `content_engine/providers/factory.py`: `get_llm_provider()` rejects non-`LOCAL` modes with `ConfigurationError`. Only `TorchLocalProvider` (Qwen2.5-1.5B-Instruct) is returned.
- `content_engine/providers/llm/torch_local.py`: `TorchLocalProvider.generate()` routes through `get_torch_generator()` (local PyTorch/transformers). `requires_api_key = False`. `status()` reports `local_only: True`, `remote_inference_disabled: True`.
- `content_engine/ai_mode.py`: `AI_EXECUTION_MODE` defaults to `LOCAL`. `is_cloud_testing()` returns True only when explicitly set to `cloud_testing`.
- `content_engine/copy_generator.py`: `_generate()` docstring states "Routes exclusively through TorchLocalProvider (Qwen2.5-1.5B-Instruct, models/qwen/). No cloud fallback, no template substitution on failure." No cloud provider is imported or called.
- No changes were made to `provider factory`, `torch_local.py`, `ai_mode.py`, or any model configuration files.

---

## 9. RUNTIME VERIFICATION STILL REQUIRED

The following must be verified at runtime before acceptance:

1. **Scoring renormalization:** Execute `_process_image` and `_process_video` on real assets with missing concepts (e.g. `concept_match_score = None`) and confirm `final_score` is renormalized, not penalized.
2. **Measured zero vs unavailable:** Confirm a face detector returning 0.0 (no faces found) and a face detector raising an exception produce different provenance (`available_signals` vs `missing_signals`).
3. **Placeholder detection:** Run `detect_placeholders()` against real Qwen output containing `{{brand_name}}`, `[event date]`, `{industry type}`, `[1st_date]`.
4. **Retry behavior:** Simulate Qwen returning placeholder-containing output and confirm bounded retries execute and `validation.exhausted` is set correctly.
5. **Video pipeline:** Confirm video scoring works end-to-end with the highlight adjustment applied after availability-aware base scoring.
6. **105-image dataset:** Confirm classification moves from 100% `Other`/`uncertain` to meaningful categories.

---

**NO COMMANDS, TESTS, BUILDS, SERVERS, MODEL INFERENCE, API REQUESTS OR BROWSER CHECKS WERE RUN.**
