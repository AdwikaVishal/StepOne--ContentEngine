/**
 * VisualReferencesPanel — Brand Intelligence Phase 1.
 *
 * Visual reference management for one brand: multiple logo variants and
 * categorized reference photographs with upload, preview, replace,
 * recategorize, notes and removal, plus the reference-quality report
 * (counts, category coverage, diversity, warnings).
 *
 * All data comes from the real /api/brand-intel and /api/studio endpoints —
 * no mock assets, no local-only "AI" claims. Parent is notified of server
 * profile changes (logo_path / visual_references) via onProfileChanged so
 * the surrounding form stays in sync.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import {
  AlertTriangle, ImagePlus, Info, Pencil, Plus, RefreshCw, Replace,
  ScanLine, Trash2, Upload, X,
} from 'lucide-react'
import { Card, Spinner, Tag, AnimatedBtn } from '../ui'
import { Modal } from '../ui/Modal'
import { toast } from '../ui/Toast'
import {
  listBrandAssets, updateBrandAsset, deleteBrandAsset,
  replaceBrandAsset, uploadBrandAsset, getReferenceQuality,
  type BrandAssetEntry, type ReferenceQualityReport,
} from '../../api'
import { assetUrl, type BrandProfile } from '../../lib/brandProfile'

const REFERENCE_CATEGORIES = [
  'product', 'packaging', 'signage', 'storefront', 'banner',
  'uniform', 'label', 'placement', 'other',
] as const

const errMsg = (e: unknown, fallback: string) => {
  const err = e as { response?: { data?: { detail?: unknown } }; message?: unknown }
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (typeof err?.message === 'string' && err.message) return err.message
  return fallback
}

const formatBytes = (bytes: number) => {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const severityIcon = (severity: string) =>
  severity === 'error' ? AlertTriangle : severity === 'warning' ? AlertTriangle : Info

interface Props {
  profileId: string
  /** Called with the refreshed server profile after asset mutations. */
  onProfileChanged?: (serverProfile: BrandProfile) => void
}

