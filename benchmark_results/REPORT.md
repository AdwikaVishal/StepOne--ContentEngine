# Local model benchmark report

**Date:** 2026-10-28  
**Machine:** MacBook Air M2, 8 GB unified memory  
**Production status:** Qwen remains the production default. No production model or Studio workflow was changed.

## Result

The text comparison is **inconclusive**. Qwen 2.5 1.5B and Gemma 3 1B both loaded from their existing caches under the project virtual environment, but neither completed its first bounded CPU generation prompt before the configured manual stop. There are no text outputs, generation latencies, or schema pass results to compare. The earlier system-Python runs exited with signal 11. This is evidence of a runtime incompatibility in that environment, not evidence that either model is defective.

BLIP Base passed a real local image-captioning smoke test. It is an image captioner and was not treated as a text-generation competitor.

## Audit and environment

- Production generation is Qwen-only. `content_engine/copy_generator.py` directly loads Qwen with `local_files_only=True`, a hard-coded cache snapshot fallback, `torch.float32`, and CPU placement when CUDA is absent. That path does not select Gemma through configuration.
- `content_engine/captioning/providers/local_provider.py` is a separate lazy local provider. It exposes model/path environment variables, but the factory and Studio integration enforce Qwen. This is not a second production selection path for Gemma.
- `content_engine/studio/content_orchestrator.py` catches LinkedIn and Instagram generation errors and substitutes literal fallback copy. This is a pre-existing silent fallback despite the Qwen-only/no-template-fallback requirement; it was reported but left unchanged to preserve the production workflow.
- The repository has Florence-2 and CLIP vision analysis, but no Salesforce BLIP application integration. The BLIP check below is an isolated benchmark smoke test.
- `pyproject.toml` declares Python `>=3.9,<3.12`; `requirements.txt` pins Transformers to `>=4.35,<5.0`. No supported Python interpreter was present on this host.
- The project `.venv` is Python 3.13.18, torch 2.14.1, Transformers 4.57.6, tokenizers 0.22.2, huggingface-hub 0.36.2, accelerate 1.15.0, safetensors 0.8.0. Transformers is within the project range; Python is not.
- System Python is 3.15.0 with torch 2.14.1, Transformers 5.21.0, tokenizers 0.23.3, and huggingface-hub 2.3.0. Both its Python and Transformers versions are outside project constraints.
- Both PyTorch installations report MPS built in but unavailable (`torch.backends.mps.is_available() == False`). Dynamic quantization was probed; the quantized engine is `none`, and a small `Linear` conversion failed with `NoQEngine`.
- Gemma access is governed by Google's usage license; the [Hugging Face model page](https://huggingface.co/google/gemma-3-1b-it) says users must review and agree to it. The existing local cache is complete and loads in the `.venv`.
- `pgrep` could not enumerate host processes (`sysmon service not found`). I used the tool-managed session IDs for the benchmark processes I started and stopped only those specific sessions; no unrelated Python process was targeted.

## Cache verification

All requested local checkpoints are complete. No weights were downloaded or removed during this continuation.

| Model | Verified cached file | Size |
|---|---|---:|
| Qwen 2.5 1.5B | `model.safetensors` | 3,087,467,144 bytes |
| Gemma 3 1B Instruct | `model.safetensors` | 1,999,811,208 bytes |
| BLIP Base | `pytorch_model.bin` | 989,820,849 bytes |

## Text-model attempts

The deterministic prompt set remains in [`benchmarks/model_prompts.json`](../benchmarks/model_prompts.json). The quick comparison selects LinkedIn, Instagram, and structured JSON; `--full-suite` keeps all ten scenarios available.

| Model / configuration | Load result | Generation result | Process memory |
|---|---|---|---|
| Qwen, system Python 3.15 / Transformers 5.21, float32 CPU | Process exited 139 (SIGSEGV) | No output; no Python traceback was produced | Not measured |
| Gemma, system Python 3.15 / Transformers 5.21, float32 CPU | Process exited 139 (SIGSEGV) | No output; no Python traceback was produced | Not measured |
| Qwen, `.venv` Python 3.13 / Transformers 4.57.6, bfloat16 CPU, 96-token cap | Loaded in 0.579 s | Stopped after about 3 minutes before prompt 1 completed | 439.5 MiB process high-water after load; incomplete inference peak unavailable |
| Qwen, same runtime, bfloat16 CPU, 48-token cap, 4 threads | Loaded in 0.598 s | Stopped after about 90 seconds before prompt 1 completed | 334.0 MiB process high-water after load; incomplete inference peak unavailable |
| Gemma, same runtime, bfloat16 CPU, 48-token cap, 4 threads | Loaded in 1.092 s | Stopped after about 90 seconds before prompt 1 completed | 725.1 MiB process high-water after load; incomplete inference peak unavailable |

These RSS values are process high-water readings taken after loading, before a prompt completed. They are **not** peak inference memory. System-wide `memory_pressure -Q` snapshots during the CPU runs showed 31–36% free memory; these are snapshots, not model-attributed measurements. Time to first token is unavailable because this Transformers `generate()` call is non-streaming.

The interrupted attempts and their reasons are preserved in [`benchmark_results/three_prompt_bf16/qwen.json`](three_prompt_bf16/qwen.json) and [`benchmark_results/three_prompt_bf16_48/`](three_prompt_bf16_48/). No semantic quality score is claimed. There are no generated text outputs for manual review, no JSON schema-validity result, and no quality basis for replacing Qwen.

### Signal-11 investigation

The system-Python runner produced the Transformers `torch_dtype` deprecation warning and a macOS distributed-redirect warning, then exited with status 139 / signal 11 during model loading, without a Python traceback. The captured evidence is in [`runtime_signal11.json`](runtime_signal11.json). Under the existing `.venv` (Python 3.13, Transformers 4.57.6), both models loaded successfully; Gemma's bfloat16 load took 1.092 seconds. That isolates the crash to the system runtime path more strongly than to the cached model, while Python 3.13 remains outside the repository's declared support range. No dependency upgrade or virtual-environment replacement was attempted.

## BLIP real-inference smoke test

- Command: `./.venv/bin/python scripts/smoke_blip_caption.py`
- Image: `test_photos/download.jpg` (`download.jpg`, 201 × 251 RGB).
- Model: `Salesforce/blip-image-captioning-base`, loaded locally, CPU float32.
- Load time: 0.357 s. Caption latency: 3.167 s. Peak process RSS: 1,003.8 MiB.
- Output: “a woman with a large afro hairs”. This is an unverified visual caption, not a verified identity or other factual claim.
- Result: **1 real image-captioning inference passed**. Batch association, multiple-image failure handling, BLIP-to-text integration, and Studio pipeline behavior were not tested.

Full measurements are saved in [`benchmark_results/blip_smoke.json`](blip_smoke.json).

## Commands and tests

Commands used for the finalized smoke and focused tests:

```sh
./.venv/bin/python scripts/smoke_blip_caption.py
./.venv/bin/python -m py_compile scripts/benchmark_local_models.py scripts/smoke_blip_caption.py tests/test_benchmark_suite.py
./.venv/bin/python -m pytest -q tests/test_benchmark_suite.py
./.venv/bin/python -m pytest -q tests/test_benchmark_suite.py tests/test_qwen_only.py tests/test_local_provider.py tests/test_copy_generator.py tests/test_studio.py
```

