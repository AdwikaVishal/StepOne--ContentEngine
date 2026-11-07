#!/usr/bin/env python3
"""Download Qwen/Qwen2.5-1.5B-Instruct with explicit approval"""
from huggingface_hub import snapshot_download
import os, sys

print("Downloading Qwen/Qwen2.5-1.5B-Instruct...")
print("This may take several minutes...")
try:
    path = snapshot_download(repo_id="Qwen/Qwen2.5-1.5B-Instruct", local_files_only=False)
    print(f"DOWNLOADED_TO: {path}")
    # Calculate size
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            total += os.path.getsize(fp)
    print(f"SIZE_BYTES: {total}")
    print(f"SIZE_GB: {total/1024**3:.2f}")
    sys.exit(0)
except Exception as e:
    print(f"ERROR: {e}", file=sys.stderr)
    sys.exit(1)
