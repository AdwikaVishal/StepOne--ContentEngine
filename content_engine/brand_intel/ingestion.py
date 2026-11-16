"""
Dataset ingestion primitives (Brand Intelligence, Phase 2).

Two responsibilities, both pure/local, no models, no network:

1. Content-based image validation — the file's actual bytes decide whether it
   is accepted (magic-number sniff + Pillow decode), never the extension or
   the multipart MIME header. Supported dataset formats: JPEG, PNG, WebP.
2. ZIP security — stdlib `zipfile` only. Hostile entries (path traversal,
   absolute paths, drive letters, symlinks) abort the whole archive before a
   single byte is written; zip-bomb limits (file count, per-entry size,
   total uncompressed size, compression ratio) are enforced in a pre-scan;
   entries are flattened to sanitized basenames and extracted only into the
   caller-provided temp directory (which must live inside the dataset dir).

Rejected files carry machine-readable reason codes:
  empty | too_large | unsupported_type | corrupt
ZIP policy violations raise IngestionError with codes:
  zip_traversal | zip_symlink | zip_too_many_files | zip_entry_too_large |
  zip_total_too_large | zip_bomb_ratio | zip_unreadable
"""
import hashlib
import io
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import settings

# ── Supported dataset formats (Phase 2 scope: JPEG / PNG / WebP) ─────────────
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP"}
FORMAT_EXTENSIONS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}

# Refuse absurd pixel counts (decompression-bomb guard on top of Pillow's own
# MAX_IMAGE_PIXELS warning). ~80 MP is larger than any realistic photo here.
MAX_IMAGE_PIXELS = 80_000_000

# ── ZIP security limits ──────────────────────────────────────────────────────
# Documented defaults; tests construct ZipLimits with tighter values.
ZIP_MAX_FILES = 10_000                  # entries per archive
ZIP_MAX_TOTAL_BYTES = 4_000_000_000     # 4 GB total uncompressed
ZIP_MAX_COMPRESSION_RATIO = 100.0       # uncompressed / compressed
ZIP_RATIO_MIN_BYTES = 1_000_000         # ratio only enforced above this size
EXTRACT_CHUNK_BYTES = 1024 * 1024       # streaming copy granularity

# Archives nested inside archives are never extracted (documented policy).
NESTED_ARCHIVE_EXTENSIONS = {
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar",
    ".jar", ".iso", ".cab", ".lz", ".lz4", ".zst",
}

# Characters that are illegal in Windows filenames (entry basenames are
# written to a Windows disk here, so sanitize for the strictest host).
_WINDOWS_ILLEGAL = re.compile(r'[<>:"|?*\x00-\x1f]')


