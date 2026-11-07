"""Run the pre-registered A/B/C Studio prompt comparison with cached Qwen."""
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
CASES_FILE = ROOT / "benchmark_results" / "studio_prompt_benchmark_cases.json"
OUTPUT = ROOT / "benchmark_results" / "studio_prompt_repeated_qwen.json"
LOG = ROOT / "benchmark_results" / "studio_prompt_repeated_qwen.log"
TOKEN_BUDGET = 96
REPEATS = 2
CURRENT_SYSTEM = (
    "Write exactly one plain sentence and no explanation. Use only information stated in the supplied fact record. "
    "Do not infer or add any detail absent from that record. Include a call to action only when one is explicitly supplied. "
    "Never use bracketed fill-ins. Follow the supplied brand tone and restrictions."
)
MINIMAL_SYSTEM = (
    "Write one short social caption. Use only facts in the supplied fact record. A null or missing field is unknown. "
    "Do not add facts. Return only the caption."
)
JSON_SYSTEM = (
    "Return exactly one valid JSON object with exactly one string field named caption. Do not use markdown or add other keys. "
    "Use only supplied facts; null or missing fields are unknown. Do not add facts."
)


def save(report: dict) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary, OUTPUT)


def peak_rss_mib() -> float:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(value / (1024 * 1024) if sys.platform == "darwin" else value / 1024, 1)


def make_fact_record(case: dict) -> dict:
    from content_engine.studio.facts import build_fact_record

    return build_fact_record(
        case["event_name"], case["brief"], activity=case.get("activity"),
        audience=case.get("audience"), date=case.get("date"), time=case.get("time"),
        location=case.get("location"), organizer=case.get("organizer"),
        call_to_action=case.get("call_to_action"), key_points=case.get("key_points"),
        brand_profile=case.get("brand_profile"),
    )


def style_prompt(style: str, case: dict, facts: dict, production: object, llm: object) -> dict:
    from content_engine.copy_generator import _compact_prompt_facts

    # Hold fact serialization constant across styles. A's production helper
    # applies this compaction internally; B and C receive the same payload.
    serialized = _compact_prompt_facts(json.dumps(facts, ensure_ascii=False, separators=(",", ":")))
    if style == "A_current_production":
        captured: dict = {}
        original = production._generate_qwen

        def controlled_current_prompt(prompt, max_new_tokens, correction="", system_prompt=None):
            if correction:
                prompt = f"{prompt}\n\nRetry constraint: {correction}"
            captured.update(
                user_prompt=prompt,
                system_prompt=system_prompt,
                production_token_cap=max_new_tokens,
            )
            return llm.generate(prompt, max_new_tokens=TOKEN_BUDGET, system_prompt=system_prompt)

        production._generate_qwen = controlled_current_prompt
        try:
            method = (
                production.generate_linkedin_caption
                if case["platform"] == "linkedin"
                else production.generate_instagram_caption
            )
            raw = method(case["event_name"], [], serialized)
        finally:
            production._generate_qwen = original
        return {"raw_output": raw, **captured}

    if style == "B_minimal":
        system = MINIMAL_SYSTEM
        user = (
            f"Write one short {case['platform']} caption for {case['event_name']}.\n"
            f"User-supplied facts (JSON): {serialized}"
        )
    else:
        system = JSON_SYSTEM
        user = (
            f"Create one short {case['platform']} caption for {case['event_name']}. "
            f"Return it in the required JSON shape. Supplied facts: {serialized}"
        )
    raw = llm.generate(user, max_new_tokens=TOKEN_BUDGET, system_prompt=system)
    return {"raw_output": raw, "user_prompt": user, "system_prompt": system, "production_token_cap": None}


