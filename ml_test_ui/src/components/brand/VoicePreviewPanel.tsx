/**
 * VoicePreviewPanel — generates a sample paragraph from the CURRENT (unsaved)
 * form values via POST /api/studio/brand-profiles/voice-preview, which runs
 * the local Qwen2.5-1.5B-Instruct model only. Nothing is persisted.
 */
import { useState } from 'react'
import { AlertTriangle, Play, RefreshCw, Sparkles } from 'lucide-react'
import { Card, Spinner } from '../ui'
import { toast } from '../ui/Toast'
import { previewBrandVoice } from '../../api'
import type { BrandProfile } from '../../lib/brandProfile'

type PreviewState = 'idle' | 'loading' | 'done' | 'error'

const errMsg = (e: any, fallback: string) => {
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (typeof e?.message === 'string' && e.message) return e.message
  return fallback
}

export function VoicePreviewPanel({ profile }: { profile: BrandProfile }) {
  const [state, setState] = useState<PreviewState>('idle')
  const [sample, setSample] = useState('')
  const [error, setError] = useState('')
  const [meta, setMeta] = useState<{ model?: string; duration_s?: number }>({})

  const generate = async () => {
    setState('loading')
    setError('')
    try {
      // Send the unsaved form values exactly as configured.
      const res = await previewBrandVoice({ ...profile })
      if (!res?.sample) throw new Error('Empty sample returned')
      setSample(res.sample)
      setMeta({ model: res.model, duration_s: res.duration_s })
      setState('done')
    } catch (e: any) {
      const message = errMsg(e, 'The local Qwen model could not generate a preview.')
      setError(message)
      setState('error')
      toast.error('Voice preview failed', message)
    }
  }

  return (
    <Card style={{ padding: 22 }} className="bp-preview-card">
      <div className="bp-preview-head">
        <div className="bp-preview-title">
          <Sparkles size={15} aria-hidden="true" />
          <div>
            <h3>Brand Voice Preview</h3>
            <p>
              See how your current settings — including unsaved changes — sound in
              practice. Generated locally by Qwen2.5-1.5B-Instruct; the profile is
              not saved.
            </p>
          </div>
        </div>
        <button
          type="button"
          className="bp-preview-btn"
          onClick={generate}
          disabled={state === 'loading'}
        >
          {state === 'loading'
            ? <Spinner size={14} />
            : state === 'done'
              ? <RefreshCw size={14} />
              : <Play size={14} />}
          {state === 'loading' ? 'Generating…' : state === 'done' ? 'Regenerate' : 'Generate preview'}
        </button>
      </div>

      {state === 'idle' && (
        <p className="bp-preview-idle">
          Adjust tone, personality, audience or vocabulary, then generate a short
          sample paragraph to hear the voice before you save.
        </p>
      )}

      {state === 'loading' && (
        <div className="bp-preview-loading" role="status">
          <Spinner size={18} />
          <span>Asking the local model for a sample… this can take up to a minute on first load.</span>
        </div>
      )}

      {state === 'error' && (
        <div className="bp-preview-error" role="alert">
          <AlertTriangle size={15} aria-hidden="true" />
          <div>
            <strong>Preview unavailable.</strong>
            <p>{error}</p>
          </div>
        </div>
      )}

      {state === 'done' && (
        <div className="bp-preview-result">
          <blockquote className="bp-preview-sample">{sample}</blockquote>
          <div className="bp-preview-meta">
            <span className="bp-preview-badge">Local · {meta.model || 'Qwen2.5-1.5B-Instruct'}</span>
            {typeof meta.duration_s === 'number' && <span>{meta.duration_s}s</span>}
            <span>Not saved to profile</span>
          </div>
        </div>
      )}
    </Card>
  )
}
