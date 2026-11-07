import { createContext, useContext, useState, useEffect, useCallback, useRef, type ReactNode } from 'react'
import type { JobStatus } from '../api'

interface JobState {
  jobId: string | null
  status: JobStatus | null
  progress: number
  step: string
  error: string | null
  isConnected: boolean
}

interface JobContextType {
  job: JobState
  startJob: (jobId: string) => void
  cancelJob: () => void
  retryJob: () => void
}

const defaultJob: JobState = {
  jobId: null,
  status: null,
  progress: 0,
  step: '',
  error: null,
  isConnected: false,
}

const JobContext = createContext<JobContextType | undefined>(undefined)

export function JobProvider({ children }: { children: ReactNode }) {
  const [job, setJob] = useState<JobState>(defaultJob)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const reconnectAttemptsRef = useRef(0)
  const jobIdRef = useRef<string | null>(null)
  const MAX_RECONNECT_ATTEMPTS = 10
  const BASE_RECONNECT_DELAY = 1000 // ms

  const connectJobWS = useCallback((jobId: string) => {
    // Close existing connection
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }

    // Use relative WS URL — works with Vite proxy
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.hostname
    const port = import.meta.env.DEV ? '8000' : window.location.port
    const url = `${protocol}//${host}:${port}/ws/jobs/${jobId}`

    try {
      const socket = new WebSocket(url)

      socket.onopen = () => {
        reconnectAttemptsRef.current = 0
        setJob(prev => ({ ...prev, isConnected: true, error: null }))
      }

      socket.onmessage = (event) => {
        try {
          const data: JobStatus & { progress?: number; step?: string } = JSON.parse(event.data)
          setJob(prev => ({
            ...prev,
            status: data,
            progress: typeof data.progress === 'number' ? data.progress : (data.progress as any)?.pct ?? prev.progress,
            step: (data.progress as any)?.step ?? prev.step,
            error: data.error ?? null,
          }))
        } catch {}
      }

      socket.onclose = () => {
        setJob(prev => ({ ...prev, isConnected: false }))
        wsRef.current = null

        // Only auto-reconnect if we have an active jobId and haven't exceeded max attempts
        if (jobIdRef.current && reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
          reconnectAttemptsRef.current += 1
          const delay = Math.min(BASE_RECONNECT_DELAY * Math.pow(2, reconnectAttemptsRef.current - 1), 30000)
          reconnectTimeoutRef.current = setTimeout(() => {
            if (jobIdRef.current) {
              connectJobWS(jobIdRef.current)
            }
          }, delay)
        }
      }

      socket.onerror = () => {
        setJob(prev => ({ ...prev, isConnected: false, error: 'WebSocket connection failed — using polling fallback' }))
        wsRef.current = null
      }

      wsRef.current = socket
    } catch {
      // WebSocket not available — polling hook handles it
    }
  }, [])

  const startJob = useCallback((jobId: string) => {
    reconnectAttemptsRef.current = 0
    setJob({ jobId, status: null, progress: 0, step: '', error: null, isConnected: false })
    jobIdRef.current = jobId
    connectJobWS(jobId)
  }, [connectJobWS])

  const cancelJob = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    jobIdRef.current = null
    reconnectAttemptsRef.current = 0
    setJob(defaultJob)
  }, [])

  const retryJob = useCallback(() => {
    if (job.jobId) startJob(job.jobId)
  }, [job.jobId, startJob])

  useEffect(() => {
    return () => {
      if (wsRef.current) wsRef.current.close()
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
        reconnectTimeoutRef.current = null
      }
      jobIdRef.current = null
      reconnectAttemptsRef.current = 0
    }
  }, [])

  return (
    <JobContext.Provider value={{ job, startJob, cancelJob, retryJob }}>
      {children}
    </JobContext.Provider>
  )
}

export function useJob() {
  const context = useContext(JobContext)
  if (!context) throw new Error('useJob must be used within JobProvider')
  return context
}