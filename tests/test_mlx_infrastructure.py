"""
Mock-based tests for MLX Client and Worker infrastructure.
Tests concurrency, lifecycle, protocol, and memory guard without loading real models.
"""

import sys
import threading
import time
import json
from unittest.mock import patch, MagicMock, Mock, PropertyMock
from io import StringIO
import pytest

# Add project root
sys.path.insert(0, "/Users/admin/Downloads/contentfinal5 copy 2")

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
from content_engine.llm.mlx_config import MLXConfig
from content_engine.llm.mlx_client import (
    MLXClient,
    MLXClientError,
    MLXWorkerUnavailable,
    MLXGenerationTimeout,
    MLXModelError,
    get_mlx_client,
    reset_mlx_client,
)


class FakeProcess:
    """Fake subprocess.Popen for testing."""
    def __init__(self, stdout_lines=None, stderr_lines=None, returncode=None):
        self._stdout_lines = stdout_lines or []
        self._stderr_lines = stderr_lines or []
        self._stdout_idx = 0
        self._stderr_idx = 0
        self._returncode = returncode
        self._poll_count = 0
        self.stdin = StringIO()
        self.stdout = iter(self._stdout_lines)
        self.stderr = iter(self._stderr_lines)
        self._terminated = False
        self._killed = False

    def poll(self):
        self._poll_count += 1
        return self._returncode

    def wait(self, timeout=None):
        if self._returncode is None:
            self._returncode = 0
        return self._returncode

    def terminate(self):
        self._terminated = True
        self._returncode = -15

    def kill(self):
        self._killed = True
        self._returncode = -9


class TestMLXProtocol:
    """Test protocol serialization and parsing."""

    def test_generation_request_creation(self):
        req = GenerationRequest.create(
            system="system prompt",
            user="user prompt",
            max_tokens=100,
            temperature=0.5,
            timeout=30,
            model="test-model",
        )
        assert req.system == "system prompt"
        assert req.user == "user prompt"
        assert req.max_tokens == 100
        assert req.temperature == 0.5
        assert req.timeout == 30
        assert req.model == "test-model"
        assert len(req.id) == 8

    def test_generation_request_validation(self):
        with pytest.raises(ValueError):
            GenerationRequest.create("", "", 100, 0.5, 30)
        with pytest.raises(ValueError):
            GenerationRequest.create("sys", "user", -1, 0.5, 30)
        with pytest.raises(ValueError):
            GenerationRequest.create("sys", "user", 100, 3.0, 30)
        with pytest.raises(ValueError):
            GenerationRequest.create("sys", "user", 100, 0.5, -1)

    def test_generation_request_json_roundtrip(self):
        req = GenerationRequest.create("sys", "user", 100, 0.0, 30, "model")
        line = req.to_json_line()
        parsed = json.loads(line)
        assert parsed["system"] == "sys"
        assert parsed["user"] == "user"
        assert parsed["max_tokens"] == 100

    def test_health_check_request(self):
        req = HealthCheckRequest.create()
        assert req.type == "health"
        assert len(req.id) == 8
        line = req.to_json_line()
        parsed = json.loads(line)
        assert parsed["type"] == "health"

    def test_shutdown_request(self):
        req = ShutdownRequest.create()
        assert req.type == "shutdown"
        line = req.to_json_line()
        parsed = json.loads(line)
        assert parsed["type"] == "shutdown"

    def test_generation_response_parsing(self):
        resp = GenerationResponse(
            id="test-123",
            text="generated text",
            prompt_tokens=10,
            completion_tokens=20,
            duration_ms=100,
            model="test-model",
        )
        line = resp.to_json_line()
        parsed = parse_response(line)
        assert isinstance(parsed, GenerationResponse)
        assert parsed.text == "generated text"
        assert parsed.success is True

    def test_health_check_response_parsing(self):
        resp = HealthCheckResponse(
            id="test-123",
            status="ok",
            model_loaded=True,
            model="test-model",
            memory_pressure=0.5,
        )
        line = resp.to_json_line()
        parsed = parse_response(line)
        assert isinstance(parsed, HealthCheckResponse)
        assert parsed.model_loaded is True
        assert parsed.status == "ok"

    def test_error_response_parsing(self):
        resp = GenerationResponse(
            id="test-123",
            text="",
            error="Model unavailable",
            error_code=ErrorCode.MODEL_UNAVAILABLE,
        )
        assert resp.success is False
        line = resp.to_json_line()
        parsed = parse_response(line)
        assert parsed.error_code == ErrorCode.MODEL_UNAVAILABLE


