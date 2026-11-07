"""Bounded, local-only one-prompt Qwen smoke test on Apple MPS."""
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "Qwen/Qwen2.5-1.5B-Instruct"
REPORT = ROOT / "benchmark_results" / "qwen_mps_single.json"
LOG = ROOT / "benchmark_results" / "qwen_mps_single.log"


def _save(data: dict) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=REPORT.parent,
            prefix=f".{REPORT.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, REPORT)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def _peak_rss_mib() -> float:
    # Darwin reports ru_maxrss in bytes (Linux reports KiB).
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / (1024 * 1024) if sys.platform == "darwin" else value / 1024


def _mps_memory(torch) -> dict:
    values = {}
    for output, method in (
        ("current_allocated_mib", "current_allocated_memory"),
        ("driver_allocated_mib", "driver_allocated_memory"),
        ("recommended_max_mib", "recommended_max_memory"),
    ):
        function = getattr(torch.mps, method, None)
        try:
            values[output] = round(function() / (1024 * 1024), 1) if function else None
        except Exception:
            values[output] = None
    return values


def _worker() -> int:
    report = {
        "model_id": MODEL_ID,
        "status": "running",
        "stage": "imports",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "device": "mps",
        "dtype": "float16",
        "generation": {"do_sample": False, "max_new_tokens": 32},
        "prompt": "Write one short, friendly sentence welcoming attendees to a fictional community meetup.",
        "network_access": "disabled; local_files_only=True",
    }
    _save(report)
    try:
        import torch
        import transformers
        import tokenizers

        report.update({
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "tokenizers": tokenizers.__version__,
            "mps_built": torch.backends.mps.is_built(),
            "mps_available": torch.backends.mps.is_available(),
            "peak_rss_mib_before_load": round(_peak_rss_mib(), 1),
        })
        if not torch.backends.mps.is_available():
            report.update(status="load_failure", stage="mps_unavailable",
                          error="PyTorch reports MPS unavailable in this process")
            _save(report)
            return 1

        from transformers import AutoModelForCausalLM, AutoTokenizer

        tokenizer_started = time.perf_counter()
        tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, local_files_only=True)
        report["tokenizer_load_seconds"] = time.perf_counter() - tokenizer_started
        model_started = time.perf_counter()
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_ID, local_files_only=True, torch_dtype=torch.float16,
        ).to("mps").eval()
        torch.mps.synchronize()
        report["model_load_seconds"] = time.perf_counter() - model_started
        report["load_seconds"] = report["tokenizer_load_seconds"] + report["model_load_seconds"]
        report["peak_rss_mib_after_load"] = round(_peak_rss_mib(), 1)
        report["mps_memory_after_load"] = _mps_memory(torch)
        report.update(status="running", stage="prompt_preparation")
        _save(report)

        prompt_started = time.perf_counter()
        formatted = tokenizer.apply_chat_template(
            [{"role": "user", "content": report["prompt"]}],
            tokenize=False, add_generation_prompt=True,
        )
        report["prompt_preparation_seconds"] = time.perf_counter() - prompt_started
        tokenization_started = time.perf_counter()
        inputs = tokenizer(formatted, return_tensors="pt")
        report["tokenization_seconds"] = time.perf_counter() - tokenization_started
        prompt_tokens = int(inputs["input_ids"].shape[1])
        inputs = {key: value.to("mps") for key, value in inputs.items()}

        report.update(status="running", stage="generation", prompt_tokens=prompt_tokens)
        _save(report)
        torch.mps.synchronize()
        generation_started = time.perf_counter()
        with torch.inference_mode():
            generated = model.generate(
                **inputs,
                max_new_tokens=32,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )
        torch.mps.synchronize()
        report["generation_seconds"] = time.perf_counter() - generation_started
        report["generated_token_count"] = int(generated.shape[1] - prompt_tokens)
        report["output"] = tokenizer.decode(
            generated[0][prompt_tokens:], skip_special_tokens=True,
        ).strip()
        report["peak_rss_mib_after_generation"] = round(_peak_rss_mib(), 1)
        report["mps_memory_after_generation"] = _mps_memory(torch)
        report["status"] = "success" if report["output"] else "inference_failure"
        report["stage"] = "complete" if report["output"] else "empty_output"
        _save(report)
        del generated, inputs, model, tokenizer
        return 0 if report["status"] == "success" else 1
    except Exception as exc:
        report.update(
            status="inference_failure" if report.get("stage") == "generation" else "load_failure",
            error=f"{type(exc).__name__}: {exc}",
            traceback=traceback.format_exc(),
            peak_rss_mib_at_failure=round(_peak_rss_mib(), 1),
        )
        _save(report)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args._worker:
        return _worker()

    LOG.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(Path(__file__).resolve()), "--_worker"]
    environment = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    with LOG.open("w", encoding="utf-8") as log:
        child = subprocess.Popen(
            command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=(os.name == "posix"),
        )
        try:
            child.communicate(timeout=args.timeout_seconds)
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
            try:
                report = json.loads(REPORT.read_text())
            except (OSError, json.JSONDecodeError):
                report = {"model_id": MODEL_ID, "results": []}
            report.update(
                status="timeout", stage="process_timeout",
                timeout_seconds=args.timeout_seconds,
                error="Qwen smoke process exceeded its wall-time limit; the child process group was terminated.",
                log_path=str(LOG.relative_to(ROOT)),
            )
            _save(report)
            return 124
    return child.returncode or 0


if __name__ == "__main__":
    raise SystemExit(main())
