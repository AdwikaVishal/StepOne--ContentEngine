import { motion } from 'framer-motion'
import { Home, BarChart3, FileText, Palette } from 'lucide-react'
import type { View } from '../../App'

interface Props { view: View; onViewChange: (view: View) => void; hasResults?: boolean }

const NAV_ITEMS = [
  { id: 'studio'    as const, label: 'Studio',    icon: Home },
  { id: 'results'   as const, label: 'Results',   icon: FileText },
  { id: 'analytics' as const, label: 'Analytics', icon: BarChart3 },
  { id: 'brand-profiles' as const, label: 'Brands', icon: Palette },
]

export default function BottomNav({ view, onViewChange, hasResults = false }: Props) {
  return (
    <nav
      role="navigation"
      aria-label="Mobile navigation"
      className="mobile-nav"
      style={{
        position: 'fixed', bottom: 0, left: 0, right: 0,
        background: 'rgba(6,6,9,0.94)',
        backdropFilter: 'blur(24px) saturate(180%)',
        WebkitBackdropFilter: 'blur(24px) saturate(180%)',
        borderTop: '1px solid var(--b1)',
        zIndex: 100,
        paddingBottom: 'env(safe-area-inset-bottom, 8px)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'stretch', height: 58 }}>
        {NAV_ITEMS.map(item => {
          const isActive   = view === item.id
          const isDisabled = item.id === 'results' && !hasResults
          const Icon = item.icon
          return (
            <button
              key={item.id}
              onClick={() => !isDisabled && onViewChange(item.id)}
              disabled={isDisabled}
              aria-label={item.label}
              aria-current={isActive ? 'page' : undefined}
              style={{
                flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 4,
                background: 'none', border: 'none', cursor: isDisabled ? 'not-allowed' : 'pointer',
                color: isDisabled ? 'var(--t4)' : isActive ? 'var(--accent-light)' : 'var(--t3)',
                fontSize: 10, fontWeight: isActive ? 700 : 500, position: 'relative',
                transition: 'color .15s', opacity: isDisabled ? 0.35 : 1, minHeight: 44,
              }}
            >
              {isActive && (
                <motion.div
                  layoutId="nav-indicator"
                  style={{ position: 'absolute', top: 0, left: '15%', right: '15%', height: 2, background: 'linear-gradient(90deg,#7c6aff,#a78bfa)', borderRadius: '0 0 3px 3px', boxShadow: '0 0 10px rgba(124,106,255,0.6)' }}
                  transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                />
              )}
              <motion.div animate={{ scale: isActive ? 1.15 : 1, y: isActive ? -1 : 0 }} transition={{ type: 'spring', stiffness: 400, damping: 20 }}>
                <Icon size={19} />
              </motion.div>
              <span style={{ letterSpacing: '0.02em' }}>{item.label}</span>
            </button>
          )
        })}
      </div>
    </nav>
  )
}
