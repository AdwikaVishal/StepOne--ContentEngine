from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from scripts import benchmark_studio_models as bench


def test_fixed_suite_has_twelve_stable_studio_cases():
    cases = json.loads(bench.CASES_PATH.read_text(encoding="utf-8"))
    assert len(cases) == 12
    assert len({case["id"] for case in cases}) == 12
    assert {case["platform"] for case in cases} == {"linkedin", "instagram"}
    assert any(case.get("date") is None for case in cases)
    assert any(case.get("time") is None for case in cases)
    assert any(case.get("location") is None for case in cases)
    assert any(case.get("audience") is None for case in cases)
    assert any((case.get("brand_profile") or {}).get("avoid_words_claims") for case in cases)
    assert any(case.get("uncertain_image_caption") for case in cases)


def test_unverified_image_caption_is_outside_verified_fact_record():
    case = next(
        row for row in json.loads(bench.CASES_PATH.read_text(encoding="utf-8"))
        if row.get("uncertain_image_caption")
    )
    facts = bench.build_fact_record(case)
    messages = bench.build_messages(case, facts)
    encoded_facts = json.dumps(facts, ensure_ascii=False)
    assert case["uncertain_image_caption"] not in encoded_facts
    assert case["uncertain_image_caption"] in messages[1]["content"]
    assert "Unverified image description" in messages[1]["content"]


def test_shared_messages_and_generation_settings_are_model_independent():
    case = json.loads(bench.CASES_PATH.read_text(encoding="utf-8"))[0]
    facts = bench.build_fact_record(case)
    assert bench.build_messages(case, facts) == bench.build_messages(case, facts)
    assert bench.MAX_NEW_TOKENS == 64
    assert bench.MODEL_IDS == {
        "qwen": "Qwen/Qwen2.5-1.5B-Instruct",
        "gemma": "google/gemma-3-1b-it",
    }


def test_validator_adapter_separates_acceptance_from_manual_review():
    cases = json.loads(bench.CASES_PATH.read_text(encoding="utf-8"))
    safe_case = next(case for case in cases if case["id"] == "restrictive_brand_linkedin")
    facts = bench.build_fact_record(safe_case)
    accepted = bench.validate_caption_read_only(
        "Volunteers review the food sorting plan at the briefing.", facts, safe_case,
    )
    rejected = bench.validate_caption_read_only(
        "Volunteers review the plan today and build community.", facts, safe_case,
    )
    assert accepted == {"status": "accepted", "reason": None}
    assert rejected["status"] == "rejected"
    assert rejected["reason"]


def test_memory_gate_refuses_cpu_fallback_and_insufficient_headroom():
    assert "MPS unavailable" in bench.preflight_blocker(False, {"available_mib": 8192})
    assert "require" in bench.preflight_blocker(True, {"available_mib": 2048})
    assert bench.preflight_blocker(True, {"available_mib": 4096}) is None


def test_gemma_license_is_never_marked_approved_by_cache_presence():
    metadata = bench._license_metadata()
    assert metadata["gemma"]["license_review_status"] == "review required; cache is not proof of approval"
    assert metadata["gemma"]["license_lines"]


def test_run_directories_are_unique_and_do_not_reuse_existing_results(tmp_path: Path):
    first = bench.create_run_dir(tmp_path, "preflight")
    second = bench.create_run_dir(tmp_path, "preflight")
    assert first != second
    assert first.parent == tmp_path and second.parent == tmp_path
    assert first.is_dir() and second.is_dir()


def test_cached_model_loader_uses_local_mps_float16(monkeypatch, tmp_path: Path):
    calls = []
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    monkeypatch.setattr(bench, "resolve_cached_snapshot", lambda model_id: snapshot)
    monkeypatch.setattr(bench, "_memory_info", lambda: {"total_mib": 8192, "available_mib": 5000, "percent_used": 39})
    monkeypatch.setattr(bench, "_rss_peak_mib", lambda: 1000.0)

    class FakeTokenizer:
        pass

    class FakeModel:
        def to(self, device):
            calls.append(("device", device))
            return self

        def eval(self):
            return self

    tokenizer = FakeTokenizer()
    model = FakeModel()

    class FakeAutoTokenizer:
        @staticmethod
        def from_pretrained(path, **kwargs):
            calls.append(("tokenizer", path, kwargs))
            return tokenizer

    class FakeAutoModel:
        @staticmethod
        def from_pretrained(path, **kwargs):
            calls.append(("model", path, kwargs))
            return model

    fake_torch = SimpleNamespace(
        float16="float16",
        __version__="test-torch",
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True)),
        mps=SimpleNamespace(current_allocated_memory=lambda: 1, driver_allocated_memory=lambda: 2),
    )
    fake_transformers = ModuleType("transformers")
    fake_transformers.__version__ = "test-transformers"
    fake_transformers.AutoTokenizer = FakeAutoTokenizer
    fake_transformers.AutoModelForCausalLM = FakeAutoModel
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    loaded_tokenizer, loaded_model, info = bench._load_components(bench.MODEL_IDS["qwen"])
    assert loaded_tokenizer is tokenizer and loaded_model is model
    assert calls[0][0] == "tokenizer" and calls[0][2]["local_files_only"] is True
    assert calls[1][0] == "model" and calls[1][2]["local_files_only"] is True
    assert calls[1][2]["torch_dtype"] == "float16"
    assert calls[2] == ("device", "mps")
    assert info["device"] == "mps" and info["dtype"] == "float16"


def test_atomic_report_write_round_trips_json(tmp_path: Path):
    path = tmp_path / "preflight.json"
    bench._atomic_write(path, {"status": "blocked_memory", "results": {}})
    assert json.loads(path.read_text()) == {"status": "blocked_memory", "results": {}}
    assert list(tmp_path.glob(".preflight.json.*.tmp")) == []
