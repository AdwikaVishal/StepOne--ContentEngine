/**
 * Dataset upload helper tests (Brand Intelligence Phase 2).
 *
 * Verifies the chunk math mirrors the server contract exactly — a mismatch
 * here would break resumable uploads at the final-chunk boundary.
 */
import { describe, expect, it } from 'vitest'
import {
  chunkRange,
  expectedChunkBytes,
  formatBytes,
  isSupportedImageName,
  isZipFile,
  planChunkCount,
  rejectionLabel,
  uploadErrorMessage,
} from './datasetUpload'

const MB = 1024 * 1024

describe('planChunkCount', () => {
  it('requests 4MB-equivalent chunks', () => {
    expect(planChunkCount(1 * MB)).toBe(1)
    expect(planChunkCount(4 * MB)).toBe(1)
    expect(planChunkCount(4 * MB + 1)).toBe(2)
    expect(planChunkCount(10 * MB)).toBe(3)
    expect(planChunkCount(0)).toBe(1)
  })
})

describe('chunkRange / expectedChunkBytes (server parity)', () => {
  it('covers the file exactly with no gaps or overlap', () => {
    const total = 10 * MB + 12345
    const chunks = planChunkCount(total)          // 3
    const chunkSize = Math.ceil(total / chunks)   // server formula

    let covered = 0
    for (let i = 0; i < chunks; i++) {
      const [start, end] = chunkRange(total, chunkSize, i)
      expect(start).toBe(covered)
      expect(end).toBeGreaterThan(start)
      expect(end - start).toBe(
        expectedChunkBytes(total, chunkSize, chunks, i))
      covered = end
    }
    expect(covered).toBe(total)
  })

  it('last chunk carries the remainder (odd sizes)', () => {
    const total = 1000
    const chunks = 3
    const chunkSize = Math.ceil(total / chunks)   // 334
    expect(expectedChunkBytes(total, chunkSize, chunks, 0)).toBe(334)
    expect(expectedChunkBytes(total, chunkSize, chunks, 1)).toBe(334)
    expect(expectedChunkBytes(total, chunkSize, chunks, 2)).toBe(332)
    const [, end] = chunkRange(total, chunkSize, 2)
    expect(end).toBe(total)
  })
})

describe('file type helpers', () => {
  it('detects ZIPs and supported image names', () => {
    expect(isZipFile('photos.ZIP')).toBe(true)
    expect(isZipFile('photo.jpg')).toBe(false)
    expect(isSupportedImageName('a.JPG')).toBe(true)
    expect(isSupportedImageName('a.jpeg')).toBe(true)
    expect(isSupportedImageName('a.webp')).toBe(true)
    expect(isSupportedImageName('a.gif')).toBe(false)
    expect(isSupportedImageName('a.txt')).toBe(false)
  })
})

describe('formatBytes', () => {
  it('formats across units', () => {
    expect(formatBytes(0)).toBe('—')
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(2048)).toBe('2 KB')
    expect(formatBytes(5 * MB)).toBe('5.0 MB')
    expect(formatBytes(2 * 1024 * MB)).toBe('2.00 GB')
  })
})

describe('uploadErrorMessage', () => {
  it('prefers server detail, then message, then fallback', () => {
    expect(uploadErrorMessage(
      { response: { data: { detail: 'Server says no' } } }, 'fb',
    )).toBe('Server says no')
    expect(uploadErrorMessage({ message: 'Network Error' }, 'fb'))
      .toBe('Network Error')
    expect(uploadErrorMessage({}, 'fb')).toBe('fb')
    expect(uploadErrorMessage(undefined, 'fb')).toBe('fb')
  })
})

describe('rejectionLabel', () => {
  it('maps reason codes to readable text', () => {
    expect(rejectionLabel('corrupt')).toContain('corrupt')
    expect(rejectionLabel('unsupported_type')).toContain('supported')
    expect(rejectionLabel('zip_bomb_ratio')).toContain('bomb')
    expect(rejectionLabel(undefined)).toBe('Rejected')
    expect(rejectionLabel('weird_code')).toBe('weird code')
  })
})