class TestMLXConfig:
    """Test configuration loading and validation."""

    def test_config_from_env(self, monkeypatch):
        monkeypatch.setenv("MLX_MODEL_ID", "custom/model")
        monkeypatch.setenv("MLX_MAX_TOKENS", "512")
        monkeypatch.setenv("MLX_TEMPERATURE", "0.7")
        config = MLXConfig.from_env()
        assert config.model_id == "custom/model"
        assert config.max_tokens == 512
        assert config.temperature == 0.7

    def test_config_defaults(self, monkeypatch):
        # Clear env vars
        for key in ["MLX_MODEL_ID", "MLX_MAX_TOKENS", "MLX_TEMPERATURE", "MLX_MODEL_PATH"]:
            monkeypatch.delenv(key, raising=False)
        config = MLXConfig.from_env()
        assert config.model_id == "mlx-community/Qwen2.5-0.5B-Instruct-4bit"
        assert config.max_tokens == 256
        assert config.temperature == 0.0

    def test_config_validation_warnings(self, monkeypatch):
        monkeypatch.setenv("MLX_MAX_TOKENS", "2000")
        monkeypatch.setenv("MLX_TEMPERATURE", "3.0")
        config = MLXConfig.from_env()
        issues = config.validate()
        assert any("MLX_MAX_TOKENS=2000 is high" in i for i in issues)
        assert any("MLX_TEMPERATURE=3.0 should be 0.0-2.0" in i for i in issues)

    def test_memory_guard_config(self, monkeypatch):
        monkeypatch.setenv("MLX_MIN_AVAILABLE_GB", "1.5")
        monkeypatch.setenv("MLX_MAX_SWAP_PERCENT", "30.0")
        monkeypatch.setenv("MLX_MAX_MEMORY_PERCENT", "80.0")
        config = MLXConfig.from_env()
        assert config.min_available_gb == 1.5
        assert config.max_swap_percent == 30.0
        assert config.max_memory_percent == 80.0


class TestMLXClientConcurrency:
    """Test client concurrency and locking behavior."""

    def setup_method(self):
        reset_mlx_client()

    def teardown_method(self):
        reset_mlx_client()

    def test_single_client_instance(self):
        client1 = get_mlx_client()
        client2 = get_mlx_client()
        assert client1 is client2

    def test_client_lock_separation(self):
        """Verify separate locks for lifecycle, requests, and responses."""
        client = MLXClient()
        assert hasattr(client, "_lifecycle_lock")
        assert hasattr(client, "_request_lock")
        assert hasattr(client, "_response_lock")
        assert client._lifecycle_lock is not client._request_lock
        assert client._lifecycle_lock is not client._response_lock
        assert client._request_lock is not client._response_lock

    def test_generate_serializes_requests(self, monkeypatch):
        """Test that generation requests are serialized using the request lock."""
        client = MLXClient()
        
        # Track lock acquisition by creating a wrapper lock
        lock_acquisitions = []
        original_lock = client._request_lock
        
        class TrackingLock:
            def __init__(self, lock):
                self._lock = lock
            def __enter__(self):
                lock_acquisitions.append(time.time())
                return self._lock.__enter__()
            def __exit__(self, *args, **kwargs):
                return self._lock.__exit__(*args, **kwargs)
        
        tracking_lock = TrackingLock(original_lock)
        monkeypatch.setattr(client, "_request_lock", tracking_lock)
        
        def mock_spawn_worker(self):
            pass
        monkeypatch.setattr(client, "_spawn_worker", mock_spawn_worker)
        
        def mock_send_request(self, request):
            # Simulate delayed response
            time.sleep(0.005)
            resp = GenerationResponse(
                id=request.id,
                text="response",
                prompt_tokens=5,
                completion_tokens=10,
                duration_ms=50,
                model="test",
            )
            with client._response_lock:
                client._response_buffer[request.id] = resp
                if request.id in client._response_events:
                    client._response_events[request.id].set()
        
        monkeypatch.setattr(client, "_send_request", mock_send_request.__get__(client, MLXClient))
        monkeypatch.setattr(client, "_ensure_worker_started", lambda: None)

        # Launch two concurrent generations
        results = []
        def gen_call(idx):
            try:
                resp = client.generate(f"sys{idx}", f"user{idx}", max_tokens=10)
                results.append((idx, resp.text))
            except Exception as e:
                results.append((idx, str(e)))

        t1 = threading.Thread(target=gen_call, args=(1,))
        t2 = threading.Thread(target=gen_call, args=(2,))
        
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Should have acquired lock twice (once per request)
        assert len(lock_acquisitions) == 2
        assert len(results) == 2