- Benchmark unit tests: **3 passed**.
- Focused benchmark and regression tests: **12 passed, 2 failed, 9 skipped**.
- Existing failures: `test_local_only_raises_without_model` expects no cached Qwen model, but Qwen is present; `test_template_only_works` expects template-only factory access, which current Qwen-only factory code intentionally rejects. These are existing environment/code expectation mismatches; no application code was changed to alter them.
- The full repository test suite was not run.
- The benchmark harness now checkpoints after every prompt, can resume completed prompt IDs, saves logs, runs models in separate sequential child processes, and applies a per-model timeout. The complete ten-prompt suite remains available with `--full-suite`.

Text-model commands and outcomes:

```sh
python3 scripts/benchmark_local_models.py --models qwen
python3 scripts/benchmark_local_models.py --output-dir benchmark_results --_model-child gemma
./.venv/bin/python scripts/benchmark_local_models.py --output-dir benchmark_results/three_prompt_bf16 --models qwen gemma
./.venv/bin/python scripts/benchmark_local_models.py --output-dir benchmark_results/three_prompt_bf16_48 --models qwen gemma --max-new-tokens 48 --torch-threads 4
./.venv/bin/python scripts/benchmark_local_models.py --output-dir benchmark_results/three_prompt_bf16_48 --models gemma --max-new-tokens 48 --torch-threads 4
```

The first two system-Python attempts exited 139 / signal 11. The `.venv` bfloat16 runs loaded the models but were manually stopped after the recorded no-output intervals. The timeout-enabled, log-writing parent harness was added afterward and has not yet been exercised end to end.

## Recommendation

Keep Qwen as the production default and do not switch to Gemma on this evidence. Neither text model produced reviewable output under the available CPU configuration, so quality and schema validity remain unknown. The host's PyTorch reports MPS unavailable, and dynamic quantization is unsupported by its current quantized backend. For an 8 GB M2, first establish a supported Python runtime and a working Apple Silicon inference backend or a validated quantized runtime for the existing Qwen model; then rerun the saved three-prompt comparison. The initial model-comparison phase made no production changes.

## Continuation update (2026-10-28)

### Runtime and MPS gate

- Python 3.11 is not installed. Homebrew currently has Python 3.13 and 3.15 only. No .venv311 was created and no packages or model weights were installed or removed. Exact user-run setup command: brew install python@3.11.
- Existing .venv remains unchanged: Python 3.13.18, torch 2.14.1, Transformers 4.57.6, tokenizers 0.22.2, Hugging Face Hub 0.36.2. pip check reports “No broken requirements found”, but this is not a supported project runtime because pyproject.toml requires Python <3.12.
- MPS diagnostic in .venv: platform.machine() == arm64, macOS 27.0.1, torch 2.14.1, is_built() == True, is_available() == False. No MPS tensor op or Qwen inference was attempted. No new CPU inference was attempted because MPS is unavailable and earlier CPU runs were too slow.

### Harness validation

The harness now writes checkpoints atomically (temporary file + os.replace) so a failed write cannot truncate the last saved report. Resume merges old and requested prompt IDs and deduplicates by prompt ID while retaining a completed result. Model children run in their own process group; a timeout sends SIGTERM, waits five seconds, then sends SIGKILL to that group only. Reports distinguish load_failure, inference_failure, timeout, success, and process_failure. Loading uses local_files_only=True for tokenizer and model, and the parent sets Hugging Face offline flags. JSON schema validity is a separate field from the human semantic review note.

### Studio failure behavior

LinkedIn and Instagram Qwen exceptions now raise a safe StudioGenerationError; literal fallback captions are no longer returned. The API stores and returns an actionable safe message with HTTP 503, while logging internal exception details server-side. The multi-image Studio frontend displays the API detail in its error toast, with a generic safe message for non-API failures. Successful Qwen caption text remains unchanged. Qwen remains the production model; Gemma and BLIP are not integrated into Studio.

### Current validation

- Focused benchmark, Studio generation-error, Studio storage, and Qwen-only factory tests: **15 passed, 1 deselected**. The deselected test would start real Qwen generation.
- Frontend production build: npm run build passed. Vite emitted its existing large-chunk advisory.
- No Qwen inference was run in this continuation. The previous text comparison remains inconclusive; no model quality or text schema-validity conclusion is made.

## End-to-end mission follow-up (2026-10-28)

This section supersedes earlier statements in this report about whether Studio uses BLIP or whether the timeout-enabled harness has been exercised.

### Local inference and environment

