# Brand Intelligence Studio — System Architecture

Status: **DRAFT — Phase 0 deliverable. No code changes until approved.**
Date: 2026-11-16
Supersedes: the earlier Milestone 3 direction (conventional Brand Voice Preview / marketing-profile form).

---

## 0. Phase 0 — Architecture audit and preservation inventory

Read-only audit of the current codebase before any redesign. Line references verified 2026-11-16.

### 0.1 What exists today (and must be preserved)

| Asset | Location | Status |
|---|---|---|
| 45-field brand profile schema (v1 first 13 fields immutable) | `content_engine/studio/storage.py:20-68` (`BRAND_PROFILE_DEFAULTS`, `BRAND_PROFILE_TEXT_LIMITS`, `BRAND_PROFILE_LIST_FIELDS`) | Complete, in use |
| Profile validation (rejects unknown keys) | `storage.py:224-256` | Constraint: new fields must be additive |
| Read-time default merge (migration-free forward compat) | `storage.py:258-269` `_with_brand_profile_defaults` | Keep as the extension pattern |
| Profile CRUD + duplicate with asset copy | `storage.py:271-366` | Complete |
| Asset-path confinement | `storage.py:299-307` — every `logo_path` / `visual_references[]` entry must resolve inside `output/studio/brand_assets/<profile_id>/`; UUID validation `storage.py:296-298` | Complete, tested (`tests/test_brand_profile_schema_v2.py`) |
| Asset upload (logo / reference kinds) | `api/studio_routes.py:381-400` → `storage.save_brand_asset` `storage.py:368-385` (ext whitelist, server-generated filename) | Complete |
| Brand API (8 endpoints) | `api/studio_routes.py:299-430` | Complete |
| Local model inventory (6.9 GB, 7 models, `models/model_manifest.json`) | CLIP `models/clip`, DINOv2 `models/dinov2`, Florence-2 `models/florence`, BLIP `models/blip`, YOLOv8 `models/yolov8`, YOLOv11-face `models/yolov11-face`, Qwen `models/qwen` | All local, `local_files_only=True` everywhere |
| BrandMatcher (CLIP + DINOv2 + ORB + HSV, per-brand embeddings, `classify()` / `segregate()`) | `content_engine/brand/brand_matcher.py` | Working; used by GFF 4-brand segregation (`content_engine/gff/orchestrator_gff.py:69-70`) |
| Shared CLIP singleton | `content_engine/utils/model_registry.py:84-147` | Reuse, do not duplicate |
| Florence-2 runner (`<OD>` task) | `content_engine/models/content_understanding.py`, `content_engine/providers/vision/local.py:115-142` | Reuse as the OCR/region runner host |
| Focal-point cropping + manual overrides | `content_engine/composition/focal_analyzer.py`, `smart_crop.py` (`CropOverrideStore` 962-1029) | **Do not modify** |
| Upload validation (MIME sniffing, uuid rename) | `api/main.py:validate_upload` 455-571 | Reuse pattern |
| Path confinement for served files | `api/main.py:_resolve_image_path` 801-848 (403 on escape), `_output_file_path` 1262-1276 | Reuse |
| Offline enforcement | `content_engine/llm/torch_backend.py:27-31` (`HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`), `providers/factory.py:23-46` (cloud rejected), `content_engine/ai_mode.py` | Extend to the new pipeline |
| Frontend brand CRUD | `ml_test_ui/src/pages/BrandProfilesPage.tsx`, `src/lib/brandProfile.ts` (6-section mirror, `assetUrl()`), `src/components/brand/*` | Complete, extend not replace |
| Tests | `tests/test_brand_profiles.py`, `test_brand_profile_schema_v2.py`, `test_local_qwen_only.py`, `test_focal_analyzer.py`, `test_smart_crop.py`; frontend `vitest` (`ml_test_ui/src/lib/brandProfile.test.ts`) | Run: `pytest tests/ -v`, `npm run test` (in `ml_test_ui`) |

### 0.2 Critical gaps (things the brief assumes that do NOT exist)

1. **No OCR anywhere.** Zero matches for EasyOCR/PaddleOCR/Tesseract in code or `requirements.txt`. The only candidate is Florence-2's `<OCR>` task (weights already local, currently only `<OD>` is used).
2. **No logo detector.** `brand_matcher._detect_logo_crop` (`brand_matcher.py:408-434`) just crops the highest-confidence YOLOv8 **COCO** box — it is not logo detection. `config.py:58-59` defines `brand_use_logo_detection` but nothing reads it. YOLOv11-face is a face model and must not be repurposed.
3. **No ZIP handling** (no `zipfile`, no jszip) — import and export both need building from stdlib.
4. **No database/ORM/migrations** — everything is JSON files under `output/studio/`.
5. **No dataset concept** — uploads today are per-file or ad-hoc directories; no manifest, no dedupe across a collection, no batch ingestion.
6. **No classification/review/export stores.**
7. **No standalone embedding module** — CLIP/DINOv2 embedding code is private to `BrandMatcher`/`FocalAnalyzer` and must be extracted, not copy-pasted.
8. **Retention conflict:** daily `cleanup.py` deletes `uploads/` after 7 days and **`output/` after 30 days** (`config.py:49-50`, scheduled `api/main.py:81-99`). Any dataset stored under `output/` would be silently destroyed. Must be exempted (§7.4).
9. Prior audit doc `docs/BRAND_INTELLIGENCE_ARCHITECTURE_AUDIT.md` is stale (describes 13 fields); this document supersedes it for the redirection.

### 0.3 Preservation contract

The following are **frozen** unless this document is amended and approved:

- The 45-field profile schema: no renames, no removals; extension only via additive defaults.
- Profile CRUD endpoints and semantics.
- Asset confinement logic.
- Crop algorithm and `CropOverrideStore`.
- All model weights and loaders (`local_files_only=True`); no model swaps.
- Content Engine Studio / Results / GFF workflows and their navigation.
- Original uploaded files (never moved, never rewritten, never deleted by this feature).

---

## 1. Proposed system architecture

Brand Intelligence Studio becomes a **separate feature slice** alongside (not inside) the existing Studio brand mode:

