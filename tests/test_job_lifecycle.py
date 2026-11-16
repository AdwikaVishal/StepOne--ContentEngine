"""
Job lifecycle tests for the APScheduler (in-process) async backend.

These tests exercise the real scheduler functions (submit_generate_job / get_job)
with the ML pipeline faked out, so they run fast without downloading models.
They verify:
  - submission returns a job_id immediately,
  - generation runs in the background and status progresses,
  - completed jobs expose their results,
  - job state is not discarded after the scheduler finishes.
"""
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

from api.scheduler import submit_generate_job, get_job
from config import settings


def _make_metadata(path: str) -> MagicMock:
    m = MagicMock()
    m.path = path
    m.final_score = 0.9
    m.quality_score = 0.8
    m.aesthetic_score = 0.8
    m.scene_concepts = ["speaker", "stage"]
    m.face_count = 1
    return m


def _fake_output_dir(tmp_path: Path, event_name: str) -> Path:
    out = tmp_path / "output" / _safe(event_name)
    out.mkdir(parents=True)
    (out / "linkedin_collage.jpg").write_bytes(b"collage-bytes")
    (out / "instagram_carousel_1.jpg").write_bytes(b"carousel-bytes")
    (out / "linkedin_caption.txt").write_text("A wonderful event.", encoding="utf-8")
    (out / "case_study.md").write_text("# Case Study\n\nA wonderful event.", encoding="utf-8")
    return out


def _safe(name: str) -> str:
    import re
    return re.sub(r"[^\w\-]", "_", name).strip("_")


def test_submit_generate_job_returns_immediately(tmp_path):
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    fake_out = _fake_output_dir(tmp_path, "Lifecycle Event")
    patches = [
        patch("content_engine.ContentEngine.process_assets_parallel", return_value=[_make_metadata(str(img))]),
        patch("content_engine.orchestrator.ContentOrchestrator.run", return_value=fake_out),
        patch("content_engine.orchestrator.ContentOrchestrator.__init__", return_value=None),
    ]
    with patches[0], patches[1], patches[2]:
        # Returns a job_id immediately, without waiting for generation.
        job_id = submit_generate_job([str(img)], "Lifecycle Event", "A lifecycle event")
        assert isinstance(job_id, str) and len(job_id) > 0
        job = get_job(job_id)
        assert job is not None
        assert job["job_id"] == job_id
        assert job["status"] in ("pending", "running")
        assert job["progress"]["pct"] in (0, 5, 10)
        # Let the background thread finish so the single worker is released.
        deadline = time.time() + 60
        while time.time() < deadline:
            if get_job(job_id) and get_job(job_id)["status"] in ("completed", "failed"):
                break
            time.sleep(0.25)


def _run_and_wait(tmp_path, event_name):
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    fake_out = _fake_output_dir(tmp_path, event_name)
    patches = [
        patch("content_engine.ContentEngine.process_assets_parallel", return_value=[_make_metadata(str(img))]),
        patch("content_engine.orchestrator.ContentOrchestrator.run", return_value=fake_out),
        patch("content_engine.orchestrator.ContentOrchestrator.__init__", return_value=None),
    ]
    with patches[0], patches[1], patches[2]:
        job_id = submit_generate_job([str(img)], event_name, "desc")
        # Keep the ML fakes active while the background thread runs.
        deadline = time.time() + 60
        final = None
        while time.time() < deadline:
            job = get_job(job_id)
            if job and job["status"] in ("completed", "failed"):
                final = job
                break
            time.sleep(0.25)
    return job_id, final


def test_job_status_progresses_to_completed(tmp_path):
    job_id, final = _run_and_wait(tmp_path, "Progress Event")

    assert final is not None, "Job never reached a terminal state"
    assert final["status"] == "completed", f"Job failed: {final.get('error')}"
    assert final["progress"]["step"] == "done"
    assert final["progress"]["pct"] == 100

    result = final["result"]
    assert result is not None
    assert result["status"] == "completed"
    assert result["event"] == "Progress Event"
    assert isinstance(result.get("files"), dict) and len(result["files"]) > 0


def test_job_state_not_discarded_after_completion(tmp_path):
    job_id, final = _run_and_wait(tmp_path, "Persist Event")

    assert final is not None and final["status"] == "completed"

    # State remains readable after the scheduler thread has finished.
    assert get_job(job_id) is not None
    assert get_job(job_id)["status"] == "completed"
    assert get_job(job_id)["result"]["status"] == "completed"
    assert settings.output_dir  # settings still intact


def test_get_job_unknown_returns_none():
    assert get_job("definitely-not-a-real-job-id") is None