- Repository constraints remain Python `>=3.9,<3.12` and Transformers `>=4.35,<5`. Python 3.11 is not installed (`command -v python3.11` returned no path); no `.venv311` was created and `.venv` was preserved. Manual setup command: `brew install python@3.11`.
- `.venv` versions: Python 3.13.18, torch 2.14.1, Transformers 4.57.6, tokenizers 0.22.2, Hugging Face Hub 0.36.2. `pip check` says no broken requirements. The runtime is still outside the project's declared Python support range.
- MPS: arm64, macOS 27.0.1; `is_built() == True`, `is_available() == False`. No tensor or model operation was attempted on MPS. No `llama.cpp`/Ollama runtime or local GGUF model was found.
- Qwen cache is complete at 3,087,467,144 bytes. A bounded local-only run used: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python scripts/benchmark_local_models.py --models qwen --output-dir benchmark_results/mission_smoke --run-timeout-seconds 60 --max-new-tokens 32`. Qwen loaded in 2.957 s, then timed out before prompt 1 completed. It produced no text, latency, or schema result. RSS was 441.7 MiB after load; peak inference RSS is unavailable because the process timed out before recording it. The report and log are in [`mission_smoke/`](mission_smoke/). The harness terminated its own child. Gemma was not rerun because Qwen has not completed a prompt.
- BLIP cache is complete at 989,820,849 bytes. A local-only real inference on `test_photos/download.jpg` returned “a woman wearing a dress” with `caption_status=completed`: load 4.831 s, total 7.777 s, process peak RSS 1,079.9 MiB. This is one uncertain caption, not factual verification or evidence of text-generation quality.

### Production and image workflow changes

- Qwen remains the only production text provider; Gemma and hosted text APIs were not selected. `CopyGenerator` now loads Qwen lazily, uses the configured local model path when supplied, and never downloads at runtime. Story and brand-aware caption methods no longer substitute template copy after inference failure; empty output is an error. Template helper functions remain outside generation fallback paths.
- Studio LinkedIn/Instagram errors are raised as safe `StudioGenerationError`s, persisted on the failed job, returned with HTTP 503, and shown in the frontend toast without stack traces or paths. The frontend build succeeded.
- The Studio prompt now carries selected image captions explicitly as uncertain, unverified visual cues. Caption records are joined by asset ID, individual caption failures remain attached to the correct asset, and duplicate selection now ranks candidates before retaining the best item from a duplicate set. BLIP is already present in the checkout's Studio analysis flow; this work did not add another vision model or publishing integration.
- `api.main`'s model preloader was using a nonexistent `ContentUnderstander.clip_model` property; it now accesses `clip`. After correction, `bash start_dev.sh` completed startup and preloaded its models in 59.46 seconds. The app served the Studio page and API during verification (Vite HTTP 200; OpenAPI HTTP 200, 49 paths). Publishing endpoints were not invoked; both dev servers were stopped after verification.

### Tests and verification

- Focused benchmark, local-provider, copy-generator, Studio, image-intelligence, and ingestion tests: **52 passed, 8 warnings**. Model output in these unit tests is mocked; this does not count as a real text-generation pass.
- Full suite: **173 passed, 6 failed, 6 errors**. All 12 failures/errors are in legacy image-quality/content-understanding tests and share `ModuleNotFoundError: optree` during the installed Torch/Transformers import path. No dependency was installed into the unsupported `.venv`.
- Frontend: `npm run build` passed; Vite reported the existing large-chunk advisory.
- `python -m py_compile` for changed Python files passed. `git diff --check` still reports trailing whitespace in pre-existing modified files `api/tasks.py`, `content_engine/models/video_processing.py`, and `ml_test_ui/src/pages/AssetSelectionPage.tsx`; those unrelated edits were left untouched.
- Local server verification: `bash start_dev.sh`; Vite page HTTP 200 and FastAPI OpenAPI HTTP 200. The dev processes were stopped after verification. There was no successful real Qwen inference and no actual Studio generation, editing, or draft journey with generated text.

### Recommendation and remaining action

Keep Qwen selected, but do not describe local text generation as working on this host yet. Install Python 3.11 (`brew install python@3.11`), create a separate compatible environment, verify MPS availability there, and only then retry one short Qwen smoke test. If MPS remains unavailable, evaluate an explicitly licensed, locally available quantized Qwen runtime before any model conversion or production switch. The full suite also needs `optree` resolved in a supported environment. No Qwen/Gemma weights were downloaded or deleted.

## Python 3.11 / Qwen MPS continuation (2026-10-28)

### Supported environment

`pyproject.toml` requires Python `>=3.9,<3.12`. Homebrew Python 3.11 was installed with `brew install python@3.11`; `.venv311` was created separately and the prior `.venv` was preserved. Versions in `.venv311`: Python 3.11.18, PyTorch 2.15.0, Transformers 4.57.6, tokenizers 0.22.2, Hugging Face Hub 0.36.2, optree 0.20.0. PyTorch/Transformers imports succeeded and `python -m pip check` reported no broken requirements. `optree>=0.13.0` was added to requirements because PyTorch declares it as its optree extra dependency.

The first six failures plus six errors reproduced in the old `.venv` all traced to `ModuleNotFoundError: optree`. A separate quality test attempted an unintended Hugging Face network retry because it exercised CLIP without a local model cache; the score calculation is now isolated with a deterministic mocked CLIP score. A Studio unit test that previously loaded Qwen was changed to use a mock; real inference is covered by separate smoke scripts. With offline flags, the full suite passes: **191 passed, 3 warnings**. These are unit/regression tests, not evidence of model quality. Warnings are Starlette/httpx and FastAPI lifecycle deprecations.

### MPS and real local Qwen inference

Inside the restricted test sandbox, MPS reported unavailable. A native diagnostic outside that restriction confirmed Apple Silicon (`arm64`, macOS 27.0.1), PyTorch 2.15.0 with `mps.is_built() == True` and `mps.is_available() == True`; an MPS tensor matrix multiplication returned the expected result. No model weights were downloaded; the Qwen smoke process disabled Hugging Face network access and used `local_files_only=True`.

One standalone Qwen prompt completed on MPS float16. Load (tokenizer plus model): 35.320 s; prompt preparation: 0.127 s; tokenization: 0.119 s; generation: 8.760 s for 29 tokens. Process peak RSS was 1807.8 MiB; PyTorch MPS allocator reported 2968.8 MiB current allocated and driver memory 3162.7 MiB. RSS excludes GPU/driver accounting, which is reported separately. Exact output: “Welcome to our vibrant community meetup! Let's explore new ideas and connect with like-minded individuals who share your passion for [insert topic here].” The output is nonempty but leaks a placeholder, so it is a successful inference and a failed quality check. Full measurements: `qwen_mps_single.json`.

A real Studio API journey also completed with HTTP 200 and a persisted completed job on MPS float16, but generated instruction leakage and unsupported embellishments. Its exact output and timings are retained in `studio_api_qwen.json`; do not treat this as an acceptable content-quality result. The Studio validator now rejects common prompt leakage, unfinished placeholders, and unverified links with sanitized actionable errors. A regression case covers “End each line with a hashtag.” The API journey predates the final broadened leakage pattern; the final rejection behavior is unit-tested, but a second API inference after that regex change was not run.

### Studio behavior and validation

Production remains Qwen-only. Local loading is offline-only and uses MPS float16 when MPS is available, otherwise the prior CPU fallback; no Gemma/BLIP production selection was introduced. Failed Studio generation no longer silently becomes literal copy: it raises a safe Studio error, and API failure handling persists the failed job and returns a sanitized message. The Studio UI displays that message without exposing traceback details. Provider output is preserved when validation succeeds.

Commands:

```sh
brew install python@3.11
python3.11 -m venv .venv311
.venv311/bin/python -m pip install -r requirements.txt
.venv311/bin/python -m pip check
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv311/bin/python -m pytest -q --tb=short
npm run build --prefix ml_test_ui
.venv311/bin/python scripts/smoke_qwen_mps.py --timeout-seconds 180
.venv311/bin/python scripts/smoke_studio_api_qwen.py --timeout-seconds 180
```

For local development with the validated runtime, run backend and frontend separately:

```sh
.venv311/bin/uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
npm run dev --prefix ml_test_ui
```

The build passed with Vite's advisory about several chunks over 500 kB. Final `git diff --check` still reports unrelated pre-existing whitespace in `api/tasks.py`, `content_engine/models/video_processing.py`, and `ml_test_ui/src/pages/AssetSelectionPage.tsx`; these were not edited as part of this work. A process check found no benchmark, pytest, uvicorn, or Vite processes left running.

### Recommendation and remaining work

The Python/runtime and MPS blockers are resolved, and real Qwen generation works. Keep Qwen selected, but do not treat this as approval of generated content quality: the sample placeholder leakage is unacceptable and the Studio API sample repeated instructions. The safe validation now blocks those known artifacts. Remaining useful work is a further prompt/decoding evaluation and one new API smoke after the validator change; no Gemma run was made, and no model replacement is warranted from this evidence.

## Studio generation quality continuation (2026-10-28)

### Audit and changes

The prior real API result in `studio_api_qwen.json` showed one flat user prompt and generated instruction leakage, placeholders, embellished details, and a token-limit LinkedIn output. Studio was concatenating the event brief, visual captions, and brand profile text; image captions were then sent in the same description string as verified facts. The production provider did not apply Qwen's chat template, although the standalone smoke did.

`_LocalLLMGenerator.generate` now applies the tokenizer's chat template with distinct system and user messages. LinkedIn and Instagram use separate concise system instructions and platform-specific user briefs with deterministic decoding and smaller caps (112 and 48 new tokens). Studio no longer sends image caption text or visual scene concepts as verified facts; those captions remain marked uncertain in the response metadata. Brand rules remain included in the user content. No provider/model switch or hosted inference path was added.

Studio validation now rejects empty output, unfinished placeholders, prompt leakage, unexpected links/numbers, common unprovided time/schedule/offer claims, selected unsupported promise language, excessive length, and debug text. It retries a validation rejection once with a bounded corrective instruction, then raises a sanitized error. It does not claim to prove semantic truth: these checks are intentionally heuristic and cannot catch every unsupported statement. A rejected caption is never saved as generated content. The API persists a failed job and returns a sanitized HTTP 503. The Studio UI shows the returned detail in its error toast; accepted content is set from the same API response.

### Real local Qwen evaluations

`studio_quality_qwen.json` records three sequential synthetic cases, with raw output per attempt, prompt/system text, token counts, latency, retries, decisions, model load time, RSS, and MPS allocator readings. Qwen used local cached weights only, network disabled, MPS float16. Load was 20.33 s; process peak RSS was 2219.7 MiB; MPS allocator reported 2968.8 MiB current and 3172.7 MiB driver memory.

- LinkedIn factual meetup: Qwen twice claimed it could transform/improve the neighborhood; after one retry, rejected. Latencies 6.86 s and 3.27 s (47 and 46 tokens). No caption returned as successful.
- Instagram factual open studio: accepted in 3.23 s (33 tokens): “Join us at Harbor Lab's Open Studio! Share your thoughts on our students' designs. Let's create together! #HarborLabOpenStudio #DesignCommunity”. This is concise and tracks the supplied student-design and feedback brief; semantic review remains human-level/heuristic.
- Uncertain image-caption case: source visual caption claimed a famous actor, a sold-out event, and 500 attendees. None of that text was included in the model prompt. Qwen twice invented an evening and additional social claims, so both outputs were rejected after one retry. Latencies 2.71 s and 2.79 s (33 tokens each). The uncertain visual text did not leak into the accepted content because no caption was accepted.

The real API journey after the changes used the synthetic Cedar Circle brief. The provider generated two outputs, both inventing unsupported “today/day/night” timing. The API returned **503**, persisted job `598bb056-c693-4254-8282-b162805073ed` as **failed**, and returned `Qwen could not produce a caption that passed the content checks. Edit the brief and retry.` No caption was saved to the project; raw model outputs and latency (4.78 s and 3.03 s) remain only in the local smoke report. No paths, stack traces, secrets, or raw model output were returned to the client. This is a correct rejection, not a successful API generation.

The report's `saved_matches_api_output` field is false for this rejection because there is intentionally no accepted API output to match; `saved_output` is null. Interpret `api_outcome: rejected_and_persisted` together with the failed job, 503 response, and absent saved output.

### Regression verification

With the following final command, **197 passed, 3 warnings**:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv311/bin/python -m pytest -q --tb=short
npm run build --prefix ml_test_ui
```

