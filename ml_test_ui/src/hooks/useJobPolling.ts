import { useState, useEffect, useRef, useCallback } from 'react'
import { getJobStatus } from '../api'
import type { JobStatus } from '../api'

/**
 * Polls /api/jobs/{jobId}/status every 2 seconds until terminal state.
 *
 * Callbacks are stored in refs to prevent dependency array churn
 * (avoids ERR_INSUFFICIENT_RESOURCES from restarting interval on every render).
 */
export function useJobPolling(
  jobId: string | null,
  onDone?: ((s: JobStatus) => void) | null,
  onFail?: ((e: string) => void) | null,
) {
  const [status, setStatus] = useState<JobStatus | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Store callbacks in refs — never stale, never trigger re-renders
  const onDoneRef = useRef(onDone)
  const onFailRef = useRef(onFail)
  useEffect(() => { onDoneRef.current = onDone }, [onDone])
  useEffect(() => { onFailRef.current = onFail }, [onFail])

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
  }, [])

  // Restart interval only when jobId changes
  useEffect(() => {
    if (!jobId) {
      stopPolling()
      setStatus(null)
      return
    }

    let cancelled = false
    let retries = 0
    const MAX_RETRIES = 150 // 150 * 2s = 300s = 5 minutes

    const poll = async () => {
      if (cancelled) return
      retries += 1

      if (retries > MAX_RETRIES) {
        stopPolling()
        onFailRef.current?.('Job timed out. Please try again.')
        return
      }

      try {
        const s = await getJobStatus(jobId)
        if (cancelled) return
        setStatus(s)

        if (['completed', 'SUCCESS'].includes(s.status)) {
          stopPolling()
          onDoneRef.current?.(s)
        } else if (['failed', 'FAILURE'].includes(s.status)) {
          stopPolling()
          onFailRef.current?.(s.error ?? 'Job failed')
        }
      } catch (err) {
        // Surface network errors meaningfully instead of silently swallowing
        const msg = err instanceof Error ? err.message : String(err)
        if (cancelled) return
        stopPolling()
        onFailRef.current?.(`Network error: ${msg}`)
      }
    }

    poll() // immediate first poll
    intervalRef.current = setInterval(poll, 2000)

    return () => {
      cancelled = true
      stopPolling()
    }
  }, [jobId, stopPolling])


  const pct  = status?.progress?.pct  ?? _toPct(status?.status)
  const step = status?.progress?.step ?? _toStep(status?.status)

  return { status, polling: !!intervalRef.current, pct, step }
}

function _toPct(s?: string) {
  if (s === 'completed' || s === 'SUCCESS')  return 100
  if (s === 'PROGRESS')                      return 60
  if (s === 'running'  || s === 'STARTED')   return 30
  return 5
}

function _toStep(s?: string) {
  if (s === 'completed' || s === 'SUCCESS') return 'done'
  if (s === 'PROGRESS' || s === 'running' || s === 'STARTED') return 'processing_assets'
  if (s === 'failed'    || s === 'FAILURE') return 'failed'
  return 'queued'
}