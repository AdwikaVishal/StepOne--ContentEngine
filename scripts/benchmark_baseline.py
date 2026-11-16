"""
Baseline benchmark for all seven production models on Windows + RTX 4050.

Records:
- Current device for each model
- Model loading time
- Inference latency
- Peak VRAM
- Peak RAM
- Whether multiple models remain loaded simultaneously

Run BEFORE any Phase F changes to establish a baseline.
Run AFTER Phase F changes to compare results.
"""

from __future__ import annotations

import gc
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

# Force offline mode
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import psutil
import torch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

RESULTS: Dict[str, Any] = {
    "platform": sys.platform,
    "torch_version": torch.__version__,
    "cuda_available": torch.cuda.is_available(),
    "cuda_device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    "cuda_vram_total_gb": round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 3) if torch.cuda.is_available() else None,
    "system_ram_total_gb": round(psutil.virtual_memory().total / 1024**3, 2),
    "models": {},
    "simultaneous_load": {},
}

process = psutil.Process()


def get_ram_mb() -> float:
    return process.memory_info().rss / 1024**2


def get_vram_mb() -> float:
    if torch.cuda.is_available():
        return torch.cuda.memory_allocated(0) / 1024**2
    return 0.0


def reset_cuda() -> None:
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()


def get_peak_vram_mb() -> float:
    if torch.cuda.is_available():
        return torch.cuda.max_memory_allocated(0) / 1024**2
    return 0.0


# ── CLIP ──
def bench_clip() -> Dict[str, Any]:
    from sentence_transformers import SentenceTransformer
    from config import CLIP_MODEL_PATH

    result: Dict[str, Any] = {"local_path": str(CLIP_MODEL_PATH), "path_exists": os.path.isdir(CLIP_MODEL_PATH)}

    ram_before = get_ram_mb()
    reset_cuda()
    vram_before = get_vram_mb()

    t0 = time.perf_counter()
    model = SentenceTransformer(CLIP_MODEL_PATH, device="cuda" if torch.cuda.is_available() else "cpu")
    load_time = time.perf_counter() - t0

    result["device"] = str(model.device)
    result["load_time_seconds"] = round(load_time, 3)
    result["ram_mb_after_load"] = round(get_ram_mb() - ram_before, 1)
    result["vram_mb_after_load"] = round(get_vram_mb() - vram_before, 1)
    result["peak_vram_mb"] = round(get_peak_vram_mb(), 1)

    # Inference test
    import numpy as np

    test_texts = ["professional networking event", "keynote presentation on stage", "crowd applauding"]
    t0 = time.perf_counter()
    emb = model.encode(test_texts)
    infer_time = time.perf_counter() - t0
    result["inference_latency_seconds"] = round(infer_time, 4)
    result["embedding_shape"] = list(emb.shape)
    result["ram_mb_after_infer"] = round(get_ram_mb() - ram_before, 1)
    result["vram_mb_after_infer"] = round(get_vram_mb() - vram_before, 1)

    del model
    gc.collect()
    reset_cuda()
    return result


# ── DINOv2 ──
def bench_dinov2() -> Dict[str, Any]:
    from transformers import AutoImageProcessor, AutoModel
    from config import DINOV2_MODEL_PATH

    result: Dict[str, Any] = {"local_path": str(DINOV2_MODEL_PATH), "path_exists": os.path.isdir(DINOV2_MODEL_PATH)}

    ram_before = get_ram_mb()
    reset_cuda()
    vram_before = get_vram_mb()

    t0 = time.perf_counter()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    processor = AutoImageProcessor.from_pretrained(DINOV2_MODEL_PATH, local_files_only=True)
    model = AutoModel.from_pretrained(DINOV2_MODEL_PATH, local_files_only=True).to(device)
    model.eval()
    load_time = time.perf_counter() - t0

    result["device"] = device
    result["load_time_seconds"] = round(load_time, 3)
    result["ram_mb_after_load"] = round(get_ram_mb() - ram_before, 1)
    result["vram_mb_after_load"] = round(get_vram_mb() - vram_before, 1)
    result["peak_vram_mb"] = round(get_peak_vram_mb(), 1)

    # Inference test
    from PIL import Image
    import numpy as np

    img = Image.fromarray(np.random.randint(0, 255, (224, 224, 3), dtype=np.uint8))
    inputs = processor(images=img, return_tensors="pt").to(device)
    t0 = time.perf_counter()
    with torch.no_grad():
        out = model(**inputs)
    infer_time = time.perf_counter() - t0
    result["inference_latency_seconds"] = round(infer_time, 4)
    result["output_shape"] = list(out.last_hidden_state.shape)
    result["ram_mb_after_infer"] = round(get_ram_mb() - ram_before, 1)
    result["vram_mb_after_infer"] = round(get_vram_mb() - vram_before, 1)

    del model, processor
    gc.collect()
    reset_cuda()
    return result


