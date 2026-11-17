# CONTENT ENGINE — CRITICAL PIPELINE REPAIR REPORT

**Static Code Changes Only**
*No commands, tests, builds, servers, model inference, API requests or browser checks were run.*

---

## 1. D-001 TO D-005 RESOLUTION DETAILS

All five defects were undefined-variable bugs in `content_engine/pipeline.py` that would cause `NameError` at runtime for every asset processed.

### D-001: Undefined `final_score` in `_process_image` (image processing)

**File:** `content_engine/pipeline.py`  
**Location:** `ContentEngine._process_image`, lines ~196, ~203

**Root cause:** `final_score` was referenced in the `AssetMetadata` constructor but never assigned.

**Fix:** Added computation before `AssetMetadata` construction:

```python
final_score = round(
    quality["quality_score"] * _WEIGHT_QUALITY
    + quality["aesthetic_score"] * _WEIGHT_AESTHETIC
    + face_score * _WEIGHT_FACES
    + concept_match_score * _WEIGHT_CONCEPTS,
    4,
)
```

Weights: quality 0.30, aesthetic 0.20, faces 0.30, concepts 0.20. Missing signals contribute 0 (no renormalization). Result is an uncalibrated 0–1 ranking score.

### D-002: Undefined `final_score` in `_process_video` (video processing)

**File:** `content_engine/pipeline.py`  
**Location:** `ContentEngine._process_video`, lines ~329, ~349

**Root cause:** `final_score` was referenced in `AssetMetadata` constructor and in highlight-score adjustment but never assigned. Also had an indentation bug where `brand_relevance` and `model_confidence` were accidentally indented 4 levels deep, which would cause `IndentationError`.

**Fix:** 
- Corrected indentation of `brand_relevance` and `model_confidence` blocks
- Added `final_score` computation using the same composite formula as images
- Added `technical_quality` computation (blur + brightness)
- Added `category` / `class_conf` computation via `_classify_asset`
- Preserved video-specific highlight scoring: `metadata.final_score *= 0.5 + 0.5 * avg_highlight_score`

### D-003: Undefined `category`

**File:** `content_engine/pipeline.py`  
**Location:** `ContentEngine._process_image` (line ~203) and `_process_video` (line ~363)

**Root cause:** `category` was referenced in `AssetMetadata` constructor but never assigned. Default was implicitly `"uncertain"` from `data_types.py` but the variable itself was undefined.

**Fix:** Added `_classify_asset()` call that returns `(category, class_conf)` tuple using genuine signals (face count, Florence-2 scene concepts, CLIP relevance scores). Returns `UNCERTAIN` when signals are insufficient.

### D-004: Undefined `class_conf`

**File:** `content_engine/pipeline.py`  
**Location:** Same as D-003

**Root cause:** `class_conf` was referenced but never assigned.

**Fix:** Returned as second element of `_classify_asset()` tuple. Confidence is computed from vote concentration (dominant category share) plus CLIP relevance boost. Returns 0.0 when no signals exist.

### D-005: Undefined `technical_quality` in `_process_video`

**File:** `content_engine/pipeline.py`  
**Location:** `ContentEngine._process_video`, line ~358

**Root cause:** `technical_quality` was assigned to `metadata.technical_quality` after `AssetMetadata` construction but was never computed.

**Fix:** Added computation before `AssetMetadata` construction:

```python
technical_quality = round(
    quality["blur_score"] * 0.5 + quality["brightness_score"] * 0.3, 4
)
```

Same formula as images: 50% blur + 30% brightness.

---

## 2. CANONICAL CATEGORY DEFINITION

**New file:** `content_engine/categories.py`

Defines the single source of truth for all 10 canonical event asset categories:

| Identifier | Label | Icon (frontend) |
|------------|-------|-----------------|
| `event_venue` | Event Venue | Building |
| `people` | People | Users |
| `speakers` | Speakers | Mic |
| `booths` | Booths | Store |
| `products` | Products | Package |
| `branding` | Branding | Tag |
| `signage` | Signage | Flag |
| `promotional` | Promotional | Megaphone |
| `other` | Other | Folder |
| `uncertain` | Unclassified | HelpCircle |

Key design decisions:

- **`other` vs `uncertain` distinction:** `other` = recognized asset that doesn't fit a specific category; `uncertain` = insufficient signal to classify. Never silently coerces `uncertain` → `other`.
- **Conservative label-to-category mapping:** Keywords are matched case-insensitively against Florence-2 object detection labels. Unknown labels return `None` (no vote) rather than forcing a category.
- **Vote-based classification:** Multiple labels can vote for categories; the category with the most votes wins. Confidence reflects vote concentration plus CLIP relevance boost.
- **`normalize_category()`:** Returns `UNCERTAIN` default for unknown values; never silently maps to `other`.
- **`data_types.py`:** `AssetMetadata.__post_init__` normalizes `classification` to a valid canonical identifier using `normalize_category()`.

---

## 3. CLASSIFICATION EVIDENCE AND LIMITATIONS

### Classification implementation (`content_engine/pipeline.py:_classify_asset`)

Signals used (all genuine, none invented):

| Signal | Source | Used for |
|--------|--------|----------|
| Face count > 0 | YOLOv11 `FaceDetector.detect_faces_detailed` | Adds a `people` vote |
| Scene concepts | Florence-2 `<OD>` via `ContentUnderstander.understand_image` | Keyword-to-category votes |
| Relevance scores | CLIP cosine similarity via `ContentUnderstander` | Confidence boost when score > 0.5 |

