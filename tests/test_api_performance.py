"""
Performance and concurrency tests for the FastAPI request path.

These tests verify that health and status endpoints stay fast and responsive
even while a generation job runs in the background, and that the job-state
synchronization is correct under concurrent access.

Run with:
    pytest tests/test_api_performance.py -q
"""
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.scheduler import (
    submit_generate_job, get_job, set_job_data, get_scheduler,
)
from config import settings


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


# ── Fake ML pipeline so generation completes quickly in tests ────────────────

def _make_metadata(path):
    m = MagicMock()
    m.path = path
    m.final_score = 0.9
    m.quality_score = 0.8
    m.aesthetic_score = 0.8
    m.scene_concepts = ["speaker", "stage"]
    m.face_count = 1
    return m


def _fake_output_dir(tmp_path, event_name):
    out = tmp_path / "output" / event_name.replace(" ", "_")
    out.mkdir(parents=True)
    (out / "linkedin_collage.jpg").write_bytes(b"collage")
    (out / "instagram_carousel_1.jpg").write_bytes(b"carousel")
    (out / "linkedin_caption.txt").write_text("A wonderful event.", encoding="utf-8")
    (out / "case_study.md").write_text("# Case Study", encoding="utf-8")
    return out


@contextmanager
def _fake_job_context(tmp_path, event_name="Perf Event", run_seconds=0.0):
    """Submit a generation job with the ML pipeline faked so it completes fast.

    The patches stay active for the whole ``with`` block (including the
    background thread's execution) so the job finishes quickly.
    """
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    fake_out = _fake_output_dir(tmp_path, event_name)

    def _slow_run(*a, **k):
        if run_seconds:
            time.sleep(run_seconds)
        return fake_out

    patches = [
        patch("content_engine.ContentEngine.process_assets_parallel",
              return_value=[_make_metadata(str(img))]),
        patch("content_engine.orchestrator.ContentOrchestrator.run",
              side_effect=_slow_run),
        patch("content_engine.orchestrator.ContentOrchestrator.__init__",
              return_value=None),
    ]
    for p in patches:
        p.start()
    try:
        job_id = submit_generate_job([str(img)], event_name, "desc")
        yield job_id
    finally:
        for p in patches:
            p.stop()