```
ml_test_ui (React)                          api (FastAPI)
┌─────────────────────────────┐             ┌──────────────────────────────────────────┐
│ Brand Intelligence workspace│             │ api/brand_intel_routes.py   (NEW, own    │
│  ├ Brand Library            │────────────▶│  router, prefix /api/brand-intel)        │
│  ├ Dataset Upload           │             │  ├ datasets  ├ runs  ├ review  ├ export  │
│  ├ Detection Studio         │             │  └ reuses: studio_routes brand CRUD,     │
│  ├ Review & Verification    │             │      validate_upload, path confinement   │
│  ├ Dataset Explorer         │             └───────────────┬──────────────────────────┘
│  └ Export Center            │                             │
└─────────────────────────────┘             ┌───────────────▼──────────────────────────┐
                                            │ content_engine/brand_intel/  (NEW pkg)   │
                                            │  ├ ingestion.py    (datasets, dedupe)    │
                                            │  ├ signals/ocr.py         (Florence-2 <OCR>)
                                            │  ├ signals/logo_scan.py   (region scan)  │
                                            │  ├ signals/visual.py      (CLIP+DINOv2)  │
                                            │  ├ embeddings.py  (shared, extracted)    │
                                            │  ├ aggregator.py   (calibrated fusion)   │
                                            │  ├ runner.py       (chunked, resumable)  │
                                            │  └ stores.py       (JSON/JSONL stores)   │
                                            └───────────────┬──────────────────────────┘
                                            reuse unchanged: model_registry (CLIP),
                                            content_understanding (Florence-2),
                                            brand_matcher scoring primitives,
                                            composition/* (NOT touched), studio/storage.py
```

Design principles:

- **Additive slice.** Nothing in `api/main.py` changes except registering one new router. Nothing in the existing Brand Profiles page is deleted.
- **Signals are pluggable modules** behind one interface (`SignalResult`), so an OCR engine or logo scanner can be upgraded without touching aggregation.
- **Raw model output and human decisions are stored separately** and never overwrite each other (§2.4).
- **Fully offline.** The new package inherits the offline env vars; a test asserts no outbound calls during a run (same pattern as `tests/test_local_qwen_only.py`).

---

## 2. Data model

No database exists and introducing one is out of scope for approval-free work; the model uses the existing JSON/JSONL-on-disk pattern, chosen for restart-persistence and append-friendly classification data.

### 2.1 Brand (extends existing profile)

Existing 45 fields stay untouched. **Additive fields** (with defaults, merged at read time like every other field):

| New field | Type | Purpose |
|---|---|---|
| `known_text_aliases` | `list[str]` | Optional OCR matching aids: brand name, misspellings, taglines (≤50 × 200) |
| `brand_category` | `str` | Industry/category for the Brand Library (≤120) |
| `reference_notes` | `str` | Free text about visual identity (≤1000) |

`logo_path` and `visual_references` remain the canonical persisted asset fields (backward compatible, confinement rules unchanged).

**New sidecar manifest** — `output/studio/brand_assets/<profile_id>/manifest.json`, because each asset needs metadata the flat schema has no room for:

```json
{
  "assets": [
    {
      "asset_id": "uuid",
      "kind": "logo",                    // "logo" | "reference"
      "category": "packaging",           // product|packaging|signage|storefront|banner|uniform|label|placement|other
      "stored_name": "<uuid>.png",
      "original_name": "coke-can.png",
      "sha256": "…",
      "bytes": 41234, "width": 800, "height": 600,
      "uploaded_at": "…", "notes": ""
    }
  ]
}
```

The manifest is **derived-safe**: `visual_references` / `logo_path` keep pointing at the same files, so existing profile consumers and the 45-field validator are unaffected. If manifest and schema disagree, the schema wins (source of truth for paths) and the manifest is rebuilt.

Logo variants = multiple `kind:"logo"` assets. Reference photographs = multiple `kind:"reference"` assets, categorized.

### 2.2 Datasets and images

Stored under `output/brand_intelligence/` (§7.1).

```json
// datasets/<dataset_id>.json
{
  "id": "uuid", "name": "Event Photography 2026",
  "created_at": "…", "status": "ingesting|ready|running|classified",
  "source": {"kind": "files|zip", "original_name": "photos.zip"},
  "image_count": 1400, "duplicate_count": 61, "rejected_count": 4,
  "rejected_reasons": {"unsupported_type": 3, "corrupt": 1},
  "bytes_total": 987654321
}
```

```json
// datasets/<dataset_id>/images.jsonl   (one line per image, append-only)
{ "image_id": "sha256[:16]", "stored_path": "images/ab/abcdef….jpg",
  "original_filename": "IMG_0042.jpg", "sha256": "…", "bytes": 402133,
  "width": 4032, "height": 3024, "format": "JPEG",
  "uploaded_at": "…", "duplicate_of": null }
```

Images are stored **content-addressed** (`images/<sha[:2]>/<sha>.<ext>`): dedupe for free, source files untouched, stable identity for referencing results.

### 2.3 Predictions (immutable raw model output)

```json
// datasets/<id>/runs/<run_id>/predictions.jsonl   (append-only, write-once)
{
  "run_id": "uuid", "image_id": "…",
  "model_versions": {"florence": "…", "clip": "…", "dinov2": "…"},
  "signals": {
    "ocr":   { "available": true, "text": "COCA-COLA", "tokens": [{"text":"COCA-COLA","confidence":0.87,"box":[x,y,w,h]}] },
    "logo":  { "available": true, "regions": [{"brand_id":"…","score":0.81,"box":[…],"reference_asset":"…"}] },
    "visual":{ "available": true, "brand_scores": {"<brand_id>": {"clip":0.31,"dinov2":0.66}} }
  },
  "detections": [
    { "brand_id": "…", "confidence": 0.93, "tier": "high",
      "contributions": {"ocr": 0.4, "logo": 0.33, "visual": 0.2},
      "matched_reference": "asset_id", "boxes": [[…]], "matched_text": "COCA-COLA" }
  ],
  "tier": "high|medium|low|unmatched", "processed_at": "…"
}
```