class TestMLXClientLifecycle:
    """Test client lifecycle: startup, health check, shutdown."""

    def setup_method(self):
        reset_mlx_client()

    def teardown_method(self):
        reset_mlx_client()

    def test_ensure_started_idempotent(self, monkeypatch):
        client = MLXClient()
        spawn_count = 0
        
        def mock_spawn(self):
            nonlocal spawn_count
            spawn_count += 1
            client._proc = FakeProcess()
            client._started = True
        
        monkeypatch.setattr(client, "_spawn_worker", mock_spawn.__get__(client, MLXClient))
        
        client.ensure_started()
        client.ensure_started()
        client.ensure_started()
        
        assert spawn_count == 1

    def test_health_check_without_model_load(self, monkeypatch):
        """Health check should succeed without model being loaded."""
        client = MLXClient()
        client._proc = FakeProcess()
        client._started = True
        
        # Mock health check response
        def mock_send_request(self, request):
            if isinstance(request, HealthCheckRequest):
                resp = HealthCheckResponse(
                    id=request.id,
                    status="ok",
                    model_loaded=False,
                    model="",
                    memory_pressure=0.3,
                )
                with client._response_lock:
                    client._response_buffer[request.id] = resp
                    if request.id in client._response_events:
                        client._response_events[request.id].set()
        
        monkeypatch.setattr(client, "_send_request", mock_send_request.__get__(client, MLXClient))
        
        health = client.health_check(timeout=5.0)
        assert health.status == "ok"
        assert health.model_loaded is False

    def test_shutdown_idempotent(self, monkeypatch):
        client = MLXClient()
        client._proc = FakeProcess()
        client._started = True
        
        client.shutdown()
        client.shutdown()  # Should not raise
        client.shutdown()
        
        assert client._proc is None
        assert client._started is False

    def test_shutdown_during_generation(self, monkeypatch):
        """Shutdown during generation should be safe."""
        client = MLXClient()
        client._proc = FakeProcess()
        client._started = True
        
        def mock_send_request(self, request):
            if isinstance(request, ShutdownRequest):
                return
            # Delay response
            time.sleep(0.1)
            resp = GenerationResponse(
                id=request.id,
                text="response",
                prompt_tokens=5,
                completion_tokens=10,
                duration_ms=50,
                model="test",
            )
            with client._response_lock:
                client._response_buffer[request.id] = resp
                if request.id in client._response_events:
                    client._response_events[request.id].set()
        
        monkeypatch.setattr(client, "_send_request", mock_send_request.__get__(client, MLXClient))
        monkeypatch.setattr(client, "_ensure_worker_started", lambda: None)

        # Start generation in background
        gen_done = threading.Event()
        gen_result = {}
        
        def do_gen():
            try:
                resp = client.generate("sys", "user", max_tokens=10)
                gen_result["resp"] = resp
            except Exception as e:
                gen_result["error"] = str(e)
            finally:
                gen_done.set()
        
        t = threading.Thread(target=do_gen)
        t.start()
        
        time.sleep(0.02)  # Let generation start
        
        # Shutdown while generation in progress
        client.shutdown()
        
        t.join(timeout=1.0)
        assert gen_done.is_set()


class TestMLXClientTimeouts:
    """Test timeout handling."""

    def setup_method(self):
        reset_mlx_client()

    def teardown_method(self):
        reset_mlx_client()

    def test_generation_timeout(self, monkeypatch):
        """Test that generation timeout raises MLXGenerationTimeout."""
        client = MLXClient()
        client._proc = FakeProcess()
        client._started = True
        
        def mock_send_request(self, request):
            # Never respond - simulates stuck worker
            pass
        
        monkeypatch.setattr(client, "_send_request", mock_send_request.__get__(client, MLXClient))
        monkeypatch.setattr(client, "_ensure_worker_started", lambda: None)

        with pytest.raises(MLXGenerationTimeout):
            client.generate("sys", "user", max_tokens=10, timeout=1)

    def test_health_check_timeout(self, monkeypatch):
        """Test that health check timeout works."""
        client = MLXClient()
        client._proc = FakeProcess()
        client._started = True
        
        def mock_send_request(self, request):
            pass  # Never respond
        
        monkeypatch.setattr(client, "_send_request", mock_send_request.__get__(client, MLXClient))
        monkeypatch.setattr(client, "_ensure_worker_started", lambda: None)

        with pytest.raises(MLXGenerationTimeout):
            client.health_check(timeout=0.5)


