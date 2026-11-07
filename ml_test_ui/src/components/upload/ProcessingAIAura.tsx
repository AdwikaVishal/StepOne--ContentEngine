import { motion } from 'framer-motion'
import { Sparkles } from 'lucide-react'

export function ProcessingAIAura({ label }: { label: string }) {
  return (
    <div style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', gap: 10 }}>
      <motion.div
        aria-hidden="true"
        animate={{
          boxShadow: ['0 0 0 rgba(124,106,255,.0)', '0 0 30px rgba(124,106,255,.30)', '0 0 0 rgba(124,106,255,.0)'],
        }}
        transition={{ duration: 1.6, repeat: Infinity, ease: 'easeInOut' }}
        style={{ width: 12, height: 12, borderRadius: 999, background: 'var(--accent-purple)' }}
      />
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, color: 'var(--a2)', fontWeight: 800, fontSize: 12 }}>
        <Sparkles size={14} /> {label}
      </span>
    </div>
  )
}

