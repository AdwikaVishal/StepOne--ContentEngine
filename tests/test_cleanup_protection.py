"""
Cleanup protection tests (Brand Intelligence requirement F).

output/brand_intelligence/ (datasets) plus the existing persistent user data
under output/studio/brand_profiles and output/studio/brand_assets must never
be deleted by the scheduled cleanup, regardless of file age. Everything else
in output/ keeps the normal 30-day retention, and dry-run still deletes
nothing.
"""
import os
import time
from pathlib import Path

import pytest

import cleanup
from config import settings


def _age_file(path: Path, days: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"old-data")
    stamp = time.time() - days * 86400
    os.utime(path, (stamp, stamp))


@pytest.fixture()
def fake_dirs(tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    output_dir = tmp_path / "output"
    upload_dir.mkdir()
    output_dir.mkdir()
    monkeypatch.setattr(settings, "upload_dir", upload_dir)
    monkeypatch.setattr(settings, "output_dir", output_dir)
    return upload_dir, output_dir


def test_protected_output_subtrees_survive_cleanup(fake_dirs):
    upload_dir, output_dir = fake_dirs

    # Old files everywhere.
    _age_file(output_dir / "brand_intelligence" / "datasets" / "ds1" / "images" / "a.jpg", 90)
    _age_file(output_dir / "brand_intelligence" / "datasets" / "ds1" / "predictions.jsonl", 90)
    _age_file(output_dir / "brand_intelligence" / "images" / "ab" / "abcdef.jpg", 90)
    _age_file(output_dir / "studio" / "brand_profiles" / "abc.json", 90)
    _age_file(output_dir / "studio" / "brand_assets" / "abc" / "logo.png", 90)
    # Old file OUTSIDE protected subtrees — must be deleted.
    _age_file(output_dir / "some_event" / "render.png", 90)
    _age_file(output_dir / "brand_intelligence_old_backup.json", 90)  # not inside protected dir
    # Fresh file outside protected subtrees — must survive.
    fresh = output_dir / "recent" / "new.png"
    _age_file(fresh, 1)

    result = cleanup.run_cleanup(upload_days=0, output_days=30, dry_run=False)

    # Protected: all five old files still present.
    assert (output_dir / "brand_intelligence" / "datasets" / "ds1" / "images" / "a.jpg").exists()
    assert (output_dir / "brand_intelligence" / "datasets" / "ds1" / "predictions.jsonl").exists()
    assert (output_dir / "brand_intelligence" / "images" / "ab" / "abcdef.jpg").exists()
    assert (output_dir / "studio" / "brand_profiles" / "abc.json").exists()
    assert (output_dir / "studio" / "brand_assets" / "abc" / "logo.png").exists()
    # Unprotected old file removed, fresh file kept.
    assert not (output_dir / "some_event" / "render.png").exists()
    assert not (output_dir / "brand_intelligence_old_backup.json").exists()
    assert fresh.exists()
    assert result["outputs"]["skipped_protected"] >= 5
    assert result["outputs"]["errors"] == 0


def test_protected_subtree_empty_dirs_not_removed(fake_dirs):
    _, output_dir = fake_dirs
    # An empty (but protected) directory must not be pruned even when ancient.
    protected_empty = output_dir / "brand_intelligence" / "datasets" / "empty_ds"
    protected_empty.mkdir(parents=True)
    old = time.time() - 90 * 86400
    os.utime(protected_empty, (old, old))
    os.utime(protected_empty.parent, (old, old))

    cleanup.run_cleanup(upload_days=0, output_days=0, dry_run=False)
    assert protected_empty.exists()
    assert protected_empty.parent.exists()


def test_dry_run_deletes_nothing(fake_dirs):
    _, output_dir = fake_dirs
    victim = output_dir / "old" / "thing.png"
    _age_file(victim, 90)

    result = cleanup.run_cleanup(upload_days=0, output_days=0, dry_run=True)
    assert victim.exists()
    # Dry run never deletes, but (existing behaviour) reports would-delete
    # counts so operators can preview the sweep.
    assert result["outputs"]["deleted"] == 1
    assert result["uploads"]["deleted"] == 0


def test_upload_retention_unchanged(fake_dirs):
    upload_dir, _ = fake_dirs
    old_upload = upload_dir / "photo.jpg"
    fresh_upload = upload_dir / "fresh.jpg"
    _age_file(old_upload, 30)
    _age_file(fresh_upload, 1)

    cleanup.run_cleanup(upload_days=7, output_days=30, dry_run=False)
    assert not old_upload.exists()
    assert fresh_upload.exists()


def test_protected_prefix_match_is_exact(fake_dirs):
    """A sibling directory whose name merely starts with a protected name is
    NOT protected (e.g. brand_intelligence_backup)."""
    assert cleanup._is_protected("brand_intelligence", cleanup.PROTECTED_OUTPUT_PATHS)
    assert cleanup._is_protected("brand_intelligence/datasets/x", cleanup.PROTECTED_OUTPUT_PATHS)
    assert cleanup._is_protected("brand_intelligence/images/ab/sha.jpg", cleanup.PROTECTED_OUTPUT_PATHS)
    assert cleanup._is_protected("studio/brand_profiles/a.json", cleanup.PROTECTED_OUTPUT_PATHS)
    assert not cleanup._is_protected("brand_intelligence_backup/x", cleanup.PROTECTED_OUTPUT_PATHS)
    assert not cleanup._is_protected("studio/other/file.json", cleanup.PROTECTED_OUTPUT_PATHS)