class TestMLXClientErrorHandling:
    """Test error handling and error codes."""

    def setup_method(self):
        reset_mlx_client()

    def teardown_method(self):
        reset_mlx_client()

    def test_model_unavailable_error(self, monkeypatch):
        client = MLXClient()
        client._proc = FakeProcess()
        client._started = True
        
        def mock_send_request(self, request):
            resp = GenerationResponse(
                id=request.id,
                text="",
                error="Model not loaded",
                error_code=ErrorCode.MODEL_UNAVAILABLE,
            )
            with client._response_lock:
                client._response_buffer[request.id] = resp
                if request.id in client._response_events:
                    client._response_events[request.id].set()
        
        monkeypatch.setattr(client, "_send_request", mock_send_request.__get__(client, MLXClient))
        monkeypatch.setattr(client, "_ensure_worker_started", lambda: None)

        with pytest.raises(MLXWorkerUnavailable):
            client.generate("sys", "user", max_tokens=10)

    def test_memory_guard_rejected_error(self, monkeypatch):
        client = MLXClient()
        client._proc = FakeProcess()
        client._started = True
        
        def mock_send_request(self, request):
            resp = GenerationResponse(
                id=request.id,
                text="",
                error="Insufficient RAM",
                error_code=ErrorCode.MEMORY_GUARD_REJECTED,
            )
            with client._response_lock:
                client._response_buffer[request.id] = resp
                if request.id in client._response_events:
                    client._response_events[request.id].set()
        
        monkeypatch.setattr(client, "_send_request", mock_send_request.__get__(client, MLXClient))
        monkeypatch.setattr(client, "_ensure_worker_started", lambda: None)

        with pytest.raises(MLXModelError, match="Memory guard rejected"):
            client.generate("sys", "user", max_tokens=10)

    def test_generation_failed_error(self, monkeypatch):
        client = MLXClient()
        client._proc = FakeProcess()
        client._started = True
        
        def mock_send_request(self, request):
            resp = GenerationResponse(
                id=request.id,
                text="",
                error="CUDA out of memory",
                error_code=ErrorCode.GENERATION_FAILED,
            )
            with client._response_lock:
                client._response_buffer[request.id] = resp
                if request.id in client._response_events:
                    client._response_events[request.id].set()
        
        monkeypatch.setattr(client, "_send_request", mock_send_request.__get__(client, MLXClient))
        monkeypatch.setattr(client, "_ensure_worker_started", lambda: None)

        with pytest.raises(MLXModelError, match="GENERATION_FAILED"):
            client.generate("sys", "user", max_tokens=10)