export function VisualReferencesPanel({ profileId, onProfileChanged }: Props) {
  const [assets, setAssets] = useState<BrandAssetEntry[]>([])
  const [quality, setQuality] = useState<ReferenceQualityReport | null>(null)
  const [loadedProfileId, setLoadedProfileId] = useState<string | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)   // asset_id or 'upload'
  const [uploadCategory, setUploadCategory] = useState<string>('product')
  const [uploadProgress, setUploadProgress] = useState<string | null>(null)
  const [preview, setPreview] = useState<BrandAssetEntry | null>(null)
  const [previewNotes, setPreviewNotes] = useState('')
  const [replaceTarget, setReplaceTarget] = useState<BrandAssetEntry | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<BrandAssetEntry | null>(null)

  const logoInput = useRef<HTMLInputElement>(null)
  const refInput = useRef<HTMLInputElement>(null)
  const replaceInput = useRef<HTMLInputElement>(null)

  const reload = useCallback(async () => {
    try {
      const [assetRes, qualityRes] = await Promise.all([
        listBrandAssets(profileId),
        getReferenceQuality(profileId),
      ])
      setAssets(assetRes?.assets || [])
      setQuality(qualityRes)
      setLoadError(null)   // cleared only after data lands (never sync in the effect)
    } catch (e) {
      setLoadError(errMsg(e, 'Reference assets could not be loaded.'))
    } finally {
      setLoadedProfileId(profileId)
    }
  }, [profileId])

  useEffect(() => {
    // Async data load: every setState below happens after `await Promise.all`
    // resolves (never synchronously in this effect). Mirrors the established
    // loader pattern of BrandProfilesPage / ResultsPage.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    reload()
  }, [reload])
  // Derived, not set inside the effect: loading until THIS brand's data lands.
  const loading = loadedProfileId !== profileId

  const logos = assets.filter(a => a.kind === 'logo')
  const references = assets.filter(a => a.kind === 'reference')

  const handleUpload = async (files: FileList | null, kind: 'logo' | 'reference') => {
    if (!files || files.length === 0) return
    setBusy('upload')
    try {
      let lastProfile: BrandProfile | null = null
      for (let i = 0; i < files.length; i++) {
        const file = files[i]
        setUploadProgress(
          files.length > 1 ? `Uploading ${i + 1} of ${files.length}: ${file.name}` : `Uploading ${file.name}`)
        const res = await uploadBrandAsset(
          profileId, file, kind,
          kind === 'logo' ? undefined : uploadCategory,
        )
        lastProfile = res?.profile ?? null
      }
      setUploadProgress(null)
      toast.success('Uploaded', `${files.length} file${files.length > 1 ? 's' : ''} added`)
      if (lastProfile) onProfileChanged?.(lastProfile)
      await reload()
    } catch (e) {
      setUploadProgress(null)
      toast.error('Upload failed', errMsg(e, 'The file could not be uploaded.'))
    } finally {
      setBusy(null)
      if (logoInput.current) logoInput.current.value = ''
      if (refInput.current) refInput.current.value = ''
    }
  }

  const handleCategoryChange = async (asset: BrandAssetEntry, category: string) => {
    const previous = asset.category
    setAssets(prev => prev.map(a => a.asset_id === asset.asset_id ? { ...a, category } : a))
    try {
      await updateBrandAsset(profileId, asset.asset_id, { category })
      await reload()
    } catch (e) {
      setAssets(prev => prev.map(a => a.asset_id === asset.asset_id ? { ...a, category: previous } : a))
      toast.error('Update failed', errMsg(e, 'The category could not be saved.'))
    }
  }

  const handleReplace = async (file: File | null) => {
    if (!file || !replaceTarget) return
    setBusy(replaceTarget.asset_id)
    try {
      const res = await replaceBrandAsset(profileId, replaceTarget.asset_id, file)
      toast.success('Replaced', `Now showing ${file.name}`)
      if (res?.profile) onProfileChanged?.(res.profile)
      setReplaceTarget(null)
      setPreview(null)
      await reload()
    } catch (e) {
      toast.error('Replace failed', errMsg(e, 'The asset could not be replaced.'))
    } finally {
      setBusy(null)
      if (replaceInput.current) replaceInput.current.value = ''
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setBusy(deleteTarget.asset_id)
    try {
      const res = await deleteBrandAsset(profileId, deleteTarget.asset_id)
      toast.success('Removed', `${deleteTarget.original_name} deleted`)
      if (res?.profile) onProfileChanged?.(res.profile)
      setDeleteTarget(null)
      setPreview(null)
      await reload()
    } catch (e) {
      toast.error('Remove failed', errMsg(e, 'The asset could not be removed.'))
    } finally {
      setBusy(null)
    }
  }

  const saveNotes = async () => {
    if (!preview) return
    setBusy(preview.asset_id)
    try {
      await updateBrandAsset(profileId, preview.asset_id, { notes: previewNotes })
      setPreview({ ...preview, notes: previewNotes.trim() })
      await reload()
      toast.success('Saved', 'Reference notes updated')
    } catch (e) {
      toast.error('Save failed', errMsg(e, 'Notes could not be saved.'))
    } finally {
      setBusy(null)
    }
  }

  const openPreview = (asset: BrandAssetEntry) => {
    setPreviewNotes(asset.notes || '')
    setPreview(asset)
  }

  const warnings = quality?.warnings ?? []
  const readiness = quality?.readiness ?? 0
  // Near-duplicate flags come from the quality report (per quality asset).
  const flaggedIds = new Set(
    (quality?.assets ?? []).filter(a => a.near_duplicate_of).map(a => a.asset_id))

  const assetMeta = (asset: BrandAssetEntry) => [
    asset.width && asset.height ? `${asset.width}×${asset.height}` : null,
    asset.format || null,
    formatBytes(asset.bytes),
    asset.uploaded_at ? new Date(asset.uploaded_at).toLocaleDateString(undefined, {
      day: 'numeric', month: 'short', year: 'numeric',
    }) : null,
  ].filter(Boolean).join(' · ')

  const renderAssetCard = (asset: BrandAssetEntry) => {
    const url = assetUrl(`output/studio/brand_assets/${profileId}/${asset.stored_name}`)
    const isBusy = busy === asset.asset_id
    return (
      <motion.article
        key={asset.asset_id}
        className={`vrp-card${flaggedIds.has(asset.asset_id) ? ' vrp-card--flagged' : ''}`}
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        layout
      >
        <button
          type="button"
          className="vrp-card__thumb"
          onClick={() => openPreview(asset)}
          title={`Preview ${asset.original_name}`}
        >
          {url ? <img src={url} alt={asset.original_name} loading="lazy" /> : <span>Preview</span>}
        </button>
        <div className="vrp-card__body">
          <p className="vrp-card__name" title={asset.original_name}>{asset.original_name}</p>
          <p className="vrp-card__meta">{assetMeta(asset)}</p>
          {asset.kind === 'reference' && (
            <label className="vrp-card__cat">
              <select
                className="bp-select"
                aria-label={`Category for ${asset.original_name}`}
                value={asset.category}
                disabled={isBusy}
                onChange={e => handleCategoryChange(asset, e.target.value)}
              >
                {REFERENCE_CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
          )}
          {asset.notes && <p className="vrp-card__notes" title={asset.notes}>{asset.notes}</p>}
          {flaggedIds.has(asset.asset_id) && (
            <span className="vrp-card__flag"><AlertTriangle size={11} /> Near-duplicate</span>
          )}
          <div className="vrp-card__actions">
            <button type="button" className="vrp-iconbtn" title="Preview"
              onClick={() => openPreview(asset)}><ScanLine size={13} /></button>
            <button type="button" className="vrp-iconbtn" title="Replace file"
              disabled={isBusy}
              onClick={() => { setReplaceTarget(asset); setTimeout(() => replaceInput.current?.click(), 0) }}>
              <Replace size={13} />
            </button>
            <button type="button" className="vrp-iconbtn vrp-iconbtn--danger" title="Remove"
              disabled={isBusy} onClick={() => setDeleteTarget(asset)}>
              <Trash2 size={13} />
            </button>
          </div>
        </div>
      </motion.article>
    )
  }

  const groupedRefs = REFERENCE_CATEGORIES
    .map(cat => ({ cat, items: references.filter(r => r.category === cat) }))
    .filter(g => g.items.length > 0)

  return (
    <div className="vrp">
      {/* ── Quality summary ── */}
      {quality && (
        <Card style={{ padding: 18 }} className="vrp-quality">
          <div className="vrp-quality__head">
            <div>
              <span className="vrp-quality__score" data-level={
                readiness >= 80 ? 'good' : readiness >= 50 ? 'mid' : 'low'
              }>{readiness}</span>
              <div>
                <p className="vrp-quality__title">Reference readiness</p>
                <p className="vrp-quality__sub">
                  {quality.counts.logos} logo{quality.counts.logos === 1 ? '' : 's'} ·{' '}
                  {quality.counts.references} reference photo{quality.counts.references === 1 ? '' : 's'}
                  {quality.diversity != null && (
                    <> · diversity {quality.diversity.score.toFixed(2)}</>
                  )}
                </p>
              </div>
            </div>
            <AnimatedBtn type="button" variant="ghost" size="sm" label="Refresh report" onClick={reload}>
              <RefreshCw size={13} /> Refresh
            </AnimatedBtn>
          </div>

          {Object.keys(quality.categories).length > 0 && (
            <div className="vrp-quality__cats">
              {Object.entries(quality.categories).map(([cat, count]) => (
                <Tag key={cat} label={`${cat} · ${count}`} color="var(--accent-light)" />
              ))}
            </div>
          )}

          {warnings.length > 0 && (
            <ul className="vrp-warnings">
              {warnings.map(w => {
                const Icon = severityIcon(w.severity)
                return (
                  <li key={w.code} className={`vrp-warning vrp-warning--${w.severity}`}>
                    <Icon size={13} />
                    <span>{w.message}</span>
                  </li>
                )
              })}
            </ul>
          )}
        </Card>
      )}

      {/* ── Logos ── */}
      <section className="vrp-section">
        <header className="vrp-section__head">
          <div>
            <h3>Logo variants</h3>
            <p>All uploaded logos — wordmarks, symbols, monochrome and co-brand variants.</p>
          </div>
          <AnimatedBtn
            type="button" variant="default" size="sm" label="Add logo"
            disabled={busy === 'upload'}
            onClick={() => logoInput.current?.click()}
          >
            <Plus size={14} /> Add logo
          </AnimatedBtn>
        </header>
        <input
          ref={logoInput} type="file" accept="image/*,.svg,.pdf" hidden
          onChange={e => handleUpload(e.target.files, 'logo')}
        />
        {logos.length === 0 ? (
          <div className="vrp-empty">
            <ImagePlus size={18} />
            <p>No logos yet. Upload at least one logo so text-free brand marks can be matched.</p>
          </div>
        ) : (
          <div className="vrp-grid">{logos.map(renderAssetCard)}</div>
        )}
      </section>

      {/* ── Reference photographs ── */}
      <section className="vrp-section">
        <header className="vrp-section__head">
          <div>
            <h3>Reference photographs</h3>
            <p>Products, packaging, signage, storefronts, banners, uniforms — real-world brand appearances.</p>
          </div>
          <div className="vrp-section__actions">
            <select
              className="bp-select"
              aria-label="Category for new uploads"
              value={uploadCategory}
              onChange={e => setUploadCategory(e.target.value)}
            >
              {REFERENCE_CATEGORIES.map(c => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
            <AnimatedBtn
              type="button" variant="default" size="sm" label="Add photos"
              disabled={busy === 'upload'}
              loading={busy === 'upload'}
              onClick={() => refInput.current?.click()}
            >
              <Upload size={14} /> Add photos
            </AnimatedBtn>
          </div>
        </header>
        <input
          ref={refInput} type="file" accept="image/*" multiple hidden
          onChange={e => handleUpload(e.target.files, 'reference')}
        />
        {uploadProgress && <p className="vrp-progress">{uploadProgress}</p>}
        {references.length === 0 ? (
          <div className="vrp-empty">
            <ImagePlus size={18} />
            <p>No reference photographs yet. Aim for 3+ diverse photos across categories.</p>
          </div>
        ) : (
          groupedRefs.map(group => (
            <div className="vrp-group" key={group.cat}>
              <h4 className="vrp-group__title">{group.cat} <span>{group.items.length}</span></h4>
              <div className="vrp-grid">{group.items.map(renderAssetCard)}</div>
            </div>
          ))
        )}
      </section>

      {/* Hidden input for replace flow */}
      <input
        ref={replaceInput} type="file" accept="image/*,.svg,.pdf" hidden
        onChange={e => handleReplace(e.target.files?.[0] ?? null)}
      />

      {/* ── Loading / error ── */}
      {loading && <div className="bp-loading"><Spinner size={24} /></div>}
      {loadError && !loading && (
        <div className="vrp-error">
          <p>{loadError}</p>
          <AnimatedBtn type="button" variant="ghost" size="sm" label="Retry" onClick={reload}>
            <RefreshCw size={13} /> Try again
          </AnimatedBtn>
        </div>
      )}

      {/* ── Preview modal ── */}
      <Modal open={!!preview} onClose={() => setPreview(null)} title={preview?.original_name || 'Preview'} width={720}>
        {preview && (
          <div className="vrp-preview">
            {assetUrl(`output/studio/brand_assets/${profileId}/${preview.stored_name}`) && (
              <img
                className="vrp-preview__img"
                src={assetUrl(`output/studio/brand_assets/${profileId}/${preview.stored_name}`)!}
                alt={preview.original_name}
              />
            )}
            <dl className="vrp-preview__meta">
              <div><dt>Type</dt><dd>{preview.kind === 'logo' ? 'Logo' : 'Reference photo'}</dd></div>
              <div><dt>Category</dt><dd>{preview.category}</dd></div>
              <div><dt>Size</dt><dd>{preview.width ?? '?'}×{preview.height ?? '?'} · {formatBytes(preview.bytes)}</dd></div>
              <div><dt>Format</dt><dd>{preview.format || '—'}</dd></div>
              <div><dt>Uploaded</dt><dd>{preview.uploaded_at ? new Date(preview.uploaded_at).toLocaleString() : '—'}</dd></div>
              <div><dt>SHA-256</dt><dd className="vrp-preview__sha">{preview.sha256.slice(0, 16)}…</dd></div>
            </dl>
            <label className="vrp-preview__notes">
              <span>Notes</span>
              <textarea
                className="bp-textarea"
                maxLength={1000}
                rows={3}
                placeholder="What to look for in this reference…"
                value={previewNotes}
                onChange={e => setPreviewNotes(e.target.value)}
              />
            </label>
            <div className="vrp-preview__actions">
              <AnimatedBtn
                type="button" variant="ghost" size="md" label="Save notes"
                disabled={busy === preview.asset_id}
                onClick={saveNotes}
              >
                <Pencil size={14} /> Save notes
              </AnimatedBtn>
              <AnimatedBtn
                type="button" variant="ghost" size="md" label="Replace file"
                disabled={busy === preview.asset_id}
                onClick={() => { setReplaceTarget(preview); setTimeout(() => replaceInput.current?.click(), 0) }}
              >
                <Replace size={14} /> Replace
              </AnimatedBtn>
              <AnimatedBtn
                type="button" variant="danger" size="md" label="Remove asset"
                disabled={busy === preview.asset_id}
                onClick={() => setDeleteTarget(preview)}
              >
                <Trash2 size={14} /> Remove
              </AnimatedBtn>
            </div>
          </div>
        )}
      </Modal>

      {/* ── Delete confirmation ── */}
      <Modal
        open={!!deleteTarget}
        onClose={() => { if (busy !== deleteTarget?.asset_id) setDeleteTarget(null) }}
        title="Remove asset"
        width={440}
      >
        <p className="bp-modal-text">
          Remove <strong>{deleteTarget?.original_name}</strong> from this brand? The file is
          deleted permanently and the profile's asset list is updated.
        </p>
        <div className="bp-modal-actions">
          <AnimatedBtn
            type="button" variant="ghost" size="md" label="Cancel"
            disabled={busy === deleteTarget?.asset_id}
            onClick={() => setDeleteTarget(null)}
          >
            <X size={15} /> Cancel
          </AnimatedBtn>
          <AnimatedBtn
            type="button" variant="danger" size="md" label="Remove asset"
            loading={busy === deleteTarget?.asset_id}
            onClick={handleDelete}
          >
            <Trash2 size={15} /> Remove
          </AnimatedBtn>
        </div>
      </Modal>
    </div>
  )
}

export default VisualReferencesPanel