The frontend build passed with the existing Vite chunk-size advisory. `git diff --check` reports whitespace only in pre-existing unrelated edits to `api/tasks.py`, `content_engine/models/video_processing.py`, and `ml_test_ui/src/pages/AssetSelectionPage.tsx`; those lines were left untouched. Process inspection found no smoke, pytest, Uvicorn, or Vite process left running.

### Remaining limits

Qwen remains the production model, but overall content quality is not fully reliable. One Instagram caption passed; two other cases were appropriately rejected after retry. The checks catch known failure patterns but cannot establish truth for every natural-language claim. For this 1.5B model, keep the clear failure behavior, review accepted copy before publication, and expand groundedness checks only against explicit structured brief facts rather than pretending a keyword heuristic guarantees truth. No content was published externally.

## Structured Studio facts and controlled acceptance evaluation (2026-10-28)

### Implementation

Added `content_engine/studio/facts.py` to build a JSON fact record from the explicit Studio inputs. It carries the event name, user brief, activity, audience, date, time, location, organizer, CTA, key points, tone, and selected brand guidance. Labeled date/time/location/organizer/activity/CTA values are extracted verbatim from the brief; explicit request fields override those. Missing values remain `null`. Uncertain image captions and detected image concepts are excluded from generation facts.

The generation provider now compacts that record before prompting, leaving null fields out while keeping the original full record for validation and audit. Platform-specific prompts request one short factual sentence; system instructions use the fact record and prohibit additions. Decoding remains deterministic, local, and Qwen-only. The API forwards optional activity/date/time/location/organizer inputs to the orchestrator.

Validation checks explicit dates/times, numbers, URLs, multiword named entities, venue wording when location is missing, bracketed fill-ins, recognized schedule/offer/outcome language, internal/debug text, platform length, and brand forbidden terms. There is one bounded retry with a correction tailored to the first rejection reason. The API still returns only sanitized errors and persists rejected jobs as failed. As the evaluation shows, these deterministic checks are incomplete; an accepted caption can still contain unsupported semantic claims.

### Real local evaluation

The same original three synthetic briefs were retained, with five new synthetic briefs for missing event details, supplied date/location, brand tone, and additional Instagram/LinkedIn announcements. They ran sequentially in one local Qwen process with Hugging Face offline flags, cached weights, MPS float16, `do_sample=False`, and no weight download. Per-attempt prompt, raw output/error, tokens, latency, retry, structured fact record, decision, RSS, and MPS memory are saved in `studio_quality_qwen.json`.

Final run: model load **22.55 s**, peak process RSS **1459.5 MiB**, MPS current allocation **2968.8 MiB**, driver allocation **3172.7 MiB**. Automatic validation accepted **1/8** and rejected **7/8**, with one bounded retry for each invalid initial result. Manual review of the single automatically accepted Willow Library caption found “for all ages,” which was not supplied. Therefore **0/8 are established as fully grounded/publishable** by this evaluation; the checks are heuristics, and human review remains necessary.

| Case | Automated result | Observed issue / decision |
|---|---|---|
| Original factual LinkedIn | Rejected | Qwen emitted `[insert date]` / `[date]` on both attempts. |
| Original factual Instagram | Rejected | Initial generation hit the token cap; retry exceeded the cap. |
| Original uncertain image caption | Rejected | Qwen invented time/venue language; uncertain image text was not in the prompt. |
| Missing details | Rejected | Qwen added unsupported audience/outcome wording. |
| Supplied date and location | Rejected | Qwen added an unprovided LinkedIn URL and event/offer claims on retry. |
| Brand tone constraints | Rejected | Qwen added unprovided timing and gift/memory claims. |
| Additional Instagram brief | Automatically accepted, not human-approved | Output added “for all ages,” which was absent from the input. |
| Additional LinkedIn announcement | Rejected | Retry still introduced a date placeholder. |

Baseline comparison from the previous real evaluation: **1/3 automatically accepted** on the original set (the Instagram caption only). On the final run, the same three produced **0/3** automatic acceptance. Across all eight, the automatic acceptance fraction was 1/8, but that sole pass failed manual grounding review. Thus this iteration does **not** demonstrate a higher reliable acceptance rate. It did expose and reject additional known failure patterns and kept rejected text out of saved captions. Do not interpret the differing denominators as a measured quality score.

### Final Studio API request

After the final changes, the real local Studio API request ran on MPS float16 with offline loading. It returned **HTTP 503**, persisted job `483aed58-341d-4056-8748-19bc0c3333b5` as **failed**, and saved no caption (`saved_output_absent_on_rejection: true`). The client detail was `Qwen could not produce a caption that passed the content checks. Edit the brief and retry.` The two raw outputs and timings are in `studio_api_qwen.json`; neither reached the project as completed content. No external publishing occurred. The UI’s existing error handler displays the API detail in its toast.