# ── Florence-2 ──
def bench_florence() -> Dict[str, Any]:
    from transformers import AutoModelForCausalLM, AutoProcessor
    from config import FLORENCE_MODEL_PATH

    result: Dict[str, Any] = {"local_path": str(FLORENCE_MODEL_PATH), "path_exists": os.path.isdir(FLORENCE_MODEL_PATH)}

    ram_before = get_ram_mb()
    reset_cuda()
    vram_before = get_vram_mb()

    t0 = time.perf_counter()
    device = "cpu"  # Florence-2 stays on CPU per existing config
    model = AutoModelForCausalLM.from_pretrained(
        FLORENCE_MODEL_PATH,
        torch_dtype=torch.float32,
        trust_remote_code=True,
        attn_implementation="eager",
        local_files_only=True,
    ).to(device)
    processor = AutoProcessor.from_pretrained(FLORENCE_MODEL_PATH, trust_remote_code=True, local_files_only=True)
    model.eval()
    load_time = time.perf_counter() - t0

    result["device"] = device
    result["dtype"] = "float32"
    result["load_time_seconds"] = round(load_time, 3)
    result["ram_mb_after_load"] = round(get_ram_mb() - ram_before, 1)
    result["vram_mb_after_load"] = round(get_vram_mb() - vram_before, 1)
    result["peak_vram_mb"] = round(get_peak_vram_mb(), 1)

    # Inference test (errors don't invalidate load data)
    try:
        from PIL import Image
        import numpy as np

        img = Image.fromarray(np.random.randint(0, 255, (384, 384, 3), dtype=np.uint8)).convert("RGB")
        inputs = processor(text="<OD>", images=img, return_tensors="pt").to(device)
        t0 = time.perf_counter()
        with torch.no_grad():
            generated_ids = model.generate(input_ids=inputs["input_ids"], pixel_values=inputs["pixel_values"], max_new_tokens=50, do_sample=False)
        infer_time = time.perf_counter() - t0
        result["inference_latency_seconds"] = round(infer_time, 4)
        if hasattr(generated_ids, 'shape'):
            result["generated_tokens"] = int(generated_ids.shape[1])
        else:
            result["generated_tokens"] = "unknown"
        result["ram_mb_after_infer"] = round(get_ram_mb() - ram_before, 1)
        result["vram_mb_after_infer"] = round(get_vram_mb() - vram_before, 1)
    except Exception as e:
        result["inference_error"] = str(e)

    del model, processor
    gc.collect()
    reset_cuda()
    return result


# ── BLIP ──
def bench_blip() -> Dict[str, Any]:
    from transformers import BlipProcessor, BlipForConditionalGeneration
    from config import BLIP_MODEL_PATH

    result: Dict[str, Any] = {"local_path": str(BLIP_MODEL_PATH), "path_exists": os.path.isdir(BLIP_MODEL_PATH)}

    ram_before = get_ram_mb()
    reset_cuda()
    vram_before = get_vram_mb()

    t0 = time.perf_counter()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    processor = BlipProcessor.from_pretrained(BLIP_MODEL_PATH, local_files_only=True)
    model = BlipForConditionalGeneration.from_pretrained(BLIP_MODEL_PATH, local_files_only=True).to(device)
    model.eval()
    load_time = time.perf_counter() - t0

    result["device"] = device
    result["load_time_seconds"] = round(load_time, 3)
    result["ram_mb_after_load"] = round(get_ram_mb() - ram_before, 1)
    result["vram_mb_after_load"] = round(get_vram_mb() - vram_before, 1)
    result["peak_vram_mb"] = round(get_peak_vram_mb(), 1)

    # Inference test
    from PIL import Image
    import numpy as np

    img = Image.fromarray(np.random.randint(0, 255, (384, 384, 3), dtype=np.uint8)).convert("RGB")
    inputs = processor(images=img, return_tensors="pt").to(device)
    t0 = time.perf_counter()
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=30)
    infer_time = time.perf_counter() - t0
    result["inference_latency_seconds"] = round(infer_time, 4)
    result["generated_tokens"] = int(out.shape[1])
    result["ram_mb_after_infer"] = round(get_ram_mb() - ram_before, 1)
    result["vram_mb_after_infer"] = round(get_vram_mb() - vram_before, 1)

    del model, processor
    gc.collect()
    reset_cuda()
    return result