### Limitations (honest assessment)

1. **Not a trained event-category classifier.** The system uses keyword matching against object detection labels, not a trained classifier. If Florence-2 doesn't detect relevant labels, the result is `uncertain`.
2. **Conservative by design.** When signals cannot distinguish a category reliably, the result is `uncertain` with low confidence — never an invented classification.
3. **Branding vs signage separation:** `logo` → `branding`, `sign`/`banner`/`poster` → `signage`. Kept separate per canonical definition.
4. **No multi-tag support in `AssetMetadata`:** The data model stores a single `classification` string. If multiple categories receive votes, only the top vote-getter is stored. This limitation is documented; callers can re-run `_classify_asset` with raw concepts if multi-tag analysis is needed.
5. **Confidence is not calibrated.** `classification_confidence` is a heuristic (vote share + relevance boost), not a probability.

---

## 4. API MAPPING CONSOLIDATION

**File:** `api/main.py`

Three previously-divergent inline category keyword systems were consolidated into one canonical system:

| Endpoint | Before | After |
|----------|--------|-------|
| `/api/assets/enhanced` | Inline `category_keywords` dict (6 categories) | `categorize_asset_canonical()` + canonical categories |
| `/api/assets/categorized` | Inline `category_keywords` dict (7 categories, default `'other'`) | `categorize_asset_canonical()` + `categorize_asset_for_api()` |
| `/api/jobs/{id}/case-study/enriched` | Inline `category_keywords` dict (6 categories, default `'other'`) | `categorize_asset_for_api()` |

### Consolidation helpers

- **`categorize_asset_canonical(asset)`**: Returns canonical category. Priority: (1) asset's `classification` field from fixed pipeline; (2) keyword fallback against `scene_concepts`. Never silently coerces to `other` — returns `UNCERTAIN` when no signal.
- **`categorize_asset_for_api(asset)`**: Returns `{category, display_category, label}` for API consumers.
- **`CANONICAL_TO_DISPLAY`**: Maps canonical → display names for backward compatibility (e.g., `event_venue` → `stage`, `people` → `crowd`).
- **Backward compatibility:** Existing frontend consumers receive `category` (display name) as before. New fields `canonical_category` and `category_label` are additive.

---

## 5. FRONTEND CATEGORY MAPPING

**File:** `ml_test_ui/src/pages/AssetSelectionPage.tsx`

### Changes

- Added imports: `Building`, `Package`, `Flag`, `Megaphone`, `Folder`, `HelpCircle` from `lucide-react`
- Expanded `categoryIcons` to include all 10 canonical categories plus 5 display-name aliases for backward compatibility:

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

### Unknown category handling

- `categoryIcons[id ?? Tag]` fallback already existed; `uncertain` now explicitly maps to `HelpCircle` (Unknown/Unclassified state), not silently to `other`.
- `cat.name` / `cat.label` from API response is used for display text.
- No existing user-facing functionality removed.

---

## 6. FILES AND FUNCTIONS CHANGED

| File | Change | Defects addressed |
|------|--------|-------------------|
| `content_engine/categories.py` | **New file** — canonical category definitions, label mapping, normalization helpers | D-008, D-009 |
| `content_engine/data_types.py` | Import canonical categories; `AssetMetadata.__post_init__` normalizes `classification` | D-003, D-008 |
| `content_engine/pipeline.py` | Added `_classify_asset()`; fixed `final_score`, `technical_quality`, `category`, `class_conf` in `_process_image` and `_process_video`; fixed indentation bug | D-001, D-002, D-003, D-004, D-005 |
| `api/main.py` | Import canonical categories; added `categorize_asset_canonical()` / `categorize_asset_for_api()`; replaced 3 inline keyword systems | D-008, D-009 |
| `ml_test_ui/src/pages/AssetSelectionPage.tsx` | Expanded `categoryIcons` with all canonical categories + aliases; `uncertain` → `HelpCircle` | D-008 |

---

## 7. REMAINING ISSUES

| ID | Issue | Location | Status |
|----|-------|----------|--------|
| D-006 | Missing signals not renormalized — absent faces/concepts reduce score by full weight | `pipeline.py` formula | Documented (by design, not a bug) |
| D-007 | Placeholder regex misses `{{brand_name}}`, multi-word, digit-prefixed placeholders | `copy_generator.py:192` | Unchanged |
| D-010 | Brand relevance computed but excluded from `final_score` | `pipeline.py` | Documented (by design) |
| D-011 | No runtime verification of any fix | — | Required |

---

## 8. RUNTIME VERIFICATION STILL REQUIRED

The following must be verified at runtime before the repair can be accepted:

1. **105-image dataset classification**: Confirm classification moves from 100% `Other`/`uncertain` to meaningful categories using actual Florence-2 + CLIP output.
2. **`NameError` resolution**: Verify `_process_image` and `_process_video` execute without `NameError` on real assets.
3. **Placeholder validation on real Qwen output**: Test `{{brand_name}}` and multi-word placeholders against actual model output.
4. **MP4 generation**: Verify actual video pipeline produces a valid `instagram_reel.mp4`.
5. **End-to-end pipeline**: Full upload → process → select → layout → copy → output flow.
6. **Frontend category display**: Verify all 10 canonical categories render correctly with icons and labels.

---

**NO COMMANDS, TESTS, BUILDS, SERVERS, MODEL INFERENCE, API REQUESTS OR BROWSER CHECKS WERE RUN.**
