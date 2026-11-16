# Milestone 1 — Brand Profile Architecture Audit

Date: 2026-11-11
Scope: read-only audit of the existing brand profile implementation before any changes.

---

## 1. Existing profile fields

The canonical schema is `StudioStorage.BRAND_PROFILE_DEFAULTS` —
`content_engine/studio/storage.py:17-23` (13 data fields, i.e. the "11-field schema"
plus the two asset fields `logo_path` / `visual_references`):

| # | Field | Type | Default | Text limit |
|---|---|---|---|---|
| 1 | `name` | str | `""` (required non-empty) | 120 |
| 2 | `description` | str | `""` | 2000 |
| 3 | `target_audience` | str | `""` | 1000 |
| 4 | `campaign_objectives` | str | `""` | 1000 |
| 5 | `tone_of_voice` | str | `"professional"` | 80 |
| 6 | `preferred_vocabulary` | list[str] | `[]` | ≤50 items × 200 chars |
| 7 | `avoid_words_claims` | list[str] | `[]` | ≤50 items × 200 chars |
| 8 | `preferred_cta` | str | `""` | 500 |
| 9 | `hashtag_guidance` | str | `""` | 500 |
| 10 | `logo_path` | str\|None | `None` | 1000, confined to asset dir |
| 11 | `brand_colors` | list[str] | `[]` | `#RRGGBB` only |
| 12 | `fonts` | list[str] | `[]` | — |
| 13 | `visual_references` | list[str] | `[]` | confined to asset dir |

System fields added at runtime: `id` (uuid4), `created_at`, `updated_at`.

Frontend mirror (local, unexported type): `ml_test_ui/src/pages/BrandProfilesPage.tsx:24-42`
— identical 13 data fields. The API layer (`ml_test_ui/src/api.ts:405-417`) is `any`-typed.

Validation: `StudioStorage.validate_brand_profile` — `storage.py:178-210`.
**Rejects unknown keys** (line 188-189) — this is the main migration constraint for M2.

## 2. Which fields are persisted

All 13 fields + `id`/`created_at`/`updated_at` are persisted, one JSON file per profile:

- Profiles: `output/studio/brand_profiles/<uuid>.json` (`storage.py:35`, `_save_brand_profile` `storage.py:254-257`)
- Assets: `output/studio/brand_assets/<uuid>/…` (`storage.py:36`, `save_brand_asset` `storage.py:309-326`)
- Load/list/save/delete/duplicate: `storage.py:219-307` (duplicate deep-copies assets and rewrites paths)

There is **no database, no ORM, no migration framework** — plain JSON files.
One real profile exists on disk (`output/studio/brand_profiles/f273c615-….json`).

## 3. Which fields are actually consumed during generation

Consumed today (only on the Studio generate path):

| Stage | What reaches the model | Where |
|---|---|---|
| Fact record | `name, description, tone_of_voice, target_audience, preferred_vocabulary, avoid_words_claims, preferred_cta, hashtag_guidance` (empty values dropped) | `content_engine/studio/facts.py:58-64` |
| Prompt compaction | `brand_profile` kept in compact prompt JSON | `content_engine/copy_generator.py:97` (`_compact_prompt_facts`) |
| Prompt hints | "Follow the supplied brand tone and restrictions" | `copy_generator.py:623-625, 648-650` |
| CTA default | `preferred_cta` | `studio/content_orchestrator.py:72-73` |
| Hard validation | `avoid_words_claims` substring rejection | `content_orchestrator.py:323-326` |
| Compliance report | `_check_brand_rules` → `brand_compliance` | `content_orchestrator.py:382-410` |

**Not consumed at all:** `campaign_objectives`, `brand_colors`, `fonts`, `logo_path`,
`visual_references`.

**Dead code:** `StudioContentOrchestrator._build_brand_prompt_section`
(`content_orchestrator.py:346-380`) — a full "BRAND RULES:" prompt builder that is only
ever called from tests (`tests/test_brand_profiles.py:204,218`). Never invoked in production.

**Paths that receive NO brand profile:**
- Standard (non-Studio) pipeline — `content_engine/orchestrator.py` (captions L253-278,
  L454-479, L568-590; case study L284-290, L485-491, L592-598)
- Batch generation — `generate_all_captions_batch` (`copy_generator.py:553-607`)
- Reel captions / story captions — get only a raw context string (`copy_generator.py:661-721`)
- `/api/captions/regenerate` — `api/main.py:2153-2213`
- GFF pipeline — hardcoded StepOne voice (`gff/stepone_voice.py`)
- Case studies / AI reports — deterministic templates, no LLM
  (`case_study_generator.py:35-250`, enriched endpoint `api/main.py:1943-2088`)

## 4. Is brand selection connected to Studio?

**No.** `StudioPage.tsx` has a "Brand Mode" toggle (line 97) — that is the unrelated
GFF 4-brand photo-segregation feature with free-text names
(`BrandSegregationPanel.tsx`, `BRAND_COUNT = 4`). It never fetches
`/api/studio/brand-profiles`.

- No brand-profile selector exists anywhere in Studio.
- `setProjectBrandProfile` / `getBrandProfile` / `generateStudioPost`
  (`ml_test_ui/src/api.ts:382, 407, 411`) are **defined but never called** by any page.
- The backend project↔profile link (`project.brand_profile_id`, set via
  `api/studio_routes.py:395-415`) and the profile-aware generate route
  (`studio_routes.py:157-185`) are fully implemented but unreachable from the UI.

