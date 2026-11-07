import { useEffect } from 'react'

type Shortcut = { key: string; ctrl?: boolean; meta?: boolean; shift?: boolean; action: () => void; description: string }

export function useKeyboardShortcuts(shortcuts: Shortcut[]) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      for (const s of shortcuts) {
        const ctrlOk  = !s.ctrl  || e.ctrlKey
        const metaOk  = !s.meta  || e.metaKey
        const shiftOk = !s.shift || e.shiftKey
        const keyOk   = e.key.toLowerCase() === s.key.toLowerCase()
        if (ctrlOk && metaOk && shiftOk && keyOk) {
          e.preventDefault()
          s.action()
          return
        }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [shortcuts])
}

export const SHORTCUTS: Shortcut[] = []  // populated by App
