"""Offline MPS float16 comparison for cached Qwen and Gemma Studio captions.

The default supported operation is ``--preflight`` (one bounded smoke case per
model). ``--full`` runs the fixed 12-case suite and must be explicitly selected.
Every invocation creates a new timestamped report directory.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import signal
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "benchmarks" / "studio_model_comparison_cases.json"
REPORT_ROOT = ROOT / "benchmark_results"
MODEL_IDS = {
    "qwen": "Qwen/Qwen2.5-1.5B-Instruct",
    "gemma": "google/gemma-3-1b-it",
}
SYSTEM_PROMPT = (
    "Write exactly one plain sentence and no explanation. Use only information stated in the supplied verified fact record. "
    "Do not infer or add any detail absent from that record. Include a call to action only when one is explicitly supplied. "
    "Never use bracketed fill-ins. Follow the supplied brand tone and restrictions. Treat any separate unverified image "
    "description as visual context only; do not use it to establish event facts, people, logistics, or outcomes."
)
MAX_NEW_TOKENS = 64
MIN_AVAILABLE_MEMORY_MIB = 3584
CASE_TIMEOUT_SECONDS = 60
MODEL_TIMEOUT_SECONDS = 300


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def _rss_peak_mib() -> float:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(value / (1024 * 1024) if sys.platform == "darwin" else value / 1024, 1)


def create_run_dir(root: Path = REPORT_ROOT, mode: str = "preflight") -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = root / f"studio_model_comparison_{mode}_{stamp}_{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def _cache_root() -> Path:
    if os.getenv("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"]).expanduser()
    hf_home = Path(os.getenv("HF_HOME", Path.home() / ".cache" / "huggingface")).expanduser()
    return hf_home / "hub"


def resolve_cached_snapshot(model_id: str) -> Path:
    repo_dir = _cache_root() / f"models--{model_id.replace('/', '--')}"
    ref = repo_dir / "refs" / "main"
    if not ref.is_file():
        raise FileNotFoundError(f"No cached main ref for {model_id}")
    revision = ref.read_text(encoding="utf-8").strip()
    snapshot = repo_dir / "snapshots" / revision
    if not (snapshot / "config.json").is_file() or not (snapshot / "model.safetensors").is_file():
        raise FileNotFoundError(f"Cached model weights/config incomplete for {model_id}: {snapshot}")
    return snapshot


def build_fact_record(case: dict[str, Any]) -> dict[str, Any]:
    """Build the same explicit Studio fact object for either model."""
    from content_engine.studio.facts import build_fact_record as studio_build_fact_record

    return studio_build_fact_record(
        case["event_name"], case.get("brief", ""),
        activity=case.get("activity"), audience=case.get("audience"),
        date=case.get("date"), time=case.get("time"), location=case.get("location"),
        organizer=case.get("organizer"), call_to_action=case.get("call_to_action"),
        key_points=case.get("key_points"), brand_profile=case.get("brand_profile"),
        tone=(case.get("brand_profile") or {}).get("tone_of_voice"),
    )


def build_messages(case: dict[str, Any], fact_record: dict[str, Any]) -> list[dict[str, str]]:
    platform = case["platform"].casefold()
    if platform == "linkedin":
        requirement = "Write one factual LinkedIn announcement sentence of at most 35 words. No hashtags unless brand guidance asks for them."
    elif platform == "instagram":
        requirement = "Write one factual Instagram caption sentence of at most 24 words. No hashtags unless brand guidance asks for them."
    else:
        raise ValueError(f"Unsupported platform in fixed case: {case['platform']}")
    user_parts = [
        "Verified fact record (sole source for event facts): "
        + json.dumps(fact_record, ensure_ascii=False, separators=(",", ":")),
    ]
    unverified = case.get("uncertain_image_caption")
    if unverified:
        user_parts.append("Unverified image description (not a verified event fact): " + str(unverified))
    user_parts.append("Requirement: " + requirement)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


def validate_caption_read_only(caption: str, fact_record: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    """Call the production validator only; this adapter creates no app/storage/publisher objects."""
    from content_engine.studio.content_orchestrator import (
        StudioContentOrchestrator, StudioGenerationError,
    )

    context = json.dumps(fact_record, ensure_ascii=False, separators=(",", ":"))
    max_chars = 3000 if case["platform"].casefold() == "linkedin" else 2200
    try:
        StudioContentOrchestrator._validate_generated_caption(
            caption, context, max_chars=max_chars, brand_profile=case.get("brand_profile"),
        )
        return {"status": "accepted", "reason": None}
    except StudioGenerationError as exc:
        return {"status": "rejected", "reason": str(exc)}


def _memory_info() -> dict[str, Any]:
    import psutil
    memory = psutil.virtual_memory()
    return {
        "total_mib": round(memory.total / 1048576, 1),
        "available_mib": round(memory.available / 1048576, 1),
        "percent_used": memory.percent,
    }


def preflight_blocker(mps_available: bool, memory: dict[str, Any], minimum_mib: int = MIN_AVAILABLE_MEMORY_MIB) -> str | None:
    if not mps_available:
        return "MPS unavailable; CPU fallback is prohibited"
    if memory.get("available_mib", 0) < minimum_mib:
        return f"Only {memory.get('available_mib')} MiB available; require {minimum_mib} MiB before model load"
    return None


def _mps_info(torch_module: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    try:
        result["current_allocated_mib"] = round(torch_module.mps.current_allocated_memory() / 1048576, 1)
        result["driver_allocated_mib"] = round(torch_module.mps.driver_allocated_memory() / 1048576, 1)
    except Exception:
        result["available"] = False
    return result


def _load_components(model_id: str) -> tuple[Any, Any, dict[str, Any]]:
    import torch
    import transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer

    memory = _memory_info()
    blocker = preflight_blocker(torch.backends.mps.is_available(), memory)
    if blocker:
        raise RuntimeError(blocker)
    snapshot = resolve_cached_snapshot(model_id)
    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True)
    tokenizer_seconds = time.perf_counter() - started
    model_started = time.perf_counter()
    model = AutoModelForCausalLM.from_pretrained(
        str(snapshot), local_files_only=True, torch_dtype=torch.float16,
    ).to("mps").eval()
    model_seconds = time.perf_counter() - model_started
    info = {
        "model_id": model_id,
        "snapshot_path": str(snapshot),
        "device": "mps",
        "dtype": "float16",
        "quantization": "none",
        "tokenizer_load_seconds": tokenizer_seconds,
        "model_load_seconds": model_seconds,
        "total_load_seconds": tokenizer_seconds + model_seconds,
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "memory_before_load": memory,
        "memory_after_load": _memory_info(),
        "mps_after_load": _mps_info(torch),
        "peak_process_rss_after_load_mib": _rss_peak_mib(),
    }
    return tokenizer, model, info


def _atomic_case_checkpoint(report_path: Path, report: dict[str, Any]) -> None:
    report["completed_cases"] = sum(row.get("inference_status") == "completed" for row in report["results"])
    report["failed_cases"] = sum(row.get("inference_status") in {"error", "timeout"} for row in report["results"])
    _atomic_write(report_path, report)


def _model_child(model_key: str, run_dir: Path, mode: str, max_new_tokens: int,
                 case_timeout: int) -> int:
    model_id = MODEL_IDS[model_key]
    all_cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    selected_cases = all_cases[:1] if mode == "preflight" else all_cases
    report_path = run_dir / f"{model_key}.json"
    report: dict[str, Any] = {
        "status": "running", "stage": "startup", "model_key": model_key,
        "model_id": model_id, "mode": mode, "device": "mps", "dtype": "float16",
        "quantization": "none", "offline": True, "local_files_only": True,
        "generation": {"do_sample": False, "max_new_tokens": max_new_tokens},
        "case_timeout_seconds": case_timeout,
        "results": [], "manual_grounding_review": "pending",
    }
    _atomic_write(report_path, report)
    try:
        import torch
        report.update({
            "stage": "device_preflight", "torch": torch.__version__,
            "mps_built": torch.backends.mps.is_built(),
            "mps_available": torch.backends.mps.is_available(),
            "memory_before_load": _memory_info(),
        })
        _atomic_write(report_path, report)
        blocker = preflight_blocker(report["mps_available"], report["memory_before_load"])
        if blocker:
            raise RuntimeError(blocker)
        report["stage"] = "model_load"
        _atomic_write(report_path, report)
        tokenizer, model, model_info = _load_components(model_id)
        report.update(model_info, stage="generation")
        _atomic_write(report_path, report)
        for case in selected_cases:
            fact_record = build_fact_record(case)
            messages = build_messages(case, fact_record)
            row: dict[str, Any] = {
                "case_id": case["id"], "platform": case["platform"],
                "input_case": case, "fact_record": fact_record,
                "unverified_image_caption_excluded_from_facts": case.get("uncertain_image_caption"),
                "prompt_messages": messages,
                "inference_status": "running", "automatic_grounding": {"status": "not_run", "reason": None},
                "manual_grounding_review": {"status": "pending", "unsupported_claim": None, "reviewer": None},
                "raw_output": None,
            }
            report["active_case_id"] = case["id"]
            report["active_case_started_monotonic"] = time.monotonic()
            report["results"].append(row)
            _atomic_case_checkpoint(report_path, report)
            prompt_started = time.perf_counter()
            try:
                formatted = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                inputs = tokenizer(formatted, return_tensors="pt")
                input_token_count = int(inputs["input_ids"].shape[1])
                inputs = inputs.to("mps")
                generation_started = time.perf_counter()
                with torch.inference_mode():
                    output = model.generate(
                        **inputs, max_new_tokens=max_new_tokens, do_sample=False,
                        pad_token_id=tokenizer.eos_token_id,
                    )
                generation_seconds = time.perf_counter() - generation_started
                generated_tokens = output[0][inputs["input_ids"].shape[1]:]
                caption = tokenizer.decode(generated_tokens, skip_special_tokens=True).strip()
                validation = validate_caption_read_only(caption, fact_record, case)
                row.update({
                    "inference_status": "completed", "raw_output": caption,
                    "automatic_grounding": validation,
                    "token_count": int(generated_tokens.shape[0]),
                    "input_token_count": input_token_count,
                    "prompt_prepare_seconds": generation_started - prompt_started,
                    "generation_seconds": generation_seconds,
                    "mps_after_case": _mps_info(torch),
                    "peak_process_rss_mib_after_case": _rss_peak_mib(),
                })
            except Exception as exc:
                row.update({
                    "inference_status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "automatic_grounding": {"status": "not_run", "reason": None},
                    "peak_process_rss_mib_after_case": _rss_peak_mib(),
                })
            report["active_case_id"] = None
            report["active_case_started_monotonic"] = None
            _atomic_case_checkpoint(report_path, report)
            if row["inference_status"] != "completed":
                for remaining in selected_cases:
                    if remaining["id"] != case["id"] and not any(r.get("case_id") == remaining["id"] for r in report["results"]):
                        report["results"].append({
                            "case_id": remaining["id"], "platform": remaining["platform"],
                            "input_case": remaining, "fact_record": build_fact_record(remaining),
                            "inference_status": "not_run",
                            "automatic_grounding": {"status": "not_run", "reason": None},
                            "manual_grounding_review": {"status": "pending", "unsupported_claim": None, "reviewer": None},
                            "error": "Stopped after prior case inference failure", "raw_output": None,
                        })
                report.update(status="inference_failure", stage="case_error")
                _atomic_write(report_path, report)
                return 1
        report.update(status="success", stage="complete", completed_at_utc=datetime.now(timezone.utc).isoformat())
        _atomic_write(report_path, report)
        del model, tokenizer
        return 0
    except Exception as exc:
        existing_ids = {row.get("case_id") for row in report.get("results", [])}
        for case in selected_cases:
            if case["id"] not in existing_ids:
                report.setdefault("results", []).append({
                    "case_id": case["id"], "platform": case["platform"],
                    "input_case": case, "fact_record": build_fact_record(case),
                    "inference_status": "not_run",
                    "automatic_grounding": {"status": "not_run", "reason": None},
                    "manual_grounding_review": {"status": "pending", "unsupported_claim": None, "reviewer": None},
                    "error": f"Model initialization/preflight failed: {type(exc).__name__}", "raw_output": None,
                })
        report.update(
            status="preflight_failure" if mode == "preflight" else "load_failure",
            stage=report.get("stage", "startup"),
            error=f"{type(exc).__name__}: {exc}",
            peak_process_rss_mib=_rss_peak_mib(),
        )
        _atomic_write(report_path, report)
        return 1


def _terminate_owned_group(child: subprocess.Popen[Any]) -> str:
    if os.name == "posix":
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            return "already_exited"
    else:
        child.terminate()
    try:
        child.wait(timeout=5)
        return "SIGTERM"
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            child.kill()
        child.wait()
        return "SIGKILL_after_SIGTERM"


def _run_model_bounded(model_key: str, run_dir: Path, mode: str, max_new_tokens: int,
                       case_timeout: int, model_timeout: int) -> dict[str, Any]:
    report_path = run_dir / f"{model_key}.json"
    log_path = run_dir / f"{model_key}.log"
    command = [
        sys.executable, str(Path(__file__).resolve()), "--_model-child", model_key,
        "--run-dir", str(run_dir), "--mode", mode,
        "--max-new-tokens", str(max_new_tokens), "--case-timeout-seconds", str(case_timeout),
    ]
    env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log:
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                 start_new_session=(os.name == "posix"))
        reason = None
        while child.poll() is None:
            now = time.monotonic()
            try:
                snapshot = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                snapshot = {}
            case_started = snapshot.get("active_case_started_monotonic")
            if case_started is not None and now - case_started > case_timeout:
                reason = "case_timeout"
                break
            if now - started > model_timeout:
                reason = "model_timeout"
                break
            time.sleep(0.2)
        if reason:
            termination = _terminate_owned_group(child)
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                report = {"model_key": model_key, "model_id": MODEL_IDS[model_key], "results": []}
            if reason == "case_timeout":
                active = report.get("active_case_id")
                if active and not any(r.get("case_id") == active and r.get("inference_status") == "timeout" for r in report.get("results", [])):
                    for row in report.get("results", []):
                        if row.get("case_id") == active and row.get("inference_status") == "running":
                            row.update(inference_status="timeout", error=f"Exceeded {case_timeout}s case deadline")
                            row["automatic_grounding"] = {"status": "not_run", "reason": None}
                            break
            report.update(
                status="timeout", stage=reason, timeout_reason=reason,
                termination_reason=f"terminated only child process group {child.pid}: {termination}",
                model_timeout_seconds=model_timeout,
            )
            report["active_case_id"] = None
            report["active_case_started_monotonic"] = None
            all_cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
            selected_cases = all_cases[:1] if mode == "preflight" else all_cases
            existing_ids = {row.get("case_id") for row in report.get("results", [])}
            for case in selected_cases:
                if case["id"] not in existing_ids:
                    report.setdefault("results", []).append({
                        "case_id": case["id"], "platform": case["platform"],
                        "input_case": case, "fact_record": build_fact_record(case),
                        "inference_status": "not_run",
                        "automatic_grounding": {"status": "not_run", "reason": None},
                        "manual_grounding_review": {"status": "pending", "unsupported_claim": None, "reviewer": None},
                        "error": f"Not attempted because {reason} stopped this model run", "raw_output": None,
                    })
            _atomic_write(report_path, report)
        else:
            child.wait()
    try:
        return json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "report_failure", "model_id": MODEL_IDS[model_key], "log_path": str(log_path)}


def _license_metadata() -> dict[str, Any]:
    metadata = {}
    for key, model_id in MODEL_IDS.items():
        try:
            snapshot = resolve_cached_snapshot(model_id)
            readme = snapshot / "README.md"
            lines = readme.read_text(encoding="utf-8", errors="replace").splitlines() if readme.exists() else []
            metadata[key] = {
                "model_id": model_id,
                "snapshot_path": str(snapshot),
                "license_lines": [line.strip() for line in lines[:60] if "license" in line.casefold() or "gated" in line.casefold() or "agree to" in line.casefold()],
                "license_review_status": "not_assessed",
            }
        except Exception as exc:
            metadata[key] = {"model_id": model_id, "cache_error": f"{type(exc).__name__}: {exc}"}
    if "gemma" in metadata:
        metadata["gemma"]["license_review_status"] = "review required; cache is not proof of approval"
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--preflight", action="store_true", help="Run one smoke generation per cached model")
    operation.add_argument("--full", action="store_true", help="Run all 12 fixed cases per model")
    parser.add_argument("--max-new-tokens", type=int, default=MAX_NEW_TOKENS)
    parser.add_argument("--case-timeout-seconds", type=int, default=CASE_TIMEOUT_SECONDS)
    parser.add_argument("--model-timeout-seconds", type=int, default=MODEL_TIMEOUT_SECONDS)
    parser.add_argument("--_model-child", choices=sorted(MODEL_IDS), help=argparse.SUPPRESS)
    parser.add_argument("--run-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=("preflight", "full"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args._model_child:
        if not args.run_dir or not args.mode:
            parser.error("child mode requires --run-dir and --mode")
        return _model_child(args._model_child, args.run_dir, args.mode,
                            args.max_new_tokens, args.case_timeout_seconds)

    mode = "full" if args.full else "preflight"
    run_dir = create_run_dir(mode=mode)
    prompt_cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    report: dict[str, Any] = {
        "status": "running", "mode": mode, "run_id": run_dir.name,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": " ".join(sys.argv),
        "cases_path": str(CASES_PATH), "all_case_ids": [case["id"] for case in prompt_cases],
        "case_ids": [case["id"] for case in (prompt_cases if mode == "full" else prompt_cases[:1])],
        "model_ids": MODEL_IDS, "device": "mps", "dtype": "float16", "quantization": "none",
        "offline_flags": {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
        "local_files_only": True,
        "generation": {"do_sample": False, "max_new_tokens": args.max_new_tokens},
        "case_timeout_seconds": args.case_timeout_seconds,
        "model_timeout_seconds": args.model_timeout_seconds,
        "minimum_available_memory_mib_before_load": MIN_AVAILABLE_MEMORY_MIB,
        "license_metadata": _license_metadata(),
        "results": {},
        "outcome_definitions": {
            "inference_status": ["completed", "timeout", "error", "not_run"],
            "automatic_grounding": ["accepted", "rejected", "not_run"],
            "manual_grounding_review": ["pending", "grounded", "unsupported"],
        },
        "validator_adapter": "Calls StudioContentOrchestrator._validate_generated_caption only; it does not instantiate the orchestrator, storage, API routes, or publishing integrations.",
        "full_comparison_ready": False,
        "next_full_command": "HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 ./.venv311/bin/python scripts/benchmark_studio_models.py --full",
        "memory_note": "RSS and MPS allocations are separate measurements, may overlap, and are not summed as unified-memory use.",
    }
    _atomic_write(run_dir / "preflight.json" if mode == "preflight" else run_dir / "summary.json", report)

    try:
        import torch
        report["torch"] = torch.__version__
        report["mps_built"] = torch.backends.mps.is_built()
        report["mps_available"] = torch.backends.mps.is_available()
        report["memory_before_any_model"] = _memory_info()
    except Exception as exc:
        report.update(status="blocked", blocker=f"MPS preflight failed: {type(exc).__name__}: {exc}")
        _atomic_write(run_dir / ("preflight.json" if mode == "preflight" else "summary.json"), report)
        print(run_dir)
        return 2
    blocker = preflight_blocker(report["mps_available"], report["memory_before_any_model"])
    if blocker:
        report.update(
            status="blocked", blocker=blocker,
            results={
                "qwen": {"status": "not_run_memory_or_device_guard"},
                "gemma": {"status": "not_run_memory_or_device_guard"},
            },
            preflight_smoke_status="not_run_memory_or_device_guard",
            full_comparison_ready=False,
            recommendation="Do not start either model until MPS is available and at least the configured memory headroom is free; rerun --preflight first.",
        )
        _atomic_write(run_dir / ("preflight.json" if mode == "preflight" else "summary.json"), report)
        print(run_dir)
        return 2
    report["memory_guard_note"] = "3.5 GiB minimum leaves modest headroom above prior ~3.2 GiB Qwen MPS driver allocation; it is a conservative guard, not a total-memory prediction."

    failures = []
    for model_key in ("qwen", "gemma"):
        # Recheck between sequential model processes so a previous run can release MPS memory.
        current_memory = _memory_info()
        blocker = preflight_blocker(report["mps_available"], current_memory)
        if blocker:
            report["results"][model_key] = {
                "status": "not_run_memory_guard",
                "memory_before_model": current_memory,
                "error": f"Stopped before loading {MODEL_IDS[model_key]}: {blocker}",
            }
            failures.append(model_key)
            break
        result = _run_model_bounded(
            model_key, run_dir, mode, args.max_new_tokens,
            args.case_timeout_seconds, args.model_timeout_seconds,
        )
        report["results"][model_key] = {
            "status": result.get("status"),
            "report_path": str(run_dir / f"{model_key}.json"),
            "log_path": str(run_dir / f"{model_key}.log"),
            "model_load_seconds": result.get("total_load_seconds"),
            "device": result.get("device"), "dtype": result.get("dtype"),
            "completed_cases": result.get("completed_cases", 0),
        }
        _atomic_write(run_dir / ("preflight.json" if mode == "preflight" else "summary.json"), report)
        if result.get("status") != "success":
            failures.append(model_key)
            if mode == "preflight":
                report["results"].setdefault("gemma" if model_key == "qwen" else "qwen", {"status": "not_run_after_preflight_failure"})
                break
    report.update(
        status="ready_for_full_comparison" if mode == "preflight" and not failures
        else "preflight_failed" if mode == "preflight"
        else "full_comparison_complete" if not failures else "full_comparison_incomplete",
        preflight_passed=(mode == "preflight" and not failures),
        independent_human_review="pending; no output is auto-labeled grounded",
    )
    _atomic_write(run_dir / ("preflight.json" if mode == "preflight" else "summary.json"), report)
    print(run_dir)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
