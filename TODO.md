# TODO

- [x] Fix 1: `api/main.py` — `/api/jobs/{job_id}/result` should return Redis result immediately when `status == SUCCESS` and `job:{job_id}` payload exists.
- [x] Fix 2: `api/main.py` — `/api/assets/enhanced/{job_id}` should read completed job payload from Redis and populate `top_overall` / `per_category` instead of returning `pending_processing: true` + empty arrays.
- [ ] Fix 3: Frontend navigation trigger — verify polling/onDone path triggers results navigation when job completes (may be implicitly fixed by Fix 1).
- [x] TS cleanup: `ml_test_ui/src/components/CaseStudyReport.tsx` remove unused imports `BarChart3` and `Users`.
- [x] TS cleanup: `ml_test_ui/src/components/export/BulkDownload.tsx` remove unused import `Download` and fix duplicate `border` property.
- [x] TS cleanup: `ml_test_ui/src/pages/AssetSelectionPage.tsx` remove unused import `X`.

- [ ] Run tests/build: backend `pytest` and frontend `npm run build` (or `npm run typecheck`) if available.