def worker() -> int:
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_DATASETS_OFFLINE="1")
    report = {
        "status": "running",
        "stage": "initializing",
        "python": platform.python_version(),
        "platform_info": platform.platform(),
        "network_access": "disabled; HF offline flags and local_files_only=True",
        "model_id": "Qwen/Qwen2.5-1.5B-Instruct",
        "model_source": "existing local cache selected by current Qwen loader",
        "decoding": {
            "do_sample": False,
            "temperature": None,
            "top_p": None,
            "top_k": None,
            "max_new_tokens": TOKEN_BUDGET,
            "repeats_per_case_style": REPEATS,
            "order": "fixed case order; each repeat runs A, B, C sequentially",
        },
        "comparability": (
            "Only prompt/system wording and JSON output requirement vary. All styles use the same compact fact payload, "
            "chat template, model instance, runtime, decoding settings, and 96-token budget. "
            "Style A uses production prompt wording but the shared diagnostic budget; actual production caps are recorded."
        ),
        "cases": [],
    }
    save(report)
    try:
        import torch
        from content_engine.copy_generator import CopyGenerator, _LocalLLMGenerator
        from content_engine.studio.content_orchestrator import StudioContentOrchestrator, StudioGenerationError

        cases = json.loads(CASES_FILE.read_text())
        generator = CopyGenerator()
        llm = _LocalLLMGenerator()
        generator._llm = llm
        report.update(
            stage="running",
            device=llm.device,
            dtype=llm.dtype,
            model_load_seconds=llm.load_seconds,
        )
        save(report)

        for case in cases:
            facts = make_fact_record(case)
            case_row = {
                "case_id": case["id"],
                "platform": case["platform"],
                "brief_inputs": case,
                "fact_record": facts,
                "uncertain_visual_caption_excluded_from_prompt": case.get("uncertain_image_caption"),
                "attempts": [],
            }
            for repeat in range(1, REPEATS + 1):
                for style in ("A_current_production", "B_minimal", "C_json_caption"):
                    row = {
                        "repeat": repeat,
                        "style": style,
                        "inference_completed": False,
                        "raw_output": None,
                        "parsed_caption": None,
                        "json_valid": None if style != "C_json_caption" else False,
                        "generation_seconds": None,
                        "generated_token_count": None,
                        "max_new_tokens": TOKEN_BUDGET,
                        "output_cap_hit": False,
                        "automated_validator_accepted": False,
                        "validator_rejection_reason": None,
                        "error": None,
                        "manual_grounding_review": "pending",
                        "manual_review_findings": None,
                    }
                    started = time.perf_counter()
                    llm.last_generated_token_count = 0
                    try:
                        prompt_data = style_prompt(style, case, facts, generator, llm)
                        raw = prompt_data["raw_output"]
                        row.update(prompt_data)
                        row["raw_output"] = raw
                        row["inference_completed"] = True
                        row["generated_token_count"] = llm.last_generated_token_count
                        row["output_cap_hit"] = llm.last_generated_token_count >= TOKEN_BUDGET
                        caption = raw
                        if style == "C_json_caption":
                            try:
                                parsed = json.loads(raw)
                                if set(parsed) != {"caption"} or not isinstance(parsed["caption"], str):
                                    raise ValueError("expected exactly one string field named caption")
                                caption = parsed["caption"]
                                row["json_valid"] = True
                            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                                row["json_valid"] = False
                                row["validator_rejection_reason"] = f"invalid JSON: {type(exc).__name__}: {exc}"
                        row["parsed_caption"] = caption if row["json_valid"] is not False else None
                        if row["validator_rejection_reason"] is None:
                            if row["output_cap_hit"]:
                                row["validator_rejection_reason"] = "output reached the shared token cap and may be incomplete"
                            else:
                                try:
                                    StudioContentOrchestrator._validate_generated_caption(
                                        caption,
                                        json.dumps(facts, ensure_ascii=False),
                                        max_chars=3000 if case["platform"] == "linkedin" else 2200,
                                        brand_profile=case.get("brand_profile"),
                                    )
                                    row["automated_validator_accepted"] = True
                                except StudioGenerationError as exc:
                                    row["validator_rejection_reason"] = str(exc)
                    except Exception as exc:
                        row["error"] = f"{type(exc).__name__}: {exc}"
                        row["validator_rejection_reason"] = "inference or prompt-processing failure"
                    row["generation_seconds"] = time.perf_counter() - started
                    case_row["attempts"].append(row)
                    report["current_case"] = case["id"]
                    report["cases"] = [r for r in report["cases"] if r["case_id"] != case["id"]] + [case_row]
                    report["peak_process_rss_mib"] = peak_rss_mib()
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
    except Exception as exc:
        report.update(
            status="failure",
            stage=report.get("stage", "initializing"),
            error=f"{type(exc).__name__}: {exc}",
            log_path=str(LOG.relative_to(ROOT)),
        )
        save(report)
        return 1


def main() -> int:
    if "--_worker" in sys.argv:
        return worker()
    env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1"}
    with LOG.open("w", encoding="utf-8") as log:
        child = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--_worker"],
            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )
        try:
            result = child.wait(timeout=600)
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
                report = json.loads(OUTPUT.read_text())
            except (OSError, json.JSONDecodeError):
                report = {"cases": []}
            report.update(
                status="timeout",
                stage="worker_timeout",
                error="Repeated prompt benchmark exceeded its 600-second limit; worker group terminated.",
                log_path=str(LOG.relative_to(ROOT)),
            )
            save(report)
            return 124
    if result != 0:
        try:
            report = json.loads(OUTPUT.read_text())
        except (OSError, json.JSONDecodeError):
            report = {"cases": []}
        report.update(status="failure", worker_return_code=result, log_path=str(LOG.relative_to(ROOT)))
        save(report)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