# ── YOLOv8 ──
def bench_yolov8() -> Dict[str, Any]:
    from ultralytics import YOLO
    from config import YOLOV8_MODEL_PATH

    result: Dict[str, Any] = {"local_path": str(YOLOV8_MODEL_PATH), "path_exists": os.path.isfile(YOLOV8_MODEL_PATH)}

    ram_before = get_ram_mb()
    reset_cuda()
    vram_before = get_vram_mb()

    t0 = time.perf_counter()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = YOLO(YOLOV8_MODEL_PATH)
    load_time = time.perf_counter() - t0

    result["device"] = device
    result["load_time_seconds"] = round(load_time, 3)
    result["ram_mb_after_load"] = round(get_ram_mb() - ram_before, 1)
    result["vram_mb_after_load"] = round(get_vram_mb() - vram_before, 1)
    result["peak_vram_mb"] = round(get_peak_vram_mb(), 1)

    # Inference test
    import numpy as np

    img = np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)
    t0 = time.perf_counter()
    results = model(img, verbose=False)
    infer_time = time.perf_counter() - t0
    result["inference_latency_seconds"] = round(infer_time, 4)
    result["num_detections"] = len(results[0].boxes) if results[0].boxes is not None else 0
    result["ram_mb_after_infer"] = round(get_ram_mb() - ram_before, 1)
    result["vram_mb_after_infer"] = round(get_vram_mb() - vram_before, 1)

    del model
    gc.collect()
    reset_cuda()
    return result


# ── YOLOv11 Face ──
def bench_yolov11_face() -> Dict[str, Any]:
    from ultralytics import YOLO
    from config import YOLOV11_FACE_MODEL_PATH

    result: Dict[str, Any] = {"local_path": str(YOLOV11_FACE_MODEL_PATH), "path_exists": os.path.isfile(YOLOV11_FACE_MODEL_PATH)}

    ram_before = get_ram_mb()
    reset_cuda()
    vram_before = get_vram_mb()

    t0 = time.perf_counter()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = YOLO(YOLOV11_FACE_MODEL_PATH)
    load_time = time.perf_counter() - t0

    result["device"] = device
    result["load_time_seconds"] = round(load_time, 3)
    result["ram_mb_after_load"] = round(get_ram_mb() - ram_before, 1)
    result["vram_mb_after_load"] = round(get_vram_mb() - vram_before, 1)
    result["peak_vram_mb"] = round(get_peak_vram_mb(), 1)

    # Inference test
    import numpy as np

    img = np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)
    t0 = time.perf_counter()
    results = model(img, verbose=False)
    infer_time = time.perf_counter() - t0
    result["inference_latency_seconds"] = round(infer_time, 4)
    result["num_detections"] = len(results[0].boxes) if results[0].boxes is not None else 0
    result["ram_mb_after_infer"] = round(get_ram_mb() - ram_before, 1)
    result["vram_mb_after_infer"] = round(get_vram_mb() - vram_before, 1)

    del model
    gc.collect()
    reset_cuda()
    return result


# ── Qwen ──
def bench_qwen() -> Dict[str, Any]:
    from content_engine.llm.torch_backend import get_torch_generator, reset_torch_generator

    result: Dict[str, Any] = {
        "local_path": str(os.getenv("TORCH_LLM_MODEL", "models/qwen/")),
        "path_exists": os.path.isdir(os.getenv("TORCH_LLM_MODEL", "models/qwen/")),
    }

    ram_before = get_ram_mb()
    reset_cuda()
    vram_before = get_vram_mb()

    reset_torch_generator()
    gen = get_torch_generator()

    t0 = time.perf_counter()
    gen._ensure_loaded()
    load_time = time.perf_counter() - t0

    result["device"] = gen.device
    result["load_time_seconds"] = round(load_time, 3)
    result["ram_mb_after_load"] = round(get_ram_mb() - ram_before, 1)
    result["vram_mb_after_load"] = round(get_vram_mb() - vram_before, 1)
    result["peak_vram_mb"] = round(get_peak_vram_mb(), 1)

    # Inference test
    t0 = time.perf_counter()
    output = gen.generate(
        system="You are a social media copywriter.",
        user="Write a short LinkedIn caption for a tech conference.",
        max_tokens=50,
        temperature=0.0,
    )
    infer_time = time.perf_counter() - t0
    result["inference_latency_seconds"] = round(infer_time, 4)
    result["output_length"] = len(output)
    result["output_sample"] = output[:100].replace("\n", " ")
    result["ram_mb_after_infer"] = round(get_ram_mb() - ram_before, 1)
    result["vram_mb_after_infer"] = round(get_vram_mb() - vram_before, 1)

    reset_torch_generator()
    gc.collect()
    reset_cuda()
    return result


