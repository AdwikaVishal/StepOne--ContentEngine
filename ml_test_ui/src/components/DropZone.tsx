import { useDropzone } from 'react-dropzone'
import { motion, AnimatePresence } from 'framer-motion'
import { Upload, Image, Film, Camera } from 'lucide-react'
import { useIsMobile } from '../hooks/useMediaQuery'
import { MAX_FILE_SIZE_BYTES, LARGE_FILE_WARNING_MB } from '../lib/constants'
import { toast } from './ui/Toast'

interface Props {
  onFiles: (files: File[]) => void
  multiple?: boolean
  label?: string
  compact?: boolean
}

export default function DropZone({ onFiles, multiple = true, label, compact }: Props) {
  const isMobile = useIsMobile()

  const { getRootProps, getInputProps, isDragActive, isDragReject } = useDropzone({
    onDrop: (accepted, rejected) => {
      if (rejected.length > 0) {
        rejected.forEach(r => {
          const reason = r.errors[0]?.message ?? 'Unsupported file'
          toast.error(`Rejected: ${r.file.name}`, reason)
        })
      }
      // Warn about large files
      accepted.forEach(f => {
        if (f.size > LARGE_FILE_WARNING_MB * 1024 * 1024) {
          toast.warning(`Large file: ${f.name}`, 'Files over 50MB may take longer to process')
        }
      })
      if (accepted.length > 0) onFiles(accepted)
    },
    accept: {
      'image/jpeg': ['.jpg', '.jpeg'],
      'image/png': ['.png'],
      'image/webp': ['.webp'],
      'video/mp4': ['.mp4'],
      'video/quicktime': ['.mov'],
      'video/x-msvideo': ['.avi'],
    },
    multiple,
    maxSize: MAX_FILE_SIZE_BYTES,
  })

  if (compact) {
    return (
      <div
        {...getRootProps()}
        style={{
          border: `1.5px dashed ${isDragActive ? 'var(--accent)' : 'var(--b1)'}`,
          borderRadius: 'var(--rs)',
          padding: '8px 14px',
          cursor: 'pointer',
          background: isDragActive ? 'rgba(124,106,255,.08)' : 'transparent',
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          transition: 'all .2s',
          fontSize: 12,
          color: isDragActive ? 'var(--a2)' : 'var(--t3)',
        }}
      >
        <input {...getInputProps()} />
        <Upload size={12} />
        {isDragActive ? 'Drop files' : label ?? 'Add more'}
      </div>
    )
  }

  return (
    <div
      {...getRootProps()}
      role="button"
      aria-label="Upload files — drag and drop or click to browse"
      tabIndex={0}
      style={{
        border: `2px dashed ${isDragReject ? 'var(--red)' : isDragActive ? 'var(--accent)' : 'var(--b1)'}`,
        borderRadius: 'var(--r)',
        padding: isMobile ? '32px 16px' : '48px 24px',
        textAlign: 'center',
        cursor: 'pointer',
        background: isDragReject
          ? 'rgba(239,68,68,.05)'
          : isDragActive
          ? 'rgba(124,106,255,.06)'
          : 'var(--s1)',
        transition: 'all .2s',
        outline: 'none',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      <input {...getInputProps()} />

      {/* Animated glow on drag */}
      <AnimatePresence>
        {isDragActive && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            style={{
              position: 'absolute', inset: 0,
              background: 'radial-gradient(ellipse at center, rgba(124,106,255,.12) 0%, transparent 70%)',
              pointerEvents: 'none',
            }}
          />
        )}
      </AnimatePresence>

      {/* Icon */}
      <motion.div
        animate={{ scale: isDragActive ? 1.1 : 1, y: isDragActive ? -4 : 0 }}
        transition={{ type: 'spring', stiffness: 300, damping: 20 }}
        style={{
          width: 56, height: 56, borderRadius: '50%',
          background: isDragActive ? 'rgba(124,106,255,.2)' : 'var(--s2)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          margin: '0 auto 16px',
          border: `1px solid ${isDragActive ? 'var(--accent)' : 'var(--b1)'}`,
          transition: 'all .2s',
        }}
      >
        <Upload size={24} color={isDragActive ? 'var(--accent)' : 'var(--t3)'} />
      </motion.div>

      <p style={{ fontWeight: 600, fontSize: 16, color: isDragReject ? 'var(--red)' : isDragActive ? 'var(--a2)' : 'var(--t1)', marginBottom: 6 }}>
        {isDragReject ? 'Unsupported file type' : isDragActive ? 'Release to upload' : 'Drop event photos & videos here'}
      </p>
      <p style={{ fontSize: 12, color: 'var(--t3)', marginBottom: 16 }}>
        or click to browse files
      </p>

      {/* Supported formats */}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'center', flexWrap: 'wrap' }}>
        {[
          { icon: <Image size={11} />, label: 'JPG' },
          { icon: <Image size={11} />, label: 'PNG' },
          { icon: <Image size={11} />, label: 'WebP' },
          { icon: <Film size={11} />, label: 'MP4' },
          { icon: <Film size={11} />, label: 'MOV' },
        ].map(({ icon, label: fmt }) => (
          <span key={fmt} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: 'var(--t3)', background: 'var(--s2)', borderRadius: 5, padding: '3px 8px', border: '1px solid var(--b1)' }}>
            {icon} {fmt}
          </span>
        ))}
        <span style={{ fontSize: 11, color: 'var(--t3)', background: 'var(--s2)', borderRadius: 5, padding: '3px 8px', border: '1px solid var(--b1)' }}>
          up to 200MB each
        </span>
      </div>

      {/* Mobile camera hint */}
      {isMobile && (
        <p style={{ fontSize: 11, color: 'var(--t3)', marginTop: 12, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4 }}>
          <Camera size={11} /> Tap to use camera or browse gallery
        </p>
      )}
    </div>
  )
}
