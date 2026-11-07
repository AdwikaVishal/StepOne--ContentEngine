"""
MLX Client
Communicates with MLX worker via JSON-lines over subprocess pipes.
"""

import subprocess
import threading
import time
import atexit
import os
from typing import Optional

from content_engine.llm.mlx_config import get_config, MLXConfig
from content_engine.llm.mlx_protocol import (
    GenerationRequest,
    GenerationResponse,
    HealthCheckRequest,
    HealthCheckResponse,
    ShutdownRequest,
    parse_request,
    parse_response,
    ErrorCode,
)


class MLXClientError(Exception):
    """Base exception for MLX client errors."""
    pass


class MLXWorkerUnavailable(MLXClientError):
    """Worker process is not available."""
    pass


class MLXGenerationTimeout(MLXClientError):
    """Generation request timed out."""
    pass


class MLXModelError(MLXClientError):
    """Model-related error from worker."""
    pass


class MLXClient:
    """
    Client for MLX inference worker.
    
    Locking strategy:
    - _lifecycle_lock: protects worker process state (_proc, _started, _shutting_down)
    - _request_lock: serializes generation requests (one at a time)
    - _response_lock: protects response buffer and events
    
    This prevents:
    - Nested lock acquisition (deadlock)
    - Race between startup/shutdown and requests
    - Concurrent model generation
    """

    def __init__(self, config: Optional[MLXConfig] = None):
        self._config = config or get_config()
        self._proc: Optional[subprocess.Popen] = None
        self._lifecycle_lock = threading.Lock()
        self._request_lock = threading.Lock()  # Serializes generation requests
        self._response_lock = threading.Lock()
        self._reader_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._response_buffer: dict[str, GenerationResponse | HealthCheckResponse] = {}
        self._response_events: dict[str, threading.Event] = {}
        self._stderr_log: list[str] = []
        self._started = False
        self._shutting_down = False
        atexit.register(self.shutdown)

    def _spawn_worker(self) -> None:
        """Spawn the MLX worker subprocess. Must hold _lifecycle_lock."""
        if self._proc and self._proc.poll() is None:
            return

        worker_python = self._config.worker_python
        worker_script = self._config.worker_script

        if not os.path.exists(worker_python):
            raise MLXWorkerUnavailable(f"Worker Python not found: {worker_python}")
        if not os.path.exists(worker_script):
            raise MLXWorkerUnavailable(f"Worker script not found: {worker_script}")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        self._proc = subprocess.Popen(
            [worker_python, worker_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1,
        )

        with self._response_lock:
            # Preserve active response waiters so in-flight requests are not
            # orphaned when the worker is (re)spawned. Only drop orphaned
            # buffer entries that have no waiter.
            active_waiter_ids = set(self._response_events.keys())
            self._response_buffer = {
                k: v for k, v in self._response_buffer.items() if k in active_waiter_ids
            }
        self._stderr_log.clear()

        self._reader_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader_thread.start()

        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stderr_thread.start()

        self._started = True

    def _read_stdout(self) -> None:
        """Read JSON-lines from worker stdout."""
        proc = self._proc
        if not proc or not proc.stdout:
            return
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                response = parse_response(line)
                resp_id = response.id
                with self._response_lock:
                    self._response_buffer[resp_id] = response
                    if resp_id in self._response_events:
                        self._response_events[resp_id].set()
            except Exception as e:
                # Log to stderr log, not stdout
                with self._response_lock:
                    self._stderr_log.append(f"[MLXClient] Failed to parse response: {e} | line: {line}")
                    if len(self._stderr_log) > 100:
                        self._stderr_log.pop(0)

    def _read_stderr(self) -> None:
        """Capture worker stderr for debugging."""
        proc = self._proc
        if not proc or not proc.stderr:
            return
        for line in proc.stderr:
            line = line.strip()
            if line:
                with self._response_lock:
                    self._stderr_log.append(line)
                    if len(self._stderr_log) > 100:
                        self._stderr_log.pop(0)

    def _send_request(self, request: GenerationRequest | HealthCheckRequest | ShutdownRequest) -> None:
        """Send a request to the worker. Must hold _lifecycle_lock or be called from generate()."""
        proc = self._proc
        if not proc or not proc.stdin:
            raise MLXWorkerUnavailable("Worker process not available")
        proc.stdin.write(request.to_json_line() + "\n")
        proc.stdin.flush()

    def _register_response_waiter(self, request_id: str) -> threading.Event:
        """Register a response waiter. Returns the event to wait on."""
        event = threading.Event()
        with self._response_lock:
            self._response_events[request_id] = event
        return event

    def _wait_for_response(self, request_id: str, timeout: float) -> GenerationResponse | HealthCheckResponse:
        """Wait for a response with timeout."""
        event = None
        with self._response_lock:
            event = self._response_events.get(request_id)
        
        if event is None:
            # Race condition - response may have already arrived
            with self._response_lock:
                response = self._response_buffer.pop(request_id, None)
                if response is not None:
                    return response
            raise MLXClientError(f"Response waiter for {request_id} not registered")

        if not event.wait(timeout):
            with self._response_lock:
                self._response_events.pop(request_id, None)
            raise MLXGenerationTimeout(f"Request {request_id} timed out after {timeout}s")

        with self._response_lock:
            self._response_events.pop(request_id, None)
            response = self._response_buffer.pop(request_id, None)
            if response is None:
                raise MLXClientError(f"Response {request_id} not found in buffer")
            return response

    def _ensure_worker_started(self) -> None:
        """Ensure worker process is running. Does not wait for model load."""
        with self._lifecycle_lock:
            if self._shutting_down:
                raise MLXWorkerUnavailable("Client is shutting down")
            if not self._started or (self._proc and self._proc.poll() is not None):
                self._spawn_worker()

    def ensure_started(self) -> None:
        """Public method to ensure worker is started."""
        self._ensure_worker_started()

    def generate(
        self,
        system: str,
        user: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        timeout: Optional[int] = None,
    ) -> GenerationResponse:
        """
        Generate text using the MLX worker.
        
        Serializes generation requests. Worker lifecycle is managed separately.
        """
        config = self._config
        max_tokens = max_tokens or config.max_tokens
        temperature = temperature if temperature is not None else config.temperature
        timeout = timeout or config.timeout_seconds

        if max_tokens > config.max_tokens:
            max_tokens = config.max_tokens
        if max_tokens <= 0:
            raise MLXClientError("max_tokens must be positive")

        request = GenerationRequest.create(
            system=system,
            user=user,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            model=config.resolve_model_path(),
        )

        # Ensure worker is started before registering the waiter.
        # _ensure_worker_started() may spawn a worker and reset response
        # buffers, but no waiter is registered yet so nothing is lost.
        self._ensure_worker_started()

        # Serialize generation requests
        with self._request_lock:
            # Re-check worker is still alive after acquiring request lock
            with self._lifecycle_lock:
                if self._shutting_down or not self._proc or self._proc.poll() is not None:
                    raise MLXWorkerUnavailable("Worker process died or shutting down")

                # Register waiter BEFORE sending request (fixes race condition).
                # Worker startup is already complete, so it cannot clear this waiter.
                event = self._register_response_waiter(request.id)

                try:
                    self._send_request(request)
                except Exception:
                    # Send failed: remove the waiter so it does not go stale.
                    with self._response_lock:
                        self._response_events.pop(request.id, None)
                    raise

            # Wait for response
            try:
                response = self._wait_for_response(request.id, float(timeout) + 5.0)
            except MLXGenerationTimeout:
                # On timeout, worker might still be processing - mark as uncertain
                with self._lifecycle_lock:
                    if self._proc and self._proc.poll() is None:
                        # Worker still alive but timed out - uncertain state
                        pass
                raise

        if not response.success:
            error_code = response.error_code or ErrorCode.GENERATION_FAILED
            if error_code == ErrorCode.MODEL_UNAVAILABLE:
                raise MLXWorkerUnavailable(response.error or "Model unavailable")
            if error_code == ErrorCode.MEMORY_GUARD_REJECTED:
                raise MLXModelError(f"Memory guard rejected: {response.error}")
            raise MLXModelError(f"{error_code}: {response.error}")

        return response

    def health_check(self, timeout: float = 10.0) -> HealthCheckResponse:
        """Check worker health and model status. Does not trigger model load."""
        # Ensure worker is started first (this may spawn the worker and clear response buffers)
        self._ensure_worker_started()

        request = HealthCheckRequest.create()
        event = self._register_response_waiter(request.id)

        with self._lifecycle_lock:
            if self._proc and self._proc.poll() is None:
                try:
                    self._send_request(request)
                except Exception:
                    with self._response_lock:
                        self._response_events.pop(request.id, None)
                    raise
            else:
                with self._response_lock:
                    self._response_events.pop(request.id, None)
                raise MLXWorkerUnavailable("Worker process not running")

        return self._wait_for_response(request.id, timeout)

    def shutdown(self) -> None:
        """Gracefully shut down the worker. Idempotent."""
        with self._lifecycle_lock:
            if self._shutting_down:
                return
            self._shutting_down = True
            
            proc = self._proc
            if proc and proc.poll() is None:
                try:
                    request = ShutdownRequest.create()
                    self._send_request(request)
                    # Give worker a moment to process shutdown
                    time.sleep(0.1)
                except Exception:
                    pass
                
                # Wait for graceful shutdown
                try:
                    proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    try:
                        proc.terminate()
                        proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
            
            self._proc = None
            self._started = False
            self._shutting_down = False

    def get_stderr_logs(self) -> list[str]:
        """Get captured stderr logs from worker."""
        with self._response_lock:
            return self._stderr_log.copy()


# Global client instance
_client: Optional[MLXClient] = None
_client_lock = threading.Lock()


def get_mlx_client() -> MLXClient:
    """Get the global MLX client instance."""
    global _client
    with _client_lock:
        if _client is None:
            _client = MLXClient()
        return _client


def reset_mlx_client() -> None:
    """Reset the global client (for testing)."""
    global _client
    with _client_lock:
        if _client:
            _client.shutdown()
        _client = None