One image → one prediction record containing **0..N detections** (multi-brand).

### 2.4 Human decisions (separate, append-only)

```json
// datasets/<id>/decisions.jsonl
{ "decision_id": "uuid", "image_id": "…", "run_id": "…",
  "action": "confirm|reject|reassign|set_multi|set_uncertain|set_unmatched",
  "brands": ["brand_a"],            // authoritative brand list after the action
  "note": "banner logo is from sponsor B", "decided_by": "user",
  "decided_at": "…", "supersedes": null }
```

Effective status = latest decision for the image if present, else latest run prediction. Raw predictions are never modified. Rejecting/reassigning writes a new line; history is fully auditable (feeds the export "human verification history").

### 2.5 Runs and exports

```json
// runs/<run_id>.json
{ "id": "uuid", "dataset_id": "…", "status": "pending|running|paused|done|failed|cancelled",
  "config": { "brand_ids": ["…"], "signals": ["ocr","logo","visual"],
              "thresholds": {"high": 0.85, "medium": 0.55},
              "weights": {"ocr": 0.4, "logo": 0.35, "visual": 0.25},
              "multi_brand": true, "max_detections": 5 },
  "created_at": "…", "cursor": 812, "total": 1400,
  "counts": {"high": 600, "medium": 150, "low": 90, "unmatched": 560} }
```

`cursor` makes runs resumable across restarts (acceptance item 13).

```json
// exports/<export_id>.json
{ "id": "uuid", "dataset_id": "…", "kind": "zip_brand|zip_all|csv|json|ocr|uncertain|history",
  "brand_id": "…", "file": "exports/<id>.zip", "image_count": 420, "created_at": "…" }
```

---

## 3. Image ingestion pipeline (Phase 2)

```
client (incremental, ≤ N files per request, browser never holds the full set)
   │  multipart POST (files)  OR  zip upload
   ▼
validate_upload-style gate  ── reject: bad MIME/signature, >max bytes, unsupported ext
   ▼
decode check (PIL verify; corrupt → rejected_count with reason)
   ▼
sha256  ── already in this dataset? → duplicate_count, skip copy
   ▼
content-addressed copy → output/brand_intelligence/datasets/<id>/images/<ab>/<sha>.<ext>
   ▼
append images.jsonl + update dataset manifest counters
```

- **Routes**: individual, multi-select, and ZIP.
- **ZIP safety** (stdlib `zipfile`, no new dependency): reject entries with absolute paths, drive letters, `..` segments, or symlinks (path traversal test required); enforce per-entry and total uncompressed limits (zip-bomb guard: reject if ratio or total exceeds config); flatten entry paths to sanitized basenames; extract to a temp dir inside the dataset folder, validate each file, then move in. Never extract outside the dataset directory.
- **Originals untouched**: uploaded files are copied, never moved or renamed in place; ZIP sources are deleted only from the temp staging area after successful ingestion.
- **Incremental**: uploads arrive in chunks (e.g. 25 files/request or 50 MB) with per-chunk progress; the server writes incrementally so a failed chunk loses only that chunk.
- **Supported formats**: JPEG, PNG, WebP (config-driven, reuses `settings.allowed_image_extensions`).
- **Integrity**: `images.jsonl` is append-only; a re-ingest of the same sha is a no-op; dataset counts derived from the manifest and reconcilable from the jsonl.

---

## 4. OCR and visual matching strategy (Phase 3)

Three **independent** signals. Each produces a per-(image, brand) evidence vector plus regions. No signal alone decides.

### 4.1 Shared embedding layer (extracted, not copied)

New `content_engine/brand_intel/embeddings.py` wraps the existing singletons:

- `get_clip()` from `content_engine/utils/model_registry.py` (already thread-safe, offline).
- DINOv2 loader — same construction as `brand_matcher.py:326-331` (`local_files_only=True`, CLS token), but moved into a reusable, cached module. **The crop/focal code that also loads DINOv2 is not touched.**
- Optional region embedder: Florence-2 `<OD>`/`<REGION_PROPOSAL>` boxes → crop → DINOv2/CLIP embed.

Reference-side: per brand, precompute and cache embeddings for every reference photo and logo (invalidate on asset upload/delete via manifest sha). Brand prototype = normalized mean of reference embeddings, plus the **individual** reference embeddings kept for best-match explanation ("matched_reference").

### 4.2 Signal A — OCR

**Runner:** Florence-2 (`models/florence`, already local, already loaded via `trust_remote_code=True, local_files_only=True`) using its `<OCR>` task; implemented as a new task call beside the existing `<OD>` path in `content_engine/models/content_understanding.py`'s style (a new module in `brand_intel/signals/`, importing the same loading pattern — no change to existing files).

**Extract:** full-text string + token-level strings. Florence-2's `<OCR>` returns text without reliable per-token boxes; boxes are approximated by also running `<OD>`/`<REGION_PROPOSAL>` and OCR-ing top regions where region evidence is needed (§10.2 documents the accuracy limits).

**Matching:** normalize text (casefold, strip punctuation, collapse whitespace), then match against `known_text_aliases`, brand `name`, and `tagline` using token-set similarity with edit-distance tolerance for OCR noise (e.g. "COCA·COLA", "Coca Cola", "COCA-C0LA"). Output: per-brand `ocr_score ∈ [0,1]`, matched string, confidence, box when available.

**Honesty rule:** if OCR quality on a validation sample is insufficient, we report measured precision/recall from Phase 9 tests — no claimed accuracy figures before measurement.

### 4.3 Signal B — Logo recognition

**Facts:** there is no logo detector in the model inventory, and YOLOv8-COCO/`_detect_logo_crop` is not one. Face model is irrelevant. So logo recognition is built as a **region-scanning matcher** over existing weights:

1. Generate candidate regions: Florence-2 `<REGION_PROPOSAL>` boxes + `<OD>` boxes for sign/banner/cloth classes + a coarse multi-scale tile sweep (logos are small; full-image similarity misses them).
2. Embed each region (DINOv2 primary — stronger on fine-grained instance identity; CLIP secondary).
3. Compare against **logo reference embeddings** (all variants) → `logo_score = max over regions, over variants`.
4. Keystroke check: ORB ratio-match (primitives already exist in `brand_matcher.py:245-268, 436-460`) between the best region and each logo reference — cheap, translation/rotation-tolerant confirmation for flat logo graphics.
5. Record the winning region box + reference asset id as evidence.

