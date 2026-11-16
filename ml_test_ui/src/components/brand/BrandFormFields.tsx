/**
 * Brand form field controls — chips input, selects with char counters,
 * color picker, logo/reference uploaders, and the per-kind field renderer.
 * All controls map 1:1 onto the backend 45-field flat schema.
 */
import { useRef, useState } from 'react'
import { Image as ImageIcon, Plus, Upload, X } from 'lucide-react'
import type { BrandFieldDef } from '../../lib/brandProfile'
import { assetUrl, TONE_OPTIONS } from '../../lib/brandProfile'

const MAX_CHIPS = 50
const MAX_CHIP_LEN = 200
const HEX_RE = /^#[0-9a-fA-F]{6}$/

/* ── Chips (multi-select list fields) ─────────────────────────────────────── */

export function ChipsInput({
  id, value, onChange, placeholder,
}: {
  id: string
  value: string[]
  onChange: (v: string[]) => void
  placeholder?: string
}) {
  const [draft, setDraft] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const commit = (raw: string) => {
    const item = raw.trim().slice(0, MAX_CHIP_LEN)
    if (!item) return
    if (value.length >= MAX_CHIPS || value.includes(item)) {
      setDraft('')
      return
    }
    onChange([...value, item])
    setDraft('')
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      commit(draft)
    } else if (e.key === 'Backspace' && !draft && value.length) {
      onChange(value.slice(0, -1))
    }
  }

  return (
    <div className="bp-chips" onClick={() => inputRef.current?.focus()} role="presentation">
      {value.map(item => (
        <span key={item} className="bp-chip">
          {item}
          <button
            type="button"
            className="bp-chip__x"
            aria-label={`Remove ${item}`}
            onClick={e => { e.stopPropagation(); onChange(value.filter(v => v !== item)) }}
          >
            <X size={10} />
          </button>
        </span>
      ))}
      <input
        id={id}
        ref={inputRef}
        className="bp-chips__input"
        value={draft}
        placeholder={value.length === 0 ? placeholder : ''}
        onChange={e => setDraft(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => commit(draft)}
        maxLength={MAX_CHIP_LEN}
        disabled={value.length >= MAX_CHIPS}
      />
    </div>
  )
}

/* ── Brand colors ─────────────────────────────────────────────────────────── */

export function ColorField({ id, value, onChange }: { id: string; value: string[]; onChange: (v: string[]) => void }) {
  const [draft, setDraft] = useState('')
  const pickerId = `${id}-picker`

  const add = (raw: string) => {
    const hex = raw.trim()
    if (!HEX_RE.test(hex)) return
    if (!value.includes(hex) && value.length < 50) onChange([...value, hex.toUpperCase()])
    setDraft('')
  }

  return (
    <div className="bp-color-field">
      <div className="bp-swatches-preview" style={{ marginBottom: 8 }}>
        {value.filter(c => HEX_RE.test(c)).map(c => (
          <span key={c} className="bp-color-chip">
            <span className="bp-swatch" style={{ background: c }} aria-hidden="true" />
            <code>{c}</code>
            <button
              type="button"
              className="bp-chip__x"
              aria-label={`Remove color ${c}`}
              onClick={() => onChange(value.filter(v => v !== c))}
            >
              <X size={10} />
            </button>
          </span>
        ))}
        {value.length === 0 && <span className="bp-hint">No brand colors yet.</span>}
      </div>
      <div className="bp-color-add">
        <input
          type="color"
          id={pickerId}
          className="bp-color-picker"
          value={HEX_RE.test(draft) ? draft : '#7c6aff'}
          onChange={e => add(e.target.value)}
          aria-label="Pick a brand color"
        />
        <input
          id={id}
          className="bp-input bp-color-hex"
          value={draft}
          placeholder="#7C6AFF"
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); add(draft) } }}
          onBlur={() => add(draft)}
          maxLength={7}
        />
        <button type="button" className="bp-color-add-btn" onClick={() => add(draft)} aria-label="Add color">
          <Plus size={13} />
        </button>
      </div>
    </div>
  )
}

/* ── Logo & visual references ─────────────────────────────────────────────── */

