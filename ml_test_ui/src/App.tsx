import { useState, useEffect, lazy, Suspense } from 'react'
import type React from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Zap, AlertCircle, BarChart3, Home, FileText, Sparkles, Palette } from 'lucide-react'

import { checkHealth, generateCustom } from './api'
import { ThemeProvider, useTheme } from './contexts/ThemeContext'
import { JobProvider } from './contexts/JobContext'
import { AnalyticsProvider } from './contexts/AnalyticsContext'
import { ToastProvider } from './components/ui/Toast'
import { toast } from './components/ui/Toast'
import BottomNav from './components/navigation/BottomNav'
import { useIsMobile } from './hooks/useMediaQuery'
import { useKeyboardShortcuts } from './hooks/useKeyboardShortcuts'
import { Skeleton } from './components/ui/Skeleton'

const StudioPage    = lazy(() => import('./pages/StudioPage'))
const ResultsPage   = lazy(() => import('./pages/ResultsPage'))
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage'))
const AssetSelectionPage = lazy(() => import('./pages/AssetSelectionPage'))
const StudioMultiImagePage = lazy(() => import('./pages/StudioMultiImagePage'))
import { PhotoIntelligencePage } from './pages/PhotoIntelligencePage'
import { BrandProfilesPage } from './pages/BrandProfilesPage'

export type View = 'studio' | 'studio-multi' | 'asset-selection' | 'results' | 'analytics' | 'photo-intelligence' | 'brand-profiles'

const PageFallback = () => (
  <div style={{ maxWidth: 860, margin: '0 auto', padding: '40px 24px' }}>
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <Skeleton height={48} width="60%" />
      <Skeleton height={200} />
      <Skeleton height={120} />
    </div>
  </div>
)

