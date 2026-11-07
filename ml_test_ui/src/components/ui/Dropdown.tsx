import { useState, useRef, useEffect, useLayoutEffect } from 'react'
import { createPortal } from 'react-dom'
import { ChevronDown, Check } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

interface Option { value: string; label: string }
interface Props {
  options: Option[]
  value: string
  onChange: (v: string) => void
  label?: string
  placeholder?: string
}

interface MenuPosition {
  top: number
  left: number
  width: number
  maxHeight: number
  openUpward: boolean
}

export function Dropdown({ options, value, onChange, label, placeholder = 'Select…' }: Props) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const [menuPos, setMenuPos] = useState<MenuPosition | null>(null)
  const selected = options.find(o => o.value === value)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  useLayoutEffect(() => {
    if (!open) return

    const updatePosition = () => {
      const trigger = triggerRef.current
      if (!trigger) return
      const rect = trigger.getBoundingClientRect()
      const viewportHeight = window.innerHeight
      const minSpace = 180
      const gap = 8
      const bottomSpace = viewportHeight - rect.bottom - gap
      const topSpace = rect.top - gap
      const openUpward = bottomSpace < minSpace && topSpace > bottomSpace
      const maxHeight = Math.max(120, Math.min(320, openUpward ? topSpace - 6 : bottomSpace - 6))

      setMenuPos({
        top: openUpward ? rect.top - gap : rect.bottom + gap,
        left: rect.left,
        width: rect.width,
        maxHeight,
        openUpward,
      })
    }

    updatePosition()
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)

    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [open])

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      {label && (
        <label
          style={{
            display: 'block',
            fontSize: 10,
            color: 'var(--t3)',
            marginBottom: 6,
            textTransform: 'uppercase',
            letterSpacing: '.08em',
            fontWeight: 600,
          }}
        >
          {label}
        </label>
      )}

      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        style={{
          width: '100%',
          background: open ? 'var(--s3)' : 'var(--s2)',
          border: `1px solid ${open ? 'rgba(124,106,255,0.45)' : 'var(--b1)'}`,
          borderRadius: 10,
          padding: '10px 12px',
          color: selected ? 'var(--t1)' : 'var(--t3)',
          fontSize: 13,
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 8,
          transition: 'border-color .18s, background .18s, box-shadow .18s',
          boxShadow: open ? '0 0 0 3px rgba(124,106,255,0.1)' : 'none',
          fontWeight: selected ? 500 : 400,
          outline: 'none',
        }}
        onMouseEnter={e => {
          if (!open) (e.currentTarget as HTMLElement).style.borderColor = 'var(--b2)'
        }}
        onMouseLeave={e => {
          if (!open) (e.currentTarget as HTMLElement).style.borderColor = 'var(--b1)'
        }}
      >
        <span style={{ flex: 1, textAlign: 'left', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {selected?.label ?? placeholder}
        </span>
        <motion.div
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: 0.2, ease: [0.4, 0, 0.2, 1] }}
          style={{ flexShrink: 0, display: 'flex', alignItems: 'center' }}
        >
          <ChevronDown size={13} color="var(--t3)" />
        </motion.div>
      </button>

      {typeof document !== 'undefined' && createPortal(
        <AnimatePresence>
          {open && menuPos && (
            <motion.div
              role="listbox"
              initial={{ opacity: 0, y: menuPos.openUpward ? 6 : -6, scale: 0.985 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: menuPos.openUpward ? 6 : -6, scale: 0.985 }}
              transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
              style={{
                position: 'fixed',
                top: menuPos.openUpward ? menuPos.top : menuPos.top,
                left: menuPos.left,
                width: menuPos.width,
                transformOrigin: menuPos.openUpward ? 'bottom center' : 'top center',
                background: 'linear-gradient(180deg, rgba(24,24,31,0.92) 0%, rgba(17,17,24,0.96) 100%)',
                border: '1px solid rgba(124,106,255,0.18)',
                borderRadius: 12,
                zIndex: 1200,
                boxShadow: '0 20px 50px rgba(0,0,0,0.58), 0 2px 10px rgba(0,0,0,0.38), 0 0 0 1px rgba(255,255,255,0.03) inset',
                overflowY: 'auto',
                overflowX: 'hidden',
                maxHeight: menuPos.maxHeight,
                padding: '6px',
                backdropFilter: 'blur(16px) saturate(160%)',
                WebkitBackdropFilter: 'blur(16px) saturate(160%)',
                scrollBehavior: 'smooth',
              }}
              className="dropdown-scroll"
            >
              {options.map((opt, idx) => {
                const isSelected = opt.value === value
                return (
                  <motion.button
                    key={opt.value}
                    role="option"
                    aria-selected={isSelected}
                    onClick={() => { onChange(opt.value); setOpen(false) }}
                    initial={{ opacity: 0, x: -3 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: idx * 0.012, duration: 0.14 }}
                    style={{
                      width: '100%',
                      padding: '10px 11px',
                      marginBottom: 2,
                      background: isSelected ? 'rgba(124,106,255,0.16)' : 'transparent',
                      border: 'none',
                      borderRadius: 9,
                      color: isSelected ? 'var(--accent-light)' : 'var(--t1)',
                      fontSize: 13,
                      cursor: 'pointer',
                      textAlign: 'left',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: 10,
                      fontWeight: isSelected ? 600 : 450,
                      transition: 'background .14s, color .14s',
                    }}
                    onMouseEnter={e => {
                      if (!isSelected) (e.currentTarget as HTMLElement).style.background = 'rgba(124,106,255,0.1)'
                    }}
                    onMouseLeave={e => {
                      if (!isSelected) (e.currentTarget as HTMLElement).style.background = 'transparent'
                    }}
                  >
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{opt.label}</span>
                    {isSelected && (
                      <motion.div
                        initial={{ scale: 0.7, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        transition={{ type: 'spring', stiffness: 420, damping: 23 }}
                      >
                        <Check size={12} color="var(--accent-light)" strokeWidth={2.5} />
                      </motion.div>
                    )}
                  </motion.button>
                )
              })}
            </motion.div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </div>
  )
}
