/**
 * StudioDropZone — cinematic drag-drop zone. All functionality preserved.
 */
import { useCallback, useMemo, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { AnimatePresence, motion } from 'framer-motion'
import { Camera, Film, Sparkles, Upload } from 'lucide-react'
import { useIsMobile } from '../../hooks/useMediaQuery'
import { LARGE_FILE_WARNING_MB, MAX_FILE_SIZE_BYTES, MAX_FILE_SIZE_MB } from '../../lib/constants'
import { toast } from '../ui/Toast'

type PreviewItem = { kind: 'image'; file: File; url: string } | { kind: 'video'; file: File; url: string }

interface Props { onFiles: (files: File[]) => void; files: File[]; isProcessing?: boolean }

const fmtTypeBadge = (f: File) => {
  if (f.type.startsWith('image/')) return f.type.replace('image/', '').toUpperCase()
  if (f.type.startsWith('video/')) return f.type.replace('video/', '').toUpperCase()
  return 'FILE'
}

export default function StudioDropZone({ onFiles, files, isProcessing = false }: Props) {
  const isMobile = useIsMobile()
  const [dragActive, setDragActive] = useState(false)

  const previews: PreviewItem[] = useMemo(() => {
    const next: PreviewItem[] = []
    for (const f of files) {
      if (f.type.startsWith('image/')) next.push({ kind: 'image', file: f, url: URL.createObjectURL(f) })
      else if (f.type.startsWith('video/')) next.push({ kind: 'video', file: f, url: URL.createObjectURL(f) })
    }
    return next
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files])

  const onDrop = useCallback((accepted: File[], rejected: any[]) => {
    setDragActive(false)
    if (rejected?.length) {
      rejected.forEach((r: any) => {
        const reason = r?.errors?.[0]?.message ?? 'Unsupported file'
        toast.error(`Rejected: ${r?.file?.name ?? 'file'}`, reason)
      })
    }
    accepted.forEach(f => {
      if (f.size > LARGE_FILE_WARNING_MB * 1024 * 1024) {
        toast.warning(`Large file: ${f.name}`, `Files over ${LARGE_FILE_WARNING_MB}MB may take longer to process`)
      }
    })
    if (accepted.length > 0) onFiles(accepted)
  }, [onFiles])

  const { getRootProps, getInputProps, isDragActive, isDragReject } = useDropzone({
    onDrop,
    onDragEnter: () => setDragActive(true),
    onDragLeave: () => setDragActive(false),
    accept: {
      'image/jpeg': ['.jpg', '.jpeg'], 'image/png': ['.png'], 'image/webp': ['.webp'],
      'video/mp4': ['.mp4'], 'video/quicktime': ['.mov'], 'video/x-msvideo': ['.avi'],
    },
    multiple: true,
    maxSize: MAX_FILE_SIZE_BYTES,
  })

  const hint = isDragReject ? 'Unsupported file type' : isDragActive ? 'Release to ingest' : 'Drag media to the Studio'

  return (
    <div
      {...getRootProps()}
      role="button"
      aria-label="Upload media — drag and drop or click"
      tabIndex={0}
      className="no-select"
      style={{
        borderRadius: 20,
        padding: isMobile ? '24px 16px' : '32px 28px',
        border: `1.5px dashed ${isDragReject ? 'var(--red)' : isDragActive ? 'var(--accent)' : 'var(--b2)'}`,
        background: isDragReject
          ? 'rgba(239,68,68,0.04)'
          : isDragActive
            ? 'radial-gradient(ellipse at center, rgba(124,106,255,0.12) 0%, transparent 70%)'
            : 'transparent',
        position: 'relative',
        overflow: 'hidden',
        transition: 'border-color .2s ease, background .2s ease',
        cursor: isProcessing ? 'not-allowed' : 'pointer',
      }}
    >
      {/* Drag glow overlay */}
      <AnimatePresence>
        {(isDragActive || dragActive) && (
          <motion.div key="glow" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            style={{
              position: 'absolute', inset: 0, pointerEvents: 'none',
              background: 'radial-gradient(ellipse at 30% 20%, rgba(59,130,246,0.12) 0%, transparent 50%), radial-gradient(ellipse at 70% 80%, rgba(124,106,255,0.15) 0%, transparent 50%)',
            }}
          />
        )}
      </AnimatePresence>

      <input {...getInputProps()} />

      {/* Top row */}
      <div style={{ display: 'flex', gap: 16, alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
          <motion.div
            animate={{ scale: isDragActive ? 1.1 : 1, y: isDragActive ? -4 : 0 }}
            transition={{ type: 'spring', stiffness: 300, damping: 22 }}
            style={{
              width: 56, height: 56, borderRadius: 16,
              background: isDragActive ? 'rgba(124,106,255,0.15)' : 'var(--s3)',
              border: `1px solid ${isDragActive ? 'var(--b-accent)' : 'var(--b1)'}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: isDragActive ? 'var(--shadow-glow)' : 'none',
              flexShrink: 0,
            }}
          >
            {files.some(f => f.type.startsWith('video/')) ? <Film size={22} color="var(--accent-light)" /> : <Upload size={20} color={isDragActive ? 'var(--accent-light)' : 'var(--t2)'} />}
          </motion.div>

          <div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <p style={{ fontSize: isMobile ? 15 : 17, fontWeight: 800, letterSpacing: '-0.01em', color: isDragReject ? 'var(--red)' : isDragActive ? 'var(--accent-light)' : 'var(--t1)' }}>
                {isProcessing ? 'AI is ingesting your media…' : hint}
              </p>
              <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--t3)', borderRadius: 999, padding: '3px 10px', border: '1px solid var(--b1)', background: 'var(--s3)' }}>
                up to {MAX_FILE_SIZE_MB}MB
              </span>
            </div>
            <p style={{ fontSize: 12, color: 'var(--t3)', marginTop: 4 }}>
              {files.length ? 'Preview ready — configure the event and generate.' : 'Creator-grade ingestion for images & short clips.'}
            </p>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {isProcessing
            ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--accent-light)', fontWeight: 700, fontSize: 12 }}><Sparkles size={13} /> Processing</span>
            : <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--t3)', fontWeight: 600, fontSize: 12 }}><Camera size={13} /> Drag to studio</span>
          }
        </div>
      </div>

      {/* Preview grid */}
      <AnimatePresence>
        {files.length > 0 && (
          <motion.div key="previews" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 10 }} transition={{ duration: 0.22 }} style={{ marginTop: 20 }}>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', marginBottom: 10 }}>
              <p style={{ fontSize: 11, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '.08em', fontWeight: 700 }}>Media deck</p>
              <p style={{ fontSize: 11, color: 'var(--t3)' }}>{files.length} items ready</p>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr 1fr' : 'repeat(6, minmax(0, 1fr))', gap: 8 }}>
              {previews.slice(0, isMobile ? 8 : 12).map((p, idx) => (
                <motion.div key={p.file.name + p.file.size + idx} whileHover={{ y: -3, boxShadow: 'var(--shadow-glow)' }}
                  style={{ aspectRatio: '1/1', borderRadius: 12, overflow: 'hidden', border: '1px solid var(--b1)', background: 'var(--s3)', position: 'relative' }}
                >
                  {p.kind === 'image'
                    ? <img src={p.url} alt={p.file.name} style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
                    : <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'linear-gradient(135deg, rgba(124,106,255,.12), rgba(59,130,246,.06))' }}>
                        <Film size={18} color="var(--accent-light)" />
                      </div>
                  }
                  <div style={{ position: 'absolute', left: 6, top: 6 }}>
                    <span style={{ background: 'rgba(0,0,0,.55)', color: 'white', borderRadius: 999, padding: '2px 7px', fontSize: 10, fontWeight: 800 }}>
                      {fmtTypeBadge(p.file)}
                    </span>
                  </div>
                </motion.div>
              ))}
              {files.length > (isMobile ? 8 : 12) && (
                <div style={{ borderRadius: 12, border: '1px solid var(--b1)', background: 'var(--s3)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--t2)', fontWeight: 800, aspectRatio: '1/1', fontSize: 14 }}>
                  +{files.length - (isMobile ? 8 : 12)}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Format badges */}
      <div style={{ display: 'flex', gap: 6, justifyContent: 'center', flexWrap: 'wrap', marginTop: 16 }}>
        {[
          { label: 'JPG / PNG / WebP', color: 'rgba(59,130,246,0.15)', text: '#60a5fa' },
          { label: 'MP4 / MOV / AVI',  color: 'rgba(124,106,255,0.15)', text: 'var(--accent-light)' },
          { label: 'Premium ingest',   color: 'rgba(236,72,153,0.10)', text: 'var(--pink)' },
        ].map(b => (
          <span key={b.label} style={{ fontSize: 10, fontWeight: 700, color: b.text, background: b.color, borderRadius: 999, padding: '5px 10px', border: '1px solid rgba(255,255,255,0.08)' }}>
            {b.label}
          </span>
        ))}
      </div>

      <p style={{ fontSize: 11, color: 'var(--t4)', marginTop: isMobile ? 10 : 12, textAlign: 'center' }}>
        Tip: drop multiple files to batch-create content.
      </p>
    </div>
  )
}
