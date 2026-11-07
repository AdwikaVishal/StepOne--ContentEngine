/**
 * FileQueue — all functionality preserved, premium visual upgrade.
 */
import { X, Image, Film, AlertTriangle } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { fmtBytes } from '../../lib/formatters'
import { LARGE_FILE_WARNING_MB, MAX_FILE_SIZE_MB } from '../../lib/constants'

interface Props { files: File[]; onRemove: (name: string) => void }

export default function FileQueue({ files, onRemove }: Props) {
  if (!files.length) return null

  const nameCounts = files.reduce<Record<string, number>>((acc, f) => {
    acc[f.name] = (acc[f.name] ?? 0) + 1
    return acc
  }, {})

  const images = files.filter(f => f.type.startsWith('image/')).length
  const videos = files.filter(f => f.type.startsWith('video/')).length

  return (
    <div style={{ marginTop: 14 }}>
      {/* Summary row */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: 12, color: 'var(--t2)', fontWeight: 700 }}>{files.length} files queued</span>
        {images > 0 && (
          <span style={{ fontSize: 11, background: 'rgba(59,130,246,0.12)', color: '#60a5fa', borderRadius: 6, padding: '2px 9px', display: 'inline-flex', alignItems: 'center', gap: 4, fontWeight: 700, border: '1px solid rgba(59,130,246,0.2)' }}>
            <Image size={10} /> {images} images
          </span>
        )}
        {videos > 0 && (
          <span style={{ fontSize: 11, background: 'rgba(192,132,252,0.12)', color: '#c084fc', borderRadius: 6, padding: '2px 9px', display: 'inline-flex', alignItems: 'center', gap: 4, fontWeight: 700, border: '1px solid rgba(192,132,252,0.2)' }}>
            <Film size={10} /> {videos} videos
          </span>
        )}
      </div>

      {/* File list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5, maxHeight: 200, overflowY: 'auto' }}>
        <AnimatePresence>
          {files.map(f => {
            const isLarge     = f.size > LARGE_FILE_WARNING_MB * 1024 * 1024
            const isTooBig    = f.size > MAX_FILE_SIZE_MB * 1024 * 1024
            const isDuplicate = nameCounts[f.name] > 1
            const isVideo     = f.type.startsWith('video/')

            return (
              <motion.div
                key={f.name + f.size}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 8, height: 0 }}
                style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  background: isTooBig ? 'rgba(239,68,68,0.06)' : isDuplicate ? 'rgba(245,158,11,0.06)' : 'var(--s3)',
                  border: `1px solid ${isTooBig ? 'rgba(239,68,68,0.2)' : isDuplicate ? 'rgba(245,158,11,0.2)' : 'var(--b1)'}`,
                  borderRadius: 8, padding: '7px 12px',
                }}
              >
                {isVideo
                  ? <Film size={13} color="var(--pink)" style={{ flexShrink: 0 }} />
                  : <Image size={13} color="#60a5fa" style={{ flexShrink: 0 }} />
                }
                <span style={{ flex: 1, fontSize: 12, color: 'var(--t2)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {f.name}
                </span>
                <span style={{ fontSize: 11, color: isTooBig ? 'var(--red)' : isLarge ? 'var(--yellow)' : 'var(--t3)', flexShrink: 0, fontWeight: 600 }}>
                  {fmtBytes(f.size)}
                </span>
                {isTooBig && <span title={`Exceeds ${MAX_FILE_SIZE_MB}MB limit`}><AlertTriangle size={12} color="var(--red)" /></span>}
                {!isTooBig && isLarge && <span title="Large file — may take longer"><AlertTriangle size={12} color="var(--yellow)" /></span>}
                {isDuplicate && (
                  <span style={{ fontSize: 10, background: 'rgba(245,158,11,0.15)', color: 'var(--yellow)', borderRadius: 4, padding: '1px 6px', fontWeight: 700, border: '1px solid rgba(245,158,11,0.2)' }}>
                    DUP
                  </span>
                )}
                <motion.button
                  onClick={() => onRemove(f.name)}
                  aria-label={`Remove ${f.name}`}
                  whileHover={{ scale: 1.1, color: 'var(--red)' }}
                  whileTap={{ scale: 0.9 }}
                  style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--t3)', padding: 3, display: 'flex', flexShrink: 0, borderRadius: 4 }}
                >
                  <X size={12} />
                </motion.button>
              </motion.div>
            )
          })}
        </AnimatePresence>
      </div>
    </div>
  )
}
