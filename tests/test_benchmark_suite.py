import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from scripts.benchmark_local_models import (
    MODELS, PROMPTS, QUICK_PROMPT_IDS, _checkpoint_prompt, _deduplicate_results,
    _json_valid, _merge_prompt_ids, _run_child, _save,
)
import os
import sys



def test_benchmark_suite_has_ten_named_scenarios():
    prompts = json.loads(PROMPTS.read_text())
    assert len(prompts) >= 10
    assert len({item["id"] for item in prompts}) == len(prompts)
    assert {item["category"] for item in prompts} >= {
        "LinkedIn professional post", "Instagram caption", "Carousel narrative",
        "Short-form video storyboard", "Strong opening hook", "Call to action",
        "Brand voice adherence", "Structured JSON output", "Missing-context handling",
        "Avoiding unsupported claims",
    }
    assert MODELS == {
        "qwen": "Qwen/Qwen2.5-1.5B-Instruct",
        "gemma": "google/gemma-3-1b-it",
    }
    assert QUICK_PROMPT_IDS == ["linkedin_professional", "instagram_caption", "structured_json"]
    assert set(QUICK_PROMPT_IDS) <= {item["id"] for item in prompts}


def test_structured_output_validation_is_strict():
    assert _json_valid('{"caption":"Hello","hashtags":["#hi"],"uncertainty":[]}')
    assert not _json_valid("Here is the JSON: {}")
    assert not _json_valid('{"caption":"Hello","hashtags":"#hi","uncertainty":[]}')
    assert not _json_valid('{"caption":"Hello","hashtags":[],"uncertainty":[],"extra":true}')


def test_prompt_result_is_checkpointed_and_resumable(tmp_path: Path):
    target = tmp_path / "qwen.json"
    report = {"status": "running", "results": []}
    _checkpoint_prompt(target, report, {
        "id": "linkedin_professional", "status": "ok", "output": "Draft",
        "generation_seconds": 2.5, "json_valid": None,
    }, ["linkedin_professional", "structured_json"], 512.0)
    saved = json.loads(target.read_text())
    assert saved["results"][0]["output"] == "Draft"
    assert saved["results"][0]["generation_seconds"] == 2.5
    assert saved["successful_prompts"] == 1
    assert saved["peak_process_rss_mib"] == 512.0

    _checkpoint_prompt(target, saved, {
        "id": "structured_json", "status": "failed", "error": "timeout",
    }, ["linkedin_professional", "structured_json"], 640.0)
    resumed = json.loads(target.read_text())
    assert [row["id"] for row in resumed["results"]] == [
        "linkedin_professional", "structured_json",
    ]
    assert resumed["results"][0]["output"] == "Draft"
    assert resumed["results"][1]["error"] == "timeout"


def test_resume_merges_prompt_ids_without_duplicate_results():
    assert _merge_prompt_ids(["linkedin_professional", "instagram_caption"],
                             ["instagram_caption", "structured_json"]) == [
        "linkedin_professional", "instagram_caption", "structured_json",
    ]
    rows = _deduplicate_results([
        {"id": "linkedin_professional", "status": "ok", "output": "saved"},
        {"id": "linkedin_professional", "status": "inference_failure", "error": "later retry failed"},
        {"id": "structured_json", "status": "ok", "output": "{}"},
    ])
    assert len(rows) == 2
    assert rows[0]["output"] == "saved"
    assert rows[1]["id"] == "structured_json"


def test_model_loader_is_local_only(monkeypatch):
    from scripts.benchmark_local_models import _load_local_components

    tokenizer = object()

    class FakeModel:
        def to(self, device):
            assert device == "cpu"
            return self

        def eval(self):
            return self

    model = FakeModel()
    def tokenizer_loader(model_id, **kwargs):
        assert model_id == MODELS["qwen"]
        assert kwargs["local_files_only"] is True
        return tokenizer

    def model_loader(model_id, **kwargs):
        assert model_id == MODELS["qwen"]
        assert kwargs["local_files_only"] is True
        assert kwargs["torch_dtype"] == "bf16"
        return model
    fake_transformers = ModuleType("transformers")
    fake_transformers.AutoTokenizer = SimpleNamespace(from_pretrained=tokenizer_loader)
    fake_transformers.AutoModelForCausalLM = SimpleNamespace(from_pretrained=model_loader)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    loaded_tokenizer, loaded_model = _load_local_components(
        MODELS["qwen"], type("TorchStub", (), {"bfloat16": "bf16"})()
    )
    assert loaded_tokenizer is tokenizer
    assert loaded_model is model


def test_timed_out_child_process_group_is_terminated(tmp_path: Path):
    from scripts.benchmark_local_models import _run_child

    log_path = tmp_path / "sleep.log"
    status, return_code = _run_child(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        Path.cwd(), dict(os.environ), log_path, 0.1,
    )
    assert status == "timeout"
    assert return_code is not None
    assert log_path.exists()


def test_failed_checkpoint_write_preserves_previous_report(tmp_path: Path):
    target = tmp_path / "report.json"
    previous = {"status": "running", "results": [{"id": "linkedin_professional", "status": "ok", "output": "saved"}]}
    _save(target, previous)

    with pytest.raises(TypeError):
        _save(target, {"not_json_serializable": {1, 2, 3}})

    assert json.loads(target.read_text()) == previous
    assert list(tmp_path.glob(".report.json.*.tmp")) == []
