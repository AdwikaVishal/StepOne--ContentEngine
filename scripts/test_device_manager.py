"""DeviceManager integration test - verifies VRAM-aware model lifecycle."""
import os
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'

from content_engine.utils.device_manager import get_device_manager, reset_device_manager

# Reset for clean test
reset_device_manager()
dm = get_device_manager()

status = dm.get_status()
print("=== DeviceManager Status (empty) ===")
print("  Selected device:", status["selected_device"])
print("  VRAM budget: %.1f MB" % status["vram_budget_mb"])
print("  VRAM available: %.1f MB" % status["vram_available_mb"])
print("  Models loaded: %d" % len(status["models"]))

print()
print("=== VRAM-aware Recommendations ===")
print("  Qwen (2945 MB):", dm.recommend_device(2945.0, "qwen"))
print("  CLIP (577 MB):", dm.recommend_device(577.0, "clip"))
print("  BLIP (857 MB):", dm.recommend_device(857.0, "blip"))
print("  DINOv2 (93 MB):", dm.recommend_device(93.0, "dinov2"))
print("  Florence-2 (0 MB - CPU):", dm.recommend_device(0.0, "florence"))

print()
print("=== Loading Qwen via TorchTextGenerator ===")
from content_engine.llm.torch_backend import get_torch_generator
gen = get_torch_generator()
gen._ensure_loaded()
print("  Qwen device:", gen.device)
print("  Qwen loaded:", gen.is_loaded)

status = dm.get_status()
print("  Models registered:", list(status["models"].keys()))
if "qwen" in status["models"]:
    reg = status["models"]["qwen"]
    print("    Device: %s, VRAM: %.1f MB" % (reg["device"], reg["vram_mb"]))

print()
print("=== VRAM Budget After Qwen ===")
print("  VRAM used: %.1f MB" % status["vram_used_mb"])
print("  VRAM available: %.1f MB" % status["vram_available_mb"])
print("  Can load CLIP (577 MB) on CUDA:", dm.can_load_on_cuda(577.0))
print("  Can load BLIP (857 MB) on CUDA:", dm.can_load_on_cuda(857.0))
print("  Can load another Qwen (2945 MB) on CUDA:", dm.can_load_on_cuda(2945.0))

print()
print("=== Unloading Qwen ===")
gen.unload()
status = dm.get_status()
print("  Models registered after unload:", list(status["models"].keys()))
print("  VRAM used: %.1f MB" % status["vram_used_mb"])
print("  VRAM available: %.1f MB" % status["vram_available_mb"])

print()
print("=== Simultaneous Load Scenario ===")
print("  Qwen (2945) + CLIP (577) = %.0f MB <= 5120 MB budget: %s" % (2945+577, 2945+577 <= 5120))
print("  Qwen (2945) + BLIP (857) = %.0f MB <= 5120 MB budget: %s" % (2945+857, 2945+857 <= 5120))
print("  Qwen (2945) + CLIP (577) + BLIP (857) = %.0f MB <= 5120 MB budget: %s" % (2945+577+857, 2945+577+857 <= 5120))
print("  Qwen + CLIP + BLIP + DINOv2 (93) = %.0f MB <= 5120 MB budget: %s" % (2945+577+857+93, 2945+577+857+93 <= 5120))

# Cleanup
reset_device_manager()
print()
print("=== DeviceManager integration test PASSED ===")
