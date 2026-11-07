import { useEffect, useState } from 'react'
import {
  Heart, MessageCircle, Send, Bookmark, MoreHorizontal,
  ChevronLeft, ChevronRight, Globe, ThumbsUp, Lightbulb, Repeat2, Film
} from 'lucide-react'
import { motion } from 'framer-motion'

// All paths are relative — served through Vite proxy (/output, /uploads → :8000)
const img = (p: string) => p ?? ''
const PORTRAIT_PREVIEW_STYLE = {
  position: 'relative' as const,
  width: 220,
  aspectRatio: '9 / 16',
  maxHeight: 390,
  background: '#000',
}

/* ── Shared wrapper that adds a premium "device frame" feel ── */
function PreviewShell({ children, label }: { children: React.ReactNode; label?: string }) {
  return (
    <div>
      {label && (
        <p style={{ fontSize: 11, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '.07em', marginBottom: 10, fontWeight: 700 }}>
          {label}
        </p>
      )}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        style={{
          borderRadius: 16,
          overflow: 'hidden',
          boxShadow: '0 24px 64px rgba(0,0,0,0.6), 0 4px 16px rgba(0,0,0,0.4)',
          border: '1px solid rgba(255,255,255,0.08)',
          position: 'relative',
        }}
      >
        {children}
      </motion.div>
    </div>
  )
}