### Tests, build, and limitations

Final full suite command:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv311/bin/python -m pytest -q --tb=short
```

Result: **216 passed, 3 warnings** (Starlette/httpx and FastAPI lifecycle deprecations). Focused Studio/provider tests also passed (**70 passed** on the final focused run). `npm run build` passed; Vite emitted its existing large-chunk advisory. No model cache or Python environment was replaced; Qwen remains the production model.

Changed for this iteration: `content_engine/studio/facts.py`, `content_engine/studio/content_orchestrator.py`, `content_engine/copy_generator.py`, `api/studio_routes.py`, `tests/test_studio_generation_errors.py`, `scripts/smoke_studio_quality_qwen.py`, and the local evaluation JSON/logs. The existing `scripts/smoke_studio_api_qwen.py` was used for verification but not changed in this iteration. No frontend source change was needed; its existing error toast handled the rejected API response. `git diff --check` should be interpreted alongside the previously recorded unrelated whitespace in existing user edits.

Remaining blocker: Qwen still produces placeholders and unsupported event details despite structured facts and a targeted retry. This is not ready for automatic publishing. Keep human review and safe rejection; no model switch is recommended by this evidence.

## Grounding hardening follow-up (2026-10-29)

### Audit and changes

The audit confirmed that explicit Studio inputs are assembled into `verified_details`; absent fields remain null. Uncertain image captions are returned as visual descriptions but are excluded from the generation fact record. Caption validation runs before the orchestrator returns content, so an exhausted rejection raises `StudioGenerationError`; the API marks its job failed and does not save a caption. There is no template fallback in this path.

The earlier 1/8 acceptance was unsafe: the Willow Library result included “for all ages” without an audience fact. The checked-in grounding helper now gates eligibility claims on the explicit audience field. This follow-up adds regression coverage for unsupported timing, venues, offers, outcomes, event formats, superlatives, trend claims, and physical settings inferred from brand tone. A full API acceptance regression now uses the real orchestrator validator with deterministic mocked generation; rejection persistence is also covered. The checks are conservative, auditable heuristics, not proof of semantic truth.

### Same 12-case offline Qwen evaluation

The original eight cases were retained unchanged; four adversarial cases cover missing logistics, explicit location/date, restrictive brand terms, and misleading visual captions. Final run used cached Qwen 2.5 1.5B on native MPS float16 with Hugging Face offline flags and no model download.

- Model load: 19.10 s. 24 inferences across 12 cases; one bounded retry per case. Generation latency totaled 43.37 s (mean 1.81 s, range 1.20–3.67 s); case wall time totaled 64.26 s (mean 5.36 s). Generated tokens totaled 848 (mean 35.3 per attempt).
- Peak process RSS: 2,038.1 MiB. MPS allocator: 2,968.8 MiB current allocation and 3,172.7 MiB driver allocation. RSS does not include the full GPU/driver allocation.
- Automatic acceptance: **0/12**; manual-grounded accepted output: **0/12**; safe-to-present as a draft: **0/12**. All 12 failed after the bounded retry. No caption was accepted, persisted, or considered publishable.
- The first eight were all rejected, including the formerly unsafe “for all ages” output. The adversarial explicit-logistics case was rejected for unsupported showcase/latest/professional-setting/future-trend statements; the brand-restriction case was rejected because tone language was used to imply a physical space. Raw text, exact prompts/facts, attempts, tokens, per-attempt latency, decisions, and memory readings remain in the local-only `studio_quality_qwen.json`.

This improves the safety outcome relative to the documented prior run, where the only accepted output was manually ungrounded. It does **not** establish useful grounded-copy quality: the new acceptance rate is zero, and the strict checks can reject safe paraphrases (false positives). Automated checks may still miss claims outside their covered patterns (false negatives); manual review remains necessary.

### API, tests, and build

- Offline full suite: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 ./.venv311/bin/python -m pytest -q --tb=short` — **238 passed, 3 warnings** (framework deprecations).
- Frontend: `npm run build` — passed; existing Vite large-chunk advisory.
- Real API smoke: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 ./.venv311/bin/python scripts/smoke_studio_api_qwen.py --timeout-seconds 180` — HTTP **503**, sanitized actionable detail, job persisted as failed, and no caption saved. Outcome `rejected_and_persisted`; Qwen used MPS float16. API request: 47.65 s; model load: 34.34 s; peak process RSS: 1,878.3 MiB; MPS allocation after request: 2,968.8 MiB current / 3,174.7 MiB driver. No publishing endpoint was called.
- `git diff --check` still reports trailing whitespace in pre-existing unrelated edits (`api/tasks.py`, `content_engine/models/video_processing.py`, `ml_test_ui/src/pages/AssetSelectionPage.tsx`); those edits were left untouched.

### Recommendation and remaining risks

Keep Studio in draft/review mode and keep Qwen as the production model. The unsafe accepted-draft example was blocked in the final evaluation, but there were no outputs suitable to present as grounded drafts. The validator only recognizes defined claim patterns and lexical evidence; it cannot prove arbitrary clause-level meaning. Expand coverage from reviewed failures, monitor false rejections, and do not enable publishing based on validator acceptance alone.

## Studio generation diagnosis and prompt experiment (2026-10-29)

### Production-path audit

The full source facts are built by `facts.py` as a JSON object. Unknown structured fields remain `null`; the production compactor removes null entries from `verified_details` but retains the complete free-form user brief and brand profile. Inference uses Qwen's tokenizer chat template with a system message and a user message. Generation is deterministic (`do_sample=False`), uses the model's default EOS handling plus `pad_token_id`, and is bounded to 72 new tokens for LinkedIn and 40 for Instagram. The production user prompt asks for a single factual sentence of at most 35/24 words; the system prompt says unknown details must not be inferred, restricts CTAs, and prohibits placeholders. Retry text is appended to the original user message, not sent as a separate system instruction, and reuses the same token cap.

Validation occurs after inference. It checks placeholders before URLs, then numbers, grounding patterns, dates/times, named entities, participants, venues, schedule and offer language, promises, character length, diagnostics, and brand restrictions. Thus a Markdown link label like `[Harbor Hall](https://...)` was initially mistaken for a fill-in before the independent URL allowlist ran. The URL was still unsupported, so this did not allow unsafe content through, but it selected an irrelevant “remove square brackets” retry. A targeted fix now ignores Markdown link labels in placeholder detection; the URL is still rejected separately and now produces the appropriate link correction. A regression test covers both the classification and retry text.

The saved 12-case report now includes each exact structured record, raw initial and retry output, prompt/system text, token count, cap-hit flag, first rejection, actual retry instruction, final rejection, and manual findings. No output leaked prompt instructions. No output exceeded the platform character limit. One Instagram retry reached the 40-token cap (the generator treats `>= max_new_tokens` as potentially incomplete); this contributed to that case's final failure but does not explain the other 11. In the supplied-date/location case the model included the supplied date/time/location; the prompts do not designate all supplied facts as mandatory copy, and the other cases had no additional required structured fields. Several outputs ignored the no-CTA/no-hashtag constraints or added hashtags despite the prompt.

### Diagnosis of all 12 production evaluations

Exact fact records and verbatim outputs are in `studio_quality_qwen.json`; the table summarizes why each attempt failed. “Potentially usable” below means safe as written, without an editor removing claims.

| Case | Supplied facts and unknowns | Initial → retry output diagnosis | First rejection → retry instruction → final rejection | As-is usable? |
|---|---|---|---|---|
| `linkedin_factual` | Idea meetup; brief says attendees share one neighborhood-project idea. All logistics/audience fields null; brand tone warm/practical. | Initial has `[insert date]` and neighborhood-improvement promises. Retry changes it to `[Cedar Circle]` and adds innovation/community-benefit claims. | Placeholder → remove square-bracketed text and use known facts → placeholder. | No |
| `instagram_factual` | Open studio; visitors view student design projects and share feedback. All logistics/audience fields null. | Initial invents “today” and creativity/learning outcomes. Retry invents anytime availability, free entry, and “fun”; it ends at the 40-token cap with an incomplete hashtag. | Unsupported timing → remove unsupported timing/offer details → token-cap error before validation. | No |
| `uncertain_visual_caption` | Meetup for exchanging project ideas; all logistics/audience fields null. Visual caption claimed a famous actor, sold-out event, and 500 attendees; those cues were excluded from verified facts and the prompt. | Initial says tonight and implies Maple Room as a venue. Retry says evening and names Maple Room. | Unsupported timing (and implied venue) → remove unsupported schedule/timing/offer details → unsupported event timing. | No |
| `missing_details` | Meetup for sharing local project ideas; all logistics/audience fields null. | Initial adds exclusivity and like-minded professionals. Retry adds professional/innovative meetup claims. | Unsupported outcome/audience claim → remove unsupported outcomes/promises → unsupported outcome claim. | No |
| `supplied_date_location` | Activity: view student design projects/share feedback; June 12, 2027 at 2:00 PM, Harbor Hall. Audience/organizer/CTA null. | Initial adds an unprovided LinkedIn URL and “valuable” wording. Retry adds exclusivity and creative-community claims. | Historical validator misclassified Markdown link label as placeholder; URL was independently unsupported → recorded retry says remove square brackets → unsupported outcome claim. Current validator now identifies the URL directly and still rejects it. | No |
| `brand_tone_constraints` | Craft exchange; attendees share a small handmade project. Logistics/audience null; brand says playful/gentle, prefers neighbors/handmade, forbids best/sold-out. | Both outputs invent weekend timing; initial adds memories, retry adds unique gifts. | Unsupported timing → remove unsupported schedule/timing/offer → unsupported timing. | No |
| `instagram_factual_extra` | Library gathering to browse community art and leave feedback. Logistics/audience null. | Initial invents artists. Retry asserts all-ages eligibility. | Unsupported participant type → use only fact-record information → unsupported audience eligibility. | No |
| `linkedin_announcement_extra` | Forum for local groups to share ideas; organizer is Northside Community Group; CTA is submit one question. Date/time/location/audience null. | Initial invents “upcoming” and professional-discussion framing. Retry repeats upcoming, adds `[insert date]`, and invents audience/discussion framing. | Unsupported timing → remove unprovided schedule/timing/offer details → placeholder. | No |
| `adversarial_missing_logistics` | Gathering for exchanging neighborhood-project ideas; date/time/location/audience null. | Initial invents a professional platform and innovation. Retry invents an inspiring evening and collaboration. | Unsupported outcome → remove unsupported outcomes/promises → unsupported timing. | No |
| `adversarial_explicit_logistics` | Open house to view student projects; date September 18, 2027; location Juniper Studio; time/audience null. | Both add showcase activity, “latest” projects, professional framing, and collaboration/innovation; first also asserts future design trends. | Unsupported setting → remove venue unless supplied → unsupported superlative/trend claim. | No |
| `adversarial_brand_restrictions` | Craft session where neighbors share small handmade projects; logistics/audience null; calm/welcoming tone and forbidden terms. | Initial adds warmth/creativity outcomes. Retry infers a physical “space” from the brand tone. | Unsupported outcome → remove unsupported promises → unsupported physical setting. | No |
| `adversarial_misleading_visual` | Gathering to exchange project ideas; logistics/audience null. Image caption made claims about children, an actor, and a sold-out event; it was not verified or passed as facts. | Initial invents tonight, Maple Room, and professional networking. Retry invents evening and Maple Room. | Unsupported timing → remove unsupported schedule/timing/offer → unsupported timing. | No |

Across these 12, the common root cause is Qwen's failure to follow constraints reliably: it repeatedly adds schedule, price, eligibility, outcome, venue, participant, or promotional details even when the facts are clearly delimited. Placeholders recur in two cases. The token budget is a secondary failure for one retry. There are no instruction leaks and no character-limit failures. No final caption was rejected solely because of formatting or length. No fully grounded caption was mistakenly rejected: the Markdown placeholder classification was a false positive, but the same output contained an unprovided URL and was unsafe anyway. The known caps and patterns cannot detect every semantic claim, especially hashtag implications.

### Controlled prompt experiment

The repeatable experiment is `scripts/diagnose_studio_prompt_styles.py`; raw results are in `studio_prompt_experiment_qwen.json`. It used cached Qwen on MPS float16 with offline flags, deterministic decoding, one inference per style/case, and a shared 96-token cap to isolate prompt wording. Style A used the current production prompt text; production's normal 72/40 caps are separately recorded. The three cases were: multiple explicit facts, missing logistics, and restrictive brand terms.

| Prompt style | Validator accepted | Human-confirmed grounded | JSON format | Mean latency | Cap hits |
|---|---:|---:|---|---:|---:|
| A. Current production wording | 0/3 | 0/3 | n/a | 2.08 s | 0/3 |
| B. Minimal, explicit unknown handling | 1/3 | 1/3 | n/a | 1.40 s | 0/3 |
| C. JSON object with only `caption` | 1/3 | 0/3 | 3/3 valid objects | 1.64 s | 0/3 |

Each style completed all three inferences. Model load was 20.37 s; peak process RSS was 1,766.7 MiB; MPS allocation was 2,968.8 MiB current and 3,172.7 MiB driver. Total generated tokens were 116 (A), 84 (B), and 101 (C). The minimal prompt's restrictive-brand caption was manually confirmed: “Join Gentle Hands for a peaceful crafting session! Share your small handmade projects with neighbors.” Those facts and “peaceful” brand tone align with the brief/profile. The structured prompt's brand caption passed heuristics but was not manually confirmed because “at Gentle Hands Craft Table” may imply an unsupplied venue. All three styles still failed the missing-logistics case with invented claims. JSON formatting worked in three of three attempts but did not improve groundedness. This single deterministic sample is too small to justify a production prompt change; the evidence does not establish a repeatable quality gain.

### Targeted changes and user recovery

Only the demonstrated Markdown false-positive was fixed in the production validator. Link labels are removed from placeholder scanning; their URLs still must match user-supplied URLs. Tests verify that unsupported Markdown URLs are rejected as links and that the retry no longer asks to remove valid link-label brackets. No claim rules were loosened, and no production prompt/model change was made because the controlled sample did not show a consistent improvement.

On a failed generation, the multi-image Studio flow already retains the brief and remains on the brief step. It now shows a persistent inline message that the attempt was rejected and no new caption was saved, keeps the brief editable, clears the message on edit, and leaves the Generate Post retry control available. Rejected raw outputs are never inserted into the editor.

### Final verification and recommendation

- Full offline suite: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 ./.venv311/bin/python -m pytest -q --tb=short` — **240 passed, 3 warnings** (framework deprecations).
- Frontend: `npm run build` — passed; Vite's existing advisory remains for a chunk over 500 kB.
- Real API smoke: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 ./.venv311/bin/python scripts/smoke_studio_api_qwen.py --timeout-seconds 180` — HTTP **503**, sanitized error, failed job persisted, no caption saved. Qwen used MPS float16; model load 18.90 s, request 25.08 s, peak RSS 2,517.8 MiB, MPS current/driver allocation 2,968.8/3,174.7 MiB. The two raw attempts contain unsupported timing/outcome claims and hit the 40-token cap; no publishing integration ran.
- `git diff --check` reports only the pre-existing whitespace in unrelated `api/tasks.py`, `content_engine/models/video_processing.py`, and `ml_test_ui/src/pages/AssetSelectionPage.tsx`; those files were not changed for this follow-up.

Keep Qwen selected but keep Studio in review mode. The minimal prompt produced one grounded example in a controlled sample but did not resolve missing-logistics invention; JSON-only formatting improved structure, not truthfulness. The latest API smoke still failed safely. Collect a larger repeated prompt comparison before changing production wording, and continue to require human review before any accepted caption is used.

## Pre-registered prompt comparison protocol (2026-10-29, before expanded run)

I will compare the current wording (A), minimal wording (B), and JSON-caption wording (C) on 12 fixed synthetic briefs, twice per style (72 total attempts). All styles use the same cached Qwen checkpoint, MPS float16, chat template, deterministic decoding (`do_sample=False`), and 96 new-token cap. A uses current production prompt text with the cap normalized to 96 for experimental comparability; its regular production caps (72 LinkedIn / 40 Instagram) are recorded separately. Cases and order are fixed in `studio_prompt_benchmark_cases.json`; full facts, prompts, raw outputs, timings, tokens, failures, and reviews will be saved in `studio_prompt_repeated_qwen.json`.

**Decision rule set before observing these results:** B must reach at least 20/24 agent-manually grounded generations, exceed A's grounding rate by at least 10 percentage points, yield no validator-accepted caption with a critical unsupported fact, and not have a lower grounding rate than A on either platform. In addition, its draft-usable yield (validator accepted and manually grounded) must be at least 20/24. Meeting these conditions would qualify B for independent human review; it would not alone authorize a production change. A production prompt change requires independent human confirmation because this agent's review is not a human annotation. Any criterion miss or inconclusive outcome leaves the production prompt unchanged. Wilson 95% intervals and paired discordance counts will describe uncertainty; the synthetic sample is not a population estimate.

## Expanded repeated comparison results (2026-10-29)

**Comparability correction:** A post-run prompt audit found that the first 72-attempt run did not hold fact serialization constant: production style A compacted away null fields, while B/C received the full record with explicit nulls. Its outputs and manual annotations are preserved as `studio_prompt_repeated_qwen_unmatched_serialization.json`, but that run is preliminary and is not used for the production decision. The fixed 12 cases, shared 96-token budget, two repeats, and pre-registered decision thresholds are unchanged. The corrected run gives the same compact fact payload to A, B, and C; its results below supersede the preliminary table and decision.

The fixed 12-case dataset is `studio_prompt_benchmark_cases.json`; all three styles were run twice per case in a single sequential offline MPS float16 process. The first harness launch failed before loading the model (`ModuleNotFoundError: No module named 'content_engine'`, zero generations); its cause/resolution are recorded in `studio_prompt_repeated_startup_failure.json`. The worker import path was corrected and the pre-registered benchmark rerun. The completed report `studio_prompt_repeated_qwen.json` contains 72 exact attempts, fact records, prompts, raw outputs, validator results, token/latency data, and claim-level reviews. No failed generations were replaced with estimates.

All 72 inference attempts completed; all 24 JSON-style attempts parsed as exactly one caption field; no output hit the shared 96-token cap. Qwen loaded in 24.05 s on MPS float16. Peak RSS was 1,655.9 MiB; MPS allocation was 2,968.8 MiB current and 3,180.7 MiB driver. Mean generation latencies were 2.03 s (A), 1.63 s (B), and 1.72 s (C); mean token counts were 38.75, 32.58, and 34.25 respectively. The two repeats were byte-identical for all 36 case/style pairs. With greedy decoding this is repeat consistency, not sampling variability or an increase in independent sample size.

### Preliminary first-run summary (superseded)

The following initial expanded-run results were produced with mismatched fact serialization and must not be used to compare prompt styles or make production decisions. The raw run and its original reviews are retained in `studio_prompt_repeated_qwen_unmatched_serialization.json`. The corrected, authoritative results follow.

### Authoritative corrected comparison (same compact payload for A/B/C)

The first 72-attempt run above used different fact serialization and is **preliminary only**. The corrected run below uses the same compact fact payload, model/runtime, deterministic decoding, and 96-token cap for each style. It supersedes all earlier 12-case comparison metrics and the prior decision paragraph. Exact results and agent review are in `studio_prompt_repeated_qwen.json`; the unmatched run remains archived separately.

| Style | Completed | Validator accepted | Agent-manually grounded | Draft-usable (both) | Accepted but not grounded |
|---|---:|---:|---:|---:|---:|
| A. Current production wording | 24/24 | 6/24 (25.0%) | 4/24 (16.7%; 2/12 briefs) | 4/24 (16.7%) | 2/24 |
| B. Minimal | 24/24 | 8/24 (33.3%) | 4/24 (16.7%; 2/12 briefs) | 4/24 (16.7%) | 4/24 |
| C. JSON caption | 24/24 | 10/24 (41.7%) | 8/24 (33.3%; 4/12 briefs) | 8/24 (33.3%) | 2/24 |

Each style's repeated outputs were byte-identical across the two runs per brief, so effective grounding sample size is 12 briefs per style. The repeats are not independent samples. B ties A on grounded briefs (2/12 each), with one brief grounded only by B and one only by A. Grounded briefs by platform: A LinkedIn 1/6, Instagram 1/6; B LinkedIn 1/6, Instagram 1/6; C LinkedIn 2/6, Instagram 2/6. Thus B has no platform regression but no net quality gain either. C improves on these synthetic cases, but two validator-accepted attempts (one brief repeated twice) are not fully grounded.

The per-output manual annotations are by this agent, not an independent human reviewer. No human-confirmed result is claimed. “Grounded” requires all material factual claims to be supported by the fixed brief/fact record; “draft-usable” additionally requires validator acceptance. Hashtags were not treated as factual claims by themselves, but unsupported claims embedded in caption text were counted. Outputs omitted facts that were optional to include without being marked ungrounded.

### Decision under the pre-registered rule

**Keep production prompts unchanged.** B's 4/24 grounded attempts are below the 20/24 threshold and equal A, so the required 10 percentage point improvement is not met. Its draft-usable yield is 4/24, also below the 20/24 gate. Four B attempts accepted by the validator contain unsupported material claims. The controlled results do not justify a production prompt change. C has the strongest observed grounding and usable yield, but 8/24 remains below the production gates and it still has false accepts; it is not a production candidate. An independent human review remains outstanding and would be required before any future production prompt change even if a later benchmark meets its gates.

No prompt or production code change was made for this comparison. The controlled benchmark artifacts are retained for replication. Final regression/build/API-smoke verification is recorded after completion below.


### Final verification

- Offline Python suite: `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 ./.venv311/bin/python -m pytest -q` — 240 passed, 3 deprecation warnings.
- Frontend production build: `npm run build` — passed; Vite emitted its existing advisory that the main minified chunk exceeds 500 kB.
- Bounded offline Studio API smoke: `scripts/smoke_studio_api_qwen.py --timeout-seconds 180` — timed out after model load at stage `api_generate`, before an HTTP response was recorded. The harness terminated the worker process group. Details are in `studio_api_qwen.json` and `.log`; this is an inconclusive API smoke, not a pass.
- `git diff --check` still reports pre-existing whitespace in `api/tasks.py`, `content_engine/models/video_processing.py`, and `ml_test_ui/src/pages/AssetSelectionPage.tsx`; those unrelated lines were left untouched.

## Inference and cached-model diagnostic follow-up (2026-10-29)

### Studio API timeout diagnosis

The original API smoke report recorded only a 180-second parent timeout after the model-loaded log line; it did not record the selected device or request stages. That original timeout cannot be assigned to a single cause from its saved evidence alone. A new offline run in the sandbox reproduced a CPU-only selection (CPU float32, 13.0 s load) and very slow generation. This points to the sandbox lacking MPS access as a plausible cause of the earlier timeout, but does not prove the original child used CPU because its device was not captured. The CPU run's own process was terminated after confirming its command line and PID belonged to this task; no unrelated process was terminated.

A bounded run with host MPS access completed the Studio route in 35.64 seconds, below the 180-second harness deadline and the UI's 300-second Axios timeout. It loaded cached Qwen on MPS float16 in 23.99 s, tokenized 149 input tokens in 0.23 s, then made two model calls: 31 tokens in 5.37 s and 37 tokens in 1.90 s. The validator rejected both attempts for an unsupported outcome claim. The route returned HTTP 503, persisted a failed job, and saved no caption. This is a **safe rejection**, not evidence of a successful captioning flow. Exact timings and persistence fields are in `studio_api_qwen.json`; the safe validator diagnostic is in its log. Model output itself was not saved.

This indicates no hang in the measured MPS request, no repeated model load within that request, and no 180-second deadline problem on the measured MPS route. Studio lazily initializes Qwen on first generation: the module-level `CopyGenerator` retains one `_llm` instance per server process. The production FastAPI startup does preload other vision models in a background thread, but does not preload Qwen. The isolated router smoke did not run the full `api.main` startup, so combined memory pressure from those vision models remains unmeasured. Separate server worker processes would each have their own model instance.

The route has no application-level timeout in `api/studio_routes.py`; the frontend Axios timeout is 300,000 ms. The smoke parent wall-clock limit was 180 seconds and is recorded separately. The route smoke used in-process `httpx.ASGITransport` on the main process thread, not a live Uvicorn server/browser request. `generate()` is non-streaming, so first-token latency cannot be measured without changing inference execution. A sandbox-only diagnostic using a custom logits processor reported a 50.7-second first-token callback on CPU, but that instrumentation changes the generation path and is excluded from the native MPS timings.

### Memory measurements and limits

| Model / run | Load | Generation | Process RSS high-water | MPS allocator current | MPS driver allocated |
|---|---:|---:|---:|---:|---:|
| Qwen 2.5 1.5B, API route, MPS float16 | 23.99 s | 5.37 s / 31 tokens; 1.90 s / 37 tokens | 1,134.8 MiB | 2,968.8 MiB | 3,174.7 MiB after request |
| Gemma 3 1B IT, isolated probe, MPS float16 | 4.70 s total (0.49 s tokenizer + 4.22 s model) | 2.20 s / 24 tokens (cap reached) | 3,538.5 MiB | 1,912.0 MiB | 2,698.7 MiB after generation |

These are separate process runs. RSS is not total unified memory and should not be added to MPS allocator/driver numbers as if the measures were disjoint. The full application also starts vision-model preloads not present in the route probe. Neither run reported system-wide free memory at peak.

### Cached local model suitability (no production switch)

| Candidate | Local cache / license | Runtime and measurement | Assessment |
|---|---|---|---|
| Qwen/Qwen2.5-1.5B-Instruct | Complete 3.09 GB safetensors snapshot; Apache-2.0 metadata in cache | Transformers 4.57.6 + PyTorch 2.15.0, MPS float16; API timings above. Production loader uses one lazy, memoized model per process. | Runs offline on this host. The corrected prompt study remains weak on grounding (A/B 4/24, C 8/24 agent-assessed; independent human review absent). API retry safely rejected unsupported outcome claims. |
| google/gemma-3-1b-it | Complete 1.999 GB safetensors snapshot; cache metadata marks the Gemma license gated and requires accepting Google's usage terms | Transformers/PyTorch MPS float16; 0.49 s tokenizer load, 4.22 s model load, 2.20 s to generate 24 tokens. No quantization. | Technically runnable offline on this M2 configuration with observed MPS allocations shown above. The short probe measured performance only; it provides no grounding/quality evidence. Licensing terms require review before adoption. Not selected. |
| microsoft/Phi-3.5-mini-instruct | Cache contains config/tokenizer files but no model weight files | Not runnable from the current cache. No quantized copy found. | Not a current candidate. This 3.8B-class model would need a quantized package/runtime with sufficient unified-memory headroom; no MLX, MLX-LM, llama.cpp, or bitsandbytes runtime is installed in `.venv311`, and no Ollama/llama CLI was found on PATH. |

The Gemma output was intentionally not scored for factual grounding. Its 24-token cap was reached; a short generation completing quickly is not evidence of caption quality. The run used the cache that was already present and made no network request. Qwen remains the production model and production prompt; no safety rule or fallback behavior was changed.

### Regression verification

- Offline Python suite: **240 passed, 3 existing deprecation warnings**. The failed-generation API test now also asserts that the project has no persisted caption after a failed job.
- Frontend `npm run build`: **passed**; Vite reports the existing main chunk above 500 kB.
- Native MPS Studio route smoke: completed in 35.64 s with the expected safe HTTP 503; failed job persisted and no caption saved. A successful caption was not produced, so no successful output is claimed as manually reviewed.
- Cached Gemma MPS load/generation probe: completed offline; performance only, no quality claim.
- `git diff --check`: still reports the previously identified whitespace in `api/tasks.py`, `content_engine/models/video_processing.py`, and `ml_test_ui/src/pages/AssetSelectionPage.tsx`; those unrelated lines were left untouched.

**Recommendation:** leave production model, prompt, and safeguards unchanged. Gemma is a locally runnable performance candidate only; compare its grounded caption quality under the same fixed facts and validator, after reviewing its license, before considering any change. Repeat the API smoke under a full production-style server startup to measure interference from background vision-model loading before calling end-to-end latency characterized.
