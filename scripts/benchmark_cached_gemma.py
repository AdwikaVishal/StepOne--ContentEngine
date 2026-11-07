"""Bounded, offline load/generation probe for the already-cached Gemma 3 1B model."""
from __future__ import annotations

import json
import os
import platform
import resource
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "benchmark_results" / "cached_gemma_mps.json"
LOG = ROOT / "benchmark_results" / "cached_gemma_mps.log"


def save(data: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=OUT.parent, delete=False) as f:
            tmp = Path(f.name)
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, OUT)
    finally:
        if tmp and tmp.exists():
            tmp.unlink()


def rss_mib() -> float:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / (1024 * 1024) if sys.platform == "darwin" else value / 1024


def worker() -> int:
    result = {
        "status": "running", "stage": "setup", "model_id": "google/gemma-3-1b-it",
        "quantization": "none; cached safetensors loaded in float16",
        "network_access": "disabled; local_files_only=True; HF offline flags",
        "python": platform.python_version(), "machine": platform.machine(),
    }
    save(result)
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        if not torch.backends.mps.is_available():
            raise RuntimeError("MPS is unavailable in this process; CPU fallback is intentionally disabled")
        model_id = result["model_id"]
        t0 = time.perf_counter()
        result["stage"] = "tokenizer_load"
        save(result)
        tokenizer = AutoTokenizer.from_pretrained(model_id, local_files_only=True)
        result["tokenizer_load_seconds"] = time.perf_counter() - t0
        t1 = time.perf_counter()
        result["stage"] = "model_load"
        save(result)
        model = AutoModelForCausalLM.from_pretrained(
            model_id, local_files_only=True, torch_dtype=torch.float16,
        ).to("mps").eval()
        result["model_load_seconds"] = time.perf_counter() - t1
        result["total_load_seconds"] = time.perf_counter() - t0
        result["torch"] = torch.__version__
        result["mps_available"] = True
        result["dtype"] = "float16"
        result["parameter_count"] = sum(p.numel() for p in model.parameters())
        result["peak_rss_after_load_mib"] = round(rss_mib(), 1)
        result["mps_memory_after_load_mib"] = {
            "current_allocated": round(torch.mps.current_allocated_memory() / 1048576, 1),
            "driver_allocated": round(torch.mps.driver_allocated_memory() / 1048576, 1),
        }
        prompt = "Write one concise caption: Volunteers review a food sorting plan and bring questions."
        formatted = tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}], tokenize=False, add_generation_prompt=True,
        )
        started = time.perf_counter()
        tokens = tokenizer(formatted, return_tensors="pt").to("mps")
        result["input_token_count"] = int(tokens["input_ids"].shape[1])
        result["tokenization_seconds"] = time.perf_counter() - started
        generation_started = time.perf_counter()
        result["stage"] = "generation"
        save(result)
        with torch.no_grad():
            output = model.generate(
                **tokens, max_new_tokens=24, do_sample=False,
                pad_token_id=tokenizer.eos_token_id,
            )
        result["generation_seconds"] = time.perf_counter() - generation_started
        new_tokens = output[0][tokens["input_ids"].shape[1]:]
        result["generated_token_count"] = int(new_tokens.shape[0])
        result["output_nonempty"] = bool(tokenizer.decode(new_tokens, skip_special_tokens=True).strip())
        result["peak_rss_mib"] = round(rss_mib(), 1)
        result["mps_memory_after_generation_mib"] = {
            "current_allocated": round(torch.mps.current_allocated_memory() / 1048576, 1),
            "driver_allocated": round(torch.mps.driver_allocated_memory() / 1048576, 1),
        }
        result.update(status="success", stage="complete", first_token_latency="unavailable; generate() is non-streaming")
        save(result)
        return 0
    except Exception as exc:
        result.update(status="error", error=f"{type(exc).__name__}: {exc}", peak_rss_mib=round(rss_mib(), 1))
        save(result)
        return 1


def main() -> int:
    if "--_worker" in sys.argv:
        return worker()
    timeout = 150
    env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    command = [sys.executable, str(Path(__file__).resolve()), "--_worker"]
    with LOG.open("w", encoding="utf-8") as log:
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            child.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.communicate()
            try:
                result = json.loads(OUT.read_text())
            except (OSError, json.JSONDecodeError):
                result = {}
            result.update(status="timeout", stage="process_timeout", timeout_seconds=timeout,
                          termination_reason=f"parent deadline; terminated only smoke-owned PID/process group {child.pid}")
            save(result)
            return 124
    return child.returncode or 0


if __name__ == "__main__":
    raise SystemExit(main())