function AppInner() {
  const [view, setView]       = useState<View>('studio')
  const [result, setResult]   = useState<any>(null)
  const [eventName, setEvent] = useState('')
  const [apiOk, setApiOk]     = useState<boolean | null>(null)
  const [studioData, setStudioData] = useState<any>(null)
  const [currentJobId, setCurrentJobId] = useState<string | null>(null)
  useTheme()
  const isMobile = useIsMobile()

  useEffect(() => {
    checkHealth()
      .then(() => setApiOk(true))
      .catch(() => {
        setApiOk(false)
        toast.error('Backend offline', 'Start the API server to use the app')
      })
  }, [])

  const handleResult = (r: any, name: string) => {
    setResult(r)
    setEvent(name)
    setView('results')
    toast.success('Content generated!', `${name} is ready to review`)
  }

  const handleStudioGenerate = (data: any) => {
    setStudioData(data)
    setCurrentJobId(data.jobId)
    if (data.result?.mode === 'gff') {
      setResult(data.result)
      setEvent(data.eventName || data.result?.event || 'Event')
      setView('results')
      toast.success('Brand content generated!', `${data.eventName || data.result?.event || 'Event'} is ready to review`)
      return
    }
    setView('asset-selection')
  }

  const handleAssetSelectionContinue = async (selectedAssetIds: string[], layouts: any) => {
    try {
      if (currentJobId) {
        const result = await generateCustom({
          job_id: currentJobId,
          asset_ids: selectedAssetIds,
          linkedin_layout: layouts.linkedin,
          story_layout: layouts.story,
          reel_layout: layouts.reel
        })
        setResult(result)
        setEvent(result.event || 'Event')
        setView('results')
        toast.success('Content generated!', `${result.event} is ready to review`)
        return
      }
    } catch (e) {
      console.log('Backend not available, using original behavior')
    }
    handleResult(studioData?.result || {}, studioData?.eventName || 'Event')
  }

  useKeyboardShortcuts([
    { key: 'h', ctrl: true, action: () => setView('studio'),    description: 'Go to Studio' },
    { key: 'a', ctrl: true, action: () => setView('analytics'), description: 'Go to Analytics' },
    { key: 'r', ctrl: true, action: () => result && setView('results'), description: 'Go to Results' },
  ])

  const navItems: { id: View; label: string; icon: React.ReactNode; disabled: boolean }[] = [
    { id: 'studio',    label: 'Studio',    icon: <Home size={14} />,      disabled: false },
    { id: 'studio-multi', label: 'Social Studio', icon: <Sparkles size={14} />, disabled: false },
    { id: 'brand-profiles', label: 'Brand Profiles', icon: <Palette size={14} />, disabled: false },
    { id: 'results',   label: 'Results',   icon: <FileText size={14} />,  disabled: !result },
    { id: 'analytics', label: 'Analytics', icon: <BarChart3 size={14} />, disabled: false },
  ]

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <a href="#main-content" className="skip-link">Skip to content</a>

      {/* ── Navbar ── */}
      <nav
        role="navigation"
        aria-label="Main navigation"
        style={{
          borderBottom: '1px solid var(--b1)',
          background: 'rgba(6,6,9,0.88)',
          backdropFilter: 'blur(24px) saturate(180%)',
          WebkitBackdropFilter: 'blur(24px) saturate(180%)',
          position: 'sticky',
          top: 0,
          zIndex: 100,
          padding: '0 24px',
        }}
      >
        <div style={{ maxWidth: 1200, margin: '0 auto', height: 58, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>

          {/* Logo */}
          <motion.button
            onClick={() => setView('studio')}
            aria-label="Go to Studio"
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.97 }}
            style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer', background: 'none', border: 'none', padding: 0 }}
          >
            <div style={{
              width: 34, height: 34, borderRadius: 10,
              background: 'linear-gradient(135deg,#7c6aff,#a855f7)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0,
              boxShadow: '0 0 20px rgba(124,106,255,0.4)',
            }}>
              <Zap size={16} color="#fff" />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
              <span style={{ fontWeight: 800, fontSize: 14, color: 'var(--t1)', letterSpacing: '-0.02em', lineHeight: 1 }}>
                Content Engine
              </span>
              <span style={{ fontSize: 10, color: 'var(--t3)', letterSpacing: '0.06em', textTransform: 'uppercase', lineHeight: 1, marginTop: 2 }}>
                AI Studio
              </span>
            </div>
          </motion.button>

          {/* Desktop nav */}
          {!isMobile && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 2,
              background: 'var(--s2)', border: '1px solid var(--b1)',
              borderRadius: 40, padding: '4px',
            }}>
              {navItems.map(item => (
                <motion.button
                  key={item.id}
                  onClick={() => !item.disabled && setView(item.id)}
                  disabled={item.disabled}
                  whileHover={item.disabled ? {} : { scale: 1.02 }}
                  whileTap={item.disabled ? {} : { scale: 0.97 }}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 6,
                    padding: '6px 16px', borderRadius: 36, border: 'none',
                    background: view === item.id
                      ? 'linear-gradient(135deg,rgba(124,106,255,0.25),rgba(168,85,247,0.15))'
                      : 'transparent',
                    color: item.disabled ? 'var(--t4)' : view === item.id ? 'var(--accent-light)' : 'var(--t2)',
                    cursor: item.disabled ? 'not-allowed' : 'pointer',
                    fontSize: 13, fontWeight: view === item.id ? 700 : 500,
                    transition: 'all .2s',
                    boxShadow: view === item.id ? '0 0 16px rgba(124,106,255,0.2)' : 'none',
                    outline: view === item.id ? '1px solid var(--b-accent)' : '1px solid transparent',
                  }}
                >
                  {item.icon} {item.label}
                </motion.button>
              ))}
            </div>
          )}

          {/* Right controls */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            {/* API status */}
            <div
              style={{
                display: 'flex', alignItems: 'center', gap: 6, fontSize: 12,
                background: 'var(--s2)', border: '1px solid var(--b1)',
                borderRadius: 20, padding: '5px 12px',
              }}
              aria-live="polite"
            >
              <div style={{
                width: 6, height: 6, borderRadius: '50%',
                background: apiOk === null ? 'var(--yellow)' : apiOk ? 'var(--green)' : 'var(--red)',
                animation: apiOk === null ? 'pulse 1.5s infinite' : apiOk ? 'none' : 'none',
                boxShadow: apiOk ? '0 0 6px var(--green)' : 'none',
              }} />
              <span style={{ color: 'var(--t3)', fontWeight: 500 }}>
                {apiOk === null ? 'Connecting' : apiOk ? 'Live' : 'Offline'}
              </span>
            </div>
          </div>
        </div>
      </nav>

      {/* Offline banner */}
      <AnimatePresence>
        {apiOk === false && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            style={{ background: 'rgba(239,68,68,0.08)', borderBottom: '1px solid rgba(239,68,68,0.2)', overflow: 'hidden' }}
          >
            <div style={{ padding: '10px 24px', display: 'flex', alignItems: 'center', gap: 10 }}>
              <AlertCircle size={14} color="#fca5a5" />
              <span style={{ fontSize: 13, color: '#fca5a5' }}>
                Backend not reachable. Run:{' '}
                <code style={{ background: 'rgba(239,68,68,0.15)', borderRadius: 4, padding: '1px 8px', fontFamily: 'monospace', fontSize: 12 }}>
                  uvicorn api.main:app --reload
                </code>
              </span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Main content */}
      <main id="main-content" style={{ flex: 1 }}>
        <Suspense fallback={<PageFallback />}>
          <AnimatePresence mode="wait">
            {view === 'studio' && (
              <motion.div key="studio"
                initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }} transition={{ duration: 0.3, ease: [.16,1,.3,1] }}
              >
                <StudioPage onResult={handleStudioGenerate} />
              </motion.div>
            )}
            {view === 'studio-multi' && <StudioMultiImagePage onBack={() => setView('studio')} />}
            {view === 'asset-selection' && (
              <motion.div key="asset-selection"
                initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }} transition={{ duration: 0.3, ease: [.16,1,.3,1] }}
              >
                <AssetSelectionPage
                  onContinue={handleAssetSelectionContinue}
                  onBack={() => setView('studio')}
                  eventName={studioData?.eventName || ''}
                  jobId={currentJobId ?? undefined}
                  files={studioData?.files || []}
                />
              </motion.div>
            )}
            {view === 'photo-intelligence' && (
              <motion.div key="photo-intelligence"
                initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }} transition={{ duration: 0.3, ease: [.16,1,.3,1] }}
              >
                <PhotoIntelligencePage onBack={() => setView('studio')} />
              </motion.div>
            )}
            {view === 'brand-profiles' && (
              <motion.div key="brand-profiles"
                initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }} transition={{ duration: 0.3, ease: [.16,1,.3,1] }}
              >
                <BrandProfilesPage onBack={() => setView('studio')} />
              </motion.div>
            )}
            {view === 'results' && result && (
              <motion.div key="results"
                initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }} transition={{ duration: 0.3, ease: [.16,1,.3,1] }}
              >
                <ResultsPage result={result} eventName={eventName} onBack={() => setView('studio')} jobId={currentJobId} />
              </motion.div>
            )}
            {view === 'analytics' && (
              <motion.div key="analytics"
                initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }} transition={{ duration: 0.3, ease: [.16,1,.3,1] }}
              >
                <AnalyticsPage />
              </motion.div>
            )}
          </AnimatePresence>
        </Suspense>
      </main>

      {isMobile && <BottomNav view={view} onViewChange={setView} hasResults={!!result} />}

      {!isMobile && (
        <footer style={{
          borderTop: '1px solid var(--b1)',
          padding: '12px 24px',
          textAlign: 'center',
          fontSize: 11,
          color: 'var(--t4)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 6,
        }}>
          <Sparkles size={11} style={{ color: 'var(--accent)' }} />
          Content & Design Engine · AI-powered social media automation
        </footer>
      )}
    </div>
  )
}

export default function App() {
  return (
    <ThemeProvider>
      <JobProvider>
        <AnalyticsProvider>
          <AppInner />
          <ToastProvider />
        </AnalyticsProvider>
      </JobProvider>
    </ThemeProvider>
  )
}