class TestMLXClientResponseRace:
    """Test the response registration race condition fix."""

    def setup_method(self):
        reset_mlx_client()

    def teardown_method(self):
        reset_mlx_client()

    def test_fast_response_before_wait(self, monkeypatch):
        """Test that fast responses (arriving before wait) are handled."""
        client = MLXClient()
        client._proc = FakeProcess()
        client._started = True
        
        def mock_send_request(self, request):
            # Respond immediately (simulating very fast worker)
            resp = GenerationResponse(
                id=request.id,
                text="fast response",
                prompt_tokens=5,
                completion_tokens=10,
                duration_ms=1,
                model="test",
            )
            with client._response_lock:
                client._response_buffer[request.id] = resp
                if request.id in client._response_events:
                    client._response_events[request.id].set()
        
        monkeypatch.setattr(client, "_send_request", mock_send_request.__get__(client, MLXClient))
        monkeypatch.setattr(client, "_ensure_worker_started", lambda: None)

        # Should not timeout even though response arrived before wait
        resp = client.generate("sys", "user", max_tokens=10, timeout=5)
        assert resp.text == "fast response"

    def test_response_cleanup_on_timeout(self, monkeypatch):
        """Test that response buffer is cleaned up on timeout."""
        client = MLXClient()
        client._proc = FakeProcess()
        client._started = True
        
        def mock_send_request(self, request):
            pass  # Never respond
        
        monkeypatch.setattr(client, "_send_request", mock_send_request.__get__(client, MLXClient))
        monkeypatch.setattr(client, "_ensure_worker_started", lambda: None)

        with pytest.raises(MLXGenerationTimeout):
            client.generate("sys", "user", max_tokens=10, timeout=0.1)

        # Buffer should be clean
        with client._response_lock:
            assert len(client._response_buffer) == 0
            assert len(client._response_events) == 0

    def test_first_generation_when_no_worker_running(self, monkeypatch):
        """First generation with no worker: startup must complete before waiter registration."""
        client = MLXClient()
        assert client._proc is None
        assert not client._started

        spawn_called = []

        def mock_spawn_worker(self):
            spawn_called.append(True)
            client._proc = FakeProcess()
            client._started = True

        monkeypatch.setattr(client, "_spawn_worker", mock_spawn_worker.__get__(client, MLXClient))

        def mock_send_request(self, request):
            resp = GenerationResponse(
                id=request.id,
                text="first gen response",
                prompt_tokens=5,
                completion_tokens=10,
                duration_ms=50,
                model="test",
            )
            with client._response_lock:
                client._response_buffer[request.id] = resp
                if request.id in client._response_events:
                    client._response_events[request.id].set()

        monkeypatch.setattr(client, "_send_request", mock_send_request.__get__(client, MLXClient))

        resp = client.generate("sys", "user", max_tokens=10)

        assert spawn_called, "_spawn_worker should have been called"
        assert resp.success is True
        assert resp.text == "first gen response"

    def test_worker_restart_after_unexpected_exit(self, monkeypatch):
        """Worker died unexpectedly; generate should restart it and succeed."""
        client = MLXClient()
        dead_proc = FakeProcess(returncode=1)
        client._proc = dead_proc
        client._started = True

        restart_count = 0

        def mock_spawn_worker(self):
            nonlocal restart_count
            restart_count += 1
            client._proc = FakeProcess()
            client._started = True

        monkeypatch.setattr(client, "_spawn_worker", mock_spawn_worker.__get__(client, MLXClient))

        def mock_send_request(self, request):
            resp = GenerationResponse(
                id=request.id,
                text="after restart",
                prompt_tokens=5,
                completion_tokens=10,
                duration_ms=50,
                model="test",
            )
            with client._response_lock:
                client._response_buffer[request.id] = resp
                if request.id in client._response_events:
                    client._response_events[request.id].set()

        monkeypatch.setattr(client, "_send_request", mock_send_request.__get__(client, MLXClient))

        resp = client.generate("sys", "user", max_tokens=10)

        assert restart_count == 1, "Worker should have been restarted"
        assert resp.success is True
        assert resp.text == "after restart"

    def test_startup_failure_without_stale_waiter(self, monkeypatch):
        """Startup failure must not leave a stale waiter registered."""
        client = MLXClient()

        def mock_spawn_worker(self):
            raise MLXWorkerUnavailable("Worker Python not found")

        monkeypatch.setattr(client, "_spawn_worker", mock_spawn_worker.__get__(client, MLXClient))

        with pytest.raises(MLXWorkerUnavailable):
            client.generate("sys", "user", max_tokens=10)

        # No stale waiter should remain
        with client._response_lock:
            assert len(client._response_events) == 0, "Stale waiter left after startup failure"
            assert len(client._response_buffer) == 0

    def test_send_failure_without_stale_waiter(self, monkeypatch):
        """Send failure must not leave a stale waiter registered."""
        client = MLXClient()
        client._proc = FakeProcess()
        client._started = True

        def mock_send_request(self, request):
            raise MLXWorkerUnavailable("Worker pipe broken")

        monkeypatch.setattr(client, "_send_request", mock_send_request.__get__(client, MLXClient))
        monkeypatch.setattr(client, "_ensure_worker_started", lambda: None)

        with pytest.raises(MLXWorkerUnavailable):
            client.generate("sys", "user", max_tokens=10)

        # No stale waiter should remain
        with client._response_lock:
            assert len(client._response_events) == 0, "Stale waiter left after send failure"

    def test_health_check_on_initial_startup(self, monkeypatch):
        """Health check with no worker running should start worker then check."""
        client = MLXClient()
        assert client._proc is None

        started = []

        def mock_spawn_worker(self):
            started.append(True)
            client._proc = FakeProcess()
            client._started = True

        monkeypatch.setattr(client, "_spawn_worker", mock_spawn_worker.__get__(client, MLXClient))

        def mock_send_request(self, request):
            assert isinstance(request, HealthCheckRequest)
            resp = HealthCheckResponse(
                id=request.id,
                status="ok",
                model_loaded=False,
                model="",
                memory_pressure=0.3,
            )
            with client._response_lock:
                client._response_buffer[request.id] = resp
                if request.id in client._response_events:
                    client._response_events[request.id].set()

        monkeypatch.setattr(client, "_send_request", mock_send_request.__get__(client, MLXClient))

        health = client.health_check(timeout=5.0)

        assert started, "_spawn_worker should have been called by health_check"
        assert health.status == "ok"
        assert health.model_loaded is False

    def test_no_orphan_worker_processes(self, monkeypatch):
        """Shutdown after normal operation should leave no worker process or threads."""
        client = MLXClient()
        client._proc = FakeProcess()
        client._started = True

        def mock_send_request(self, request):
            if isinstance(request, ShutdownRequest):
                return
            resp = GenerationResponse(
                id=request.id,
                text="response",
                prompt_tokens=5,
                completion_tokens=10,
                duration_ms=50,
                model="test",
            )
            with client._response_lock:
                client._response_buffer[request.id] = resp
                if request.id in client._response_events:
                    client._response_events[request.id].set()

        monkeypatch.setattr(client, "_send_request", mock_send_request.__get__(client, MLXClient))
        monkeypatch.setattr(client, "_ensure_worker_started", lambda: None)

        resp = client.generate("sys", "user", max_tokens=10)
        assert resp.success is True

        client.shutdown()

        assert client._proc is None, "Worker process should be None after shutdown"
        assert client._started is False

    def test_startup_clears_buffers_but_waiter_remains_registered(self, monkeypatch):
        """
        REGRESSION TEST for the original bug.

        Simulates the original faulty ordering: _ensure_worker_started() triggers
        _spawn_worker() which clears response buffers. Verifies that the generation
        request's waiter remains registered and the generation succeeds.
        """
        client = MLXClient()
        assert client._proc is None

        # Track call order: startup must happen before waiter registration
        call_order = []

        def mock_spawn_worker(self):
            call_order.append("spawn")
            client._proc = FakeProcess()
            client._started = True
            # Simulate the buffer clear that _spawn_worker performs
            with client._response_lock:
                client._response_buffer.clear()
                client._response_events.clear()

        def mock_register_waiter(self, request_id):
            call_order.append("register")
            return MLXClient._register_response_waiter.__get__(client, MLXClient)(request_id)

        monkeypatch.setattr(client, "_spawn_worker", mock_spawn_worker.__get__(client, MLXClient))
        monkeypatch.setattr(client, "_register_response_waiter", mock_register_waiter.__get__(client, MLXClient))

        def mock_send_request(self, request):
            call_order.append("send")
            resp = GenerationResponse(
                id=request.id,
                text="regression ok",
                prompt_tokens=5,
                completion_tokens=10,
                duration_ms=50,
                model="test",
            )
            with client._response_lock:
                client._response_buffer[request.id] = resp
                if request.id in client._response_events:
                    client._response_events[request.id].set()

        monkeypatch.setattr(client, "_send_request", mock_send_request.__get__(client, MLXClient))

        resp = client.generate("sys", "user", max_tokens=10)

        # Verify correct ordering: spawn -> register -> send
        assert call_order == ["spawn", "register", "send"], f"Wrong call order: {call_order}"
        assert resp.success is True
        assert resp.text == "regression ok"

    """Test worker logic with mocked MLX-LM."""

    def test_worker_health_check_without_model(self, monkeypatch):
        """Worker health check should return ok without model loaded."""
        config = MLXConfig.from_env()
        worker = MLXWorker(config)
        
        req = HealthCheckRequest.create()
        resp = worker.health_check(req)
        
        assert resp.status == "ok"
        assert resp.model_loaded is False
        assert resp.model == ""

    def test_worker_generation_triggers_load(self, monkeypatch):
        """First generation should trigger model load."""
        config = MLXConfig.from_env()
        worker = MLXWorker(config)
        
        # Reset call count
        FakeMLXLM.load_call_count = 0
        
        # Mock memory safety
        def mock_check_memory(self):
            return True, "OK"
        monkeypatch.setattr(MLXWorker, "check_memory_safety", mock_check_memory)
        
        req = GenerationRequest.create("sys", "user", 100, 0.0, 30)
        resp = worker.generate(req)
        
        assert resp.success is True
        assert FakeMLXLM.load_call_count == 1
        
        # Second generation should not reload
        req2 = GenerationRequest.create("sys", "user2", 100, 0.0, 30)
        resp2 = worker.generate(req2)
        assert FakeMLXLM.load_call_count == 1

    def test_worker_serializes_generation(self, monkeypatch):
        """Worker should serialize generation requests."""
        config = MLXConfig.from_env()
        worker = MLXWorker(config)
        
        gen_times = []
        original_generate = FakeMLXLM.generate
        
        def mock_generate(model, tokenizer, prompt, max_tokens, sampler, verbose):
            gen_times.append(time.time())
            time.sleep(0.03)
            return original_generate(model, tokenizer, prompt, max_tokens, sampler, verbose)
        
        monkeypatch.setattr(FakeMLXLM, "generate", mock_generate)
        monkeypatch.setattr(MLXWorker, "check_memory_safety", lambda self: (True, "OK"))
        
        # Reset load count
        FakeMLXLM.load_call_count = 0
        
        # Launch two concurrent generations via process_line (which uses the lock)
        results = []
        def gen_call(idx):
            req = GenerationRequest.create("sys", f"user{idx}", 100, 0.0, 30)
            resp_line = worker.process_line(req.to_json_line())
            resp = json.loads(resp_line)
            results.append((idx, resp.get("text") != ""))
        
        t1 = threading.Thread(target=gen_call, args=(1,))
        t2 = threading.Thread(target=gen_call, args=(2,))
        
        start = time.time()
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        elapsed = time.time() - start
        
        # Should be serialized (at least 2 * 0.03 = 0.06s, allow some margin)
        assert elapsed >= 0.05
        assert len(results) == 2
        assert all(r[1] for r in results)
        # Model should only be loaded once
        assert FakeMLXLM.load_call_count == 1

    def test_worker_memory_guard_rejection(self, monkeypatch):
        """Worker should reject generation when memory guard fails."""
        config = MLXConfig.from_env()
        worker = MLXWorker(config)
        
        def mock_check_memory(self):
            return False, "Insufficient RAM"
        
        monkeypatch.setattr(MLXWorker, "check_memory_safety", mock_check_memory)
        
        req = GenerationRequest.create("sys", "user", 100, 0.0, 30)
        resp = worker.generate(req)
        
        assert resp.success is False
        assert resp.error_code == ErrorCode.MEMORY_GUARD_REJECTED
        assert "Insufficient RAM" in resp.error

    def test_worker_shutdown_handling(self, monkeypatch):
        """Worker should handle shutdown request."""
        config = MLXConfig.from_env()
        worker = MLXWorker(config)
        
        req = ShutdownRequest.create()
        resp_line = worker.process_line(req.to_json_line())
        
        assert resp_line is not None
        resp = json.loads(resp_line)
        assert resp["status"] == "ok"
        assert worker._shutdown is True
        
        # Subsequent generation should be rejected
        req2 = GenerationRequest.create("sys", "user", 100, 0.0, 30)
        resp_line2 = worker.process_line(req2.to_json_line())
        resp2 = json.loads(resp_line2)
        assert resp2["error_code"] == ErrorCode.WORKER_SHUTTING_DOWN

    def test_worker_generation_passes_sampler_not_temp_zero(self, monkeypatch):
        """Temperature 0: generate() must receive sampler callable, not temp kwarg."""
        config = MLXConfig.from_env()
        worker = MLXWorker(config)
        FakeMLXLM.load_call_count = 0
        FakeMLXLM.generate_call_count = 0
        FakeMLXLM.last_generate_kwargs = None

        monkeypatch.setattr(MLXWorker, "check_memory_safety", lambda self: (True, "OK"))

        req = GenerationRequest.create("sys", "user", 100, 0.0, 30)
        resp = worker.generate(req)

        assert resp.success is True
        kwargs = FakeMLXLM.last_generate_kwargs
        assert kwargs is not None
        assert "temp" not in kwargs
        assert "sampler" in kwargs
        assert callable(kwargs["sampler"])

    def test_worker_generation_passes_sampler_not_temp_nonzero(self, monkeypatch):
        """Nonzero temperature: generate() must receive sampler callable, not temp kwarg."""
        config = MLXConfig.from_env()
        worker = MLXWorker(config)
        FakeMLXLM.load_call_count = 0
        FakeMLXLM.generate_call_count = 0
        FakeMLXLM.last_generate_kwargs = None

        monkeypatch.setattr(MLXWorker, "check_memory_safety", lambda self: (True, "OK"))

        req = GenerationRequest.create("sys", "user", 100, 0.7, 30)
        resp = worker.generate(req)

        assert resp.success is True
        kwargs = FakeMLXLM.last_generate_kwargs
        assert kwargs is not None
        assert "temp" not in kwargs
        assert "sampler" in kwargs
        assert callable(kwargs["sampler"])


