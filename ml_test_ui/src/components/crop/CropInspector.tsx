/**
 * CropInspector — crop-intelligence visibility panel.
 *
 * Lets a user inspect how the composition engine will crop an image:
 *   1. Original image with detected focal region & focal point overlay
 *   2. Proposed crop boundary overlay
 *   3. Final rendered crop
 *   4. Composition confidence + scene type
 *   5. Before/after comparison
 *   6. Manual focal-point adjustment (drag the handle) that regenerates the
 *      crop via /api/crop/compute without re-running the full AI pipeline.
 *
 * A manual adjustment can be saved (POST /api/crop/save-override) scoped to
 * the exact asset + output format. The backend rendering pipeline
 * (LayoutAssembler) consults the same store so regenerated assets reflect the
 * saved adjustment.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Crop, Eye, Upload, AlertCircle, RefreshCw, Save } from 'lucide-react'
import {
  cropAnalyze, cropCompute, cropComputeFromPath, cropSaveOverride, cropGetOverride,
  type CropComputeResult, type CropAnalysis,
} from '../../api'
import { toast } from '../ui/Toast'

type Format = { label: string; w: number; h: number; key: string }

const FORMATS: Format[] = [
  { label: '1:1 (square)', w: 1080, h: 1080, key: 'linkedin_1_1' },
  { label: '4:5 (carousel)', w: 1080, h: 1350, key: 'carousel_4_5' },
  { label: '9:16 (story/reel)', w: 1080, h: 1920, key: 'story_9_16' },
  { label: '16:9 (landscape)', w: 1920, h: 1080, key: 'landscape_16_9' },
]

export interface CropInspectorProps {
  /** File uploaded by the user (for analysis + crop compute). */
  imageFile?: File | null
  /** Display URL for the image (can be a server path). */
  imageUrl?: string | null
  /** Filesystem path used for override lookups (defaults to imageUrl). */
  imagePath?: string | null
  /** Output format key used to scope the saved override. */
  formatKey?: string | null
  onCropSave?: (meta: { focal_point: number[]; crop_box_norm: number[] }) => void
  className?: string
}

