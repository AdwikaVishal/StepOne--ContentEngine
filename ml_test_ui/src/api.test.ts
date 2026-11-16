import { describe, it, expect, vi, beforeEach } from 'vitest'

// Expose the mock axios instance so tests can control it after import.
vi.mock('axios', () => {
  const get = vi.fn()
  const post = vi.fn()
  ;(globalThis as any).__testAxiosMock__ = { get, post }
  return {
    default: {
      create: vi.fn(() => ({
        get,
        post,
      })),
    },
  }
})

function mockAxios() {
  return (globalThis as any).__testAxiosMock__ as { get: ReturnType<typeof vi.fn>; post: ReturnType<typeof vi.fn> }
}

import { checkHealth, generateAsync, getJobStatus, getJobResult, TIMEOUT } from './api'

describe('api.ts — per-request timeouts and async submission', () => {
  beforeEach(() => {
    const m = mockAxios()
    m.get.mockClear()
    m.post.mockClear()
  })

  it('generateAsync uploads and returns a job_id without waiting for generation', async () => {
    const m = mockAxios()
    m.post.mockResolvedValueOnce({
      data: { job_id: 'abc-123', status: 'pending', backend: 'apscheduler' },
    })
    const file = new File(['fake-bytes'], 'photo.jpg', { type: 'image/jpeg' })
    const res = await generateAsync([file], 'Summer Event', 'A summer event')

    expect(res).toEqual({ job_id: 'abc-123', status: 'pending', backend: 'apscheduler' })
    expect(m.post).toHaveBeenCalledTimes(1)
    expect(m.post).toHaveBeenCalledWith(
      '/api/generate/async',
      expect.any(FormData),
      { timeout: TIMEOUT.submit }
    )
  })

  it('uses a short timeout for health and status polling', async () => {
    const m = mockAxios()
    m.get.mockResolvedValueOnce({ data: { status: 'ok' } })
    await checkHealth()
    expect(m.get).toHaveBeenCalledWith('/health', { timeout: TIMEOUT.health })

    m.get.mockResolvedValueOnce({ data: { job_id: 'j', status: 'completed' } })
    await getJobStatus('j')
    expect(m.get).toHaveBeenCalledWith('/api/jobs/j/status', { timeout: TIMEOUT.status })
  })

  it('uses a bounded timeout for result retrieval', async () => {
    const m = mockAxios()
    m.get.mockResolvedValueOnce({ data: { status: 'completed', event: 'E', files: {} } })
    await getJobResult('j')
    expect(m.get).toHaveBeenCalledWith('/api/jobs/j/result', { timeout: TIMEOUT.result })
  })

  it('does not use an unlimited global timeout for any endpoint', () => {
    expect(TIMEOUT.health).toBe(15_000)
    expect(TIMEOUT.submit).toBe(120_000)
    expect(TIMEOUT.status).toBe(15_000)
    expect(TIMEOUT.result).toBe(60_000)
    expect(TIMEOUT.submit).toBeLessThan(300_000)
  })
})
