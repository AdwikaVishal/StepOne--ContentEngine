/**
 * StudioPage — premium redesign. All functionality preserved.
 */
import { useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import type { Variants } from 'framer-motion'
import {
  BarChart3, BriefcaseBusiness, Camera, CheckCircle, FileText,
  Film, Folder, Image, RefreshCw, Smartphone, AlertTriangle, Zap, Sparkles
} from 'lucide-react'
import FileQueue from '../components/upload/FileQueue'
import StudioDropZone from '../components/upload/StudioDropZone'
import { SkeletonMediaDeck } from '../components/upload/SkeletonMediaDeck'
import BrandSegregationPanel from '../components/BrandSegregationPanel'
import EventWizard, { type WizardConfig } from '../components/wizard/EventWizard'
import { Card, ProgressBar, Spinner, AnimatedBtn } from '../components/ui'
import { useJobPolling } from '../hooks/useJobPolling'
import { generateAsync, generateFast, getJobResult } from '../api'
import { toast } from '../components/ui/Toast'
import { useAnalytics } from '../contexts/AnalyticsContext'
import { saveJob } from '../lib/cache'
import type { JobStatus } from '../api'
import { JOB_STEPS } from '../lib/constants'

interface Props { onResult: (data: { result: any; eventName: string; files: File[]; jobId: string }) => void }

const ORDERED_STEPS = [
  'queued', 'loading_models', 'processing_assets', 'ml_selection',
  'layout_assembly', 'copy_generation', 'case_study', 'finalising', 'done',
]

function StepProgress({ currentStep, pct, failed }: { currentStep: string; pct: number; failed?: boolean }) {
  const currentIdx = ORDERED_STEPS.indexOf(currentStep)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <ProgressBar pct={pct} color={failed ? 'var(--red)' : 'var(--accent)'} label={failed ? 'Failed' : `${pct}%`} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 3, marginTop: 4 }}>
        {ORDERED_STEPS.filter(s => s !== 'queued').map((step, i) => {
          const info = JOB_STEPS[step]
          const StepIcon = info?.icon ?? Folder
          const stepIdx = ORDERED_STEPS.indexOf(step)
          const isDone   = stepIdx < currentIdx
          const isActive = step === currentStep
          const isFuture = stepIdx > currentIdx
          return (
            <motion.div
              key={step}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.04 }}
              style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '6px 12px', borderRadius: 8,
                background: isActive ? 'rgba(124,106,255,0.1)' : 'transparent',
                border: `1px solid ${isActive ? 'rgba(124,106,255,0.25)' : 'transparent'}`,
                transition: 'all .3s',
              }}
            >
              <StepIcon size={13} style={{ opacity: isFuture ? 0.25 : 1, flexShrink: 0, color: isDone ? 'var(--green)' : isActive ? 'var(--accent-light)' : 'var(--t3)' }} />
              <span style={{
                fontSize: 12, flex: 1,
                color: isDone ? 'var(--green)' : isActive ? 'var(--accent-light)' : 'var(--t3)',
                fontWeight: isActive ? 700 : 400,
              }}>
                {info?.label ?? step}
              </span>
              {isDone && <CheckCircle size={12} color="var(--green)" />}
              {isActive && <Spinner size={12} />}
            </motion.div>
          )
        })}
      </div>
    </div>
  )
}

const OUTPUT_CARDS = [
  { icon: BriefcaseBusiness, title: 'LinkedIn Post',      desc: '4-6 image collage + professional copy', color: '#0a66c2' },
  { icon: Image,             title: 'Instagram Carousel', desc: 'Up to 10 slides, 4:5 ratio',            color: '#e1306c' },
  { icon: Film,              title: 'Instagram Reel',     desc: '30-60s highlight video',                color: '#833ab4' },
  { icon: Smartphone,        title: 'Instagram Stories',  desc: '3-4 vertical frames with captions',     color: '#fd1d1d' },
  { icon: FileText,          title: 'Case Study',         desc: 'Structured Markdown document',          color: 'var(--cyan)' },
  { icon: BarChart3,         title: 'Selection Report',   desc: 'AI reasoning for every asset',          color: 'var(--accent-light)' },
]