class IngestionError(Exception):
    """Policy/validation failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ZipLimits:
    max_files: int = ZIP_MAX_FILES
    max_total_bytes: int = ZIP_MAX_TOTAL_BYTES
    max_compression_ratio: float = ZIP_MAX_COMPRESSION_RATIO
    ratio_min_bytes: int = ZIP_RATIO_MIN_BYTES
    max_entry_bytes: int = field(
        default_factory=lambda: settings.max_file_size_bytes)


@dataclass
class ZipExtractResult:
    files: List[Tuple[Path, str]]          # (extracted path, original name)
    skipped: List[Dict[str, str]]          # {name, reason}


# ── Image validation ─────────────────────────────────────────────────────────

def sniff_format(header: bytes) -> Optional[str]:
    """Return the format implied by the magic bytes, or None."""
    if header.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "WEBP"
    return None


def _extension_of(filename: str) -> str:
    # Never trust path components — only the final segment's suffix counts.
    name = str(filename or "").replace("\\", "/").split("/")[-1]
    return Path(name).suffix.lower()


def _check_name_and_size(filename: str, size: int) -> None:
    if size <= 0:
        raise IngestionError("empty", "File is empty")
    if size > settings.max_file_size_bytes:
        raise IngestionError(
            "too_large",
            f"File exceeds the {settings.max_file_size_mb}MB per-file limit")
    ext = _extension_of(filename)
    if ext not in SUPPORTED_EXTENSIONS:
        raise IngestionError(
            "unsupported_type",
            f"Unsupported file type '{ext or '(no extension)'}' — "
            "dataset uploads accept .jpg, .jpeg, .png and .webp only")


def _decode_meta(src: Any) -> Tuple[int, int, str]:
    """Verify + decode with Pillow. Returns (width, height, pil_format).

    `src` is a filesystem path (str) or raw bytes; each open uses a fresh
    handle because verify() may close the previous stream.
    """
    from PIL import Image

    def _open():
        if isinstance(src, (bytes, bytearray)):
            return Image.open(io.BytesIO(src))
        return Image.open(src)

    try:
        with _open() as img:
            img.verify()                       # structural integrity check
        with _open() as img:                   # re-open for real metadata
            width, height, fmt = img.width, img.height, (img.format or "")
    except IngestionError:
        raise
    except Exception as exc:                   # corrupt / truncated / bogus
        raise IngestionError("corrupt", f"Image could not be decoded: {exc}")
    if not fmt or fmt not in SUPPORTED_FORMATS:
        raise IngestionError(
            "unsupported_type",
            f"File content is {fmt or 'not a recognized image'}, "
            "not JPEG/PNG/WebP")
    if width * height > MAX_IMAGE_PIXELS:
        raise IngestionError(
            "too_large",
            f"Image dimensions {width}x{height} exceed the pixel limit")
    return width, height, fmt


def validate_image_bytes(data: bytes, filename: str) -> Dict[str, Any]:
    """Validate one in-memory image. Returns metadata or raises IngestionError."""
    _check_name_and_size(filename, len(data))
    header = data[:64]
    if sniff_format(header) is None:
        raise IngestionError(
            "unsupported_type",
            "File content does not match JPEG, PNG or WebP signatures")
    width, height, fmt = _decode_meta(data)
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "width": width,
        "height": height,
        "format": fmt,
        "extension": FORMAT_EXTENSIONS[fmt],   # content decides the extension
    }


def validate_image_file(path: Path, filename: str) -> Dict[str, Any]:
    """Validate an image on disk without loading it whole into memory.

    SHA-256 is streamed; Pillow reads the header/trailer it needs. Peak
    memory is bounded regardless of file size (never the whole batch).
    """
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError:
        raise IngestionError("empty", "File is missing or unreadable")
    _check_name_and_size(filename, size)
    with open(path, "rb") as f:
        header = f.read(64)
    if sniff_format(header) is None:
        raise IngestionError(
            "unsupported_type",
            "File content does not match JPEG, PNG or WebP signatures")
    width, height, fmt = _decode_meta(str(path))
    sha = file_sha256(path)
    return {
        "sha256": sha,
        "bytes": size,
        "width": width,
        "height": height,
        "format": fmt,
        "extension": FORMAT_EXTENSIONS[fmt],
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(EXTRACT_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ── ZIP security ─────────────────────────────────────────────────────────────

def sanitize_entry_name(name: str) -> Optional[str]:
    """Return a safe basename for a ZIP entry, or None when the name is hostile.

    Rejects: empty names, NUL bytes, absolute paths, drive letters, any `..`
    segment (after backslash normalization). Everything else is flattened to
    its final path segment and stripped of characters illegal on Windows —
    the archive's directory structure is never trusted or recreated.
    """
    if not name or "\x00" in name:
        return None
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or normalized.startswith("//"):
        return None
    if re.match(r"^[a-zA-Z]:", normalized):
        return None
    parts = [p for p in normalized.split("/") if p not in ("", ".")]
    if not parts:
        return None
    if any(p == ".." for p in parts):
        return None
    base = _WINDOWS_ILLEGAL.sub("_", parts[-1]).strip(" .")
    if not base or base in (".", ".."):
        return None
    return base


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode == 0o120000  # S_IFLNK


def _prescan(infos: List[zipfile.ZipInfo], limits: ZipLimits) -> None:
    """Reject hostile archives BEFORE extracting anything (all-or-nothing)."""
    file_infos = [i for i in infos if not i.is_dir()]
    if len(file_infos) > limits.max_files:
        raise IngestionError(
            "zip_too_many_files",
            f"Archive contains {len(file_infos)} files "
            f"(limit {limits.max_files})")
    total = 0
    for info in file_infos:
        name = info.filename
        if sanitize_entry_name(name) is None:
            raise IngestionError(
                "zip_traversal",
                f"Archive entry has a hostile path: {name!r}")
        if _is_symlink(info):
            raise IngestionError(
                "zip_symlink",
                f"Archive entry is a symbolic link: {name!r}")
        if info.file_size > limits.max_entry_bytes:
            raise IngestionError(
                "zip_entry_too_large",
                f"Archive entry {name!r} declares "
                f"{info.file_size} bytes (limit {limits.max_entry_bytes})")
        total += info.file_size
        # Zip-bomb ratio: only meaningful for large entries, otherwise a
        # legitimately tiny highly-compressible file would trip it.
        if (info.file_size >= limits.ratio_min_bytes
                and info.compress_size > 0
                and info.file_size / info.compress_size
                > limits.max_compression_ratio):
            raise IngestionError(
                "zip_bomb_ratio",
                f"Archive entry {name!r} compression ratio "
                f"{info.file_size // max(info.compress_size, 1)}:1 "
                f"exceeds {limits.max_compression_ratio}:1")
    if total > limits.max_total_bytes:
        raise IngestionError(
            "zip_total_too_large",
            f"Archive expands to {total} bytes "
            f"(limit {limits.max_total_bytes})")


def extract_zip_safely(
    zip_path: Path,
    dest_dir: Path,
    limits: Optional[ZipLimits] = None,
) -> ZipExtractResult:
    """Extract acceptable image entries from zip_path into dest_dir.

    dest_dir must be a temp directory inside the dataset folder — the caller
    owns confinement. Hostile entries abort the whole archive (nothing
    written); unsupported/nested/corrupt entries are reported as skipped.
    Extraction streams in chunks with a hard byte cap, so a lying header
    cannot overrun the pre-scanned limits.
    """
    limits = limits or ZipLimits()
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    files: List[Tuple[Path, str]] = []
    skipped: List[Dict[str, str]] = []

    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = zf.infolist()
            _prescan(infos, limits)          # security gate, before any write

            used_names: Dict[str, int] = {}
            for info in infos:
                if info.is_dir():
                    continue
                base = sanitize_entry_name(info.filename)
                if base is None:             # unreachable after prescan, but
                    raise IngestionError(     # never rely on that alone
                        "zip_traversal",
                        f"Archive entry has a hostile path: {info.filename!r}")
                ext = Path(base).suffix.lower()
                if ext in NESTED_ARCHIVE_EXTENSIONS:
                    skipped.append(
                        {"name": info.filename, "reason": "nested_archive"})
                    continue
                if ext not in SUPPORTED_EXTENSIONS:
                    skipped.append(
                        {"name": info.filename, "reason": "unsupported_type"})
                    continue
                # Flatten collisions inside the archive deterministically.
                count = used_names.get(base, 0)
                used_names[base] = count + 1
                out_name = base if count == 0 else (
                    f"{Path(base).stem}_{count + 1}{ext}")
                out_path = dest_dir / out_name

                written = 0
                try:
                    with zf.open(info) as src, open(out_path, "wb") as out:
                        while True:
                            chunk = src.read(EXTRACT_CHUNK_BYTES)
                            if not chunk:
                                break
                            written += len(chunk)
                            if written > limits.max_entry_bytes:
                                raise IngestionError(
                                    "zip_entry_too_large",
                                    f"Archive entry {info.filename!r} "
                                    "exceeded the size limit while extracting")
                            out.write(chunk)
                except IngestionError:
                    out_path.unlink(missing_ok=True)
                    raise
                except Exception as exc:
                    out_path.unlink(missing_ok=True)
                    skipped.append(
                        {"name": info.filename,
                         "reason": "corrupt",
                         "detail": str(exc)})
                    continue
                files.append((out_path, base))
    except zipfile.BadZipFile as exc:
        raise IngestionError("zip_unreadable", f"Not a readable ZIP: {exc}")

    return ZipExtractResult(files=files, skipped=skipped)


def cleanup_dir(path: Path) -> None:
    """Remove a temp extraction/staging directory (never outside a dataset)."""
    shutil.rmtree(path, ignore_errors=True)
