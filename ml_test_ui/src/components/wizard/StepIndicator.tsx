import { Check } from 'lucide-react'
import { motion } from 'framer-motion'

interface Props { steps: string[]; current: number }

export default function StepIndicator({ steps, current }: Props) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', marginBottom: 24 }}>
      {steps.map((label, i) => {
        const done   = i < current
        const active = i === current
        const future = i > current
        return (
          <div
            key={i}
            style={{
              display: 'flex',
              alignItems: 'center',
              flex: i < steps.length - 1 ? 1 : 'none',
            }}
          >
            {/* Step node */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 5 }}>
              <motion.div
                animate={{
                  background: done
                    ? 'var(--green)'
                    : active
                    ? 'linear-gradient(135deg, #7c6aff, #a78bfa)'
                    : 'var(--s3)',
                  borderColor: done
                    ? 'var(--green)'
                    : active
                    ? 'rgba(124,106,255,0.6)'
                    : 'var(--b1)',
                  boxShadow: active
                    ? '0 0 0 3px rgba(124,106,255,0.12)'
                    : 'none',
                }}
                transition={{ duration: 0.25 }}
                style={{
                  width: 24,
                  height: 24,
                  borderRadius: '50%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                  border: '1.5px solid',
                  fontSize: 10,
                  fontWeight: 700,
                  color: future ? 'var(--t4)' : '#fff',
                  letterSpacing: 0,
                }}
              >
                {done ? <Check size={11} strokeWidth={2.5} /> : i + 1}
              </motion.div>

              <motion.span
                animate={{
                  color: active ? 'var(--accent-light)' : done ? 'var(--green)' : 'var(--t4)',
                  fontWeight: active ? 600 : 400,
                }}
                transition={{ duration: 0.2 }}
                style={{
                  fontSize: 10,
                  whiteSpace: 'nowrap',
                  letterSpacing: '0.02em',
                }}
              >
                {label}
              </motion.span>
            </div>

            {/* Connector line */}
            {i < steps.length - 1 && (
              <motion.div
                animate={{
                  background: i < current
                    ? 'linear-gradient(90deg, var(--green), rgba(16,185,129,0.4))'
                    : 'var(--b1)',
                }}
                transition={{ duration: 0.4 }}
                style={{
                  flex: 1,
                  height: 1,
                  margin: '0 6px',
                  marginBottom: 18,
                  borderRadius: 1,
                }}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}
