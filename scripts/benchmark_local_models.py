"""Sequential, local-only text-model comparison harness.

Run one model per child process so ru_maxrss is an independent high-water mark.
Weights are never downloaded by this script. Outputs are saved for human review;
the simple checks below are diagnostics, not semantic quality scores.
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "benchmarks" / "model_prompts.json"
MODELS = {
    "qwen": "Qwen/Qwen2.5-1.5B-Instruct",
    "gemma": "google/gemma-3-1b-it",
}
QUICK_PROMPT_IDS = ["linkedin_professional", "instagram_caption", "structured_json"]


def _rss_peak_mib() -> float:
    # macOS reports ru_maxrss in bytes; Linux reports KiB.
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / (1024 * 1024) if sys.platform == "darwin" else value / 1024


def _save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(data, temporary, indent=2, ensure_ascii=False)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def _merge_prompt_ids(existing_ids: list[str], requested_ids: list[str]) -> list[str]:
    return list(dict.fromkeys([*existing_ids, *requested_ids]))


def _deduplicate_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        prompt_id = row.get("id")
        if not prompt_id:
            continue
        previous = by_id.get(prompt_id)
        if previous is None or row.get("status") == "ok" or previous.get("status") != "ok":
            by_id[prompt_id] = row
    return list(by_id.values())


def _run_child(command: list[str], cwd: Path, env: dict[str, str], log_path: Path,
               timeout_seconds: int) -> tuple[str, int | None]:
    """Run one child in its own process group; timeouts terminate only that group."""
    with log_path.open("a") as log:
        child = subprocess.Popen(
            command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=(os.name == "posix"),
        )
        try:
            child.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            else:
                child.terminate()
            try:
                child.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    child.kill()
                child.communicate()
            return "timeout", child.returncode
    return "completed", child.returncode


def _checkpoint_prompt(report_path: Path, report: dict[str, Any], result: dict[str, Any],
                       prompt_ids: list[str], peak_rss_mib: float) -> None:
    existing = {row["id"]: row for row in report.get("results", [])}
    existing[result["id"]] = result
    results = [existing[key] for key in prompt_ids if key in existing]
    report["results"] = results
    report["successful_prompts"] = sum(row["status"] == "ok" for row in results)
    report["failed_prompts"] = sum(row["status"] != "ok" for row in results)
    report["peak_process_rss_mib"] = peak_rss_mib
    report["status"] = "running"
    _save(report_path, report)


def _model_run(model_key: str, out_dir: Path, prompt_ids: list[str], max_new_tokens: int = 48,
               torch_threads: int = 4, resume: bool = True) -> int:
    model_id = MODELS[model_key]
    all_prompts = json.loads(PROMPTS.read_text())
    report_path = out_dir / f"{model_key}.json"
    report = {}
    if resume and report_path.exists():
        try:
            report = json.loads(report_path.read_text())
        except (OSError, json.JSONDecodeError):
            report = {}
    prompt_ids = _merge_prompt_ids(report.get("prompt_ids", []), prompt_ids)
    results = _deduplicate_results(report.get("results", []))
    prompts = [item for item in all_prompts if item["id"] in prompt_ids]
    completed_ids = {item["id"] for item in results if item.get("status") == "ok"}
    report.update({
        "model_id": model_id,
        "status": "running",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "hardware": platform.platform(),
        "processor": platform.processor(),
        "device": "cpu",
        "dtype": "bfloat16 (model config; both caches declare bfloat16)",
        "generation": {"do_sample": False, "max_new_tokens": max_new_tokens},
        "torch_threads": torch_threads,
        "prompt_ids": prompt_ids,
        "results": results,
        "time_to_first_token": "Unavailable: non-streaming generate() API used.",
        "quality_note": "Semantic quality is for human review; no heuristic score is presented as objective quality.",
    })
    _save(report_path, report)

    try:
        import torch
        import transformers
        import tokenizers
        torch.set_num_threads(torch_threads)
    except Exception as exc:
        report.update({
            "status": "load_failure", "stage": "dependency_import",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })
        _save(report_path, report)
        return 1

    report.update({
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "tokenizers": tokenizers.__version__,
        "mps_built": torch.backends.mps.is_built(),
        "mps_available": torch.backends.mps.is_available(),
        "peak_process_rss_mib_before_load": _rss_peak_mib(),
    })
    _save(report_path, report)
    model_started = time.perf_counter()
    try:
        tokenizer, model = _load_local_components(model_id, torch)
        load_s = time.perf_counter() - model_started
        report.update({"load_seconds": load_s, "peak_process_rss_after_load_mib": _rss_peak_mib()})
        _save(report_path, report)
    except Exception as exc:
        report.update({
            "status": "load_failure", "stage": "load",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "load_seconds": time.perf_counter() - model_started,
            "peak_process_rss_mib": _rss_peak_mib(),
        })
        _save(report_path, report)
        return 1

    for item in prompts:
        if item["id"] in completed_ids:
            continue
        messages = [
            {"role": "system", "content": "Write grounded social content using only the supplied brief, image descriptions, and brand profile. Treat image descriptions as uncertain captions, not verified facts."},
            {"role": "user", "content": (
                f"Platform: {item['platform']}\nBrief: {item['brief']}\n"
                f"Image descriptions (unverified): {json.dumps(item['captions'])}\n"
                f"Brand profile: {item['brand']}\nRequirement: {item['requirement']}"
            )},
        ]
        prompt_started = time.perf_counter()
        try:
            formatted = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            inputs = tokenizer(formatted, return_tensors="pt", truncation=True, max_length=1024)
            first_started = time.perf_counter()
            with torch.inference_mode():
                generated = model.generate(
                    **inputs, max_new_tokens=max_new_tokens, do_sample=False,
                    pad_token_id=tokenizer.eos_token_id,
                )
            latency = time.perf_counter() - first_started
            text = tokenizer.decode(generated[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()
            results.append({
                "id": item["id"], "category": item["category"], "status": "ok",
                "prompt_seconds": first_started - prompt_started,
                "generation_seconds": latency,
                "output": text,
                "json_valid": _json_valid(text) if item["id"] == "structured_json" else None,
                "schema_name": "benchmark_caption_json_v1" if item["id"] == "structured_json" else None,
                "peak_process_rss_mib_after_prompt": _rss_peak_mib(),
            })
        except Exception as exc:
            results.append({
                "id": item["id"], "category": item["category"], "status": "inference_failure",
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
                "peak_process_rss_mib_after_prompt": _rss_peak_mib(),
            })
        # Persist immediately so a crash or interruption cannot erase earlier prompt results.
        results = report.get("results", results)
        _checkpoint_prompt(report_path, report, results[-1], prompt_ids, _rss_peak_mib())
        print(f"{model_key}: saved prompt {item['id']} ({results[-1]['status']})", flush=True)
    result_ids = {x["id"] for x in results if x.get("status") == "ok"}
    if any(x.get("status") == "inference_failure" for x in results):
        report["status"] = "inference_failure"
    elif len(result_ids | completed_ids) >= len(prompt_ids):
        report["status"] = "success"
    else:
        report["status"] = "incomplete"
    report["peak_process_rss_mib"] = _rss_peak_mib()
    _save(report_path, report)
    del model, tokenizer
    return 0 if report["status"] == "success" else 1


def _load_local_components(model_id: str, torch_module: Any):
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(model_id, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_id, local_files_only=True, torch_dtype=torch_module.bfloat16
    ).to("cpu")
    return tokenizer, model.eval()


def _json_valid(text: str) -> bool:
    try:
        data = json.loads(text)
        return (isinstance(data, dict) and set(data) == {"caption", "hashtags", "uncertainty"}
                and isinstance(data["caption"], str)
                and isinstance(data["hashtags"], list)
                and all(isinstance(x, str) for x in data["hashtags"])
                and isinstance(data["uncertainty"], list)
                and all(isinstance(x, str) for x in data["uncertainty"]))
    except (json.JSONDecodeError, TypeError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "benchmark_results")
    parser.add_argument("--models", nargs="+", choices=sorted(MODELS), default=["qwen", "gemma"])
    parser.add_argument("--full-suite", action="store_true", help="Run all ten deterministic prompts instead of the three-prompt comparison.")
    parser.add_argument("--max-new-tokens", type=int, default=48)
    parser.add_argument("--torch-threads", type=int, default=4)
    parser.add_argument("--run-timeout-seconds", type=int, default=180,
                        help="Maximum wall time for each model process; partial prompt results are retained.")
    parser.add_argument("--no-resume", action="store_true", help="Re-run completed prompts in an existing report.")
    parser.add_argument("--_model-child", choices=sorted(MODELS), help=argparse.SUPPRESS)
    parser.add_argument("--_prompt-ids", nargs="+", help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args._model_child:
        return _model_run(args._model_child, args.output_dir, args._prompt_ids or [],
                          max_new_tokens=args.max_new_tokens, torch_threads=args.torch_threads,
                          resume=not args.no_resume)
    if args.full_suite:
        prompt_ids = [item["id"] for item in json.loads(PROMPTS.read_text())]
    else:
        prompt_ids = QUICK_PROMPT_IDS
    failures = 0
    for model_key in args.models:
        command = [sys.executable, str(Path(__file__).resolve()), "--output-dir", str(args.output_dir),
                   "--max-new-tokens", str(args.max_new_tokens), "--torch-threads", str(args.torch_threads),
                   "--_model-child", model_key, "--_prompt-ids", *prompt_ids]
        if args.no_resume:
            command.append("--no-resume")
        child_report = args.output_dir / f"{model_key}.json"
        log_path = args.output_dir / f"{model_key}.log"
        args.output_dir.mkdir(parents=True, exist_ok=True)
        run_status = "process_failure"
        try:
            run_status, child_return_code = _run_child(
                command, ROOT,
                {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
                log_path, args.run_timeout_seconds,
            )
            return_code = 124 if run_status == "timeout" else child_return_code
        except OSError as exc:
            return_code = 127
            try:
                failed = json.loads(child_report.read_text())
            except (OSError, json.JSONDecodeError):
                failed = {"model_id": MODELS[model_key], "results": []}
            failed.update({"status": "process_failure", "stage": "process_start",
                           "error": f"Unable to start model process: {type(exc).__name__}",
                           "log_path": str(log_path)})
            _save(child_report, failed)
        if run_status == "timeout":
            try:
                timed = json.loads(child_report.read_text())
            except (OSError, json.JSONDecodeError):
                timed = {"model_id": MODELS[model_key], "results": []}
            timed.update({"status": "timeout", "stage": "process_timeout",
                          "timeout_seconds": args.run_timeout_seconds,
                          "error": "Model process exceeded the configured wall-time limit; completed prompt results are preserved.",
                          "log_path": str(log_path)})
            _save(child_report, timed)
        if not child_report.exists():
            _save(child_report, {
                "model_id": MODELS[model_key], "status": "process_failure",
                "stage": "process", "error": "Model subprocess exited before writing a report.",
                "return_code": return_code,
                "signal": -return_code if return_code < 0 else None,
                "python": platform.python_version(), "hardware": platform.platform(),
                "quality_note": "No semantic quality result is available.",
            })
        elif return_code != 0 and run_status != "timeout":
            try:
                existing = json.loads(child_report.read_text())
            except (OSError, json.JSONDecodeError):
                existing = {"model_id": MODELS[model_key], "results": []}
            if existing.get("status") not in {"load_failure", "inference_failure", "timeout"}:
                existing["status"] = "process_failure"
            existing.update({"stage": existing.get("stage", "process"), "return_code": return_code,
                             "signal": -return_code if return_code < 0 else None, "log_path": str(log_path)})
            _save(child_report, existing)
        failures += int(return_code != 0)
    summary = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "models": {key: f"{key}.json" for key in args.models},
        "failed_model_runs": failures,
        "run_timeout_seconds_per_model": args.run_timeout_seconds,
        "prompt_ids": prompt_ids,
        "dtype": "bfloat16 (CPU; model configs declare bfloat16)",
        "generation": {"do_sample": False, "max_new_tokens": args.max_new_tokens},
        "torch_threads": args.torch_threads,
        "instructions": "Review saved outputs manually. Each prompt is checkpointed immediately and completed prompts can be resumed. A missing local model or runtime incompatibility is recorded as a failure; no download is attempted.",
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