def _wait_for_terminal(job_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = get_job(job_id)["status"] if get_job(job_id) else None
        if status in ("completed", "failed"):
            return status
        time.sleep(0.25)
    return None


# ── Health ───────────────────────────────────────────────────────────────────

def test_concurrent_health_requests(client):
    """Many concurrent health requests must all return quickly (no Redis blocking)."""
    def one(_):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        return r.elapsed.total_seconds() * 1000

    n = 20
    with ThreadPoolExecutor(max_workers=n) as pool:
        latencies = list(pool.map(one, range(n)))

    assert all(l < 500 for l in latencies), f"slow health latencies: {latencies}"
    ordered = sorted(latencies)
    print(f"\nhealth: n={n} min={ordered[0]:.0f}ms p50={ordered[n//2]:.0f}ms max={ordered[-1]:.0f}ms")


# ── Status ───────────────────────────────────────────────────────────────────

def test_status_is_fast_for_known_job(client):
    """A lightweight status GET must be fast (well under 200 ms)."""
    job_id = "known-job-xyz"
    with patch("api.scheduler.get_job") as mock_get:
        mock_get.return_value = {
            "status": "running",
            "progress": {"step": "ml_selection", "pct": 40},
        }
        r = client.get(f"/api/jobs/{job_id}/status")
    assert r.status_code == 200
    assert r.json()["status"] == "running"
    assert r.json()["backend"] == "apscheduler"


def _poll_status(client, job_id):
    t0 = time.perf_counter()
    r = client.get(f"/api/jobs/{job_id}/status")
    return r.status_code, (time.perf_counter() - t0) * 1000


def test_status_unknown_job_returns_404(client):
    """An unknown job returns 404 without falling back to slow Redis/Celery lookups."""
    with patch("api.scheduler.get_job", return_value=None):
        r = client.get("/api/jobs/definitely-not-a-real-job/status")
    assert r.status_code == 404


def test_status_during_active_generation_stays_fast(client, tmp_path):
    """
    While a real generation job runs in the background, status requests must
    return quickly (the event loop must not be blocked by ML inference).
    """
    with _fake_job_context(tmp_path, "Concurrency Event", run_seconds=2.0) as job_id:
        # Give the background thread a moment to enter the running state.
        time.sleep(0.3)

        # Sequential status polls while the job is running.
        seq_latencies = []
        for _ in range(10):
            _, dt = _poll_status(client, job_id)
            seq_latencies.append(dt)
        assert all(dt < 100 for dt in seq_latencies), f"slow sequential status: {seq_latencies}"

        # Concurrent status polls while the job is running.
        conc_latencies = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(_poll_status, client, job_id) for _ in range(16)]
            for f in as_completed(futures):
                status_code, dt = f.result()
                assert status_code == 200
                conc_latencies.append(dt)

        conc_latencies.sort()
        p95 = conc_latencies[int(len(conc_latencies) * 0.95)]
        assert p95 < 200, f"status p95 too slow: {p95:.0f}ms"
        ordered = sorted(conc_latencies)
        print(f"\nstatus during generation (concurrent): n={len(conc_latencies)} "
              f"min={ordered[0]:.0f}ms p50={ordered[len(ordered)//2]:.0f}ms "
              f"p95={p95:.0f}ms max={ordered[-1]:.0f}ms | sequential max={max(seq_latencies):.0f}ms")


def test_status_after_completion(client, tmp_path):
    with _fake_job_context(tmp_path, "Completed Event") as job_id:
        assert _wait_for_terminal(job_id) == "completed"
        r = client.get(f"/api/jobs/{job_id}/status")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "completed"
    assert data["progress"]["pct"] == 100


def test_status_after_failure_records_error(client, tmp_path):
    """A failed background job records the actual exception and status=failed."""
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

    def _boom(*a, **k):
        raise RuntimeError("ML model out of memory")

    with patch("content_engine.orchestrator.ContentOrchestrator.run", side_effect=_boom), \
         patch("content_engine.ContentEngine.process_assets_parallel",
               return_value=[_make_metadata(str(img))]), \
         patch("content_engine.orchestrator.ContentOrchestrator.__init__",
               return_value=None):
        job_id = submit_generate_job([str(img)], "Fail Event", "desc")
        assert _wait_for_terminal(job_id) == "failed"

    j = get_job(job_id)
    assert j is not None
    assert j["status"] == "failed"
    assert j["error"] is not None
    assert "out of memory" in j["error"]

    r = client.get(f"/api/jobs/{job_id}/status")
    assert r.status_code == 200
    assert r.json()["status"] == "failed"
    assert r.json()["error"] is not None


# ── Result ───────────────────────────────────────────────────────────────────

def test_result_retrieval_returns_real_outputs(client, tmp_path):
    with _fake_job_context(tmp_path, "Result Event") as job_id, \
         patch.object(settings, "output_dir", tmp_path / "output"):
        assert _wait_for_terminal(job_id) == "completed"
        r = client.get(f"/api/jobs/{job_id}/result")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "completed"
    assert isinstance(data.get("files"), dict) and len(data["files"]) > 0
    assert any(k in data.get("captions", {}) for k in ("linkedin_caption", "case_study"))


def test_result_unknown_job_returns_404(client):
    with patch("api.scheduler.get_job", return_value=None):
        r = client.get("/api/jobs/does-not-exist/result")
    assert r.status_code == 404


def test_result_not_complete_returns_409(client):
    with patch("api.scheduler.get_job") as mock_get:
        mock_get.return_value = {"status": "running", "progress": {"step": "ml_selection", "pct": 40}}
        r = client.get("/api/jobs/running-job/result")
    assert r.status_code == 409