# ── Simultaneous load test ──
def bench_simultaneous() -> Dict[str, Any]:
    """Load CLIP + Florence-2 + Qwen simultaneously to check VRAM competition."""
    result: Dict[str, Any] = {}

    from sentence_transformers import SentenceTransformer
    from transformers import AutoModelForCausalLM, AutoProcessor
    from config import CLIP_MODEL_PATH, FLORENCE_MODEL_PATH

    ram_before = get_ram_mb()
    reset_cuda()
    vram_before = get_vram_mb()

    models_loaded = []

    # CLIP
    try:
        clip_model = SentenceTransformer(CLIP_MODEL_PATH, device="cuda" if torch.cuda.is_available() else "cpu")
        models_loaded.append("CLIP")
    except Exception as e:
        result["clip_error"] = str(e)

    # Florence-2
    try:
        florence_model = AutoModelForCausalLM.from_pretrained(
            FLORENCE_MODEL_PATH,
            torch_dtype=torch.float32,
            trust_remote_code=True,
            attn_implementation="eager",
            local_files_only=True,
        ).to("cpu")
        florence_proc = AutoProcessor.from_pretrained(FLORENCE_MODEL_PATH, trust_remote_code=True, local_files_only=True)
        models_loaded.append("Florence-2")
    except Exception as e:
        result["florence_error"] = str(e)

    # Qwen
    try:
        from content_engine.llm.torch_backend import get_torch_generator
        qwen_gen = get_torch_generator()
        qwen_gen._ensure_loaded()
        models_loaded.append("Qwen")
    except Exception as e:
        result["qwen_error"] = str(e)

    result["models_loaded"] = models_loaded
    result["ram_mb_total"] = round(get_ram_mb() - ram_before, 1)
    result["vram_mb_total"] = round(get_vram_mb() - vram_before, 1)
    result["peak_vram_mb"] = round(get_peak_vram_mb(), 1)

    if torch.cuda.is_available():
        result["vram_total_gb"] = round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2)
        result["vram_remaining_gb"] = round(
            (torch.cuda.get_device_properties(0).total_memory - torch.cuda.memory_allocated(0)) / 1024**3, 2
        )

    # Cleanup
    del clip_model, florence_model, florence_proc, qwen_gen
    from content_engine.llm.torch_backend import reset_torch_generator
    reset_torch_generator()
    gc.collect()
    reset_cuda()
    return result


# ── Run all benchmarks ──
MODEL_BENCHS = {
    "clip": bench_clip,
    "dinov2": bench_dinov2,
    "florence": bench_florence,
    "blip": bench_blip,
    "yolov8": bench_yolov8,
    "yolov11_face": bench_yolov11_face,
    "qwen": bench_qwen,
}

for name, fn in MODEL_BENCHS.items():
    print(f"\n{'='*60}")
    print(f"Benchmarking {name.upper()}...")
    print(f"{'='*60}")
    try:
        RESULTS["models"][name] = fn()
        r = RESULTS["models"][name]
        print(f"  Device: {r.get('device')}")
        print(f"  Load time: {r.get('load_time_seconds')}s")
        print(f"  Inference latency: {r.get('inference_latency_seconds')}s")
        print(f"  VRAM after load: {r.get('vram_mb_after_load')} MB")
        print(f"  Peak VRAM: {r.get('peak_vram_mb')} MB")
        print(f"  RAM after load: {r.get('ram_mb_after_load')} MB")
    except Exception as e:
        import traceback

        RESULTS["models"][name] = {"error": str(e), "traceback": traceback.format_exc()}
        print(f"  ERROR: {e}")

print(f"\n{'='*60}")
print("Benchmarking SIMULTANEOUS LOAD (CLIP + Florence-2 + Qwen)...")
print(f"{'='*60}")
RESULTS["simultaneous_load"] = bench_simultaneous()
r = RESULTS["simultaneous_load"]
print(f"  Models loaded: {r.get('models_loaded')}")
print(f"  Total VRAM: {r.get('vram_mb_total')} MB")
print(f"  Peak VRAM: {r.get('peak_vram_mb')} MB")
print(f"  Total RAM: {r.get('ram_mb_total')} MB")
if torch.cuda.is_available():
    print(f"  VRAM total: {r.get('vram_total_gb')} GB")
    print(f"  VRAM remaining: {r.get('vram_remaining_gb')} GB")

# Save results
out_path = PROJECT_ROOT / "benchmark_results" / "phase_f_baseline.json"
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(RESULTS, f, indent=2, ensure_ascii=False)

print(f"\nBaseline results saved to: {out_path}")
print("\nBASELINE COMPLETE")