class TestMLXWorkerEnvLoading:
    """Test worker .env loading behavior."""

    def setup_method(self):
        reset_mlx_client()

    def teardown_method(self):
        reset_mlx_client()

    def test_dotenv_values_loaded_by_worker(self, monkeypatch, tmp_path):
        """Test that .env values are loaded into MLXConfig by the worker."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "MLX_MODEL_ID=mlx-community/Qwen2.5-0.5B-Instruct-4bit\n"
            "MLX_MAX_TOKENS=64\n"
            "MLX_MAX_CONTEXT=2048\n"
            "MLX_TIMEOUT_SECONDS=180\n"
        )
        monkeypatch.setattr("scripts.mlx_worker.PROJECT_ROOT", tmp_path)
        for key in ["MLX_MODEL_ID", "MLX_MAX_TOKENS", "MLX_MAX_CONTEXT", "MLX_TIMEOUT_SECONDS"]:
            monkeypatch.delenv(key, raising=False)

        _load_project_env()

        config = MLXConfig.from_env()
        assert config.model_id == "mlx-community/Qwen2.5-0.5B-Instruct-4bit"
        assert config.max_tokens == 64
        assert config.max_context == 2048
        assert config.timeout_seconds == 180

    def test_env_var_takes_precedence_over_dotenv(self, monkeypatch, tmp_path):
        """Test that existing env vars override .env values."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "MLX_MODEL_ID=dotenv/model\n"
            "MLX_MAX_TOKENS=256\n"
        )
        monkeypatch.setattr("scripts.mlx_worker.PROJECT_ROOT", tmp_path)
        monkeypatch.setenv("MLX_MODEL_ID", "env/model")
        monkeypatch.setenv("MLX_MAX_TOKENS", "512")

        _load_project_env()

        config = MLXConfig.from_env()
        assert config.model_id == "env/model"
        assert config.max_tokens == 512

    def test_missing_dotenv_does_not_crash(self, monkeypatch, tmp_path):
        """Test that missing .env does not crash worker startup."""
        empty_dir = tmp_path / "noenv"
        empty_dir.mkdir()
        monkeypatch.setattr("scripts.mlx_worker.PROJECT_ROOT", empty_dir)
        for key in ["MLX_MODEL_ID", "MLX_MAX_TOKENS", "MLX_MAX_CONTEXT", "MLX_TIMEOUT_SECONDS"]:
            monkeypatch.delenv(key, raising=False)

        _load_project_env()  # Should not raise

        config = MLXConfig.from_env()
        assert config.model_id == "mlx-community/Qwen2.5-0.5B-Instruct-4bit"
        assert config.max_tokens == 256

    def test_worker_stdout_protocol_pure(self, monkeypatch, tmp_path):
        """Test that worker stdout contains only protocol messages."""
        env_file = tmp_path / ".env"
        env_file.write_text("MLX_MODEL_ID=test/model\nMLX_MAX_TOKENS=64\n")
        monkeypatch.setattr("scripts.mlx_worker.PROJECT_ROOT", tmp_path)
        for key in ["MLX_MODEL_ID", "MLX_MAX_TOKENS"]:
            monkeypatch.delenv(key, raising=False)

        # Capture stdout while loading env
        captured_stdout = StringIO()
        original_stdout = sys.stdout
        sys.stdout = captured_stdout
        try:
            _load_project_env()
        finally:
            sys.stdout = original_stdout

        # _load_project_env must not write to stdout
        assert captured_stdout.getvalue() == ""

        # _log must write to stderr, not stdout
        captured_stdout = StringIO()
        captured_stderr = StringIO()
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        sys.stdout = captured_stdout
        sys.stderr = captured_stderr
        try:
            _log("[test] diagnostic message")
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr

        assert captured_stdout.getvalue() == ""
        assert "[test] diagnostic message" in captured_stderr.getvalue()

        # Config loads from .env without stdout pollution
        config = MLXConfig.from_env()
        assert config.model_id == "test/model"
        assert config.max_tokens == 64


