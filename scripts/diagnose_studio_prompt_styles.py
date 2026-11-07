"""Compare three deterministic Studio prompt styles with cached Qwen only."""
from __future__ import annotations

import json
import os
import platform
import resource
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "benchmark_results" / "studio_prompt_experiment_qwen.json"

CASES = [
    {
        "id": "supplied_facts",
        "platform": "linkedin",
        "event_name": "Harbor Hall Open Studio",
        "brief": "A fictional open studio where visitors may view student design projects and share feedback.",
        "activity": "View student design projects and share feedback",
        "date": "June 12, 2027",
        "time": "2:00 PM",
        "location": "Harbor Hall",
    },
    {
        "id": "missing_logistics",
        "platform": "instagram",
        "event_name": "Riverbend Idea Exchange",
        "brief": "A fictional gathering for exchanging neighborhood project ideas.",
    },
    {
        "id": "restrictive_brand",
        "platform": "instagram",
        "event_name": "Gentle Hands Craft Table",
        "brief": "A fictional craft session where neighbors can share small handmade projects.",
        "brand_profile": {
            "name": "Gentle Hands",
            "tone_of_voice": "calm and welcoming",
            "avoid_words_claims": ["best", "free", "guaranteed", "life-changing"],
        },
    },
]

EXPERIMENT_TOKENS = 96


def save(report: dict) -> None:
    temporary = OUTPUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary, OUTPUT)


def make_fact_record(case: dict) -> dict:
    from content_engine.studio.facts import build_fact_record

    return build_fact_record(
        case["event_name"], case["brief"], activity=case.get("activity"),
        audience=case.get("audience"), date=case.get("date"), time=case.get("time"),
        location=case.get("location"), organizer=case.get("organizer"),
        call_to_action=case.get("call_to_action"), key_points=case.get("key_points"),
        brand_profile=case.get("brand_profile"), tone=case.get("tone"),
    )


