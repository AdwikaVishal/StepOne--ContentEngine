"""
cleanup.py — Delete old uploads and outputs.

Can be run three ways:
  1. CLI:          python cleanup.py [--dry-run] [--upload-days N] [--output-days N]
  2. APScheduler:  Scheduled automatically at 03:00 UTC by api/main.py startup
  3. Celery Beat:  Register tasks in api/beat_schedule.py and run:
                   celery -A api.worker beat --loglevel=info

Usage:
    python cleanup.py                    # use defaults from .env
    python cleanup.py --dry-run          # preview without deleting
    python cleanup.py --upload-days 3    # override retention
    python cleanup.py --output-days 7
"""

import argparse
import time
from pathlib import Path
from datetime import datetime

from config import settings
from api.logger import get_logger

logger = get_logger("cleanup")


def _age_days(path: Path) -> float:
    """Return file/directory age in days based on mtime."""
    return (time.time() - path.stat().st_mtime) / 86400


def clean_directory(
    directory: Path,
    max_age_days: int,
    dry_run: bool = False,
    label: str = "",
) -> dict:
    """
    Delete files (and empty directories) older than max_age_days.

    Args:
        directory:    Root directory to clean.
        max_age_days: Files older than this are deleted.
        dry_run:      If True, log what would be deleted without deleting.
        label:        Human-readable label for log messages.

    Returns:
        Summary dict: {deleted, freed_bytes, errors}
    """
    if not directory.exists():
        return {"deleted": 0, "freed_bytes": 0, "errors": 0}

    deleted = 0
    freed   = 0
    errors  = 0

    for path in sorted(directory.rglob("*"), reverse=True):  # deepest first
        try:
            age = _age_days(path)
            if age <= max_age_days:
                continue

            if path.is_file():
                size = path.stat().st_size
                if dry_run:
                    logger.info(
                        "dry_run_would_delete",
                        path=f"{label}/{path.name}",
                        age_days=round(age, 1),
                        size_kb=size // 1024,
                    )
                else:
                    path.unlink()
                    logger.info(
                        "deleted_file",
                        path=f"{label}/{path.name}",
                        age_days=round(age, 1),
                        size_kb=size // 1024,
                    )
                deleted += 1
                freed   += size

            elif path.is_dir() and not any(path.iterdir()):
                # Remove empty directories
                if not dry_run:
                    path.rmdir()
                    logger.info("deleted_empty_dir", path=f"{label}/{path.name}")

        except Exception as e:
            logger.error("cleanup_error", path=str(path), error=str(e))
            errors += 1

    return {"deleted": deleted, "freed_bytes": freed, "errors": errors}


def run_cleanup(
    upload_days: int,
    output_days: int,
    dry_run: bool = False,
) -> dict:
    """
    Run cleanup on both uploads and output directories.

    Returns:
        Summary dict with per-directory stats.
    """
    start = datetime.utcnow().isoformat()
    logger.info(
        "cleanup_started",
        dry_run=dry_run,
        upload_days=upload_days,
        output_days=output_days,
        timestamp=start,
    )

    upload_result = clean_directory(
        settings.upload_dir, upload_days, dry_run, label="uploads"
    )
    output_result = clean_directory(
        settings.output_dir, output_days, dry_run, label="output"
    )

    total_freed_mb = (upload_result["freed_bytes"] + output_result["freed_bytes"]) / (1024 * 1024)

    logger.info(
        "cleanup_complete",
        uploads_deleted=upload_result["deleted"],
        outputs_deleted=output_result["deleted"],
        freed_mb=round(total_freed_mb, 2),
        errors=upload_result["errors"] + output_result["errors"],
    )

    return {
        "uploads": upload_result,
        "outputs": output_result,
        "freed_mb": round(total_freed_mb, 2),
        "timestamp": start,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clean up old uploads and outputs")
    parser.add_argument(
        "--upload-days", type=int, default=settings.upload_retention_days,
        help=f"Delete uploads older than N days (default: {settings.upload_retention_days})"
    )
    parser.add_argument(
        "--output-days", type=int, default=settings.output_retention_days,
        help=f"Delete outputs older than N days (default: {settings.output_retention_days})"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview what would be deleted without actually deleting"
    )
    args = parser.parse_args()

    result = run_cleanup(
        upload_days=args.upload_days,
        output_days=args.output_days,
        dry_run=args.dry_run,
    )

    print(f"\nCleanup {'(DRY RUN) ' if args.dry_run else ''}complete:")
    print(f"  Uploads deleted: {result['uploads']['deleted']}")
    print(f"  Outputs deleted: {result['outputs']['deleted']}")
    print(f"  Space freed:     {result['freed_mb']:.1f} MB")
    if result['uploads']['errors'] + result['outputs']['errors']:
        print(f"  Errors:          {result['uploads']['errors'] + result['outputs']['errors']}")
