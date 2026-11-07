#!/usr/bin/env python3
"""
MLX Inference Worker
Runs in .venv-mlx environment, communicates via JSON-lines over stdin/stdout.
All diagnostic output goes to stderr. Stdout is reserved for protocol messages only.
"""

import sys
import os
import json
import time
import signal
import psutil
import threading
from pathlib import Path

# Add project root to path for config import
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from content_engine.llm.mlx_config import MLXConfig
from content_engine.llm.mlx_protocol import (
    GenerationRequest,
    GenerationResponse,
    HealthCheckRequest,
    HealthCheckResponse,
    ShutdownRequest,
    parse_request,
    ErrorCode,
)


def _log(msg: str) -> None:
    """Log diagnostic message to stderr only."""
    print(msg, file=sys.stderr, flush=True)


class MLXWorker:
    """MLX inference worker - single model, serialized requests."""

    def __init__(self, config: MLXConfig):
        self.config = config
        self.model = None
        self.tokenizer = None
        self.model_loaded = False
        self.model_load_time = 0.0
        self._shutdown = False
        self._generation_lock = threading.Lock()  # Serialize generation

    def check_memory_safety(self) -> tuple[bool, str]:
        """Check if memory conditions are safe for model loading."""
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()

        available_gb = mem.available / (1024**3)
        total_gb = mem.total / (1024**3)
        swap_percent = swap.percent

        _log(f"[mlx_memory_check] RAM: {available_gb:.1f}GB free / {total_gb:.1f}GB total, Swap: {swap_percent:.1f}%")

        if available_gb < self.config.min_available_gb:
            return False, f"Insufficient RAM: {available_gb:.1f}GB free (need >={self.config.min_available_gb}GB)"
        if swap_percent > self.config.max_swap_percent:
            return False, f"High swap pressure: {swap_percent:.1f}% used (max {self.config.max_swap_percent}%)"
        if mem.percent > self.config.max_memory_percent:
            return False, f"System memory pressure too high: {mem.percent:.1f}% (max {self.config.max_memory_percent}%)"

        return True, "OK"

    def load_model(self) -> None:
        """Load the MLX model and tokenizer."""
        if self.model_loaded:
            return

        # Memory safety check before loading
        safe, msg = self.check_memory_safety()
        if not safe:
            _log(f"[mlx_memory_guard_rejected] {msg}")
            raise RuntimeError(f"Memory guard rejected model load: {msg}")

        _log(f"[mlx_model_load] Loading model: {self.config.resolve_model_path()}")
        start = time.perf_counter()

        try:
            from mlx_lm import load

            model_path = self.config.resolve_model_path()
            self.model, self.tokenizer = load(model_path)
            self.model_loaded = True
            self.model_load_time = time.perf_counter() - start

            _log(f"[mlx_model_loaded] Model loaded in {self.model_load_time:.2f}s")

        except Exception as e:
            _log(f"[mlx_model_load_failed] {e}")
            raise RuntimeError(f"Failed to load MLX model: {e}")

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        """Generate text for a single request."""
        start = time.perf_counter()

        try:
            if not self.model_loaded:
                self.load_model()

            from mlx_lm import generate
            from mlx_lm.sample_utils import make_sampler

            # Build messages for chat template
            messages = []
            if request.system:
                messages.append({"role": "system", "content": request.system})
            messages.append({"role": "user", "content": request.user})

            # Apply chat template
            prompt = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
            )

            # Validate prompt length
            prompt_tokens = len(self.tokenizer.encode(prompt))
            if prompt_tokens > self.config.max_context:
                return GenerationResponse(
                    id=request.id,
                    text="",
                    duration_ms=int((time.perf_counter() - start) * 1000),
                    model=self.config.model_id,
                    error=f"Prompt too long: {prompt_tokens} tokens (max {self.config.max_context})",
                    error_code=ErrorCode.VALIDATION_ERROR,
                )

            # Generate
            sampler = make_sampler(temp=request.temperature)
            response_text = generate(
                self.model,
                self.tokenizer,
                prompt=prompt,
                max_tokens=min(request.max_tokens, self.config.max_tokens),
                sampler=sampler,
                verbose=False,
            )

            duration_ms = int((time.perf_counter() - start) * 1000)

            # Estimate token counts (MLX doesn't return them directly)
            completion_tokens = len(self.tokenizer.encode(response_text))

            return GenerationResponse(
                id=request.id,
                text=response_text.strip(),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                duration_ms=duration_ms,
                model=self.config.model_id,
            )

        except Exception as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            _log(f"[mlx_generation_failed] {e}")
            
            # Check if this is a memory guard rejection
            error_msg = str(e)
            if "Memory guard rejected" in error_msg:
                error_code = ErrorCode.MEMORY_GUARD_REJECTED
            else:
                error_code = ErrorCode.GENERATION_FAILED
            
            return GenerationResponse(
                id=request.id,
                text="",
                duration_ms=duration_ms,
                model=self.config.model_id,
                error=error_msg,
                error_code=error_code,
            )

    def health_check(self, request: HealthCheckRequest) -> HealthCheckResponse:
        """Return worker health status. Does not load model."""
        mem = psutil.virtual_memory()
        return HealthCheckResponse(
            id=request.id,
            status="ok",  # Process is healthy regardless of model load state
            model_loaded=self.model_loaded,
            model=self.config.model_id if self.model_loaded else "",
            memory_pressure=mem.percent / 100.0,
            error=None,
        )

    def process_line(self, line: str) -> str | None:
        """Process a single JSON line from stdin, return response JSON line."""
        line = line.strip()
        if not line:
            return None

        try:
            request = parse_request(line)
        except Exception as e:
            _log(f"[mlx_invalid_request] {e} | line: {line}")
            return GenerationResponse(
                id="unknown",
                text="",
                error=f"Invalid request format: {e}",
                error_code=ErrorCode.INVALID_REQUEST,
            ).to_json_line()

        # Route request by type
        if isinstance(request, GenerationRequest):
            with self._generation_lock:  # Serialize generation
                if self._shutdown:
                    return GenerationResponse(
                        id=request.id,
                        text="",
                        error="Worker is shutting down",
                        error_code=ErrorCode.WORKER_SHUTTING_DOWN,
                    ).to_json_line()
                response = self.generate(request)
            return response.to_json_line()

        elif isinstance(request, HealthCheckRequest):
            response = self.health_check(request)
            return response.to_json_line()

        elif isinstance(request, ShutdownRequest):
            _log("[mlx_shutdown_request] Received shutdown request")
            self._shutdown = True
            return HealthCheckResponse(
                id=request.id,
                status="ok",
                model_loaded=self.model_loaded,
                model=self.config.model_id,
            ).to_json_line()

        else:
            return GenerationResponse(
                id=getattr(request, 'id', 'unknown'),
                text="",
                error=f"Unknown request type: {type(request)}",
                error_code=ErrorCode.UNKNOWN_REQUEST,
            ).to_json_line()