class TestMLXClientIntegration:
    """Integration tests for client with mocked worker."""

    def setup_method(self):
        reset_mlx_client()

    def teardown_method(self):
        reset_mlx_client()

    def test_full_generation_flow_mocked(self, monkeypatch):
        """Test complete generation flow with mocked worker process."""
        client = MLXClient()
        
        # Track what the "worker" receives
        received_requests = []
        
        class MockProc:
            def __init__(self):
                self.stdin = StringIO()
                self.stdout = []
                self.stderr = []
                self._returncode = None
            
            def poll(self):
                return self._returncode
            
            def wait(self, timeout=None):
                return self._returncode
            
            def terminate(self):
                self._returncode = -15
            
            def kill(self):
                self._returncode = -9
        
        proc = MockProc()
        client._proc = proc
        client._started = True
        
        def mock_send_request(self, request):
            received_requests.append(request)
            # Simulate worker response
            if isinstance(request, GenerationRequest):
                resp = GenerationResponse(
                    id=request.id,
                    text=f"response to: {request.user[:20]}",
                    prompt_tokens=len(request.system) + len(request.user),
                    completion_tokens=10,
                    duration_ms=50,
                    model="test-model",
                )
            elif isinstance(request, HealthCheckRequest):
                resp = HealthCheckResponse(
                    id=request.id,
                    status="ok",
                    model_loaded=True,
                    model="test-model",
                    memory_pressure=0.3,
                )
            else:
                return
            
            with client._response_lock:
                client._response_buffer[request.id] = resp
                if request.id in client._response_events:
                    client._response_events[request.id].set()
        
        monkeypatch.setattr(client, "_send_request", mock_send_request.__get__(client, MLXClient))
        monkeypatch.setattr(client, "_ensure_worker_started", lambda: None)
        
        # Generate
        resp = client.generate("You are helpful", "Write a caption", max_tokens=50)
        
        assert resp.success is True
        assert "caption" in resp.text
        assert len(received_requests) == 1
        assert isinstance(received_requests[0], GenerationRequest)
        assert received_requests[0].system == "You are helpful"
        assert received_requests[0].user == "Write a caption"


