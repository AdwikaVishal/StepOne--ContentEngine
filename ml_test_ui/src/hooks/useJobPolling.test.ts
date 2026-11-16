import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useJobPolling, POLL_INTERVAL_MS } from './useJobPolling'
import { getJobStatus } from '../api'

vi.mock('../api', () => ({
  getJobStatus: vi.fn(),
}))

const mockedGetJobStatus = vi.mocked(getJobStatus)

function jobStatus(status: string, step = 'processing_assets', pct = 50) {
  return {
    job_id: 'job-1',
    status,
    progress: { step, pct },
    backend: 'apscheduler',
    error: null,
  }
}

describe('useJobPolling', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('starts polling immediately, stops on completed and triggers onDone', async () => {
    const onDone = vi.fn()
    const onFail = vi.fn()
    mockedGetJobStatus.mockResolvedValue(jobStatus('completed', 'done', 100))

    const { result, unmount } = renderHook(() => useJobPolling('job-1', onDone, onFail))
    await act(async () => {})

    expect(onDone).toHaveBeenCalledTimes(1)
    expect(onFail).not.toHaveBeenCalled()
    expect(result.current.status?.status).toBe('completed')
    expect(result.current.polling).toBe(false)
    unmount()
  })

  it('stops and reports actual job failure (failed / FAILURE)', async () => {
    const onDone = vi.fn()
    const onFail = vi.fn()
    mockedGetJobStatus.mockResolvedValue(jobStatus('failed', 'failed', 100))

    const { result } = renderHook(() => useJobPolling('job-1', onDone, onFail))
    await act(async () => {})

    expect(onFail).toHaveBeenCalledTimes(1)
    expect(onDone).not.toHaveBeenCalled()
    expect(result.current.status?.status).toBe('failed')
    expect(result.current.polling).toBe(false)
  })

  it('recognizes SUCCESS as success and FAILURE as failure (Celery casing)', async () => {
    const onDone = vi.fn()
    mockedGetJobStatus.mockResolvedValue(jobStatus('SUCCESS', 'done', 100))
    renderHook(() => useJobPolling('job-1', onDone, vi.fn()))
    await act(async () => {})
    expect(onDone).toHaveBeenCalledTimes(1)

    vi.clearAllMocks()
    onDone.mockClear()
    mockedGetJobStatus.mockResolvedValue(jobStatus('FAILURE', 'failed', 100))
    const onFail = vi.fn()
    const { result: r2 } = renderHook(() => useJobPolling('job-2', vi.fn(), onFail))
    await act(async () => {})
    expect(onFail).toHaveBeenCalledTimes(1)
    expect(r2.current.polling).toBe(false)
  })

  it('a transient network error does NOT mark the job failed; polling resumes and completes', async () => {
    vi.useFakeTimers()
    const onDone = vi.fn()
    const onFail = vi.fn()
    mockedGetJobStatus
      .mockImplementationOnce(() => Promise.reject(new Error('timeout of 2500ms exceeded')))
      .mockResolvedValue(jobStatus('completed', 'done', 100))

    const { result } = renderHook(() => useJobPolling('job-1', onDone, onFail))
    await act(async () => {})

    // First (immediate) poll failed with a timeout: must not be treated as job failure.
    expect(onFail).not.toHaveBeenCalled()
    expect(result.current.networkError).toContain('timeout')

    // Advance past the polling interval: the retry must complete the job.
    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS + 50)
    })

    expect(onDone).toHaveBeenCalledTimes(1)
    expect(onFail).not.toHaveBeenCalled()
    expect(result.current.polling).toBe(false)
    expect(result.current.networkError).toBeNull()
    vi.useRealTimers()
  })

  it('stops polling after completion so no overlapping / stale requests occur', async () => {
    vi.useFakeTimers()
    const onDone = vi.fn()
    const statuses = [jobStatus('running', 'ml_selection', 60), jobStatus('completed', 'done', 100)]
    mockedGetJobStatus.mockImplementation(() => Promise.resolve(statuses.shift()!))

    const { result, unmount } = renderHook(() => useJobPolling('job-1', onDone, vi.fn()))
    await act(async () => {}) // immediate poll -> running
    expect(onDone).not.toHaveBeenCalled()
    expect(result.current.polling).toBe(true)
    expect(mockedGetJobStatus).toHaveBeenCalledTimes(1)

    // Advance past the interval -> second poll -> completed -> onDone, polling stops.
    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS + 50)
    })

    expect(onDone).toHaveBeenCalledTimes(1)
    expect(result.current.polling).toBe(false)
    expect(result.current.status?.status).toBe('completed')

    // The status endpoint must not be polled again once complete.
    expect(mockedGetJobStatus).toHaveBeenCalledTimes(2)
    unmount()
    vi.useRealTimers()
  })

  it('returns queued/running state before completion', async () => {
    mockedGetJobStatus.mockResolvedValue(jobStatus('pending', 'queued', 0))
    const { result } = renderHook(() => useJobPolling('job-1', vi.fn(), vi.fn()))
    await act(async () => {})
    expect(result.current.status?.status).toBe('pending')
    expect(result.current.pct).toBe(0)
    expect(result.current.step).toBe('queued')
    expect(result.current.polling).toBe(true)
  })
})