This is template/instance retrieval, not a trained detector — stated plainly everywhere it is reported (§10).

### 4.4 Signal C — Visual similarity

Two levels, both per-brand:

- **Whole image:** CLIP cosine + DINOv2 cosine between the image and (a) the brand prototype and (b) each reference photo → `visual_score`. Whole-image only ever contributes weak-to-moderate evidence (a photo of a crowd is not a brand).
- **Region level:** regions from Signal B embedding pipeline compared against reference embeddings — this is where product/packaging/signage matches actually surface. Best region match per brand wins, and its box is reported.

Reference categories can be weighted (e.g. `signage`/`product` stronger than `placement`) via config, defaulting to uniform.

### 4.5 Signal interface

```python
@dataclass
class BrandEvidence:
    brand_id: str
    score: float                # calibrated to [0,1] (§5.1)
    raw: dict                   # signal-native scores, kept for audit
    matched_reference: str | None
    boxes: list[list[float]]
    matched_text: str | None
    notes: str

class Signal(Protocol):
    name: str
    def available(self) -> bool: ...
    def run(self, image_path: str, brand_refs: BrandReferenceIndex) -> SignalOutput: ...
```

Signals degrade gracefully: if one is unavailable (`available() == False`), aggregation runs on the remaining ones and records which were missing — never fabricates a value (no mock results presented as AI output).

---

## 5. Classification and confidence (Phase 4)

### 5.1 Calibration (not naive averaging)

Each signal is converted from raw similarity to a calibrated probability-ish score using **per-signal calibration** built from measurable pairs:

- **Positives:** reference photo ↔ another reference photo of the same brand (leave-one-out within the brand set).
- **Negatives:** reference photo ↔ references of other brands (cross-brand pairs).

A monotone mapping (logistic/Platt-style fit on the score distributions, or percentile mapping if sample sizes are small) maps each signal's raw score to `p_signal ∈ [0,1]` per signal type. This is fit **from the user's own uploaded references** at run time — no invented constants, no global "accuracy" claims. Calibration diagnostics (positive/negative score distributions, separation) are stored with the run and shown in the Detection Studio.

### 5.2 Fusion

Per (image, brand):

```
evidence odds = Σ_signals  w_s · logit(p_s)        (missing signal → its term omitted, weights renormalized)
confidence    = sigmoid(evidence odds − bias)
```

- Weights `w_s` default `ocr 0.40 / logo 0.35 / visual 0.25`, user-configurable per run.
- Missing-signal renormalization keeps scores comparable when, say, an image has no readable text.
- Correlated-signal damping: OCR and logo-text are partially redundant; when both fire on the *same string/region* they contribute jointly but with the second term scaled by 0.6 (documented constant, configurable).
- Optional contextual evidence (category prior) is off by default.

### 5.3 Tiers and multi-brand

Per-brand confidence is evaluated **independently** → an image can produce multiple detections (multi-label, not argmax):

| Tier | Default threshold | Behavior |
|---|---|---|
| High | ≥ 0.85 | Auto-assigned (subject to run config; can be lowered/raised or disabled) |
| Medium | 0.55 – 0.85 | Queued for human review |
| Low | 0.30 – 0.55 | Recorded as uncertain evidence, not assigned |
| Unmatched | < 0.30 or no signals fired | Bucket "unmatched" |

- `max_detections` (default 5) caps runaway detections; below-threshold brands are still stored in `signals` for transparency.
- An image with no detection ≥ low tier lands in **Uncertain/Unmatched**, never force-assigned (acceptance item 8).
- Contradiction guard: two high-tier detections whose reference sets are flagged mutually exclusive in config are downgraded to medium with a `contradiction` note — recorded, not silently dropped (§ constraint about incompatible classifications).
- Every detection stores `contributions` (per-signal weighted share), matched text, matched reference, boxes → the UI can always answer "why?".

### 5.4 Run execution

`brand_intel/runner.py`:

- Chunked (default 25 images/request or a background job via the existing APScheduler/Celery infrastructure in `api/tasks.py`), `cursor` persisted in `runs/<id>.json`, predictions appended incrementally → **restart resumes at cursor**.
- Model loads are lazy singletons; Florence/CLIP/DINOv2 run on CPU (device via existing `mps_safe`/device_manager).
- Cancellation and pause supported; a re-run with different config creates a **new run**, never edits an old one.

---

## 6. Human verification workflow (Phase 5)

Review queue = images whose effective status is `medium`, `low`, `uncertain`, `unmatched`, or previously rejected — filtered and paginated.

Per image the reviewer sees:

- Original image (served through the existing confined path resolution).
- Predicted detections with confidence, tier, **contributions bars**, matched reference thumbnail, matched OCR string, and boxes overlaid on the image.
- OCR raw text panel.
- Full signal table (available/missing).

Actions: **Confirm** / **Reject** / **Reassign** (pick any brand(s)) / **Mark multi-brand** / **Leave uncertain** / **Leave unmatched**, plus free-text note. Each writes a line to `decisions.jsonl` (§2.4); raw predictions untouched.

- **Bulk actions** with the same record shape (one decision line per image, batch id shared).
- **Filters:** tier, brand, decision status, has-text, dataset, search by filename/OCR text.
- Re-running a new model run does not clear decisions; decisions always win over predictions for effective status (decisions record which `run_id` they judged).

---

## 7. Storage and export strategy (Phase 6–7)

### 7.1 Layout

```
output/brand_intelligence/
  datasets/<dataset_id>.json              # manifest
  datasets/<dataset_id>/
    images/<ab>/<sha256>.<ext>            # content-addressed originals (copies)
    images.jsonl                          # one row per image
    runs/<run_id>.json                    # config + cursor + counts
    runs/<run_id>/predictions.jsonl       # raw model output (immutable)
    decisions.jsonl                       # human corrections (append-only)
    exports/<export_id>.zip | .csv | .json
```