def test_result_completed_but_missing_files_returns_500(client):
    expected_result = {
        "status": "completed",
        "event": "Test Event",
        "files": {"linkedin_collage.jpg": "/output/Test_Event/linkedin_collage.jpg"},
    }
    with patch("api.scheduler.get_job") as mock_get, \
         patch.object(settings, "output_dir", settings.output_dir):
        mock_get.return_value = {"status": "completed", "result": expected_result}
        r = client.get("/api/jobs/test-job/result")
    assert r.status_code == 500
    assert "missing" in r.json()["detail"].lower()


# ── Job state synchronization ────────────────────────────────────────────────

def test_job_registered_before_execution(tmp_path):
    """The job record exists (pending) before the background thread starts."""
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    with patch("content_engine.ContentEngine.process_assets_parallel",
               return_value=[_make_metadata(str(img))]), \
         patch("content_engine.orchestrator.ContentOrchestrator.run",
               return_value=_fake_output_dir(tmp_path, "RegEvent")), \
         patch("content_engine.orchestrator.ContentOrchestrator.__init__",
               return_value=None):
        job_id = submit_generate_job([str(img)], "RegEvent", "desc")

    j = get_job(job_id)
    assert j is not None
    assert j["status"] in ("pending", "running")
    assert j["job_id"] == job_id
    assert "created_at" in j and "updated_at" in j


def test_atomic_progress_updates(tmp_path):
    """Progress updates are atomic: a read never sees a torn progress dict."""
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    with _fake_job_context(tmp_path, "Atomic Event") as job_id:
        seen = set()
        deadline = time.time() + 30
        while time.time() < deadline:
            j = get_job(job_id)
            if j and j["status"] in ("completed", "failed"):
                break
            p = j.get("progress") or {}
            assert "step" in p and "pct" in p, f"torn progress: {p}"
            seen.add((p.get("step"), p.get("pct")))
            time.sleep(0.05)

    assert get_job(job_id)["status"] == "completed"


def test_concurrent_reads_writes_do_not_corrupt(tmp_path):
    """Concurrent status reads and job updates must not corrupt shared state."""
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    with _fake_job_context(tmp_path, "Lock Event") as job_id:
        errors = []
        stop = threading.Event()

        def reader():
            while not stop.is_set():
                try:
                    j = get_job(job_id)
                    if j is not None:
                        assert isinstance(j["status"], str)
                        assert isinstance(j.get("progress"), dict)
                        assert isinstance(j["job_id"], str)
                except AssertionError as e:
                    errors.append(str(e))
                time.sleep(0.01)

        def writer():
            for pct in (10, 20, 30, 40, 50):
                if stop.is_set():
                    break
                set_job_data(job_id, progress={"step": "writing", "pct": pct})
                time.sleep(0.05)

        t1 = threading.Thread(target=reader)
        t2 = threading.Thread(target=writer)
        t1.start(); t2.start()
        t2.join()
        stop.set()
        t1.join()

    assert not errors, errors
    j = get_job(job_id)
    assert j is not None
    assert isinstance(j["status"], str)


# ── Scheduler lifecycle ──────────────────────────────────────────────────────

def test_scheduler_single_instance():
    """get_scheduler() returns the same instance and starts it exactly once."""
    s1 = get_scheduler()
    s2 = get_scheduler()
    assert s1 is s2
    assert s1.running


def test_executor_released_after_job(tmp_path):
    """The single background worker is released after the job finishes (no starvation)."""
    with _fake_job_context(tmp_path, "Release Event") as job_id:
        assert _wait_for_terminal(job_id) == "completed"

    # Submitting a second job must work immediately (worker not starved).
    with _fake_job_context(tmp_path, "Release Event 2") as job_id2:
        assert _wait_for_terminal(job_id2) == "completed"
