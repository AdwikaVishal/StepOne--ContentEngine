# TECHNICAL DEBT

## Critical (P0)

| ID | Issue | Location | Impact | Root Cause | Suggested Fix |
|----|-------|----------|--------|------------|---------------|
| **TD-001** | Python environment broken | `.venv/` | Cannot run tests, may have runtime issues | Venv created on different machine/path, Python version mismatch (3.14 vs <3.12) | Create fresh venv with Python 3.11, reinstall deps |
| **TD-002** | "Design Engine" unclear/incomplete | Throughout | Misleading product positioning vs implementation | Naming doesn't match implementation | Either add true design editor features or rename/reframe as "Content Engine with Automated Layouts" |

## High (P1)

| ID | Issue | Location | Impact | Root Cause | Suggested Fix |
|----|-------|----------|--------|------------|---------------|
| **TD-003** | Missing brand-clusters endpoint | `api/main.py` or routes | Frontend calls it but not found in gff_routes | Possibly missing implementation | Implement or remove frontend call |
| **TD-004** | No database/persistence layer | Throughout | Jobs/results only in memory/files, no history, no multi-user | Simple local-first design | Consider adding SQLite/Postgres if multi-user needed |
| **TD-005** | Heavy ML model loading | All ML modules | Slow startup, high memory usage | All models loaded eagerly or on first use | Lazy loading exists but could be optimized, consider model quantization |
| **TD-006** | No authentication/authorization | `api/main.py` | Security risk if exposed | Local/dev tool design | Add auth if network accessible, or document clearly |

## Medium (P2)

| ID | Issue | Location | Impact | Root Cause | Suggested Fix |
|----|-------|----------|--------|------------|---------------|
| **TD-007** | Large files in repo | Root | Repo bloat | `yolov8n.pt` (6.5MB) committed, models may be large | Use .gitignore for model weights, download on demand |
| **TD-008** | Code duplication | Various | Maintenance burden | Rapid development | Refactor common patterns |
| **TD-009** | Limited error messages | API/UI | Hard to debug failures | Basic error handling | Improve error messages and logging |
| **TD-010** | No rate limiting | `api/main.py` | DoS vulnerability | Not implemented | Add rate limiting middleware |
| **TD-011** | Subprocess usage without full sanitization review | LayoutAssembler, API | Potential command injection | ffmpeg/ffprobe called with paths | Audit all subprocess calls for injection risks |
| **TD-012** | Frontend has fallback logic for missing backend features | `ml_test_ui/src/api.ts` | Masks missing API implementations | Defensive coding | Ensure backend APIs exist or remove fallbacks |
| **TD-013** | No tests executable in current env | `tests/` | Can't verify changes | Environment broken | Fix environment |

## Low (P3)

| ID | Issue | Location | Impact | Root Cause | Suggested Fix |
|----|-------|----------|--------|------------|---------------|
| **TD-014** | Many .pyc files in repo | `__pycache__/` dirs | Repo clutter | Committed to git | Add to .gitignore |
| **TD-015** | TODO/FIXME comments | Various | Technical debt markers | Unfinished work | Address or track in issues |
| **TD-016** | Inconsistent logging | Mixed patterns | Hard to debug | Some use structlog, some use print | Standardize on structlog |
| **TD-017** | Hardcoded values | LayoutAssembler dimensions etc. | Less flexible | Platform-specific outputs | Make configurable where reasonable |

## Observations

- **Good patterns:** Lazy loading, dual job backends, graceful fallbacks, comprehensive API
- **Architecture is solid** for its purpose (automated content generation)
- **Brand segregation is well-implemented** with good test coverage
- **Main issue is environment/setup** preventing verification
