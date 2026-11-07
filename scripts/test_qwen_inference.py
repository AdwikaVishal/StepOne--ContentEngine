#!/usr/bin/env python3
import os, sys, time, tracemalloc
os.environ['PYTHONPATH'] = '/Users/admin/Downloads/contentfinal5 copy 2'

from content_engine.captioning.providers.local_provider import LocalLLMProvider
from content_engine.captioning.schema import CaptionGenerationContext
from content_engine.copy_generator import CopyGenerator
from content_engine.data_types import AssetMetadata

# Check model
provider = LocalLLMProvider()
print(f"PROVIDER: {provider.get_name()}")
print(f"MODEL: {provider.model_name}")
print(f"PATH: {provider.model_path}")
print(f"AVAILABLE: {provider.is_available()}")

if not provider.is_available() and not os.path.isdir(provider.model_path or ''):
    print("ERROR: Model not available")
    sys.exit(1)

# Test via provider directly
ctx = CaptionGenerationContext(
    event_name="TechSpark Innovation Summit 2026",
    event_description="Annual startup showcase featuring AI and robotics demonstrations",
    brand="TechSpark",
    platform="linkedin",
    detected_concepts=["innovation", "startup", "technology", "networking"]
)

print("\nLoading model...")
tracemalloc.start()
start = time.time()
try:
    cap = provider.generate_linkedin(ctx)
    elapsed = time.time() - start
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"ELAPSED: {elapsed:.2f}s")
    print(f"PEAK_MEMORY_MB: {peak/1024/1024:.1f}")
    print(f"CAPTION: {cap}")
    print("\nSUCCESS: Real inference completed")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
