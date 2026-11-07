/**
 * Core UI primitives — premium redesign.
 * All functionality preserved; visual layer upgraded.
 */
import { type ReactNode, type CSSProperties } from 'react'
import type React from 'react'
import { motion } from 'framer-motion'

export function Card({
  children, style, className, glow = false,
}: {
  children: ReactNode; style?: CSSProperties; className?: string; glow?: boolean
}) {
  return (
    <div
      className={className}
      style={{
        background: 'var(--glass-card)',
        backdropFilter: 'blur(20px) saturate(180%)',
        WebkitBackdropFilter: 'blur(20px) saturate(180%)',
        border: `1px solid ${glow ? 'var(--b-accent)' : 'var(--b1)'}`,
        borderRadius: 'var(--r)',
        padding: 20,
        boxShadow: glow
          ? 'var(--shadow-card), 0 0 20px rgba(124,106,255,0.08)'
          : 'var(--shadow-card)',
        position: 'relative',
        overflow: 'hidden',
        ...style,
      }}
    >
      <div
        aria-hidden="true"
        style={{
          position: 'absolute', inset: 0, pointerEvents: 'none',
          background: 'linear-gradient(180deg, rgba(255,255,255,0.025) 0%, transparent 50%)',
          borderRadius: 'inherit',
        }}
      />
      {children}
    </div>
  )
}

export function Spinner({ size = 20, color = 'var(--accent)' }: { size?: number; color?: string }) {
  return (
    <div
      role="status"
      aria-label="Loading"
      style={{
        width: size, height: size,
        border: `2px solid ${color}22`,
        borderTop: `2px solid ${color}`,
        borderRadius: '50%',
        animation: 'spin .7s linear infinite',
        display: 'inline-block',
        flexShrink: 0,
      }}
    />
  )
}

export function ScoreBar({ label, value, color }: { label: string; value: number; color?: string }) {
  const pct = Math.round(value * 100)
  const c = color ?? (value >= .7 ? 'var(--green)' : value >= .45 ? 'var(--yellow)' : 'var(--red)')
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5, fontSize: 12 }}>
        <span style={{ color: 'var(--t2)' }}>{label}</span>
        <span style={{ fontWeight: 700, color: c }}>{pct}%</span>
      </div>
      <div style={{ height: 4, background: 'var(--s4)', borderRadius: 4, overflow: 'hidden' }}>
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: .8, ease: 'easeOut' }}
          style={{ height: '100%', background: c, borderRadius: 4 }}
        />
      </div>
    </div>
  )
}

export function Btn({
  children, onClick, disabled, variant = 'primary', size = 'md', full, style, type = 'button',
}: {
  children: ReactNode; onClick?: () => void; disabled?: boolean
  variant?: 'primary' | 'ghost' | 'danger' | 'success'; size?: 'sm' | 'md' | 'lg'
  full?: boolean; style?: CSSProperties; type?: 'button' | 'submit' | 'reset'
}) {
  const bgMap = {
    primary: disabled ? 'var(--s4)' : 'linear-gradient(135deg,#7c6aff,#a78bfa)',
    ghost:   'transparent',
    danger:  disabled ? 'var(--s4)' : 'rgba(239,68,68,0.15)',
    success: disabled ? 'var(--s4)' : 'rgba(16,185,129,0.15)',
  }
  const borderMap = {
    primary: 'none',
    ghost:   '1px solid var(--b2)',
    danger:  '1px solid rgba(239,68,68,0.35)',
    success: '1px solid rgba(16,185,129,0.35)',
  }
  const colorMap = {
    primary: disabled ? 'var(--t3)' : '#fff',
    ghost:   disabled ? 'var(--t3)' : 'var(--t2)',
    danger:  disabled ? 'var(--t3)' : '#fca5a5',
    success: disabled ? 'var(--t3)' : '#6ee7b7',
  }
  const padMap = { sm: '6px 14px', md: '9px 18px', lg: '12px 26px' }
  const fsMap  = { sm: 12, md: 13, lg: 14 }

  return (
    <motion.button
      type={type}
      onClick={onClick}
      disabled={disabled}
      whileHover={disabled ? {} : { scale: 1.02, y: -1 }}
      whileTap={disabled ? {} : { scale: 0.97 }}
      style={{
        background: bgMap[variant],
        color: colorMap[variant],
        border: borderMap[variant],
        borderRadius: 'var(--rs)',
        padding: padMap[size],
        fontSize: fsMap[size],
        fontWeight: 600,
        cursor: disabled ? 'not-allowed' : 'pointer',
        display: 'inline-flex',
        alignItems: 'center',
        gap: 7,
        transition: 'opacity .15s, box-shadow .2s',
        width: full ? '100%' : undefined,
        justifyContent: full ? 'center' : undefined,
        boxShadow: variant === 'primary' && !disabled ? '0 4px 16px rgba(124,106,255,0.25)' : 'none',
        ...style,
      }}
    >
      {children}
    </motion.button>
  )
}

