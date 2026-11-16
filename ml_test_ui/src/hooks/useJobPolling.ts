import { useState, useEffect, useRef, useCallback } from 'react'
import { getJobStatus } from '../api'
import type { JobStatus } from '../api'

/**
 * useJobPolling — centralized, reliable job-status polling.
 *
 * Polls /api/jobs/{jobId}/status until the job reaches a terminal state.
 *
 * Design decisions (addressing the reported false "Generation failed" bug):
 *   - A single transient status-request failure (timeout / network blip) is
 *     NEVER treated as a job failure. It is recorded as a network error and
 *     polling resumes on the next tick.
 *   - Only one status request is in flight at a time; the previous request is
 *     aborted before a new one starts, so a slow/stale response can never
 *     overwrite newer job state.
 *   - Terminal states are recognized explicitly:
 *         completed / SUCCESS -> success  (call onDone)
 *         failed / FAILURE    -> failure  (call onFail)
 *   - Polling stops on unmount and on terminal state (AbortController + flag).
 *   - Callbacks live in refs so the interval never restarts on every render.
 */

export const TERMINAL_SUCCESS = new Set(['completed', 'SUCCESS'])
export const TERMINAL_FAILURE = new Set(['failed', 'FAILURE', 'error'])

export const POLL_INTERVAL_MS = 2500

export function useJobPolling(
  jobId: string | null,
  onDone?: ((s: JobStatus) => void) | null,
  onFail?: ((e: string) => void) | null,
) {
  const [status, setStatus] = useState<JobStatus | null>(null)
  const [networkError, setNetworkError] = useState<string | null>(null)
  const networkErrorRef = useRef<string | null>(null)

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const requestSeqRef = useRef(0) // monotonic; only the latest response wins
  const cancelledRef = useRef(false)

  // Keep a ref to the current network error so the (long-lived) poll closure
  // reads fresh state without restarting the polling effect.
  useEffect(() => {
    networkErrorRef.current = networkError
  }, [networkError])

  // Keep callbacks fresh without re-running the effect
  const onDoneRef = useRef(onDone)
  const onFailRef = useRef(onFail)
  useEffect(() => { onDoneRef.current = onDone }, [onDone])
  useEffect(() => { onFailRef.current = onFail }, [onFail])

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
  }, [])

  const isTerminal = (s: string | undefined): 'success' | 'failure' | null => {
    if (s == null) return null
    if (TERMINAL_SUCCESS.has(s)) return 'success'
    if (TERMINAL_FAILURE.has(s)) return 'failure'
    return null
  }

  const abortCurrent = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
    }
  }, [])

  // Restart polling only when jobId changes
  useEffect(() => {
    cancelledRef.current = false
    stopPolling()
    setStatus(null)
    setNetworkError(null)

    if (!jobId) return

    const poll = async () => {
      if (cancelledRef.current) return

      // Abort any still-in-flight request so we never issue overlapping polls.
      abortCurrent()
      const controller = new AbortController()
      abortRef.current = controller
      const seq = ++requestSeqRef.current

      try {
        const s = await getJobStatus(jobId, { signal: controller.signal })
        abortRef.current = null

        // A stale response must not overwrite newer job state.
        if (cancelledRef.current || seq !== requestSeqRef.current) return

        // A successful poll clears any previously shown network error.
        if (networkErrorRef.current) {
          networkErrorRef.current = null
          setNetworkError(null)
        }
        setStatus(s)

        const terminal = isTerminal(s.status)
        if (terminal === 'success') {
          stopPolling()
          onDoneRef.current?.(s)
        } else if (terminal === 'failure') {
          stopPolling()
          onFailRef.current?.(s.error ?? 'Job failed')
        }
        // Otherwise keep polling.
      } catch (rawErr) {
        abortRef.current = null
        if (cancelledRef.current || seq !== requestSeqRef.current) return

        // Axios wraps an aborted request as CanceledError / ECONNABORTED.
        // That is expected on unmount / job change and must not be reported.
        const err = rawErr as { name?: string; code?: string | number; message?: string }
        const isAborted =
          rawErr instanceof DOMException && rawErr.name === 'AbortError' ||
          err.name === 'CanceledError' ||
          err.code === 'ECONNABORTED' ||
          /canceled|aborted/i.test(String(err.message ?? ''))
        if (isAborted) return

        const msg = err.message ?? String(rawErr)
        // Transient network failure: report it but KEEP polling. A single
        // timed-out status request is not proof that the backend job failed.
        networkErrorRef.current = `Connection interrupted — checking job status again (${msg}).`
        setNetworkError(networkErrorRef.current)
      }
    }

    poll() // immediate first poll
    intervalRef.current = setInterval(poll, POLL_INTERVAL_MS)

    return () => {
      cancelledRef.current = true
      stopPolling()
    }
  }, [jobId, stopPolling, abortCurrent])

  const pct  = status?.progress?.pct  ?? _toPct(status?.status)
  const step = status?.progress?.step ?? _toStep(status?.status)

  return {
    status,
    pct,
    step,
    polling: intervalRef.current != null,
    networkError,
    isTerminal: status ? isTerminal(status.status) : null,
  }
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
  if (s === 'failed'    || s === 'FAILURE' || s === 'error') return 'failed'
  return 'queued'
}