# Mock mlx_lm module for worker tests
import types

class FakeMLXLM:
    load_call_count = 0
    generate_call_count = 0
    last_generate_kwargs = None

    @staticmethod
    def load(path):
        FakeMLXLM.load_call_count += 1
        class FakeModel:
            pass
        class FakeTokenizer:
            def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
                return "formatted prompt"
            def encode(self, text):
                return list(text)
        return FakeModel(), FakeTokenizer()

    @staticmethod
    def generate(model, tokenizer, prompt, max_tokens, sampler=None, verbose=False):
        FakeMLXLM.generate_call_count += 1
        FakeMLXLM.last_generate_kwargs = {
            "model": model,
            "tokenizer": tokenizer,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "sampler": sampler,
            "verbose": verbose,
        }
        return "generated text"


def _make_sampler(temp=0.0):
    def sampler(tokens, logits):
        return logits.argmax()
    return sampler


mlx_lm_module = types.ModuleType("mlx_lm")


class _MLXLMModule(types.ModuleType):
    def __getattr__(self, name):
        return getattr(FakeMLXLM, name)


mlx_lm_module.__class__ = _MLXLMModule

sample_utils_module = types.ModuleType("mlx_lm.sample_utils")
sample_utils_module.make_sampler = staticmethod(_make_sampler)

# Insert mock module before importing worker
import sys
sys.modules['mlx_lm'] = mlx_lm_module
sys.modules['mlx_lm.sample_utils'] = sample_utils_module

from scripts.mlx_worker import MLXWorker, _load_project_env, _log


if __name__ == "__main__":
    pytest.main([__file__, "-v"])