## 5. Does the selected brand survive refresh and job recovery?

**No.**

- Studio generation runs synchronously inside the request handler
  (`api/studio_routes.py:135-203`); job JSON is written after completion.
- What survives refresh: job id + event name (sessionStorage `ce_active_job_id`),
  job history (localStorage) — `StudioPage.tsx:144-145`, `App.tsx:66-100`.
- What does NOT survive: `brandMode`, brand names, selected brand, render files —
  plain `useState` (`StudioPage.tsx:97-100`).
- Celery/APScheduler jobs persist no `profile_id` at all (`api/tasks.py`, `api/scheduler.py`).
- Studio job meta = raw request body (`studio_routes.py:146`); the project's own
  `brand_profile_id` is **not** copied into job meta. Only on success does
  `result.brand_profile.id` land in the job JSON (`studio_routes.py:184-190`).
- There is no startup scan / resume / re-queue of pending jobs (`api/main.py:72-101`).

## 6. Do brand instructions reach local Qwen?

Partially — only LinkedIn and Instagram captions on the Studio path, and only via the
JSON `event_description` (fact record):

`studio_routes.py:157-177` → `content_orch.generate_post(brand_profile=…)` →
`facts.build_fact_record` → serialized into `event_description` →
`copy_generator._compact_prompt_facts:97` → `generate_linkedin_caption:611` /
`generate_instagram_caption:636` → `CopyGenerator._generate:487` → local Qwen.

Qwen integration itself (unchanged, local-only):
- `content_engine/llm/torch_backend.py` — `TorchTextGenerator` L103, `_load` L161-221
  enforces `local_files_only=True` (L181/192/197), offline env vars L27-31
- Model dir: `models/qwen/` (`QWEN_MODEL_PATH` `config.py:185`, `TORCH_LLM_MODEL=models/qwen` in `.env`)
- `providers/factory.py:23-35` rejects cloud backends outright
- Prompt is built inside `generate()` (`torch_backend.py:243-291`); brand context must be
  embedded upstream in the prompt string — **there is no brand injection point in the model layer**

Reel/story captions receive the fact record only as an unstructured raw context string,
so brand rules are effectively lost for those stages.

## 7. Do brand visual preferences influence image selection / composition?

**No.** `content_engine/layout_assembler.py`:
- `_burn_text` (L515-560): hardcoded — system font candidates, size 52, white fill,
  black shadow. No brand colors/fonts.
- `_apply_watermark` (L562-603): exists and works, but **no caller passes
  `watermark_path`** — brand `logo_path` is stored and never used in layout.
- Focal-point cropping (`composition/focal_analyzer.py`, `smart_crop` L138-207),
  manual crop overrides (`CropOverrideStore`, `composition/smart_crop.py:962-1029`,
  applied at `layout_assembler.py:117-134`) are fully implemented and must be preserved.
- No brand profile ever reaches layout/crop code.

---

## Summary matrix (audit questions 1-7)

| Question | Answer |
|---|---|
| All existing profile fields | 13 data fields + id/timestamps (see §1) |
| Persisted | Yes — all, as per-profile JSON files (no DB) |
| Consumed during generation | 8 of 13, Studio path only; LinkedIn+Instagram captions only (§3) |
| Brand selection connected to Studio | No — selector missing; backend link exists but UI never calls it (§4) |
| Survives refresh / job recovery | No — brand config ephemeral; jobs don't persist profile id (§5) |
| Brand instructions reach local Qwen | Partially — via fact-record JSON for2 caption stages only (§6) |
| Visual preferences influence images | No — colors/fonts/logo unused; crop & overrides preserved as-is (§7) |

## Key architectural assets to reuse (do not duplicate)

1. **Storage layer is complete**: CRUD, validation, asset confinement, duplication with
   asset copy, deletion — `content_engine/studio/storage.py:178-326`.
2. **API layer is complete**: 8 endpoints incl. duplicate/assets/project-link —
   `api/studio_routes.py:299-415`.
3. **Brand prompt machinery exists but unused**: `_build_brand_prompt_section` +
   `_check_brand_rules` (`content_orchestrator.py:346-410`) — should be superseded by the
   new BrandContextBuilder, with tests migrated.
4. **Fact record pipeline** (`facts.py:20-73`) is the current brand→prompt transport and
   the natural extension point for a richer BrandContext.
5. **Frontend CRUD page is complete** (`BrandProfilesPage.tsx`, 663 lines) — needs
   extension (sections, voice preview, summary), not replacement.
6. **Local Qwen is strictly offline** — brand context must be injected at prompt-build
   time, upstream of `TorchTextGenerator.generate`.

## Gaps to close in M2-M7

- G1: Rich schema (voice/audience/language/content/visual dimensions) + backward-compatible
  migration (validator currently rejects unknown keys — `storage.py:188`).
- G2: Central `BrandContextBuilder` producing a structured context consumed by every
  generation stage (LinkedIn, IG, hashtags, stories, reels, case studies, reports,
  regenerate, rewrite, batch/background).
- G3: Brand Voice Preview endpoint using local Qwen only.
- G4: Studio brand-profile selector with persistence (current job) and recovery.
- G5: Persist `brand_profile_id` in job meta for all job backends.
- G6: Wire `brand_colors`/`fonts`/`logo_path` into `_burn_text`/`_apply_watermark`
  without touching crop logic or model weights.
- G7: Tests proving two distinct brands produce observably different output
  (semantic constraints + a real local-Qwen acceptance test).