Brand assets stay where they are: `output/studio/brand_assets/<profile_id>/` (+ `manifest.json`). Profiles stay in `output/studio/brand_profiles/`.

### 7.2 Explorer (Phase 6)

Per dataset: brand-wise virtual collections computed from effective status — Brand A (420), Brand B (315), Multi-brand, Uncertain, Unmatched, plus per-brand confidence distribution. Galleries are paginated server-side (never load a whole dataset in the browser). Shows filename, tier/confidence, OCR evidence, verification status; search = filename + OCR text + brand name (server-side filter; existing `fuse.js` only for small client lists).

### 7.3 Export (Phase 7)

- **ZIP per brand** / **ZIP all separated datasets**: contains original files under `brand_a/…` structure, **original filenames preserved** (collision-suffixed `_2`, `_3`), read from the content-addressed store and zipped in-stream (stdlib `zipfile`, no per-file staging explosion).
- **Non-destructive**: exports are new files; neither source dataset images nor uploads are moved.
- **CSV classification report**: `filename, sha256, brand(s), confidence, tier, ocr_text, matched_reference, boxes, status(raw|verified), verified_action, verified_at`.
- **JSON metadata export**: full run config, predictions, decisions.
- **OCR extraction report**: per-image text + confidence + boxes.
- **Uncertain/unmatched report**: the review backlog as CSV/JSON.
- **Verification history**: `decisions.jsonl` copy.
- Every export row carries `sha256` + `original_filename` + `stored_path` → traceability to source (acceptance item 11).

### 7.4 Retention exemption (must implement)

`cleanup.py` deletes `output/` content older than 30 days daily. **`output/brand_intelligence/` must be excluded** from `clean_directory` (default retention applies only to generated results, not user datasets). This is a change to `cleanup.py` semantics and is explicitly part of this proposal — otherwise datasets silently vanish (acceptance item 13 fails).

---

## 8. API design (Phase 8 backend)

New router `api/brand_intel_routes.py`, prefix `/api/brand-intel`, registered once in `api/main.py`. Existing brand-profile endpoints are **reused, not duplicated**.

**Brand Library** (existing + additive)
```
GET/POST/PUT/DELETE /api/studio/brand-profiles[/{id}]      # unchanged
POST /api/studio/brand-profiles/{id}/assets                # unchanged (logo|reference)
GET    /api/brand-intel/brands/{id}/assets                 # NEW: manifest metadata (category, sha, dims)
PATCH  /api/brand-intel/brands/{id}/assets/{asset_id}      # NEW: recategorize / notes / replace
DELETE /api/brand-intel/brands/{id}/assets/{asset_id}      # NEW: remove one asset safely
POST   /api/brand-intel/brands/{id}/index                  # NEW: (re)build embedding cache
GET    /api/brand-intel/brands/{id}/index-status           # NEW
```

**Datasets**
```
POST   /api/brand-intel/datasets                           # create (name)
GET    /api/brand-intel/datasets                           # list + stats
GET    /api/brand-intel/datasets/{id}                      # manifest
DELETE /api/brand-intel/datasets/{id}                      # delete (explicit, with confirm)
POST   /api/brand-intel/datasets/{id}/upload               # multipart chunk (files)
POST   /api/brand-intel/datasets/{id}/upload-zip           # multipart zip
GET    /api/brand-intel/datasets/{id}/images               # paginated, filters (tier/brand/status/q)
```

**Detection**
```
POST /api/brand-intel/datasets/{id}/runs                   # config: brands, signals, thresholds, weights
GET  /api/brand-intel/runs/{runId}                         # progress (cursor/total/counts)
POST /api/brand-intel/runs/{runId}/cancel                  # also /pause, /resume
GET  /api/brand-intel/runs/{runId}/calibration             # score distributions + diagnostics
GET  /api/brand-intel/runs/{runId}/predictions             # paginated evidence browser
GET  /api/brand-intel/status                               # signal availability (model presence/health)
```

**Review**
```
GET  /api/brand-intel/datasets/{id}/review                 # queue, filters, pagination
POST /api/brand-intel/datasets/{id}/review/{imageId}       # single decision
POST /api/brand-intel/datasets/{id}/review/bulk            # bulk decisions
GET  /api/brand-intel/datasets/{id}/history                # decisions audit
```

**Explorer / Export**
```
GET  /api/brand-intel/datasets/{id}/collections            # brand-wise counts + stats
POST /api/brand-intel/datasets/{id}/exports                # kind: zip_brand|zip_all|csv|json|ocr|uncertain|history
GET  /api/brand-intel/exports/{exportId}/download          # streamed file
GET  /api/brand-intel/exports                              # history
```

Conventions: JSON errors, 403 on path escape (reuse `_resolve_image_path` semantics), UUID validation on every id, uploads via existing `validate_upload` rules.

---

## 9. UI navigation plan (Phase 8 frontend)

Routing stays the existing state-union pattern (`ml_test_ui/src/App.tsx:25` View type) — no new router library.

**Approach:** one new top-level nav group **"Brand Intelligence"** with an internal tab strip, backed by a single new view `'brand-intel'` carrying a sub-view state (`bi-tab`). This keeps `App.tsx` and `BottomNav.tsx` changes small and keeps the workspace visually and semantically separate from Content Engine Studio.

Desktop nav (`App.tsx:188-193`): `Studio | Brand Intelligence | Results | Analytics`.
Mobile (`BottomNav.tsx:7-12`): add `Brands →` becomes two entries (`Brands` = Content Engine brand mode stays in Studio; `Intel` = new workspace).

New components under `ml_test_ui/src/pages/brandintel/`:

