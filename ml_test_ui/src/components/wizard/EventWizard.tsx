/**
 * EventWizard — 4-step configuration.
 * All functionality preserved; visual layer refined.
 */
import { useState, useCallback } from 'react'
import {
  BriefcaseBusiness, ChevronRight, ChevronLeft,
  Film, Image, Smartphone, Zap, Sparkles,
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import StepIndicator from './StepIndicator'
import BrandVoiceSlider from './BrandVoiceSlider'
import { Dropdown } from '../ui/Dropdown'
import { EVENT_TYPES } from '../../lib/constants'

export interface WizardConfig {
  eventName: string
  eventDesc: string
  eventType: string
  platforms: string[]
  brandVoice: number
}

interface Props { initialName?: string; onSubmit: (config: WizardConfig) => void; loading?: boolean }

const PLATFORMS = [
  { id: 'linkedin',  label: 'LinkedIn',          icon: BriefcaseBusiness, desc: 'Collage + professional copy', color: '#0a66c2' },
  { id: 'instagram', label: 'Instagram Carousel', icon: Image,             desc: 'Up to 10 slides',            color: '#e1306c' },
  { id: 'stories',   label: 'Instagram Stories',  icon: Smartphone,        desc: '3-4 vertical frames',        color: '#833ab4' },
  { id: 'reel',      label: 'Instagram Reel',     icon: Film,              desc: '30-60s highlight video',     color: '#fd1d1d' },
]

const STEPS = ['Event', 'Type', 'Platforms', 'Review']

const detectEventType = (text: string): string => {
  const t = text.toLowerCase()
  if (t.includes('award') || t.includes('trophy') || t.includes('winner')) return 'awards'
  if (t.includes('workshop') || t.includes('training') || t.includes('hands-on')) return 'workshop'
  if (t.includes('expo') || t.includes('exhibition') || t.includes('trade')) return 'trade_show'
  if (t.includes('networking') || t.includes('mixer') || t.includes('meetup')) return 'networking'
  if (t.includes('launch') || t.includes('unveil') || t.includes('product')) return 'product_launch'
  if (t.includes('corporate') || t.includes('town hall')) return 'corporate'
  if (t.includes('conference') || t.includes('summit') || t.includes('keynote')) return 'conference'
  return 'conference'
}

/* ── Shared input style ─────────────────────────────────────────────────── */
const inputStyle = (active = false): React.CSSProperties => ({
  width: '100%',
  background: active ? 'var(--s3)' : 'var(--s2)',
  border: `1px solid ${active ? 'rgba(124,106,255,0.45)' : 'var(--b1)'}`,
  borderRadius: 10,
  padding: '9px 12px',
  color: 'var(--t1)',
  fontSize: 13,
  fontWeight: 500,
  outline: 'none',
  transition: 'border-color .15s, background .15s, box-shadow .15s',
  boxShadow: active ? '0 0 0 3px rgba(124,106,255,0.08)' : 'none',
})

const labelStyle: React.CSSProperties = {
  display: 'block',
  fontSize: 10,
  color: 'var(--t3)',
  marginBottom: 6,
  textTransform: 'uppercase',
  letterSpacing: '.08em',
  fontWeight: 600,
}

/* ── Step content animation ─────────────────────────────────────────────── */
const stepVariants = {
  enter:  { opacity: 0, x: 10 },
  center: { opacity: 1, x: 0 },
  exit:   { opacity: 0, x: -10 },
}

export default function EventWizard({ initialName = '', onSubmit, loading }: Props) {
  const [step, setStep] = useState(0)
  const [cfg, setCfg] = useState<WizardConfig>({
    eventName: initialName,
    eventDesc: '',
    eventType: 'conference',
    platforms: ['linkedin', 'instagram', 'stories'],
    brandVoice: 30,
  })
  const [nameActive, setNameActive] = useState(false)
  const [descActive, setDescActive] = useState(false)

  const update = useCallback(
    (patch: Partial<WizardConfig>) => setCfg(c => ({ ...c, ...patch })),
    [],
  )

  const togglePlatform = useCallback(
    (id: string) =>
      update({
        platforms: cfg.platforms.includes(id)
          ? cfg.platforms.filter(p => p !== id)
          : [...cfg.platforms, id],
      }),
    [cfg.platforms, update],
  )

  const canNext =
    step === 0 ? cfg.eventName.trim().length > 0
    : step === 2 ? cfg.platforms.length > 0
    : true

  const handleEventNameChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const newName = e.target.value
      update({ eventName: newName, eventType: detectEventType(newName + ' ' + cfg.eventDesc) })
    },
    [cfg.eventDesc, update],
  )

  const handleDescriptionChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const newDesc = e.target.value
      update({ eventDesc: newDesc, eventType: detectEventType(cfg.eventName + ' ' + newDesc) })
    },
    [cfg.eventName, update],
  )

  return (
    <div>
      <StepIndicator steps={STEPS} current={step} />

      {/* ── Step content ─────────────────────────────────────────────────── */}
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={step}
          variants={stepVariants}
          initial="enter"
          animate="center"
          exit="exit"
          transition={{ duration: 0.18, ease: [0.4, 0, 0.2, 1] }}
        >

          {/* Step 0 — Event name */}
          {step === 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div>
                <label style={labelStyle}>Event Name *</label>
                <input
                  autoFocus
                  value={cfg.eventName}
                  onChange={handleEventNameChange}
                  placeholder="e.g. Tech Summit 2025"
                  style={inputStyle(nameActive || cfg.eventName.length > 0)}
                  onFocus={() => setNameActive(true)}
                  onBlur={() => setNameActive(false)}
                  onKeyDown={e => { if (e.key === 'Enter' && canNext) setStep(1) }}
                />
              </div>

              <div>
                <label style={labelStyle}>Description <span style={{ color: 'var(--t4)', fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>(optional)</span></label>
                <input
                  value={cfg.eventDesc}
                  onChange={handleDescriptionChange}
                  placeholder="Annual tech conference with keynotes and networking…"
                  style={inputStyle(descActive)}
                  onFocus={() => setDescActive(true)}
                  onBlur={() => setDescActive(false)}
                />
              </div>

              {/* Auto-detect pill */}
              <div style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                background: 'rgba(124,106,255,0.06)',
                border: '1px solid rgba(124,106,255,0.15)',
                borderRadius: 8,
                padding: '6px 10px',
                alignSelf: 'flex-start',
              }}>
                <Sparkles size={11} color="var(--accent-light)" />
                <span style={{ fontSize: 11, color: 'var(--t3)' }}>
                  Detected:{' '}
                  <strong style={{ color: 'var(--accent-light)', fontWeight: 600 }}>
                    {EVENT_TYPES.find(e => e.value === cfg.eventType)?.label ?? cfg.eventType}
                  </strong>
                </span>
              </div>
            </div>
          )}

          {/* Step 1 — Event type */}
          {step === 1 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <Dropdown
                label="Event Type"
                options={EVENT_TYPES}
                value={cfg.eventType}
                onChange={v => update({ eventType: v })}
              />
              <p style={{ fontSize: 11, color: 'var(--t4)', lineHeight: 1.6 }}>
                Helps the AI generate more relevant captions and select the right assets.
              </p>
            </div>
          )}

          {/* Step 2 — Platforms */}
          {step === 2 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <p style={{ fontSize: 11, color: 'var(--t3)', marginBottom: 6 }}>
                Select platforms to generate content for:
              </p>
              {PLATFORMS.map((p, i) => {
                const active = cfg.platforms.includes(p.id)
                const PlatformIcon = p.icon
                return (
                  <motion.button
                    key={p.id}
                    onClick={() => togglePlatform(p.id)}
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.04, duration: 0.18 }}
                    whileHover={{ scale: 1.005 }}
                    whileTap={{ scale: 0.995 }}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 12,
                      padding: '10px 12px',
                      background: active ? `${p.color}0d` : 'var(--s2)',
                      border: `1px solid ${active ? p.color + '40' : 'var(--b1)'}`,
                      borderRadius: 10,
                      cursor: 'pointer',
                      textAlign: 'left',
                      transition: 'all .15s',
                    }}
                  >
                    {/* Icon */}
                    <div style={{
                      width: 32,
                      height: 32,
                      borderRadius: 8,
                      background: active ? `${p.color}18` : 'var(--s3)',
                      border: `1px solid ${active ? p.color + '35' : 'var(--b1)'}`,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      flexShrink: 0,
                      transition: 'all .15s',
                    }}>
                      <PlatformIcon size={15} color={active ? p.color : 'var(--t3)'} />
                    </div>

                    {/* Label */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, fontSize: 13, color: active ? 'var(--t1)' : 'var(--t2)', lineHeight: 1.2 }}>
                        {p.label}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--t4)', marginTop: 1 }}>{p.desc}</div>
                    </div>

                    {/* Checkbox */}
                    <div style={{
                      width: 16,
                      height: 16,
                      borderRadius: 5,
                      border: `1.5px solid ${active ? p.color : 'var(--b2)'}`,
                      background: active ? p.color : 'transparent',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      flexShrink: 0,
                      transition: 'all .15s',
                    }}>
                      {active && (
                        <motion.svg
                          initial={{ scale: 0, opacity: 0 }}
                          animate={{ scale: 1, opacity: 1 }}
                          transition={{ type: 'spring', stiffness: 500, damping: 25 }}
                          width="9" height="9" viewBox="0 0 9 9" fill="none"
                        >
                          <path d="M1.5 4.5L3.5 6.5L7.5 2.5" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                        </motion.svg>
                      )}
                    </div>
                  </motion.button>
                )
              })}
            </div>
          )}

          {/* Step 3 — Brand voice + review */}
          {step === 3 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <BrandVoiceSlider value={cfg.brandVoice} onChange={v => update({ brandVoice: v })} />

              {/* Summary */}
              <div style={{
                background: 'var(--s2)',
                border: '1px solid var(--b1)',
                borderRadius: 10,
                overflow: 'hidden',
              }}>
                <div style={{
                  padding: '8px 12px',
                  borderBottom: '1px solid var(--b1)',
                  fontSize: 10,
                  color: 'var(--t4)',
                  textTransform: 'uppercase',
                  letterSpacing: '.08em',
                  fontWeight: 600,
                }}>
                  Summary
                </div>
                <div style={{ padding: '4px 0' }}>
                  {[
                    ['Event',     cfg.eventName],
                    ['Type',      EVENT_TYPES.find(e => e.value === cfg.eventType)?.label ?? cfg.eventType],
                    ['Platforms', cfg.platforms.join(', ')],
                    ['Voice',     cfg.brandVoice < 40 ? 'Professional' : cfg.brandVoice < 70 ? 'Balanced' : 'Casual'],
                  ].map(([k, v]) => (
                    <div
                      key={k}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        padding: '7px 12px',
                        fontSize: 12,
                        gap: 12,
                      }}
                    >
                      <span style={{ color: 'var(--t3)', fontWeight: 500, flexShrink: 0 }}>{k}</span>
                      <span style={{
                        color: 'var(--t1)',
                        fontWeight: 600,
                        textAlign: 'right',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                        maxWidth: '60%',
                      }}>
                        {v}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

        </motion.div>
      </AnimatePresence>

      {/* ── Navigation ───────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', gap: 8, marginTop: 20, justifyContent: 'space-between' }}>
        {/* Back */}
        <motion.button
          onClick={() => setStep(s => s - 1)}
          disabled={step === 0}
          whileHover={step === 0 ? {} : { scale: 1.02 }}
          whileTap={step === 0 ? {} : { scale: 0.97 }}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 5,
            padding: '8px 14px',
            background: 'transparent',
            border: '1px solid var(--b1)',
            borderRadius: 9,
            color: step === 0 ? 'var(--t4)' : 'var(--t2)',
            cursor: step === 0 ? 'not-allowed' : 'pointer',
            fontSize: 12,
            fontWeight: 600,
            transition: 'border-color .15s, color .15s',
          }}
        >
          <ChevronLeft size={13} /> Back
        </motion.button>

        {/* Next / Generate */}
        {step < 3 ? (
          <motion.button
            onClick={() => setStep(s => s + 1)}
            disabled={!canNext}
            whileHover={canNext ? { scale: 1.02 } : {}}
            whileTap={canNext ? { scale: 0.97 } : {}}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 5,
              padding: '8px 18px',
              background: canNext
                ? 'linear-gradient(135deg, #7c6aff, #a78bfa)'
                : 'var(--s3)',
              border: 'none',
              borderRadius: 9,
              color: canNext ? '#fff' : 'var(--t4)',
              cursor: canNext ? 'pointer' : 'not-allowed',
              fontSize: 12,
              fontWeight: 700,
              boxShadow: canNext ? '0 2px 12px rgba(124,106,255,0.25)' : 'none',
              transition: 'box-shadow .2s',
            }}
          >
            Next <ChevronRight size={13} />
          </motion.button>
        ) : (
          <motion.button
            onClick={() => onSubmit(cfg)}
            disabled={loading}
            whileHover={loading ? {} : { scale: 1.02, y: -1 }}
            whileTap={loading ? {} : { scale: 0.97 }}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 7,
              padding: '9px 20px',
              background: loading
                ? 'var(--s3)'
                : 'linear-gradient(135deg, #7c6aff, #a855f7)',
              border: 'none',
              borderRadius: 9,
              color: loading ? 'var(--t4)' : '#fff',
              cursor: loading ? 'not-allowed' : 'pointer',
              fontSize: 13,
              fontWeight: 700,
              boxShadow: loading ? 'none' : '0 4px 16px rgba(124,106,255,0.3)',
              transition: 'box-shadow .2s',
            }}
          >
            {loading ? (
              <>
                <span
                  style={{
                    display: 'inline-block',
                    width: 12,
                    height: 12,
                    border: '1.5px solid rgba(255,255,255,0.25)',
                    borderTop: '1.5px solid #fff',
                    borderRadius: '50%',
                    animation: 'spin .7s linear infinite',
                  }}
                />
                Generating…
              </>
            ) : (
              <>
                <Zap size={13} /> Generate Content
              </>
            )}
          </motion.button>
        )}
      </div>
    </div>
  )
}
