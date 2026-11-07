/**
 * HashtagGenerator — all functionality preserved, premium visual upgrade.
 */
import { useState } from 'react'
import { Plus, X, Copy, Check, Hash } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { slug } from '../../lib/formatters'

interface Props { eventName: string; concepts?: string[]; onInsert: (tags: string) => void }

function generateHashtags(eventName: string, concepts: string[]): string[] {
  const base = [
    `#${slug(eventName).replace(/_/g, '')}`,
    '#EventLife', '#ContentCreator', '#BehindTheScenes',
  ]
  const conceptTags = concepts.slice(0, 4)
    .map(c => `#${c.replace(/\s+/g, '').replace(/[^a-zA-Z0-9]/g, '')}`)
    .filter(t => t.length > 2)
  return [...new Set([...base, ...conceptTags])].slice(0, 10)
}

export default function HashtagGenerator({ eventName, concepts = [], onInsert }: Props) {
  const [tags, setTags] = useState<string[]>(() => generateHashtags(eventName, concepts))
  const [custom, setCustom] = useState('')
  const [copied, setCopied] = useState(false)

  const addCustom = () => {
    const t = custom.trim().startsWith('#') ? custom.trim() : `#${custom.trim()}`
    if (t.length > 1 && !tags.includes(t)) { setTags(prev => [...prev, t]); setCustom('') }
  }

  const remove = (t: string) => setTags(prev => prev.filter(x => x !== t))

  const copyAll = () => {
    navigator.clipboard.writeText(tags.join(' '))
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div style={{ background: 'var(--s3)', border: '1px solid var(--b1)', borderRadius: 'var(--rs)', padding: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--t2)', display: 'flex', alignItems: 'center', gap: 5 }}>
          <Hash size={12} color="var(--accent)" /> Hashtags ({tags.length})
        </span>
        <div style={{ display: 'flex', gap: 6 }}>
          <button onClick={copyAll} style={{ display: 'flex', alignItems: 'center', gap: 4, background: 'var(--s4)', border: '1px solid var(--b1)', borderRadius: 6, padding: '4px 10px', cursor: 'pointer', fontSize: 11, color: copied ? 'var(--green)' : 'var(--t2)', transition: 'all .15s' }}>
            {copied ? <><Check size={10} /> Copied</> : <><Copy size={10} /> Copy all</>}
          </button>
          <button onClick={() => onInsert(tags.join(' '))} style={{ background: 'var(--accent)', border: 'none', borderRadius: 6, padding: '4px 10px', cursor: 'pointer', fontSize: 11, color: '#fff', fontWeight: 700, boxShadow: '0 2px 8px rgba(124,106,255,0.3)' }}>
            Insert
          </button>
        </div>
      </div>

      {/* Tag chips */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginBottom: 10 }}>
        <AnimatePresence>
          {tags.map(t => (
            <motion.span key={t} initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.8 }}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 4, background: 'rgba(124,106,255,0.12)', color: 'var(--accent-light)', border: '1px solid rgba(124,106,255,0.25)', borderRadius: 20, padding: '3px 10px', fontSize: 12, fontWeight: 600 }}
            >
              {t}
              <button onClick={() => remove(t)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--t3)', padding: 0, display: 'flex', lineHeight: 1, transition: 'color .15s' }}
                onMouseEnter={e => (e.currentTarget.style.color = 'var(--red)')}
                onMouseLeave={e => (e.currentTarget.style.color = 'var(--t3)')}
              >
                <X size={10} />
              </button>
            </motion.span>
          ))}
        </AnimatePresence>
      </div>

      {/* Add custom */}
      <div style={{ display: 'flex', gap: 6 }}>
        <input
          value={custom}
          onChange={e => setCustom(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') addCustom() }}
          placeholder="Add hashtag…"
          style={{ flex: 1, background: 'var(--s4)', border: '1px solid var(--b1)', borderRadius: 7, padding: '6px 10px', color: 'var(--t1)', fontSize: 12, outline: 'none', transition: 'border-color .15s' }}
          onFocus={e => (e.target.style.borderColor = 'var(--accent)')}
          onBlur={e => (e.target.style.borderColor = 'var(--b1)')}
        />
        <button onClick={addCustom} style={{ background: 'var(--s4)', border: '1px solid var(--b1)', borderRadius: 7, padding: '6px 10px', cursor: 'pointer', color: 'var(--accent-light)', display: 'flex', alignItems: 'center', transition: 'all .15s' }}
          onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'var(--accent-subtle)'; (e.currentTarget as HTMLElement).style.borderColor = 'var(--b-accent)' }}
          onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'var(--s4)'; (e.currentTarget as HTMLElement).style.borderColor = 'var(--b1)' }}
        >
          <Plus size={14} />
        </button>
      </div>
    </div>
  )
}