| Tab | Contents | Notes |
|---|---|---|
| **Brand Library** | Brand list + editor: existing 6-section 45-field form **preserved** as the "Profile" tab; new **"Visual References"** tab (logo grid + categorized reference photo grid, upload/preview/replace/remove/categorize, upload metadata, embedding index status) | Extends `BrandProfilesPage.tsx` + `brandProfile.ts`; the old page remains reachable and unbroken |
| **Dataset Upload** | Create dataset, drag-drop file queue (reuses `components/upload/*` patterns), ZIP drop, chunked progress, per-file status (accepted/duplicate/rejected+reason), dataset list | Streaming, no full-dataset client state |
| **Detection Studio** | Pick dataset → pick brands → signal toggles + thresholds/weights → run controls (start/pause/cancel), live progress, calibration chart, tier counts, evidence browser (image + detections + boxes + contributions) | Honest loading states while models warm up |
| **Review & Verification** | Queue with filters, image + overlay, evidence panel, single/bulk confirm/reject/reassign/multi/uncertain, keyboard-driven flow | |
| **Dataset Explorer** | Collection cards (per brand, multi, uncertain, unmatched) → paginated galleries, search, per-image detail drawer | |
| **Export Center** | Export kind picker, progress, download links, export history | |

API client additions in `ml_test_ui/src/api.ts` (typed, replacing the current `any`-typed brand block where touched).

The existing Content Engine Studio, its "Brand Mode" GFF toggle, Asset Selection, and Results flows are untouched.

---

## 10. Risks and limitations

1. **OCR is the weakest link.** No dedicated OCR engine exists locally; Florence-2-base `<OCR>` may be inaccurate on small/angled/stylized text and does not return token boxes directly. *Mitigation:* Phase 9 measures precision/recall on a labelled sample before any claims; if insufficient, a **decision is escalated to the user** to approve adding a dedicated local OCR engine (new dependency + one-time offline weights download — requires explicit approval under the no-new-models constraint).
2. **No trained logo detector.** Region-scan + embedding/ORB matching is retrieval heuristics; it will underperform on very small, distorted or heavily occluded logos, and can false-positive on visually similar marks. *Mitigation:* conservative thresholds, ORB confirmation, human review tier for anything below high, measured metrics only.
3. **Calibration quality depends on reference diversity.** Few or near-identical reference photos → poorly separated positive/negative score distributions. *Mitigation:* warn below a minimum reference count (e.g. <3 per brand), show calibration diagnostics, default thresholds to review-friendly values.
4. **Compute throughput.** CPU-only, per image: 1 Florence pass + CLIP + DINOv2 + region sweep. Thousands of images will take hours. *Mitigation:* chunked resumable runs, progress UI, per-signal caching (same image never re-embedded in a re-run), optional signal short-circuit (if OCR already gives ≥0.9, skip region sweep — configurable, default off for evidence completeness).
5. **Scale of JSON stores.** JSONL handles thousands of rows fine; `decisions.jsonl` scans are linear. *Mitigation:* keep an in-memory index per dataset while serving, rebuild on start; if datasets ever reach 100k+, migrating to SQLite becomes a separately approved change.
6. **Retention conflict** (§7.4) — must be fixed or data disappears; flagged as a required, explicitly-approved change to `cleanup.py`.
7. **Multi-brand overlap.** Independent per-brand scoring can double-count correlated evidence and over-detect. *Mitigation:* correlation damping (§5.2), `max_detections`, contradiction guard, and Review as the safety net.
8. **ZIP safety.** New attack surface (traversal, bombs). *Mitigation:* stdlib-only extraction with explicit entry validation + dedicated tests; extract only into temp dirs inside the dataset folder.
9. **Memory.** Never buffer whole datasets client-side or server-side; all pipelines stream.
10. **Scope interaction with Content Engine.** The Studio "Brand Mode" GFF toggle (4 fixed brands) and `BrandMatcher.segregate()` remain as-is; long-term they could consume this pipeline, but **no coupling is introduced now**.
11. **`trust_remote_code` on Florence-2** is already in use today; the new signal inherits the same offline loading — no new supply-chain surface, but the offline test must cover the new import path.
12. **No accuracy claims.** All confidence numbers are evidence-based and explainable; the UI shows contributions, not "97% accurate".

---

## 11. Phase 9 → test plan mapping

| Acceptance item | Test |
|---|---|
| 1. Multiple brands created | `tests/test_brand_intel_library.py` (CRUD + additive fields backward-compat: all existing profile fixtures still load) |
| 2. Multiple reference photos per brand | same + manifest round-trip, index cache invalidation |
| 3. Logos uploaded separately | asset kind separation, multiple logos = variants |
| 4. Dataset upload | `tests/test_brand_intel_ingest.py`: files, chunks, ZIP (valid, traversal, bomb, corrupt, unsupported), dedupe, originals untouched (byte-compare before/after) |
| 5. OCR runs locally | signal test with Florence-2 on fixture images (offline env asserted) |
| 6. Visual similarity runs locally | CLIP/DINOv2 scores + reference index test |
| 7. Multiple brands in one image | aggregator multi-label test with synthetic 2-brand image |
| 8. Uncertain not falsely assigned | tier threshold tests: low-signal image → Unmatched bucket |
| 9. Human corrections persist | decisions.jsonl append, effective-status precedence, restart reload |
| 10. Separated datasets accurate & traceable | collection counts == decision/prediction derivation; sha256 traceability |
| 11. Exports contain correct images | ZIP content byte/sha match against store, original filenames preserved |
| 12. Original uploads unchanged | sha256 of source tree before/after full pipeline |
| 13. Restart preserves everything | simulate restart mid-run → cursor resume; manifest/decisions reload; **retention exemption test** |
| 14. No internet for inference | extend `tests/test_local_qwen_only.py` pattern → block sockets during a full run |
| Constraints | crop algorithm untouched (diff guard), 45-field parity (`brandProfile.test.ts` still green), `pytest tests/ -v` + `npm run test` |

---

## 12. Decisions (settled 2026-11-16)

1. **Multi-brand per photograph: YES.** One photograph may belong to multiple brands simultaneously — multi-label detection (§5.3), not single-label classification. Images with no qualifying detection remain Uncertain/Unmatched.
2. **OCR engine: Florence-2 `<OCR>` first, measure, then decide.** Zero new downloads; Phase 9 measures real precision/recall on a labelled sample. If metrics are insufficient, implementation **pauses and escalates for explicit approval** before any dedicated OCR engine (new dependency + one-time offline weights) is added (§10.1).