export function CropInspector({
  imageFile,
  imageUrl,
  imagePath,
  formatKey,
  onCropSave,
  className,
}: CropInspectorProps) {
  const [format, setFormat] = useState<Format>(FORMATS[1])
  const [viewMode, setViewMode] = useState<'original' | 'crop' | 'compare'>('original')
  const [analysis, setAnalysis] = useState<CropAnalysis | null>(null)
  const [computed, setComputed] = useState<CropComputeResult | null>(null)
  const [cropUrl, setCropUrl] = useState<string | null>(null)
  const [manualFocal, setManualFocal] = useState<[number, number] | null>(null)
  const [overrideLoaded, setOverrideLoaded] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saveOk, setSaveOk] = useState(false)

  const imgRef = useRef<HTMLDivElement>(null)
  const dragActive = useRef(false)

  const resolvedPath = imagePath ?? imageUrl ?? null
  const resolvedFormat = formatKey ?? format.key

  // ── Analysis (focal detection) ───────────────────────────────────────────
  const runAnalyze = useCallback(async (file: File) => {
    setLoading(true); setError(null)
    try {
      const res = await cropAnalyze(file)
      setAnalysis(res.analysis)
      setManualFocal([res.analysis.focal_point[0], res.analysis.focal_point[1]])
      setComputed(null); setCropUrl(null); setOverrideLoaded(false)
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? e.message ?? 'Analysis failed')
    } finally {
      setLoading(false)
    }
  }, [])

  const handleFile = async (file: File) => {
    await runAnalyze(file)
  }

  // ── Load any saved override for this asset + format ──────────────────────
  const loadOverride = useCallback(async () => {
    if (!resolvedPath || !resolvedFormat) return
    try {
      const res = await cropGetOverride(resolvedPath, resolvedFormat)
      if (res.override) {
        setManualFocal([res.override.focal_point[0], res.override.focal_point[1]])
        setOverrideLoaded(true)
      }
    } catch {
      // override lookup is best-effort
    }
  }, [resolvedPath, resolvedFormat])

  useEffect(() => {
    if (resolvedPath && resolvedFormat) loadOverride()
  }, [resolvedPath, resolvedFormat, loadOverride])

  // ── Compute / render crop ────────────────────────────────────────────────
  const runCompute = useCallback(async () => {
    const source = imageFile ?? resolvedPath
    if (!source) return
    setLoading(true); setError(null)
    try {
      const fx = manualFocal?.[0] ?? analysis?.focal_point[0] ?? 0.5
      const fy = manualFocal?.[1] ?? analysis?.focal_point[1] ?? 0.5
      let res: CropComputeResult
      if (imageFile) {
        res = await cropCompute(imageFile, format.w, format.h, fx, fy)
      } else {
        res = await cropComputeFromPath(resolvedPath!, format.w, format.h, fx, fy)
      }
      setComputed(res)
      setCropUrl(res.crop_url)
      toast.success('Crop computed')
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? e.message ?? 'Crop compute failed')
    } finally {
      setLoading(false)
    }
  }, [imageFile, resolvedPath, format, manualFocal, analysis])

  useEffect(() => {
    if (imageFile && analysis) runCompute()
  }, [imageFile, analysis, format, runCompute])

  // ── Drag handling for the manual focal handle ────────────────────────────
  const startDrag = useCallback((e: React.MouseEvent) => {
    dragActive.current = true
    e.preventDefault()
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    onMove(e.nativeEvent)
  }, [])

  const onMove = useCallback((e: MouseEvent) => {
    if (!dragActive.current || !imgRef.current) return
    const rect = imgRef.current.getBoundingClientRect()
    let fx = (e.clientX - rect.left) / rect.width
    let fy = (e.clientY - rect.top) / rect.height
    fx = Math.min(1, Math.max(0, fx))
    fy = Math.min(1, Math.max(0, fy))
    setManualFocal([fx, fy])
  }, [])

  const onUp = useCallback(() => {
    dragActive.current = false
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
    if (imageFile) runCompute()
  }, [imageFile, runCompute])

  // ── Save manual override ─────────────────────────────────────────────────
  const saveOverride = useCallback(async () => {
    if (!analysis || !computed || !resolvedPath || !resolvedFormat) return
    setLoading(true)
    try {
      const meta = {
        focal_point: manualFocal ?? analysis.focal_point,
        crop_box_norm: computed.crop.crop_box_norm,
      }
      await cropSaveOverride(resolvedPath, resolvedFormat, meta.focal_point as [number, number], meta.crop_box_norm as [number, number, number, number])
      setSaveOk(true)
      setTimeout(() => setSaveOk(false), 1500)
      onCropSave?.(meta)
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? e.message ?? 'Save failed')
    } finally {
      setLoading(false)
    }
  }, [analysis, computed, manualFocal, resolvedPath, resolvedFormat, onCropSave])

  // ── Image aspect ─────────────────────────────────────────────────────────
  const aspect = analysis ? analysis.width / analysis.height : 1
  const focalPx = (v: number) => Math.round(v * 100)
  const regionStyle = (r: number[]) => ({
    left: `${focalPx(r[0])}%`, top: `${focalPx(r[1])}%`,
    width: `${Math.max(0, focalPx(r[2] - r[0]))}%`,
    height: `${Math.max(0, focalPx(r[3] - r[1]))}%`,
  })
  const pointStyle = (p: number[]) => ({
    left: `${focalPx(p[0])}%`, top: `${focalPx(p[1])}%`,
  })

  const displayFocal = manualFocal ?? analysis?.focal_point ?? [0.5, 0.5]
  const focalRegion = analysis?.focal_region ?? [0, 0, 1, 1]

  return (
    <div
      style={{
        ...(className ? { className } as any : {}),
        display: 'flex', flexDirection: 'column', gap: 12, width: '100%',
        maxWidth: 740, fontSize: 13,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', borderBottom: '1px solid var(--b1)', paddingBottom: 8 }}>
        <Crop size={16} />
        <span style={{ fontWeight: 700, color: 'var(--t1)' }}>Crop Inspector</span>
        <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--t3)' }}>
          {analysis ? `scene: ${analysis.scene_type} · conf: ${(analysis.confidence * 100).toFixed(0)}%` : ''}
        </span>
      </div>

      {error && (
        <div style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.25)', color: '#fca5a5', padding: '8px 12px', borderRadius: 8, fontSize: 12 }}>
          <AlertCircle size={14} /> {error}
        </div>
      )}

      {!imageFile && !imageUrl && (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--t3)', border: '1px dashed var(--b1)', borderRadius: 10 }}>
          <Upload size={32} style={{ opacity: 0.5 }} />
          <p style={{ marginTop: 8 }}>Select an image to inspect its crop</p>
        </div>
      )}

      {/* Controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {FORMATS.map(f => (
          <button
            key={f.label}
            onClick={() => setFormat(f)}
            disabled={loading}
            style={{
              padding: '4px 10px', borderRadius: 6, border: '1px solid var(--b1)',
              background: format === f ? 'var(--accent)' : 'var(--s3)',
              color: format === f ? '#fff' : 'var(--t2)',
              cursor: loading ? 'not-allowed' : 'pointer', fontSize: 12,
            }}
          >
            {f.label}
          </button>
        ))}
        <button
          onClick={runCompute}
          disabled={loading || !(imageFile || resolvedPath)}
          style={{
            padding: '6px 12px', borderRadius: 6, border: 'none',
            background: 'var(--accent)', color: '#fff', fontWeight: 600, fontSize: 12,
            cursor: (loading || !(imageFile || resolvedPath)) ? 'not-allowed' : 'pointer',
          }}
        >
          {loading ? <RefreshCw size={14} /> : <Crop size={14} />} Compute crop
        </button>
        {imageFile && (
          <button
            onClick={() => {
              const input = document.createElement('input')
              input.type = 'file'; input.accept = 'image/*'
              input.onchange = (e: any) => {
                const f = e.target.files?.[0]
                if (f) handleFile(f)
              }
              input.click()
            }}
            style={{ padding: '0 10px', borderRadius: 6, border: '1px solid var(--b1)', background: 'var(--s3)', color: 'var(--t2)', cursor: 'pointer', fontSize: 12 }}
            title="Choose another image"
          >
            <Upload size={14} />
          </button>
        )}
        {resolvedPath && resolvedFormat && (
          <>
            <button
              onClick={saveOverride}
              disabled={loading || !analysis || !computed}
              style={{
                padding: '6px 12px', borderRadius: 6, border: '1px solid var(--b1)',
                background: saveOk ? 'var(--green)' : 'var(--accent)',
                color: '#fff', fontWeight: 600, fontSize: 12,
                cursor: (loading || !analysis || !computed) ? 'not-allowed' : 'pointer',
              }}
              title="Save manual focal adjustment for this asset + format"
            >
              <Save size={14} /> {saveOk ? 'Saved!' : 'Save override'}
            </button>
            {overrideLoaded && (
              <span style={{ fontSize: 11, color: 'var(--green)', marginLeft: 6 }}>
                Using saved override
              </span>
            )}
          </>
        )}
      </div>

      {/* Original + overlays */}
      {(imageFile || imageUrl) && (
        <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
          <div
            ref={imgRef}
            style={{
              position: 'relative', width: '100%', maxWidth: 440,
              aspectRatio: aspect, background: '#000', borderRadius: 10,
              overflow: 'hidden', border: '1px solid var(--b1)',
            }}
          >
            <img
              src={imageFile ? URL.createObjectURL(imageFile) : imageUrl!}
              alt="original"
              style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
              onLoad={() => {
                if (imageFile) URL.revokeObjectURL(imageFile as any as string)
              }}
            />
            {/* Focal region overlay */}
            {analysis && (
              <div
                style={{
                  position: 'absolute', ...regionStyle(focalRegion),
                  border: '2px dashed rgba(16,185,129,0.9)', borderRadius: 4,
                  pointerEvents: 'none',
                  boxShadow: '0 0 0 1px rgba(16,185,129,0.35)',
                }}
              />
            )}
            {/* Crop boundary overlay */}
            {computed && (
              <div
                style={{
                  position: 'absolute', ...regionStyle(computed.crop.crop_box_norm),
                  border: '2px solid rgba(99,102,241,0.95)', borderRadius: 4,
                  pointerEvents: 'none',
                  boxShadow: '0 0 0 1px rgba(99,102,241,0.35)',
                }}
              />
            )}
            {/* Manual focal handle */}
            {analysis && (
              <div
                style={{
                  position: 'absolute', ...pointStyle(displayFocal),
                  width: 26, height: 26, borderRadius: '50%',
                  background: 'rgba(255,255,255,0.92)', border: '3px solid #7c6aff',
                  boxShadow: '0 2px 8px rgba(0,0,0,0.45)', transform: 'translate(-50%,-50%)',
                  cursor: 'pointer', zIndex: 10, touchAction: 'none',
                }}
                onMouseDown={startDrag}
              />
            )}
          </div>

          {analysis && (
            <div style={{ background: 'var(--s3)', border: '1px solid var(--b1)', borderRadius: 8, padding: 10, fontSize: 12, color: 'var(--t2)', minWidth: 220 }}>
              <div style={{ fontWeight: 700, color: 'var(--t1)', marginBottom: 6 }}>Focal analysis</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, fontSize: 11, marginBottom: 6 }}>
                <div>Focal point</div>
                <div style={{ textAlign: 'right' }}>{displayFocal[0].toFixed(2)}, {displayFocal[1].toFixed(2)}</div>
                <div>Faces</div>
                <div style={{ textAlign: 'right' }}>{analysis.face_count}</div>
                <div>Subjects</div>
                <div style={{ textAlign: 'right' }}>{(analysis.main_subject ? 1 : 0) + analysis.secondary_subjects.length}</div>
                <div>Models</div>
                <div style={{ textAlign: 'right' }}>{(analysis.models_used ?? []).join(', ') || 'fallback'}</div>
              </div>
              <p style={{ fontSize: 10.5, color: 'var(--t3)', margin: 0 }}>
                Drag the purple handle to re-frame the crop manually.
              </p>
            </div>
          )}
        </div>
      )}

      {/* Computed crop */}
      {computed && (
        <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: 240, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ fontWeight: 700, color: 'var(--t1)', display: 'flex', alignItems: 'center', gap: 6 }}>
              <Eye size={14} /> Rendered crop ({format.w}×{format.h})
            </div>
            <div style={{ background: '#000', borderRadius: 8, overflow: 'hidden', border: '1px solid var(--b1)', aspectRatio: `${format.w / format.h}`, width: '100%' }}>
              <img src={cropUrl!} alt="computed crop" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, fontSize: 11.5, color: 'var(--t2)', background: 'var(--s3)', borderRadius: 6, padding: 8 }}>
              <div>Score</div>
              <div style={{ textAlign: 'right', fontWeight: 700, color: 'var(--t1)' }}>{(computed.crop.composition_score * 100).toFixed(0)}%</div>
              <div>Faces kept</div>
              <div style={{ textAlign: 'right' }}>{computed.crop.faces_preserved}/{computed.crop.faces_total}</div>
              <div>Subjects</div>
              <div style={{ textAlign: 'right' }}>{computed.crop.subjects_preserved.join(', ') || '—'}</div>
              <div>Scene</div>
              <div style={{ textAlign: 'right', textTransform: 'capitalize' }}>{computed.crop.scene_type}</div>
            </div>
            {computed.crop.warnings.length > 0 && (
              <div style={{ fontSize: 11, color: '#fca5a5', background: 'rgba(239,68,68,0.08)', borderRadius: 6, padding: 6 }}>
                <b>⚠</b> {computed.crop.warnings.join('; ')}
              </div>
            )}
            {computed.crop.trade_off && (
              <div style={{ fontSize: 11, color: '#f59e0b', background: 'rgba(245,158,11,0.08)', borderRadius: 6, padding: 6 }}>
                <b>Trade-off:</b> {computed.crop.trade_off}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Before / after */}
      {computed && imageFile && (
        <div style={{ marginTop: 10, borderTop: '1px solid var(--b1)', paddingTop: 10 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <span style={{ fontWeight: 700, color: 'var(--t1)' }}>Before / After</span>
            <div style={{ display: 'flex', gap: 4 }}>
              {['original', 'crop', 'compare'].map(m => (
                <button
                  key={m}
                  onClick={() => setViewMode(m as 'original' | 'crop' | 'compare')}
                  style={{
                    padding: '2px 8px', borderRadius: 4, border: '1px solid var(--b1)',
                    background: viewMode === m ? 'var(--accent)' : 'var(--s3)',
                    color: viewMode === m ? '#fff' : 'var(--t2)', cursor: 'pointer', fontSize: 11,
                  }}
                >
                  {m === 'original' ? 'Original' : m === 'crop' ? 'Crop' : 'Both'}
                </button>
              ))}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 10, overflowX: 'auto', paddingBottom: 10 }}>
            {(viewMode === 'original' || viewMode === 'compare') && (
              <div style={{ flex: '0 0 auto', width: 200, aspectRatio: aspect, background: '#000', borderRadius: 8, overflow: 'hidden', border: '1px solid var(--b1)', flexShrink: 0 }}>
                <img src={URL.createObjectURL(imageFile)} alt="original" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} onLoad={() => URL.revokeObjectURL(imageFile as any as string)} />
              </div>
            )}
            {(viewMode === 'crop' || viewMode === 'compare') && (
              <div style={{ flex: '0 0 auto', width: 200, aspectRatio: `${format.w / format.h}`, background: '#000', borderRadius: 8, overflow: 'hidden', border: '1px solid var(--b1)', flexShrink: 0 }}>
                <img src={cropUrl!} alt="crop" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
              </div>
            )}
          </div>
        </div>
      )}

      {computed && analysis && resolvedPath && resolvedFormat && (
        <div style={{ marginTop: 8, padding: 8, background: 'rgba(124,106,255,0.08)', borderRadius: 6, fontSize: 11.5, color: 'var(--t2)', border: '1px solid rgba(124,106,255,0.15)' }}>
          <b>Save adjustment</b> — stores the manual focal point &amp; crop box scoped to
          <code style={{ color: 'var(--t1)' }}>{resolvedFormat}</code> for this asset. The renderer
          will use it instead of re-running detection.{' '}
          <button onClick={saveOverride} style={{ marginLeft: 8, background: 'none', border: '1px solid var(--accent)', color: 'var(--accent)', borderRadius: 4, padding: '2px 8px', cursor: 'pointer', fontSize: 11 }}>Save override</button>
        </div>
      )}
    </div>
  )
}
