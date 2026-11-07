# IMPLEMENTATION ROADMAP

Based on verified findings from the audit. Work in vertical slices, test each thoroughly.

## Phase 0: Environment Setup (BLOCKING) - Priority P0
**Goal:** Get a working development environment so we can run tests and the application.

| Task | Files | Acceptance Criteria | Verification |
|------|-------|---------------------|--------------|
| **0.1 Create proper Python venv** | - | Python 3.11 venv created | `python --version` shows 3.11 |
| **0.2 Install dependencies** | `requirements.txt` | All deps installed without conflicts | `pip list` shows key packages |
| **0.3 Install system deps** | - | ffmpeg, libmagic installed (macOS: brew install ffmpeg libmagic) | `ffmpeg -version`, `brew list libmagic` |
| **0.4 Setup .env** | `.env` | Valid .env with required vars | App can load config |
| **0.5 Run tests** | `tests/` | Tests execute (some may skip/fail due to missing models) | `pytest tests/ -v` runs |

## Phase 1: Understand & Fix Critical Gaps - Priority P0/P1
**Goal:** Address issues that block understanding/verifying the product.

| Task | Files | Acceptance Criteria | Verification |
|------|-------|---------------------|--------------|
| **1.1 Find/implement brand-clusters endpoint** | `api/main.py`, `api/gff_routes.py` | Frontend can call it without 404 | Check endpoint exists and returns expected format |
| **1.2 Verify API health and basic endpoints** | `api/main.py` | `/health` returns OK | `curl http://localhost:8000/health` |
| **1.3 Test frontend builds** | `ml_test_ui/` | `npm run build` succeeds | Build completes without errors |

## Phase 2: Trace and Verify Core Workflows - Priority P1
**Goal:** Verify the two core pipelines work (content generation and design/layout).

| Task | Files | Acceptance Criteria | Verification |
|------|-------|---------------------|--------------|
| **2.1 Trace standard content workflow end-to-end** | `orchestrator.py`, `pipeline.py`, `layout_assembler.py` | Understand full flow with code paths | Document trace, identify any breaks |
| **2.2 Trace brand/GFF workflow end-to-end** | `brand_orchestrator.py`, `gff/orchestrator_gff.py`, `brand_segregator.py` | Understand brand segregation flow | Document trace, verify CLIP matching logic |
| **2.3 Test with small sample data** | Test assets | Run pipeline on few images | Verify outputs created correctly |
| **2.4 Verify content-to-design connection** | Orchestrator | Confirm ML selections drive layout choices | Trace intended_use routing |

## Phase 3: Fix Broken Functionality - Priority P1
**Goal:** Fix actual bugs found during tracing/testing.

| Task | Files | Acceptance Criteria | Verification |
|------|-------|---------------------|--------------|
| **3.1 Address any import errors** | Various | All modules import cleanly | `python -c "import api.main; import content_engine.orchestrator"` |
| **3.2 Fix missing endpoints** | API files | All frontend-called endpoints exist | Test each endpoint |
| **3.3 Fix configuration issues** | `config.py`, `.env` | Config loads correctly | App starts without config errors |

## Phase 4: Polish & Optimize - Priority P2
**Goal:** Address technical debt and improve reliability.

| Task | Files | Acceptance Criteria | Verification |
|------|-------|---------------------|--------------|
| **4.1 Add basic auth consideration or document** | Docs | Clear documentation of usage scope | Update README if needed |
| **4.2 Clean up repo** | `.gitignore` | Add `__pycache__`, model weights if large | Verify .gitignore |
| **4.3 Improve error handling** | API files | Better error messages | Test failure cases |
| **4.4 Security review fixes** | Various | Address critical security issues | Review checklist |

## Recommended First Task

**START WITH PHASE 0.1-0.5: Environment Setup**

The environment is broken (wrong Python version, broken venv paths). Nothing can be tested or verified until this is fixed. This is blocking all other work.

**Order of operations:**
1. Fix environment first
2. Run tests to see baseline
3. Start the API and UI to manually test
4. Trace workflows with real code execution
5. Fix issues as discovered

## Notes

- The "Design Engine" is actually automated layout composition, not a canvas editor. The connection between content and design (orchestrator routing by intended_use) is implemented.
- Both pipelines exist: standard content pipeline and GFF brand segregation pipeline.
- Heavy ML models mean first run will be slow and need disk space.