// ── LinkedIn ──────────────────────────────────────────────────────────────────
export function LinkedInPreview({ images, caption, name }: { images: string[]; caption: string; name: string }) {
  const g = images.slice(0, 6)
  const cols = g.length <= 1 ? 1 : g.length <= 2 ? 2 : g.length <= 3 ? 3 : g.length <= 4 ? 2 : 3
  const rows = Math.ceil(g.length / cols)

  return (
    <PreviewShell>
      <div style={{ background: '#fff', fontFamily: '-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif', maxWidth: 560 }}>
        {/* Header */}
        <div style={{ padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 48, height: 48, borderRadius: '50%', background: 'linear-gradient(135deg,#7c6aff,#a78bfa)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 800, fontSize: 20, flexShrink: 0 }}>
            {name[0]?.toUpperCase()}
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 700, fontSize: 14, color: '#000' }}>{name}</div>
            <div style={{ fontSize: 12, color: '#666', display: 'flex', alignItems: 'center', gap: 4 }}>
              Just now · <Globe size={11} />
            </div>
          </div>
          <MoreHorizontal size={20} color="#666" />
        </div>

        {/* Caption */}
        <div style={{ padding: '0 16px 12px', fontSize: 14, color: '#000', lineHeight: 1.65, whiteSpace: 'pre-wrap' }}>
          {caption.slice(0, 300)}{caption.length > 300 ? '…' : ''}
        </div>

        {/* Image grid */}
        {g.length > 0 && (
          <div style={{ display: 'grid', gridTemplateColumns: `repeat(${cols},1fr)`, gridTemplateRows: `repeat(${rows},1fr)`, gap: 2, height: Math.min(360, 180 * rows) }}>
            {g.map((src, i) => (
              <div key={i} style={{ overflow: 'hidden', position: 'relative' }}>
                <img src={img(src)} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
                {i === 5 && images.length > 6 && (
                  <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontSize: 22, fontWeight: 700 }}>
                    +{images.length - 6}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Reactions */}
        <div style={{ padding: '8px 16px 4px', borderTop: '1px solid #e8e8e8', fontSize: 12, color: '#666', display: 'flex', alignItems: 'center', gap: 4 }}>
          <ThumbsUp size={13} /><Heart size={13} /><Lightbulb size={13} />
          <span style={{ marginLeft: 4 }}>247 · 38 comments</span>
        </div>
        <div style={{ display: 'flex', borderTop: '1px solid #e8e8e8' }}>
          {[
            { icon: ThumbsUp, label: 'Like' },
            { icon: MessageCircle, label: 'Comment' },
            { icon: Repeat2, label: 'Repost' },
            { icon: Send, label: 'Send' },
          ].map(({ icon: ActionIcon, label }) => (
            <button key={label} style={{ flex: 1, padding: '10px 4px', background: 'none', border: 'none', color: '#666', fontSize: 13, fontWeight: 500, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5 }}>
              <ActionIcon size={15} /> {label}
            </button>
          ))}
        </div>
      </div>
    </PreviewShell>
  )
}

// ── Instagram Carousel ────────────────────────────────────────────────────────
export function InstagramCarousel({ images, caption, name }: { images: string[]; caption: string; name: string }) {
  const [i, setI] = useState(0)
  const slides = images.slice(0, 10)

  return (
    <PreviewShell>
      <div style={{ background: '#fff', fontFamily: '-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif', maxWidth: 400 }}>
        {/* Header */}
        <div style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 34, height: 34, borderRadius: '50%', background: 'linear-gradient(45deg,#f09433,#e6683c,#dc2743,#cc2366,#bc1888)', padding: 2, flexShrink: 0 }}>
            <div style={{ width: '100%', height: '100%', borderRadius: '50%', background: 'linear-gradient(135deg,#7c6aff,#a78bfa)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 700, fontSize: 13 }}>
              {name[0]?.toUpperCase()}
            </div>
          </div>
          <span style={{ fontWeight: 700, fontSize: 13, color: '#000', flex: 1 }}>{name.toLowerCase().replace(/\s+/g, '_')}</span>
          <MoreHorizontal size={18} color="#000" />
        </div>

        {/* Image */}
        <div style={{ position: 'relative', aspectRatio: '4/5', background: '#000', overflow: 'hidden' }}>
          {slides[i]
            ? <img src={img(slides[i])} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
            : <div style={{ width: '100%', height: '100%', background: '#111' }} />
          }
          {slides.length > 1 && (
            <>
              <button onClick={() => setI(x => Math.max(0, x - 1))} style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', background: 'rgba(255,255,255,.9)', border: 'none', borderRadius: '50%', width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}>
                <ChevronLeft size={16} />
              </button>
              <button onClick={() => setI(x => Math.min(slides.length - 1, x + 1))} style={{ position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)', background: 'rgba(255,255,255,.9)', border: 'none', borderRadius: '50%', width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}>
                <ChevronRight size={16} />
              </button>
              <div style={{ position: 'absolute', top: 10, right: 10, background: 'rgba(0,0,0,.55)', color: '#fff', borderRadius: 12, padding: '2px 8px', fontSize: 12, fontWeight: 600 }}>
                {i + 1}/{slides.length}
              </div>
              <div style={{ position: 'absolute', bottom: 10, left: '50%', transform: 'translateX(-50%)', display: 'flex', gap: 4 }}>
                {slides.map((_, j) => (
                  <div key={j} style={{ width: 6, height: 6, borderRadius: '50%', background: j === i ? '#3b82f6' : 'rgba(255,255,255,.5)', transition: 'background .2s' }} />
                ))}
              </div>
            </>
          )}
        </div>

        {/* Actions */}
        <div style={{ padding: '10px 14px 4px', display: 'flex', alignItems: 'center', gap: 14 }}>
          <Heart size={22} color="#000" /><MessageCircle size={22} color="#000" /><Send size={22} color="#000" />
          <Bookmark size={22} color="#000" style={{ marginLeft: 'auto' }} />
        </div>
        <div style={{ padding: '4px 14px', fontSize: 13, fontWeight: 700, color: '#000' }}>1,247 likes</div>
        <div style={{ padding: '2px 14px 14px', fontSize: 13, color: '#000', lineHeight: 1.5 }}>
          <span style={{ fontWeight: 700 }}>{name.toLowerCase().replace(/\s+/g, '_')}</span>{' '}
          {caption.slice(0, 140)}{caption.length > 140 ? '… more' : ''}
        </div>
      </div>
    </PreviewShell>
  )
}

// ── Instagram Stories ─────────────────────────────────────────────────────────
export function InstagramStories({ images, captions, name }: { images: string[]; captions: string[]; name: string }) {
  const [i, setI] = useState(0)
  const frames = images.slice(0, 4)
  const hasFrames = frames.length > 0

  useEffect(() => {
    if (!hasFrames) {
      if (i !== 0) setI(0)
      return
    }
    if (i > frames.length - 1) setI(frames.length - 1)
  }, [hasFrames, frames.length, i])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14 }}>
      <PreviewShell>
        <div style={PORTRAIT_PREVIEW_STYLE}>
          {/* Progress bars */}
          <div style={{ position: 'absolute', top: 10, left: 10, right: 10, display: 'flex', gap: 3, zIndex: 10 }}>
            {frames.map((_, j) => (
              <div key={j} style={{ flex: 1, height: 2.5, borderRadius: 2, background: j < i ? '#fff' : j === i ? 'rgba(255,255,255,.9)' : 'rgba(255,255,255,.3)' }} />
            ))}
          </div>

          {/* Header */}
          <div style={{ position: 'absolute', top: 22, left: 10, right: 10, display: 'flex', alignItems: 'center', gap: 8, zIndex: 10 }}>
            <div style={{ width: 28, height: 28, borderRadius: '50%', background: 'linear-gradient(45deg,#f09433,#dc2743,#bc1888)', padding: 1.5 }}>
              <div style={{ width: '100%', height: '100%', borderRadius: '50%', background: 'linear-gradient(135deg,#7c6aff,#a78bfa)' }} />
            </div>
            <span style={{ color: '#fff', fontSize: 11, fontWeight: 700 }}>{name.slice(0, 18)}</span>
            <span style={{ color: 'rgba(255,255,255,.6)', fontSize: 10, marginLeft: 2 }}>now</span>
          </div>

          {/* Image */}
          {frames[i]
            ? <img src={img(frames[i])} alt="" style={{ width: '100%', height: '100%', objectFit: 'contain', objectPosition: 'center', display: 'block', background: '#000' }} />
            : <div style={{ width: '100%', height: '100%', background: 'linear-gradient(135deg,#1a1a24,#2a2a3a)' }} />
          }

          {/* Caption overlay */}
          {captions[i] && (
            <div style={{ position: 'absolute', bottom: 50, left: 12, right: 12, background: 'rgba(0,0,0,.65)', borderRadius: 10, padding: '8px 10px', color: '#fff', fontSize: 12, textAlign: 'center', backdropFilter: 'blur(6px)' }}>
              {captions[i]}
            </div>
          )}

          {/* Tap zones */}
          <div style={{ position: 'absolute', inset: 0, display: 'flex' }}>
            <div
              style={{ flex: 1, cursor: hasFrames ? 'pointer' : 'default', pointerEvents: hasFrames ? 'auto' : 'none' }}
              onClick={() => setI(x => Math.max(0, x - 1))}
            />
            <div
              style={{ flex: 1, cursor: hasFrames ? 'pointer' : 'default', pointerEvents: hasFrames ? 'auto' : 'none' }}
              onClick={() => setI(x => Math.min(frames.length - 1, x + 1))}
            />
          </div>
        </div>
      </PreviewShell>

      {/* Thumbnails */}
      <div style={{ display: 'flex', gap: 6 }}>
        {frames.map((src, j) => (
          <motion.div key={j} onClick={() => setI(j)} whileHover={{ scale: 1.08 }} whileTap={{ scale: 0.95 }}
            style={{ width: 44, height: 44, borderRadius: 10, overflow: 'hidden', cursor: 'pointer', border: `2px solid ${j === i ? 'var(--accent)' : 'transparent'}`, flexShrink: 0, boxShadow: j === i ? '0 0 10px rgba(124,106,255,0.4)' : 'none', transition: 'all .2s' }}
          >
            <img src={img(src)} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
          </motion.div>
        ))}
      </div>
    </div>
  )
}

// ── Instagram Reel ────────────────────────────────────────────────────────────
export function InstagramReel({ videoUrl, caption, name }: { videoUrl?: string; caption: string; name: string }) {
  return (
    <PreviewShell>
      <div style={PORTRAIT_PREVIEW_STYLE}>
        {videoUrl
          ? <video src={videoUrl} controls style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
          : <div style={{ width: '100%', height: '100%', background: 'linear-gradient(135deg,#1a1a24,#2a2a3a)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12 }}>
              <div style={{ width: 56, height: 56, borderRadius: '50%', background: 'rgba(124,106,255,0.15)', border: '1px solid rgba(124,106,255,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <Film size={24} color="var(--accent-light)" />
              </div>
              <span style={{ color: 'var(--t3)', fontSize: 12 }}>Reel preview</span>
            </div>
        }

        {/* Gradient overlay */}
        <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, padding: '60px 12px 16px', background: 'linear-gradient(transparent,rgba(0,0,0,.88))' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
            <div style={{ width: 24, height: 24, borderRadius: '50%', background: 'linear-gradient(135deg,#7c6aff,#a78bfa)' }} />
            <span style={{ color: '#fff', fontSize: 12, fontWeight: 700 }}>{name.toLowerCase().replace(/\s+/g, '_')}</span>
          </div>
          <p style={{ color: '#fff', fontSize: 11, lineHeight: 1.4 }}>{caption.slice(0, 80)}…</p>
        </div>

        {/* Side actions */}
        <div style={{ position: 'absolute', right: 10, bottom: 80, display: 'flex', flexDirection: 'column', gap: 16, alignItems: 'center' }}>
          {[Heart, MessageCircle, Send].map((Icon, j) => (
            <div key={j} style={{ width: 36, height: 36, borderRadius: '50%', background: 'rgba(255,255,255,.15)', display: 'flex', alignItems: 'center', justifyContent: 'center', backdropFilter: 'blur(4px)' }}>
              <Icon size={18} color="#fff" />
            </div>
          ))}
        </div>
      </div>
    </PreviewShell>
  )
}
