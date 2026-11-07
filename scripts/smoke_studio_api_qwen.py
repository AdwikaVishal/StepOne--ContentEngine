"""Run one bounded, real Qwen generation through the local Studio API route."""
from __future__ import annotations

import argparse
import asyncio
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
sys.path.insert(0, str(ROOT))
REPORT = ROOT / "benchmark_results" / "studio_api_qwen.json"
LOG = ROOT / "benchmark_results" / "studio_api_qwen.log"


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
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / (1024 * 1024) if sys.platform == "darwin" else value / 1024


def _worker() -> int:
    report = {
        "status": "running",
        "stage": "api_setup",
        "python": platform.python_version(),
        "machine": platform.machine(),
        "network_access": "disabled; Qwen loader uses local_files_only=True",
        "platform": "instagram",
        "timeout_seconds": "managed by parent process",
    }
    _save(report)
    try:
        from fastapi import FastAPI
        import httpx
        from api import studio_routes as routes
        from content_engine.copy_generator import CopyGenerator, _LocalLLMGenerator
        from content_engine.studio import StudioStorage
        import torch

        temporary_dir = tempfile.TemporaryDirectory(prefix="studio-qwen-api-")
        storage = StudioStorage(base_dir=Path(temporary_dir.name))
        routes.storage = storage
        event_name = "Cedar Circle Community Meetup"
        brief = (
            "A fictional neighborhood meetup focused on conversation and creative projects. "
            "Welcome attendees and invite them to share one idea."
        )
        project = storage.create_project(name=event_name, brief=brief, platforms=["instagram"])
        app = FastAPI()
        app.include_router(routes.router)

        generation_times = []
        generation_stages = []
        original_get_qwen = CopyGenerator._get_qwen

        def measured_get_qwen(self):
            llm = original_get_qwen(self)
            report.update(model_load_seconds=llm.load_seconds, device=llm.device, dtype=llm.dtype,
                          peak_rss_after_load_mib=round(_peak_rss_mib(), 1))
            if llm.device == "mps":
                report["mps_memory_after_load_mib"] = {
                    "current_allocated": round(torch.mps.current_allocated_memory() / 1048576, 1),
                    "driver_allocated": round(torch.mps.driver_allocated_memory() / 1048576, 1),
                }
            _save(report)
            return llm

        CopyGenerator._get_qwen = measured_get_qwen
        def measured_generate(self, prompt, max_new_tokens=300, system_prompt=None):
            call_index = len(generation_stages) + 1
            stage = {"call": call_index, "max_new_tokens": max_new_tokens}
            generation_stages.append(stage)
            def record(name, **values):
                stage.update(current_stage=name, **values)
                report["generation_stages"] = generation_stages
                report["stage"] = name
                _save(report)
            try:
                import torch
                stage_started = time.perf_counter()
                formatted = self.tokenizer.apply_chat_template(
                    [{"role": "system", "content": system_prompt or "You write concise, accurate social media copy. Follow the user request exactly. Use only supplied facts. Never emit instructions, analysis, or placeholders."},
                     {"role": "user", "content": prompt}],
                    tokenize=False, add_generation_prompt=True,
                )
                stage["chat_template_seconds"] = time.perf_counter() - stage_started
                stage_started = time.perf_counter()
                inputs = self.tokenizer(formatted, return_tensors="pt").to(self.device)
                stage["tokenization_seconds"] = time.perf_counter() - stage_started
                stage["input_token_count"] = int(inputs["input_ids"].shape[1])
                model_started = time.perf_counter()
                record("model_generate_started", model_started_monotonic=model_started)
                with torch.no_grad():
                    output = self.model.generate(
                        **inputs, max_new_tokens=max_new_tokens, do_sample=False,
                        pad_token_id=self.tokenizer.eos_token_id,
                    )
                stage["model_generate_seconds"] = time.perf_counter() - model_started
                new_tokens = output[0][inputs["input_ids"].shape[1]:]
                self.last_generated_token_count = int(new_tokens.shape[0])
                decode_started = time.perf_counter()
                result = self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
                stage["decode_seconds"] = time.perf_counter() - decode_started
                stage["generated_token_count"] = self.last_generated_token_count
                generation_times.append(time.perf_counter() - stage_started)
                record("generation_complete", total_seconds=time.perf_counter() - stage_started)
                return result
            except BaseException as exc:
                stage.update(error_type=type(exc).__name__)
                report["generation_stages"] = generation_stages
                _save(report)
                raise
            finally:
                report["generation_stages"] = generation_stages
                _save(report)

        _LocalLLMGenerator.generate = measured_generate
        report.update(
            stage="api_generate",
            model_id=_LocalLLMGenerator._MODEL_ID,
            generation_settings="Production Instagram settings; deterministic request brief; cached model only",
            transport="httpx ASGITransport in the main process thread (avoids TestClient portal thread)",
            frontend_request_timeout_ms=300_000,
            route_level_timeout="none configured in the Studio route",
            project_id=project["id"],
            event_name=event_name,
        )
        _save(report)
        request_started = time.perf_counter()
        report["request_started_monotonic"] = request_started
        async def request_route():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://studio-smoke") as client:
                return await client.post(
                    f"/api/studio/projects/{project['id']}/generate",
                    json={"event_name": event_name, "brief": brief, "platforms": ["instagram"]},
                )
        response = asyncio.run(request_route())
        report["api_request_seconds"] = time.perf_counter() - request_started
        report["http_status"] = response.status_code
        response_data = response.json()
        report["generation_seconds_in_provider"] = generation_times
        report["response_detail"] = response_data.get("detail")
        content = response_data.get("content") or {}
        report["output"] = content.get("platform_variants", {}).get("instagram", {}).get("caption")
        report["provider"] = content.get("provider")
        report["job_id"] = response_data.get("job_id")
        if not report["job_id"]:
            candidates = []
            for path in storage.jobs_dir.glob("*.json"):
                try:
                    candidate = json.loads(path.read_text())
                    if candidate.get("project_id") == project["id"]:
                        candidates.append(candidate)
                except (OSError, json.JSONDecodeError):
                    continue
            if candidates:
                candidates.sort(key=lambda item: item.get("created_at", ""), reverse=True)
                report["job_id"] = candidates[0].get("job_id")
        if report["job_id"]:
            job = storage.get_job(report["job_id"])
            report["job_status"] = job.get("status") if job else None
            report["failed_job_error"] = job.get("error") if job and job.get("status") == "failed" else None
            saved_project = storage.get_project(project["id"])
            report["saved_output"] = ((saved_project or {}).get("platform_variants") or {}).get("instagram", {}).get("caption")
            report["saved_matches_api_output"] = report["saved_output"] == report.get("output") and bool(report.get("output"))
            report["saved_output_absent_on_rejection"] = not bool(report["saved_output"])
        llm = getattr(routes.content_orch.copy_gen, "_llm", None)
        if llm:
            report["device"] = llm.device
            report["dtype"] = llm.dtype
            report["model_load_seconds"] = llm.load_seconds
        report["torch"] = torch.__version__
        report["mps_available"] = torch.backends.mps.is_available()
        report["peak_rss_mib"] = round(_peak_rss_mib(), 1)
        if report.get("device") == "mps":
            report["mps_memory_after_request"] = {
                "current_allocated_mib": round(torch.mps.current_allocated_memory() / 1048576, 1),
                "driver_allocated_mib": round(torch.mps.driver_allocated_memory() / 1048576, 1),
            }
        accepted = response.status_code == 200 and bool(report["output"]) and report.get("job_status") == "completed" and report.get("saved_matches_api_output") is True
        rejected_cleanly = (
            response.status_code == 503 and report.get("job_status") == "failed"
            and not report.get("output") and report.get("saved_output_absent_on_rejection") is True
        )
        report["api_outcome"] = "accepted_and_persisted" if accepted else "rejected_and_persisted" if rejected_cleanly else "inconsistent"
        report["status"] = "accepted_and_persisted" if accepted else "safe_rejection_persisted" if rejected_cleanly else "api_failure"
        report["stage"] = "complete" if report["status"] in ("accepted_and_persisted", "safe_rejection_persisted") else "api_response"
        _save(report)
        temporary_dir.cleanup()
        return 0 if report["status"] == "success" else 1
    except Exception as exc:
        report.update(
            status="api_failure", stage=report.get("stage", "api_setup"),
            error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc(),
            peak_rss_mib=round(_peak_rss_mib(), 1),
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
                report = {}
            report.update(
                status="timeout", stage="process_timeout",
                timeout_seconds=args.timeout_seconds,
                error="Studio API smoke process exceeded its wall-time limit; the child process group was terminated.",
                termination_reason=f"parent wall-time deadline; smoke-owned child PID {child.pid} and process group were terminated",
                log_path=str(LOG.relative_to(ROOT)),
            )
            _save(report)
            return 124
    try:
        report = json.loads(REPORT.read_text())
        report["timeout_seconds"] = args.timeout_seconds
        report["parent_wall_time_limit_seconds"] = args.timeout_seconds
        report["termination_reason"] = "completed before the parent wall-time deadline"
        _save(report)
    except (OSError, json.JSONDecodeError):
        pass
    return child.returncode or 0


if __name__ == "__main__":
    raise SystemExit(main())