def _load_project_env() -> None:
    """Load project root .env file. Existing env vars take precedence."""
    try:
        from dotenv import load_dotenv
        load_dotenv(PROJECT_ROOT / ".env", override=False)
    except ImportError:
        pass


def main():
    """Main worker loop."""
    _load_project_env()
    config = MLXConfig.from_env()
    issues = config.validate()
    for issue in issues:
        _log(f"[mlx_config_warning] {issue}")

    worker = MLXWorker(config)

    _log("[mlx_worker_started] Worker ready, waiting for requests...")

    # Signal handling
    def handle_signal(signum, frame):
        _log(f"[mlx_worker_shutdown] Signal {signum} received, shutting down...")
        worker._shutdown = True

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    try:
        for line in sys.stdin:
            if worker._shutdown:
                _log("[mlx_worker_shutdown] Shutdown flag set, exiting loop")
                break

            response_line = worker.process_line(line)
            if response_line:
                # Only protocol messages to stdout
                print(response_line, flush=True)

    except KeyboardInterrupt:
        _log("[mlx_worker_shutdown] Keyboard interrupt")
    except Exception as e:
        _log(f"[mlx_worker_error] {e}")
    finally:
        _log("[mlx_worker_stopped] Worker stopped")


if __name__ == "__main__":
    main()