export default function StudioPage({ onResult }: Props) {
  const [files, setFiles]     = useState<File[]>([])
  const [jobId, setJobId]     = useState<string | null>(null)
  const [error, setError]     = useState<string | null>(null)
  const [submitting, setSub]  = useState(false)
  const [brandMode, setBrandMode] = useState(false)
  const [brands, setBrands] = useState<string[]>(['', '', '', ''])
  const [selectedBrand, setSelectedBrand] = useState('')
  const [renderFilesByBrand, setRenderFilesByBrand] = useState<File[][]>([[], [], [], []])
  const { trackEvent } = useAnalytics()

  const addFiles = useCallback((newFiles: File[]) => {
    setFiles(prev => {
      const existing = new Set(prev.map(f => f.name + f.size))
      const added = newFiles.filter(f => !existing.has(f.name + f.size))
      if (added.length < newFiles.length) toast.warning(`${newFiles.length - added.length} duplicate(s) skipped`)
      if (added.length > 0) toast.success(`${added.length} file${added.length > 1 ? 's' : ''} added`)
      return [...prev, ...added]
    })
  }, [])

  const removeFile = (name: string) => setFiles(p => p.filter(f => f.name !== name))

  const handleWizardSubmit = async (cfg: WizardConfig) => {
    if (!files.length) { toast.error('No files', 'Please upload at least one file first'); return }
    const cleanBrands = brands.map(b => b.trim())
    if (brandMode) {
      if (cleanBrands.filter(Boolean).length !== 4) { toast.error('Brand setup incomplete', 'Enter all four brand names before generating.'); return }
      if (!selectedBrand || !cleanBrands.includes(selectedBrand)) { toast.error('Select content focus', 'Choose which brand should be prioritized.'); return }
      const missingRenderBrands = cleanBrands.filter((_, i) => (renderFilesByBrand[i]?.length ?? 0) === 0)
      if (missingRenderBrands.length) { toast.error('Render images missing', `Add render/logo images for: ${missingRenderBrands.join(', ')}`); return }
    }
    setError(null); setSub(true)
    const loadingId = toast.loading('Submitting job…')
    try {
      const r = brandMode
        ? await generateFast(files, { eventName: cfg.eventName, eventDescription: cfg.eventDesc || cfg.eventName, mode: 'gff', brands: cleanBrands, selectedBrand, renderFilesByBrand, generateReel: cfg.platforms.includes('reel') })
        : await generateAsync(files, cfg.eventName, cfg.eventDesc || cfg.eventName)
      setJobId(r.job_id)
      toast.dismiss(loadingId)
      toast.info(brandMode ? 'Brand job queued' : 'Job queued', `Backend: ${r.backend}`)
      trackEvent({ type: 'job_start', jobId: r.job_id })
    } catch (e: any) {
      toast.dismiss(loadingId)
      const msg = e?.response?.data?.detail ?? e.message ?? 'Submission failed'
      setError(msg); toast.error('Submission failed', msg)
    } finally { setSub(false) }
  }

  const handleDone = async (_s: JobStatus) => {
    if (!jobId) return
    try {
      const result = await getJobResult(jobId)
      saveJob({ id: jobId, eventName: result.event ?? 'Event', timestamp: Date.now(), fileCount: files.length, result })
      trackEvent({ type: 'job_complete', jobId })
      onResult({ result, eventName: result.event ?? 'Event', files, jobId })
    } catch (e: any) {
      const msg = e?.response?.data?.detail ?? e.message
      setError(msg); toast.error('Failed to load results', msg)
    }
  }

  const handleFail = (msg: string) => { setError(msg); toast.error('Generation failed', msg) }
  const updateRenderFiles = (index: number, nextFiles: File[]) => {
    setRenderFilesByBrand(prev => { const next = [...prev]; next[index] = nextFiles; return next })
  }

  const { pct, step, status } = useJobPolling(jobId, handleDone, handleFail)
  const isRunning = !!jobId && !['completed', 'SUCCESS', 'failed', 'FAILURE'].includes(status?.status ?? '')
  const isFailed  = status?.status === 'failed' || status?.status === 'FAILURE'
  const isDone    = status?.status === 'completed' || status?.status === 'SUCCESS'
  const imageCount = files.filter(f => f.type.startsWith('image/')).length
  const videoCount = files.filter(f => f.type.startsWith('video/')).length

  const expandVariants: Variants = {
    initial: { opacity: 0, height: 0, marginBottom: 0 },
    animate: { opacity: 1, height: 'auto', marginBottom: 20, transition: { type: 'spring', stiffness: 200, damping: 24 } },
    exit:    { opacity: 0, height: 0, marginBottom: 0, transition: { duration: 0.2 } },
  }

  return (
    <div className="studio-container fade-in">

      {/* Header */}
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease: [.16,1,.3,1] }}>
        <div className="studio-header">
          <div className="header-title">
            <h1>Studio</h1>
            <p>Upload media · Configure event · Generate AI content</p>
          </div>
          <div className="toggle-container">
            <span className="toggle-label">Brand Mode</span>
            <div
              className={`toggle-switch ${brandMode ? 'active' : ''}`}
              onClick={() => { if (!jobId) setBrandMode(!brandMode) }}
              role="switch"
              aria-checked={brandMode}
              tabIndex={0}
              onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); if (!jobId) setBrandMode(!brandMode) } }}
            >
              <div className="toggle-knob" />
            </div>
          </div>
        </div>
      </motion.div>

      {/* Upload Zone */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.05, ease: [.16,1,.3,1] }}
        style={{ marginBottom: 12 }}
      >
        <Card style={{ padding: 0, overflow: 'hidden' }}>
          <div style={{ padding: '16px 16px 0' }}>
            <StudioDropZone onFiles={addFiles} files={files} isProcessing={submitting} />
          </div>
          <div style={{ padding: '0 16px 16px' }}>
            <FileQueue files={files} onRemove={removeFile} />
            {!jobId && files.length > 0 && submitting && <SkeletonMediaDeck count={12} />}
          </div>
        </Card>
      </motion.div>

      {/* Stats Bar */}
      <AnimatePresence>
        {files.length > 0 && !jobId && (
          <motion.div variants={expandVariants} initial="initial" animate="animate" exit="exit">
            <div className="stats-bar">
              <div className="stat-item">
                <div className="stat-icon"><Camera size={16} /></div>
                <div className="stat-info"><span className="stat-value">{imageCount}</span><span className="stat-label">Images</span></div>
              </div>
              <div style={{ width: 1, height: 32, background: 'var(--b1)' }} />
              <div className="stat-item">
                <div className="stat-icon"><Film size={16} /></div>
                <div className="stat-info"><span className="stat-value">{videoCount}</span><span className="stat-label">Videos</span></div>
              </div>
              <div style={{ width: 1, height: 32, background: 'var(--b1)' }} />
              <div className="stat-item">
                <div className="stat-icon"><Folder size={16} /></div>
                <div className="stat-info"><span className="stat-value">{files.length}</span><span className="stat-label">Total</span></div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Brand Segregation */}
      <AnimatePresence>
        {brandMode && files.length > 0 && !jobId && (
          <motion.div variants={expandVariants} initial="initial" animate="animate" exit="exit" className="expandable-section">
            <div className="expandable-content">
              <BrandSegregationPanel
                brands={brands} selectedBrand={selectedBrand} renderFilesByBrand={renderFilesByBrand}
                onBrandsChange={setBrands} onSelectedBrandChange={setSelectedBrand} onRenderFilesChange={updateRenderFiles}
              />
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Event Wizard */}
      <AnimatePresence>
        {files.length > 0 && !jobId && (
          <motion.div variants={expandVariants} initial="initial" animate="animate" exit="exit">
            <Card style={{ padding: '18px 20px' }}>
              {/* Compact wizard header */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 18, paddingBottom: 14, borderBottom: '1px solid var(--b1)' }}>
                <div style={{
                  width: 28, height: 28, borderRadius: 8,
                  background: 'rgba(124,106,255,0.08)',
                  border: '1px solid rgba(124,106,255,0.18)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  flexShrink: 0,
                }}>
                  <Sparkles size={13} color="var(--accent-light)" />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <h2 style={{ fontSize: 13, fontWeight: 700, color: 'var(--t1)', lineHeight: 1.2 }}>Configure Event</h2>
                  <p style={{ fontSize: 11, color: 'var(--t4)', marginTop: 1 }}>
                    {brandMode ? 'Brand mode — photos segregated by visual references.' : 'Set up event details before generating'}
                  </p>
                </div>
              </div>
              <EventWizard initialName="" onSubmit={handleWizardSubmit} loading={submitting} />
            </Card>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Job Progress */}
      <AnimatePresence>
        {jobId && (
          <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} style={{ marginBottom: 20 }}>
            <Card glow={isRunning} style={{
              border: `1px solid ${isFailed ? 'rgba(239,68,68,0.3)' : isDone ? 'rgba(16,185,129,0.3)' : 'var(--b-accent)'}`,
              background: isFailed ? 'rgba(239,68,68,0.04)' : isDone ? 'rgba(16,185,129,0.04)' : 'rgba(124,106,255,0.04)',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
                {isRunning
                  ? <Spinner size={18} />
                  : isFailed
                  ? <AlertTriangle size={18} color="var(--red)" />
                  : <CheckCircle size={18} color="var(--green)" />
                }
                <span style={{ fontWeight: 700, fontSize: 15, color: isFailed ? 'var(--red)' : isDone ? 'var(--green)' : 'var(--t1)' }}>
                  {isFailed ? 'Generation failed' : isDone ? 'Generation complete!' : 'Generating content…'}
                </span>
                <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--t3)', background: 'var(--s3)', borderRadius: 6, padding: '3px 10px', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  {status?.backend === 'celery' ? <Zap size={10} /> : <RefreshCw size={10} />}
                  {status?.backend === 'celery' ? 'Celery' : 'In-process'}
                </span>
              </div>
              <StepProgress currentStep={step} pct={pct} failed={isFailed} />
              <p style={{ fontSize: 10, color: 'var(--t4)', marginTop: 10, fontFamily: 'monospace' }}>job: {jobId}</p>
            </Card>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Error */}
      <AnimatePresence>
        {error && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} style={{ marginBottom: 20 }}>
            <Card style={{ borderColor: 'rgba(239,68,68,0.3)', background: 'rgba(239,68,68,0.04)' }}>
              <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                <AlertTriangle size={16} color="var(--red)" style={{ flexShrink: 0, marginTop: 2 }} />
                <div style={{ flex: 1 }}>
                  <p style={{ color: 'var(--red)', fontWeight: 700, marginBottom: 4, fontSize: 14 }}>Error</p>
                  <p style={{ color: '#fca5a5', fontSize: 13 }}>{error}</p>
                </div>
              </div>
              <AnimatedBtn variant="ghost" size="sm" style={{ marginTop: 12 }} label="Try again" onClick={() => { setError(null); setJobId(null) }}>
                Try again
              </AnimatedBtn>
            </Card>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Output cards */}
      {!jobId && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.35 }}
          style={{ marginTop: 36 }}
        >
          {/* Separator */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
            <div style={{ flex: 1, height: 1, background: 'linear-gradient(90deg, transparent, var(--b1))' }} />
            <span style={{
              fontSize: 10,
              color: 'var(--t4)',
              textTransform: 'uppercase',
              letterSpacing: '.1em',
              fontWeight: 600,
              whiteSpace: 'nowrap',
            }}>
              What gets generated
            </span>
            <div style={{ flex: 1, height: 1, background: 'linear-gradient(90deg, var(--b1), transparent)' }} />
          </div>

          {/* Cards grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8 }}>
            {OUTPUT_CARDS.map(({ icon: OutputIcon, title, desc, color }, i) => (
              <motion.div
                key={title}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.35 + i * 0.05, ease: [.16, 1, .3, 1] }}
                whileHover={{ y: -2, borderColor: 'var(--b2)' }}
                style={{
                  background: 'var(--s2)',
                  border: '1px solid var(--b1)',
                  borderRadius: 12,
                  padding: '14px 13px',
                  cursor: 'default',
                  transition: 'border-color .2s, transform .2s',
                }}
              >
                <div style={{
                  width: 30,
                  height: 30,
                  borderRadius: 8,
                  background: `${color}12`,
                  border: `1px solid ${color}25`,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  marginBottom: 10,
                }}>
                  <OutputIcon size={15} color={color} />
                </div>
                <div style={{ fontWeight: 700, fontSize: 12, marginBottom: 3, color: 'var(--t1)', lineHeight: 1.3 }}>{title}</div>
                <div style={{ fontSize: 10, color: 'var(--t4)', lineHeight: 1.5 }}>{desc}</div>
              </motion.div>
            ))}
          </div>
        </motion.div>
      )}
    </div>
  )
}
