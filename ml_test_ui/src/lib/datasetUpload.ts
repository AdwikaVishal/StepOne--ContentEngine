/**
 * Dataset upload helpers (Brand Intelligence Phase 2).
 *
 * Pure functions only — chunk planning mirrors the server contract in
 * content_engine/brand_intel/dataset_store.py:
 *   total_chunks = ceil(total_bytes / requested_chunk_bytes)   (client asks)
 *   chunk_size   = ceil(total_bytes / total_chunks)            (server decides)
 *   chunk i      = [i * chunk_size, min((i+1) * chunk_size, total))
 * The client MUST slice with the server-returned chunk_size, never with its
 * own request value, or the final chunk size will not match.
 *
 * The browser only ever holds File references and slices one chunk at a
 * time — a whole dataset is never loaded into memory.
 */

/** Files at or below this size ride the plain batch endpoint. */
export const DATASET_BATCH_SIZE = 10
/** Client-side threshold: larger files use the chunked/resumable protocol. */
export const DATASET_CHUNK_BYTES = 4 * 1024 * 1024
/** How many times a single chunk is retried before the item is marked failed. */
export const CHUNK_RETRY_ATTEMPTS = 3

/** Number of chunks to request for a file of `totalBytes`. */
export function planChunkCount(
  totalBytes: number,
  chunkBytes: number = DATASET_CHUNK_BYTES,
): number {
  if (totalBytes <= 0) return 1
  return Math.max(1, Math.ceil(totalBytes / chunkBytes))
}

/** Byte range [start, end) of chunk `index` for a server-chosen chunk size. */
export function chunkRange(
  totalBytes: number,
  chunkSize: number,
  index: number,
): [number, number] {
  const start = index * chunkSize
  const end = Math.min(start + chunkSize, totalBytes)
  return [start, end]
}

/** Expected byte length of chunk `index` (server-side parity check). */
export function expectedChunkBytes(
  totalBytes: number,
  chunkSize: number,
  totalChunks: number,
  index: number,
): number {
  if (index < totalChunks - 1) return chunkSize
  return totalBytes - chunkSize * (totalChunks - 1)
}

export function isZipFile(name: string): boolean {
  return name.toLowerCase().endsWith('.zip')
}

export function isSupportedImageName(name: string): boolean {
  return /\.(jpe?g|png|webp)$/i.test(name)
}

export function formatBytes(bytes: number): string {
  if (!bytes || bytes < 0) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

/** Extract a human-readable message from an axios/unknown error. */
export function uploadErrorMessage(e: unknown, fallback: string): string {
  const err = e as {
    response?: { data?: { detail?: unknown } }
    message?: unknown
  }
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (typeof err?.message === 'string' && err.message) return err.message
  return fallback
}

/** Map a server rejection reason code to display text. */
export function rejectionLabel(reason: string | undefined): string {
  switch (reason) {
    case 'empty': return 'File is empty'
    case 'too_large': return 'Exceeds the size limit'
    case 'unsupported_type': return 'Not a supported image (JPEG/PNG/WebP)'
    case 'corrupt': return 'Image data is corrupt or unreadable'
    case 'zip_traversal': return 'ZIP contains unsafe paths'
    case 'zip_symlink': return 'ZIP contains symbolic links'
    case 'zip_too_many_files': return 'ZIP has too many files'
    case 'zip_entry_too_large': return 'ZIP entry is too large'
    case 'zip_total_too_large': return 'ZIP expands beyond the total limit'
    case 'zip_bomb_ratio': return 'ZIP compression ratio looks like a bomb'
    case 'zip_unreadable': return 'ZIP could not be read'
    case 'nested_archive': return 'Nested archives are not extracted'
    case 'corrupt_zip_entry': return 'ZIP entry is corrupt'
    default: return reason ? reason.replace(/_/g, ' ') : 'Rejected'
  }
}
