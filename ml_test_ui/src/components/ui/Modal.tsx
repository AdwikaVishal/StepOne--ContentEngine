import { type ReactNode, useEffect } from 'react'
import { X } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

interface Props { open: boolean; onClose: () => void; title?: string; children: ReactNode; width?: number }

export function Modal({ open, onClose, title, children, width = 520 }: Props) {
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          role="dialog"
          aria-modal="true"
          aria-label={title}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          style={{ position: 'fixed', inset: 0, zIndex: 500, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}
          onClick={e => { if (e.target === e.currentTarget) onClose() }}
        >
          {/* Backdrop */}
          <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(8px)', WebkitBackdropFilter: 'blur(8px)' }} />

          {/* Panel */}
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.97 }}
            transition={{ duration: .25, ease: [.16,1,.3,1] }}
            style={{
              position: 'relative',
              background: 'var(--glass-card)',
              backdropFilter: 'blur(24px) saturate(180%)',
              WebkitBackdropFilter: 'blur(24px) saturate(180%)',
              border: '1px solid var(--b1)',
              borderRadius: 'var(--rxl)',
              width: '100%', maxWidth: width, maxHeight: '90vh', overflowY: 'auto',
              boxShadow: 'var(--shadow-float)',
            }}
          >
            {/* Top gradient line */}
            <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 1, background: 'linear-gradient(90deg, transparent, rgba(124,106,255,0.5), transparent)', borderRadius: 'var(--rxl) var(--rxl) 0 0' }} />

            {title && (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '18px 22px', borderBottom: '1px solid var(--b1)' }}>
                <h2 style={{ fontSize: 16, fontWeight: 800, letterSpacing: '-0.01em' }}>{title}</h2>
                <motion.button
                  onClick={onClose}
                  aria-label="Close"
                  whileHover={{ scale: 1.1, background: 'var(--s3)' }}
                  whileTap={{ scale: 0.9 }}
                  style={{ background: 'var(--s2)', border: '1px solid var(--b1)', cursor: 'pointer', color: 'var(--t2)', padding: 6, borderRadius: 8, display: 'flex', transition: 'all .15s' }}
                >
                  <X size={16} />
                </motion.button>
              </div>
            )}
            <div style={{ padding: 22 }}>{children}</div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