export function Input({
  value, onChange, placeholder, label, type = 'text', required, autoFocus,
}: {
  value: string; onChange: (v: string) => void; placeholder?: string
  label?: string; type?: string; required?: boolean; autoFocus?: boolean
}) {
  return (
    <div>
      {label && (
        <label style={{ display: 'block', fontSize: 11, color: 'var(--t3)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '.07em', fontWeight: 700 }}>
          {label}{required && <span style={{ color: 'var(--red)', marginLeft: 2 }}>*</span>}
        </label>
      )}
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        required={required}
        autoFocus={autoFocus}
        style={{
          width: '100%', background: 'var(--s3)', border: '1px solid var(--b1)',
          borderRadius: 'var(--rs)', padding: '10px 14px', color: 'var(--t1)',
          fontSize: 14, outline: 'none', transition: 'border-color .2s, box-shadow .2s',
        }}
        onFocus={e => {
          e.target.style.borderColor = 'var(--accent)'
          e.target.style.boxShadow = '0 0 0 3px rgba(124,106,255,0.12)'
        }}
        onBlur={e => {
          e.target.style.borderColor = 'var(--b1)'
          e.target.style.boxShadow = 'none'
        }}
      />
    </div>
  )
}

export function ProgressBar({ pct, label, color = 'var(--accent)' }: { pct: number; label?: string; color?: string }) {
  return (
    <div>
      {label && (
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: 12, color: 'var(--t2)' }}>
          <span>{label}</span>
          <span style={{ color, fontWeight: 700 }}>{pct}%</span>
        </div>
      )}
      <div style={{ height: 5, background: 'var(--s4)', borderRadius: 4, overflow: 'hidden' }}>
        <motion.div
          animate={{ width: `${Math.min(100, pct)}%` }}
          transition={{ duration: .4, ease: 'easeOut' }}
          style={{
            height: '100%',
            background: `linear-gradient(90deg, ${color}, ${color === 'var(--accent)' ? 'var(--accent-light)' : color})`,
            borderRadius: 4,
            boxShadow: `0 0 8px ${color === 'var(--accent)' ? 'rgba(124,106,255,0.5)' : 'transparent'}`,
          }}
        />
      </div>
    </div>
  )
}

export function Tag({ label, color = 'var(--accent)', style }: { label: string; color?: string; style?: React.CSSProperties }) {
  return (
    <span style={{
      background: `${color}18`,
      color,
      border: `1px solid ${color}35`,
      borderRadius: 6,
      padding: '3px 10px',
      fontSize: 11,
      fontWeight: 600,
      whiteSpace: 'nowrap',
      letterSpacing: '0.02em',
      ...style,
    }}>
      {label}
    </span>
  )
}

export function SectionTitle({ children, sub }: { children: ReactNode; sub?: string }) {
  return (
    <div style={{ marginBottom: 20 }}>
      <h2 style={{ fontSize: 20, fontWeight: 800, color: 'var(--t1)', letterSpacing: '-0.02em' }}>{children}</h2>
      {sub && <p style={{ fontSize: 13, color: 'var(--t3)', marginTop: 4 }}>{sub}</p>}
    </div>
  )
}

export { AnimatedButton } from './ui/AnimatedButton'
export { AnimatedBtn } from './ui/AnimatedBtn'