export function LogoField({
  currentPath, fileName, onFile,
}: {
  currentPath?: string | null
  fileName?: string | null
  onFile: (f: File | null) => void
}) {
  const preview = fileName ? null : assetUrl(currentPath)
  return (
    <div className="bp-asset-row">
      <div className="bp-logo-preview" aria-hidden={!preview}>
        {preview ? (
          <img src={preview} alt="Brand logo preview" className="bp-logo-img" />
        ) : (
          <ImageIcon size={18} />
        )}
      </div>
      <label className="bp-file">
        <Upload size={14} />
        <span className="bp-file__name">{fileName || (currentPath ? 'Replace logo…' : 'Choose a logo…')}</span>
        <input
          type="file"
          accept="image/png,image/jpeg,image/webp,image/svg+xml"
          onChange={e => onFile(e.target.files?.[0] || null)}
        />
      </label>
      {fileName && currentPath && (
        <button type="button" className="bp-link-btn" onClick={() => onFile(null)}>
          Undo replacement
        </button>
      )}
    </div>
  )
}

export function RefsField({
  currentRefs, files, onFiles,
}: {
  currentRefs?: string[]
  files: File[]
  onFiles: (f: File[]) => void
}) {
  return (
    <div className="bp-asset-row">
      <div className="bp-ref-thumbs" aria-hidden="true">
        {(currentRefs ?? []).slice(0, 4).map(ref => {
          const url = assetUrl(ref)
          return url ? <img key={ref} src={url} alt="" className="bp-ref-thumb" /> : null
        })}
      </div>
      <label className="bp-file">
        <Upload size={14} />
        <span className="bp-file__name">
          {files.length
            ? `${files.length} file${files.length > 1 ? 's' : ''} selected`
            : (currentRefs ?? []).length
              ? `Add references (${(currentRefs ?? []).length} existing)`
              : 'Choose files…'}
        </span>
        <input
          type="file"
          multiple
          accept="image/png,image/jpeg,image/webp,image/svg+xml,application/pdf"
          onChange={e => onFiles(Array.from(e.target.files || []))}
        />
      </label>
    </div>
  )
}

/* ── Per-kind field renderer ──────────────────────────────────────────────── */

export interface BrandFieldProps {
  def: BrandFieldDef
  value: any
  onChange: (v: any) => void
  id: string
  logoFileName?: string | null
  onLogoFile?: (f: File | null) => void
  refFiles?: File[]
  onRefFiles?: (f: File[]) => void
}

export function BrandField(props: BrandFieldProps) {
  const { def, value, onChange, id } = props

  if (def.kind === 'chips') {
    return <ChipsInput id={id} value={Array.isArray(value) ? value : []} onChange={onChange} placeholder={def.placeholder} />
  }
  if (def.kind === 'color') {
    return <ColorField id={id} value={Array.isArray(value) ? value : []} onChange={onChange} />
  }
  if (def.kind === 'logo') {
    return (
      <LogoField
        currentPath={value}
        fileName={props.logoFileName ?? null}
        onFile={f => props.onLogoFile?.(f)}
      />
    )
  }
  if (def.kind === 'refs') {
    return (
      <RefsField
        currentRefs={Array.isArray(value) ? value : []}
        files={props.refFiles ?? []}
        onFiles={f => props.onRefFiles?.(f)}
      />
    )
  }
  if (def.kind === 'select') {
    const options = def.options ?? []
    const placeholder = def.placeholder ?? 'Not set'
    // Preserve unknown server-provided values (legacy tone values, etc.).
    const extra = value && !options.includes(value) ? [value] : []
    return (
      <select id={id} className="bp-select" value={value ?? ''} onChange={e => onChange(e.target.value)}>
        {extra.map(v => <option key={v} value={v}>{v}</option>)}
        {options.map(opt => (
          <option key={opt || '__none'} value={opt}>
            {opt === '' ? placeholder : opt.charAt(0).toUpperCase() + opt.slice(1)}
          </option>
        ))}
      </select>
    )
  }
  if (def.kind === 'textarea') {
    return (
      <textarea
        id={id}
        className="bp-textarea"
        value={value ?? ''}
        maxLength={def.max}
        placeholder={def.placeholder}
        onChange={e => onChange(e.target.value)}
      />
    )
  }
  // text (default)
  return (
    <input
      id={id}
      className="bp-input"
      value={value ?? ''}
      maxLength={def.max}
      placeholder={def.placeholder}
      onChange={e => onChange(e.target.value)}
    />
  )
}

/** Character counter shown under long text inputs (backend limits). */
export function CharCounter({ value, max }: { value: any; max?: number }) {
  if (!max) return null
  const len = typeof value === 'string' ? value.length : 0
  if (len < max * 0.8) return null
  return (
    <span className={`bp-counter${len >= max ? ' bp-counter--max' : ''}`} aria-hidden="true">
      {len}/{max}
    </span>
  )
}

export const BRAND_TONE_OPTIONS = TONE_OPTIONS
