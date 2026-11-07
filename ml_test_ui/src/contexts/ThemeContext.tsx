import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'

// Types
// Theme is hard-locked to dark to match Studio cinematic experience.
type Theme = 'dark'
interface ThemeContextType {
  theme: Theme
  setTheme: (theme: Theme) => void
  resolvedTheme: 'dark'
}


// Context
const ThemeContext = createContext<ThemeContextType | undefined>(undefined)

// Provider
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme] = useState<Theme>('dark')
  const [resolvedTheme] = useState<'dark'>('dark')
  // Mount flag removed to avoid state updates in effects (lint).

  // Hard-lock: always mark html as dark.
  useEffect(() => {

    if (typeof document !== 'undefined') {
      document.documentElement.classList.add('dark')
      document.documentElement.setAttribute('data-theme', 'dark')
    }
    try {
      localStorage.setItem('theme', 'dark')
    } catch {
      // ignore
    }
  }, [])

  const value = {
    theme,
    // setTheme is kept for compatibility but does nothing (dark-only)
    setTheme: (_t: Theme) => {},
    resolvedTheme,
  }


  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  )
}


// Hook
export function useTheme() {
  const context = useContext(ThemeContext)
  if (context === undefined) {
    throw new Error('useTheme must be used within ThemeProvider')
  }
  return context
}

