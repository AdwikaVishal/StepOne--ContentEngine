#!/usr/bin/env python3
"""
Download Qwen/Qwen2.5-1.5B-Instruct - REQUIRES EXPLICIT APPROVAL
Model size: ~1.5GB, RAM needed: ~4GB+, 8GB system available
"""
import sys

print("=" * 60)
print("QWEN2.5-1.5B-INSTRUCT DOWNLOAD")
print("=" * 60)
print("Model: Qwen/Qwen2.5-1.5B-Instruct")
print("Size: ~1.1-1.5 GB")
print("RAM required: ~4GB minimum, 8GB system available")
print("License: Apache 2.0")
print("=" * 60)
print()
print("This script does NOT download automatically.")
print("To download with approval, run:")
print()
print("  python -c \"from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen2.5-1.5B-Instruct')\"")
print()
print("Or use huggingface-cli:")
print("  huggingface-cli download Qwen/Qwen2.5-1.5B-Instruct")
print()
print("=" * 60)
sys.exit(0)