Status: Phase 0 architecture **APPROVED 2026-11-16**, subject to the seven binding requirements in §13.

---

## 13. Approved requirements (binding on every phase)

Added at Phase 0 approval. These are part of the architecture contract, not suggestions.

**A. Reference quality and diversity.** Track per brand: number of reference photographs, number of distinct logo variants, image diversity, reference quality, and category coverage (logos / products / packaging / signage / other appearances). Warn users when a brand has insufficient reference diversity. Ten near-identical logo uploads must never be presented as a learned brand. → `content_engine/brand_intel/reference_quality.py`, surfaced in the Visual References tab.

**B. Region-aware logo matching.** Whole-image similarity must never be the only logo signal — a photo with a small logo must not be rejected because the rest of the frame looks unrelated. Every logo match records: matched region coordinates, matched reference asset ID, similarity score and verification evidence. → §4.3 (Phase 3), fields already reserved in the prediction schema (§2.3 `boxes`, `matched_reference`).

**C. Prediction confidence ≠ classification status.** Three distinct, separately-stored concepts:
1. model confidence (0–1, immutable raw prediction),
2. human verification status (confirmed / rejected / reassigned / …),
3. effective classification (derived: decision if present, else prediction).
A human-confirmed classification never rewrites the model's original confidence. → §2.3 / §2.4 separation.

**D. Resumable + idempotent processing.** A 5,000-image run stopping at 3,200 must continue from its checkpoint on restart. No duplicate predictions, no duplicate processing on resume: `runs/<id>.json.cursor` + append-only `predictions.jsonl` keyed by `(run_id, image_id)`, with idempotent skip of already-processed images. → §5.4, enforced by tests in Phase 4.

**E. Provenance.** Every classification retains: original filename, SHA-256, dataset ID, brand ID, model versions, run ID, timestamp and the human decision history. Exported rows must carry the same fields. → §2.2–2.4, §7.3.

**F. Cleanup protection.** `output/brand_intelligence/` is exempt from `cleanup.py`'s 30-day sweep — **mandatory**, with tests. Additionally, ZIP extraction, failed uploads and temp files must never be able to remove persistent dataset assets (Phase 2: extraction confined to per-dataset temp dirs; source images content-addressed and never targeted by any cleanup path). Existing user data under `output/studio/brand_profiles/` and `output/studio/brand_assets/` is protected by the same mechanism.

**G. Benchmark before scaling.** Before any large-scale classification or any accuracy claim, build a small **manually labelled evaluation dataset** of real images covering: clear logos, partially visible logos, text-only brand references, multiple brands in one image, products without visible logos, unrelated images, and visually similar brands. Measure **precision, recall, false positives and multi-brand detection separately**. No accuracy claims exist in code, UI or docs until these measurements do. (Bridges Phase 3 → Phase 9; report lives in `docs/`.)

---

## 14. Phase 1 — implementation record (Brand Reference Library)

Delivered per the approved sequence. No dataset classification, no model runs, no Content Engine / Results / crop changes.

### Shipped

| Area | Change |
|---|---|
| Schema | 3 additive fields: `brand_category` (≤200), `known_text_aliases` (list ≤50×200), `reference_notes` (≤1000) — `storage.py` DEFAULTS/TEXT_LIMITS/LIST_FIELDS. 45 → 48 fields; v1/v2 behaviour untouched, read-time default merge covers legacy files. |
| Asset manifest | `output/studio/brand_assets/<id>/manifest.json`: per-asset `asset_id, kind, category, stored_name, original_name, sha256, bytes, width, height, format, uploaded_at, notes`. Entries store file NAMES only → profile duplication works unchanged. Schema remains source of truth for paths; manifest rebuilt in-memory on read (no write side effects), persisted only on mutation. |
| Storage ops | `record / list / get / update / remove / replace` + `_sync_profile_assets_from_manifest` so `logo_path`/`visual_references` can never drift from the manifest. Replace keeps asset identity and re-syncs paths when the extension changes. Confinement enforced on every path (asset must resolve inside the profile asset dir). |
| API (existing) | `POST /api/studio/brand-profiles/{id}/assets` gains optional `category` + `notes` form fields (backward compatible; logos forced to category `logo`) and returns the manifest entry. |
| API (new) | `api/brand_intel_routes.py` → `/api/brand-intel`: `GET/PATCH/DELETE /brands/{id}/assets[/{asset_id}]`, `POST …/replace`, `GET …/reference-quality`. Registered in `main.py`. |
| Reference quality | `content_engine/brand_intel/reference_quality.py`: counts, category coverage, dHash diversity + near-duplicate pairs, Laplacian sharpness, resolution checks → 7 warning codes + documented readiness score (0–100). Pure CPU, no models, no network. |
| Cleanup | `cleanup.py`: `PROTECTED_OUTPUT_PATHS = (brand_intelligence, studio/brand_profiles, studio/brand_assets)` skipped at any depth, any age; documented + tested (requirement F). |
| Frontend | New **Brand Intelligence** workspace (`View: 'brand-intelligence'`, desktop nav + mobile `Intel` tab) with 6-tab strip; Phase 1 ships **Brand Library** (embeds the extended brand editor with a **Visual References** tab), other tabs are honest Phase 2–6 placeholders. `VisualReferencesPanel`: multi-logo grid, categorized reference grid, upload (multi-file) with category, preview modal (dimensions/format/sha/date/notes), inline recategorize, replace, remove (confirm), quality score + warnings. |
| Schema mirror | `brandProfile.ts` + parity test updated 45 → 48 fields. |

### Verification (Phase 1)

- Backend: `tests/test_brand_reference_library.py` (28 tests: schema, manifest, quality, API), `tests/test_cleanup_protection.py` (5 tests), updated `tests/test_brand_profile_schema_v2.py` — all green, plus existing brand regressions (`test_brand_profiles`, `test_brand_voice*`, `test_studio`, `test_ingestion`).
- Frontend: `npm run test` (30 tests, incl. 48-field parity) and `npm run build` (tsc + vite) green.
- No model was loaded or run; no network access; no existing profile data modified; no Git operations performed.

