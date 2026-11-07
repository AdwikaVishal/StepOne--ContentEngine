import { createContext, useContext, useState, useEffect, type ReactNode } from 'react'
import type { AnalyticsEvent } from '../types/enhanced'

// Types
interface AnalyticsState {
  totalJobs: number
  avgTime: number
  platformsUsed: Record<string, number>
  recentJobs: string[]
  feedbackScores: number[]
}

interface AnalyticsContextType {
  analytics: AnalyticsState
  trackEvent: (event: AnalyticsEvent) => void
  getStats: () => AnalyticsState
  exportCSV: () => void
}

// Default
const defaultAnalytics: AnalyticsState = {
  totalJobs: 0,
  avgTime: 0,
  platformsUsed: { linkedin: 0, instagram: 0 },
  recentJobs: [],
  feedbackScores: [],
}

// Context
const AnalyticsContext = createContext<AnalyticsContextType | undefined>(undefined)

// Provider
export function AnalyticsProvider({ children }: { children: ReactNode }) {
  const [analytics, setAnalytics] = useState<AnalyticsState>(defaultAnalytics)

  // Load from IDB/localStorage fallback
  useEffect(() => {
    const loadAnalytics = async () => {
      try {
        // TODO: idb.get('analytics')
        const local = localStorage.getItem('analytics')
        if (local) {
          setAnalytics(JSON.parse(local))
        }
      } catch {}
    }
    loadAnalytics()
  }, [])

  const trackEvent = (event: AnalyticsEvent) => {
    console.log('Analytics:', event) // Backend later

    // Update state
    setAnalytics(prev => {
      const newState = { ...prev }
      // Example updates
      if (event.type === 'job_complete') {
        newState.totalJobs += 1
        newState.recentJobs = [event.jobId || 'unknown', ...newState.recentJobs.slice(0, 9)]
      }
      localStorage.setItem('analytics', JSON.stringify(newState))
      return newState
    })
  }

  const getStats = () => analytics

  const exportCSV = () => {
    const csv = 'Event,JobId,Timestamp\n' + analytics.recentJobs.map(id => `"job_complete",${id},${Date.now()}`).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'analytics.csv'
    a.click()
  }

  return (
    <AnalyticsContext.Provider value={{ analytics, trackEvent, getStats, exportCSV }}>
      {children}
    </AnalyticsContext.Provider>
  )
}

// Hook
export function useAnalytics() {
  const context = useContext(AnalyticsContext)
  if (!context) throw new Error('useAnalytics must be used within AnalyticsProvider')
  return context
}