def worker() -> int:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
    import torch
    from content_engine.copy_generator import CopyGenerator, _LocalLLMGenerator
    from content_engine.studio.content_orchestrator import StudioContentOrchestrator, StudioGenerationError

    report = {
        "status": "running",
        "python": platform.python_version(),
        "platform_info": platform.platform(),
        "network_access": "disabled; offline flags and local_files_only=True",
        "model_id": _LocalLLMGenerator._MODEL_ID,
        "decoding": {"do_sample": False, "experiment_max_new_tokens": EXPERIMENT_TOKENS},
        "comparability_note": (
            "All styles use the same 96-token output cap to isolate prompt wording. "
            "Style A uses current production prompt text; production's normal caps are 72 LinkedIn / 40 Instagram."
        ),
        "cases": [],
    }
    save(report)
    llm = _LocalLLMGenerator()
    production = CopyGenerator()
    production._llm = llm

    for case in CASES:
        facts = make_fact_record(case)
        serialized = json.dumps(facts, ensure_ascii=False, separators=(",", ":"))
        case_report = {
            "case_id": case["id"],
            "platform": case["platform"],
            "fact_record": facts,
            "styles": [],
        }
        for style in ("A_current_production_wording", "B_minimal", "C_json_caption"):
            call_data: dict = {}
            started = time.perf_counter()
            if style == "A_current_production_wording":
                original = production._generate_qwen

                def controlled_current_prompt(prompt, max_new_tokens, correction="", system_prompt=None):
                    if correction:
                        prompt = f"{prompt}\n\nRetry constraint: {correction}"
                    call_data.update(user_prompt=prompt, system_prompt=system_prompt,
                                     production_token_cap=max_new_tokens)
                    return llm.generate(prompt, max_new_tokens=EXPERIMENT_TOKENS,
                                        system_prompt=system_prompt)

                production._generate_qwen = controlled_current_prompt
                try:
                    if case["platform"] == "linkedin":
                        raw = production.generate_linkedin_caption(case["event_name"], [], serialized)
                    else:
                        raw = production.generate_instagram_caption(case["event_name"], [], serialized)
                finally:
                    production._generate_qwen = original
            elif style == "B_minimal":
                system = (
                    "Write one short social caption. Use only facts in the user brief. "
                    "A null or missing field is unknown. Do not add dates, times, places, audiences, offers, "
                    "outcomes, or event details that are not stated. Return only the caption."
                )
                user = (
                    f"Write one short {case['platform']} caption for {case['event_name']}.\n"
                    f"User-supplied facts (JSON): {serialized}"
                )
                call_data.update(user_prompt=user, system_prompt=system, production_token_cap=None)
                raw = llm.generate(user, max_new_tokens=EXPERIMENT_TOKENS, system_prompt=system)
            else:
                system = (
                    "Return exactly one valid JSON object with exactly one string field named caption. "
                    "Do not use markdown or add other keys. Use only supplied facts; null or missing fields are unknown. "
                    "Do not add unsupported event details, dates, times, locations, audiences, offers, or outcomes."
                )
                user = (
                    f"Create one short {case['platform']} caption for {case['event_name']}. "
                    f"Return it in the required JSON shape. Supplied facts: {serialized}"
                )
                call_data.update(user_prompt=user, system_prompt=system, production_token_cap=None)
                raw = llm.generate(user, max_new_tokens=EXPERIMENT_TOKENS, system_prompt=system)

            elapsed = time.perf_counter() - started
            caption = raw
            parse_error = None
            if style == "C_json_caption":
                try:
                    decoded = json.loads(raw)
                    if set(decoded) != {"caption"} or not isinstance(decoded["caption"], str):
                        raise ValueError("JSON must contain only a string caption field")
                    caption = decoded["caption"]
                except (json.JSONDecodeError, TypeError, ValueError) as exc:
                    parse_error = f"{type(exc).__name__}: {exc}"

            validator_reason = None
            if parse_error:
                validator_reason = "structured output parse failure"
            else:
                try:
                    StudioContentOrchestrator._validate_generated_caption(
                        caption, json.dumps(facts, ensure_ascii=False),
                        max_chars=3000 if case["platform"] == "linkedin" else 2200,
                        brand_profile=case.get("brand_profile"),
                    )
                except StudioGenerationError as exc:
                    validator_reason = str(exc)

            case_report["styles"].append({
                "style": style,
                **call_data,
                "raw_output": raw,
                "parsed_caption": caption if not parse_error else None,
                "parse_error": parse_error,
                "generated_token_count": getattr(llm, "last_generated_token_count", None),
                "max_new_tokens": EXPERIMENT_TOKENS,
                "output_cap_hit": getattr(llm, "last_generated_token_count", 0) >= EXPERIMENT_TOKENS,
                "generation_seconds": elapsed,
                "automated_validation": "accepted" if validator_reason is None else "rejected",
                "validator_rejection_reason": validator_reason,
                "manual_grounding_review": "pending",
                "manual_review_findings": None,
            })
        report["cases"].append(case_report)
        report.update(
            device=llm.device,
            dtype=llm.dtype,
            model_load_seconds=llm.load_seconds,
            peak_process_rss_mib=round(
                resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
                if sys.platform == "darwin"
                else resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                1,
            ),
        )
        if torch.backends.mps.is_available():
            report["mps_memory_mib"] = {
                "current_allocated": round(torch.mps.current_allocated_memory() / 1048576, 1),
                "driver_allocated": round(torch.mps.driver_allocated_memory() / 1048576, 1),
            }
        save(report)

    report["status"] = "complete"
    report["stage"] = "complete"
    save(report)
    return 0


def main() -> int:
    if "--_worker" in sys.argv:
        return worker()
    environment = {
        **os.environ,
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
    }
    log_path = OUTPUT.with_suffix(".log")
    with log_path.open("w", encoding="utf-8") as log:
        child = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--_worker"],
            cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            return_code = child.wait(timeout=300)
            if return_code != 0:
                try:
                    previous = json.loads(OUTPUT.read_text())
                except (OSError, json.JSONDecodeError):
                    previous = {"cases": []}
                previous.update(
                    status="failure",
                    stage="worker_failure",
                    worker_return_code=return_code,
                    log_path=str(log_path.relative_to(ROOT)),
                )
                save(previous)
            return return_code
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
    try:
        previous = json.loads(OUTPUT.read_text())
    except (OSError, json.JSONDecodeError):
        previous = {"cases": []}
    previous.update(
        status="timeout",
        stage="worker_timeout",
        error="Prompt-style experiment exceeded its 300-second limit; its worker group was terminated.",
        log_path=str(log_path.relative_to(ROOT)),
    )
    save(previous)
    return 124


if __name__ == "__main__":
    raise SystemExit(main())