### Deferred to Phase 2+
- Dataset upload, ZIP import (requirement F extraction hardening), embedding index endpoints, OCR/logo/visual signals, run orchestration (requirements B/C/D/E), review, explorer, export, benchmark dataset (requirement G).

## 15. Phase 2 — implementation record (Dataset Upload)

Ingestion only: no OCR, no classification, no model runs. Brand Reference Library, Content Engine Studio, Results and crop workflows untouched.

### Shipped

| Area | Change |
|---|---|
| Validation | `content_engine/brand_intel/ingestion.py`: content-based image validation (magic-byte sniff → Pillow `verify()`, never extension/MIME alone), streamed SHA-256, `validate_image_bytes/file`, `file_sha256`, `cleanup_dir`. Rejection codes: `empty \| too_large \| unsupported_type \| corrupt`. |
| ZIP security | `ZipLimits` dataclass (defaults: **10 000 files, 4 GB total, 200 MB/entry, compression ratio 100:1 above 1 MB**), `sanitize_entry_name`, `_prescan` + `extract_zip_safely`: all-or-nothing security gate (traversal, absolute paths, symlink entries, bomb ratio, file-count and size caps abort the whole archive with codes `zip_traversal \| zip_symlink \| zip_too_many_files \| zip_entry_too_large \| zip_total_too_large \| zip_bomb_ratio \| zip_unreadable`); unsupported/nested entries are skipped per-entry and reported; extraction streams into a temp dir under the dataset dir with a hard byte cap, flattened sanitized basenames, then moves accepted files in; temp dirs always cleaned up. Stdlib `zipfile`/`shutil` only. |
| Dataset store | `content_engine/brand_intel/dataset_store.py`: `DatasetStore` — UUID path-confinement gate, atomic JSON writes (tmp+rename), single-process `RLock` for manifest writes, append-only `images.jsonl` (one line per unique image; duplicates counted, never re-appended) + `rejected.jsonl` (deduped by (sha, filename)). CRUD, `ingest_batch` (one-file-at-a-time streaming with dedup/shared/reject counters), `ingest_zip`, chunk sessions (`create / save_chunk / complete / discard`), `finalize_dataset` verification gate, `list_images` pagination/search. `DatasetError(code, message, status)` maps to HTTP. |
| Storage layout | Shared global content-addressed store `output/brand_intelligence/images/<ab>/<sha256>.<ext>` — **one physical asset per SHA-256 across all datasets** (deliberate deviation from §3's per-dataset path, per approved Phase 2 prompt §5: dedup must hold across datasets; manifests keep their own per-dataset references; originals never modified). Dataset manifests `output/brand_intelligence/datasets/<id>.json`; chunk sessions `…/datasets/<id>/uploads/<uid>.json`; chunk parts `…/datasets/<id>/tmp/<uid>/chunk_00000`; temp extraction under `…/datasets/<id>/tmp/`. Deleting a dataset never touches the shared store (no GC in Phase 2). |
| Chunked upload | Server derives `chunk_size = ceil(total_bytes/total_chunks)`; client requests `total_chunks = ceil(size/4 MB)` and slices with the server's size (shared math helpers `planChunkCount/chunkRange/expectedChunkBytes` in `ml_test_ui/src/lib/datasetUpload.ts` with parity tests). Chunks idempotent by index, retried client-side ×3 with backoff, resumable after backend restart (session + parts on disk), `MAX_FILES_PER_REQUEST=50`, `MAX_CHUNK_BYTES=64 MB`, client batch size ≤10 for small files. Dataset is only marked `ready` by `finalize`: no pending sessions, counters reconciled from jsonl, every referenced asset exists on disk; upload after finalize reopens to `ingesting`. |
| API | `api/brand_intel_routes.py` → 18 routes total; Phase 2 adds 13 under `/api/brand-intel`: `POST/GET /datasets`, `GET/DELETE /datasets/{id}` (delete requires `confirm` == exact name), `POST /upload`, `POST /upload-zip`, `POST/GET /datasets/{id}/uploads`, `POST …/uploads/{upload_id}/chunks/{index}`, `POST …/uploads/{upload_id}/complete`, `DELETE …/uploads/{upload_id}`, `POST /datasets/{id}/finalize`, `GET /datasets/{id}/images`. Uploads streamed via 1 MB staging reads — request bodies never fully buffered. |
| Frontend | **Dataset Upload** tab (`DatasetsPanel.tsx/.css`) replaces the placeholder: dataset list/create/detail, drag-drop + file picker + ZIP input, per-file upload queue with status (Queued/Uploading/Stored/Duplicate/Rejected/Failed) and progress bar, validation-error surfacing, pending-upload resume banner with discard, finalize button + auto-finalize after drain, paginated searchable thumbnail grid (lazy, `/output/…` static URLs), delete modal with typed-name confirmation. Only `File` references held — never file contents; large files sliced chunk-by-chunk. `api.ts` gains 13 typed client functions + dataset types. No mock data anywhere. |
| Cleanup | `cleanup.py` `PROTECTED_OUTPUT_PATHS` already covers `brand_intelligence`; extended test proves the shared image store survives cleanup (requirement F). |

### Verification (Phase 2)

- Backend: `tests/test_brand_intel_ingest.py` (67 tests: validation, dedup within/across datasets, ZIP security incl. traversal/symlink/bomb/limits, chunked resume-after-restart, manifest consistency, deletion safety, API contract, incremental 60-file ingestion, end-to-end acceptance workflow) + `tests/test_cleanup_protection.py` extension — **full suite 578 passed**.
- Frontend: `npm run test` **37 passed** (incl. chunk-math parity tests), `npm run build` green, ESLint clean on all Phase 2 files; `api.ts` legacy `any`s untouched (33 pre-existing failures remain in untouched `/api/studio/*` functions), Phase 1 brand-intel lines re-typed to remove `any`.
- Real-browser verification of the Dataset Upload tab is user-side (assistant has no screenshot capability) — pending alongside the Phase 1 Visual References visual check.

### Deferred to Phase 3+
- OCR / logo-region / visual-signal extraction and run orchestration (requirements B–E), labelled benchmark (requirement G), GC of unreferenced shared assets, review/explorer/export tabs.
