/**
 * JobStatus — shows live progress for an async job.
 * Displays a progress bar, current step, and backend indicator.
 */
import { CheckCircle, XCircle, Loader, RefreshCw, Zap } from 'lucide-react'
import { useJobPolling } from '../hooks/useJobPolling'
import type { JobStatus as JobStatusType } from '../api'

interface Props {
  jobId: string
  onComplete: (status: JobStatusType) => void
  onError?: (msg: string) => void
}

const STEP_LABELS: Record<string, string> = {
  queued:            'Queued — waiting for worker',
  loading_models:    'Loading ML models…',
  processing_assets: 'Scoring assets…',
  ml_selection:      'Running ML selection…',
  layout_assembly:   'Assembling layouts…',
  copy_generation:   'Generating captions…',
  case_study:        'Writing case study…',
  serialising:       'Finalising results…',
  finalising:        'Finalising…',
  done:              'Complete',
}

export default function JobStatus({ jobId, onComplete, onError }: Props) {
  const { status, pct, step } = useJobPolling(jobId, onComplete, onError)

  const label  = STEP_LABELS[step] ?? step ?? 'Processing…'
  const failed = status?.status === 'failed' || status?.status === 'FAILURE'
  const done   = status?.status === 'completed' || status?.status === 'SUCCESS'

  return (
    <div style={{
      background: 'var(--s1)',
      border: `1px solid ${failed ? 'var(--red)' : done ? 'var(--green)' : 'var(--b1)'}`,
      borderRadius: 'var(--r)',
      padding: '18px 20px',
    }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
        {failed
          ? <XCircle size={18} color="var(--red)" />
          : done
          ? <CheckCircle size={18} color="var(--green)" />
          : <Loader size={18} color="var(--accent)" style={{ animation: 'spin 1s linear infinite' }} />
        }
        <span style={{ fontWeight: 600, fontSize: 14, color: failed ? 'var(--red)' : done ? 'var(--green)' : 'var(--t1)' }}>
          {failed ? 'Job failed' : done ? 'Complete' : label}
        </span>
        {status?.backend && (
          <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--t3)', background: 'var(--s2)', borderRadius: 5, padding: '2px 8px', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            {status.backend === 'celery' ? <Zap size={11} /> : <RefreshCw size={11} />}
            {status.backend === 'celery' ? 'Celery' : 'In-process'}
          </span>
        )}
      </div>

      {/* Progress bar */}
      <div style={{ height: 6, background: 'var(--s3)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{
          height: '100%',
          width: `${pct}%`,
          background: failed ? 'var(--red)' : done ? 'var(--green)' : 'var(--accent)',
          borderRadius: 3,
          transition: 'width 0.4s ease',
        }} />
      </div>

      {/* Percentage + step */}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, fontSize: 11, color: 'var(--t3)' }}>
        <span>{label}</span>
        <span>{pct}%</span>
      </div>

      {/* Error message */}
      {status?.error && (
        <p style={{ marginTop: 10, fontSize: 12, color: 'var(--red)', background: 'rgba(239,68,68,.08)', borderRadius: 6, padding: '8px 12px' }}>
          {status.error}
        </p>
      )}

      {/* Job ID */}
      <p style={{ marginTop: 8, fontSize: 10, color: 'var(--t3)', fontFamily: 'monospace' }}>
        job: {jobId}
      </p>
    </div>
  )
}
