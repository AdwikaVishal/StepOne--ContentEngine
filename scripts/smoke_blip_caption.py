"""Run one local-only BLIP Base captioning smoke test on a local image."""
from __future__ import annotations

import json
import platform
import resource
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "Salesforce/blip-image-captioning-base"
IMAGE_PATH = ROOT / "test_photos" / "download.jpg"
OUTPUT_PATH = ROOT / "benchmark_results" / "blip_smoke.json"


def peak_rss_mib() -> float:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value / (1024 * 1024) if sys.platform == "darwin" else value / 1024


def main() -> int:
    report = {
        "model_id": MODEL_ID,
        "task": "image captioning (not text generation)",
        "image_path": str(IMAGE_PATH),
        "image_asset_id": IMAGE_PATH.name,
        "device": "cpu",
        "dtype": "float32",
        "python": platform.python_version(),
        "hardware": platform.platform(),
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "caption_is_unverified_observation": True,
        "quality_note": "Caption is an unverified image description; it is not evidence of identity, location, date, or event.",
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2))
    if not IMAGE_PATH.is_file():
        report.update({"status": "failed", "stage": "input", "error": "Local smoke-test image is missing."})
        OUTPUT_PATH.write_text(json.dumps(report, indent=2))
        return 1
    import torch
    import transformers
    from PIL import Image
    from transformers import BlipForConditionalGeneration, BlipProcessor

    report.update({"torch": torch.__version__, "transformers": transformers.__version__,
                   "peak_process_rss_mib_before_load": peak_rss_mib()})
    OUTPUT_PATH.write_text(json.dumps(report, indent=2))
    started = time.perf_counter()
    try:
        processor = BlipProcessor.from_pretrained(MODEL_ID, local_files_only=True)
        model = BlipForConditionalGeneration.from_pretrained(
            MODEL_ID, local_files_only=True, torch_dtype=torch.float32
        ).to("cpu").eval()
        report["load_seconds"] = time.perf_counter() - started
        report["peak_process_rss_mib_after_load"] = peak_rss_mib()
        OUTPUT_PATH.write_text(json.dumps(report, indent=2))
        image = Image.open(IMAGE_PATH).convert("RGB")
        inputs = processor(images=image, return_tensors="pt")
        generation_started = time.perf_counter()
        with torch.inference_mode():
            output = model.generate(**inputs, max_new_tokens=48, do_sample=False)
        report.update({
            "status": "ok",
            "generation_settings": {"max_new_tokens": 48, "do_sample": False},
            "caption_latency_seconds": time.perf_counter() - generation_started,
            "caption": processor.decode(output[0], skip_special_tokens=True).strip(),
            "peak_process_rss_mib": peak_rss_mib(),
        })
    except Exception as exc:
        report.update({"status": "failed", "stage": "load_or_inference",
                       "error": f"{type(exc).__name__}: {exc}",
                       "traceback": traceback.format_exc(), "peak_process_rss_mib": peak_rss_mib()})
        OUTPUT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        return 1
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    del model, processor
    print(report["caption"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
