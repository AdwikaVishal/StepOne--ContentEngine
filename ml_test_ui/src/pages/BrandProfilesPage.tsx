/**
 * BrandProfilesPage — create, edit, duplicate and delete brand profiles.
 *
 * Six-section identity configuration (progressive disclosure), completeness
 * scoring, logo previews and a local-Qwen Brand Voice Preview. Visual
 * language matches Studio / Results: near-black background, charcoal
 * surfaces, violet accent, soft borders. All data flows through the
 * existing /api/studio/brand-profiles endpoints — no mock data, no
 * schema changes.
 *
 * Brand Intelligence (Phase 1): with showReferencesTab, the editor also
 * exposes a "Visual References" tab (multi-logo variants + categorized
 * reference photos + quality report) inside the Brand Intelligence
 * workspace. Default behaviour is unchanged for the classic page.
 */
import { useState, useEffect, useMemo } from 'react'
import { motion } from 'framer-motion'
import {
  ArrowLeft, CalendarDays, ChevronDown, Copy, Fingerprint, Hash,
  Image as ImageIcon, Languages, LayoutGrid, Megaphone, Mic, Palette,
  Pencil, Plus, Save, ScanSearch, Target, Trash2, Type, Users, X,
} from 'lucide-react'
import { Card, Spinner, Tag, AnimatedBtn } from '../components/ui'
import { Modal } from '../components/ui/Modal'
import { Tooltip } from '../components/ui/Tooltip'
import { toast } from '../components/ui/Toast'
import { BrandField, CharCounter } from '../components/brand/BrandFormFields'
import { VoicePreviewPanel } from '../components/brand/VoicePreviewPanel'
import { VisualReferencesPanel } from '../components/brand/VisualReferencesPanel'
import '../components/brand/VisualReferencesPanel.css'
import {
  createBrandProfile, listBrandProfiles, updateBrandProfile,
  deleteBrandProfile, duplicateBrandProfile, uploadBrandAsset,
} from '../api'
import {
  BRAND_SECTIONS, ALL_SECTION_FIELDS, assetUrl,
  emptyBrandProfile, profileCompleteness,
  type BrandProfile, type BrandSectionDef,
} from '../lib/brandProfile'

const SECTION_ICONS: Record<string, typeof Users> = {
  identity: Fingerprint,
  voice: Mic,
  audience: Users,
  language: Languages,
  content: LayoutGrid,
  visual: Palette,
}

const errMsg = (e: any, fallback: string) => {
  const detail = e?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (typeof e?.message === 'string' && e.message) return e.message
  return fallback
}

const formatDate = (iso?: string) => {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

export function BrandProfilesPage({
  onBack,
  showReferencesTab = false,
  title = 'Brand Profiles',
  subtitle = 'Configure how your brand looks, sounds and communicates.',
}: {
  onBack?: () => void
  /** Brand Intelligence workspace: add a Visual References tab to the editor. */
  showReferencesTab?: boolean
  title?: string
  subtitle?: string
}) {
  const [profiles, setProfiles] = useState<BrandProfile[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [editing, setEditing] = useState<BrandProfile | null>(null)
  const [creating, setCreating] = useState(false)
  const [initialJson, setInitialJson] = useState('')
  const [openSections, setOpenSections] = useState<string[]>(['identity'])
  const [logoFile, setLogoFile] = useState<File | null>(null)
  const [referenceFiles, setReferenceFiles] = useState<File[]>([])
  const [deleteTarget, setDeleteTarget] = useState<BrandProfile | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [showUnsavedModal, setShowUnsavedModal] = useState(false)
  const [editorTab, setEditorTab] = useState<'profile' | 'references'>('profile')

  const dirty = editing !== null && JSON.stringify(editing) !== initialJson

  useEffect(() => {
    loadProfiles()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Warn on page unload while there are unsaved edits.
  useEffect(() => {
    if (!dirty) return
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])

  const loadProfiles = async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const res = await listBrandProfiles()
      setProfiles(res?.profiles || [])
    } catch (e: any) {
      setLoadError(errMsg(e, 'Brand profiles could not be loaded.'))
    } finally {
      setLoading(false)
    }
  }

  const openEditor = (profile: BrandProfile, isCreating: boolean) => {
    setLogoFile(null)
    setReferenceFiles([])
    setCreating(isCreating)
    setEditing(profile)
    setInitialJson(JSON.stringify(profile))
    setOpenSections(['identity'])
    setEditorTab('profile')
  }

  /**
   * Asset mutations (upload / replace / remove) happen server-side; merge ONLY
   * the asset view fields back into the form so unsaved text edits are never
   * lost, and update the same fields in the dirty-check baseline.
   */
  const handleAssetProfileChanged = (serverProfile: BrandProfile) => {
    setEditing(prev => prev ? {
      ...prev,
      logo_path: serverProfile.logo_path,
      visual_references: serverProfile.visual_references,
    } : prev)
    setInitialJson(prev => {
      if (!prev) return prev
      try {
        const base = JSON.parse(prev)
        base.logo_path = serverProfile.logo_path
        base.visual_references = serverProfile.visual_references
        return JSON.stringify(base)
      } catch {
        return prev
      }
    })
    setProfiles(prev => prev.map(p =>
      p.id === serverProfile.id
        ? { ...p, logo_path: serverProfile.logo_path, visual_references: serverProfile.visual_references }
        : p))
  }

  const handleCreate = () => openEditor(emptyBrandProfile(), true)

  const attemptCancel = () => {
    if (dirty) setShowUnsavedModal(true)
    else cancelEdit()
  }

  const cancelEdit = () => {
    setEditing(null)
    setCreating(false)
    setInitialJson('')
    setLogoFile(null)
    setReferenceFiles([])
    setEditorTab('profile')
    setShowUnsavedModal(false)
  }

  const setField = (name: string, value: any) => {
    setEditing(prev => (prev ? { ...prev, [name]: value } : prev))
  }

  const toggleSection = (id: string) => {
    setOpenSections(prev =>
      prev.includes(id) ? prev.filter(s => s !== id) : [...prev, id])
  }

  const handleSave = async () => {
    if (!editing) return
    if (!editing.name?.trim()) {
      toast.error('Brand name required', 'Enter a name for this profile')
      if (!openSections.includes('identity')) setOpenSections(['identity'])
      return
    }
    setSaving(true)
    try {
      let saved: any
      if (creating) {
        saved = await createBrandProfile(editing)
        toast.success('Created', 'Brand profile created')
      } else {
        // Non-create flows always come from the server, so the id exists.
        saved = await updateBrandProfile(editing.id!, editing)
        toast.success('Saved', 'Brand profile updated')
      }
      if (logoFile) saved = (await uploadBrandAsset(saved.id, logoFile, 'logo')).profile
      for (const file of referenceFiles) {
        saved = (await uploadBrandAsset(saved.id, file, 'reference')).profile
      }
      cancelEdit()
      await loadProfiles()
    } catch (e: any) {
      toast.error('Error', errMsg(e, 'The profile could not be saved.'))
    } finally {
      setSaving(false)
    }
  }

  const handleDuplicate = async (id: string) => {
    try {
      await duplicateBrandProfile(id)
      toast.success('Duplicated', 'Brand profile duplicated')
      await loadProfiles()
    } catch (e: any) {
      toast.error('Error', errMsg(e, 'The profile could not be duplicated.'))
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteBrandProfile(deleteTarget.id!)
      toast.success('Deleted', 'Brand profile deleted')
      setDeleteTarget(null)
      await loadProfiles()
    } catch (e: any) {
      toast.error('Error', errMsg(e, 'The profile could not be deleted.'))
    } finally {
      setDeleting(false)
    }
  }

  const metaRows = (p: BrandProfile) => {
    const rows: { icon: typeof Users; label: string; value: string }[] = []
    if (p.target_audience) rows.push({ icon: Users, label: 'Audience', value: p.target_audience })
    if (p.campaign_objectives) rows.push({ icon: Target, label: 'Objectives', value: p.campaign_objectives })
    if (p.preferred_cta) rows.push({ icon: Megaphone, label: 'CTA', value: p.preferred_cta })
    if (p.hashtag_guidance) rows.push({ icon: Hash, label: 'Hashtags', value: p.hashtag_guidance })
    if (Array.isArray(p.fonts) && p.fonts.length) rows.push({ icon: Type, label: 'Fonts', value: p.fonts.join(', ') })
    const assets: string[] = []
    if (p.logo_path) assets.push('Logo uploaded')
    if (Array.isArray(p.visual_references) && p.visual_references.length) {
      assets.push(`${p.visual_references.length} visual reference${p.visual_references.length > 1 ? 's' : ''}`)
    }
    if (assets.length) rows.push({ icon: ImageIcon, label: 'Assets', value: assets.join(' · ') })
    return rows
  }

  const completeness = useMemo(() => profileCompleteness(editing), [editing])

  const renderSectionFields = (section: BrandSectionDef) =>
    section.fields
      .filter(field => field.name !== 'name') // name is always visible above
      .map(field => {
        const fieldId = `bp-${field.name}`
        const value = editing?.[field.name]
        return (
          <div
            className={`bp-form__row${field.full || field.kind === 'chips' ? ' bp-form__row--full' : ''}`}
            key={field.name}
          >
            <label className="bp-label" htmlFor={fieldId}>
              {field.label}
              {field.required && <span className="bp-label__req">*</span>}
            </label>
            <BrandField
              def={field}
              id={fieldId}
              value={value}
              onChange={v => setField(field.name, v)}
              logoFileName={logoFile?.name ?? null}
              onLogoFile={f => setLogoFile(f)}
              refFiles={referenceFiles}
              onRefFiles={f => setReferenceFiles(f)}
            />
            {(field.kind === 'text' || field.kind === 'textarea') && (
              <CharCounter value={value} max={field.max} />
            )}
            {field.hint && <span className="bp-hint">{field.hint}</span>}
          </div>
        )
      })

  return (
    <div className="studio-container fade-in bp-page" style={{ maxWidth: 1100 }}>
      {/* ── Header ── */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      >
        <div className="studio-header">
          <div className="header-title">
            <h1>{title}</h1>
            <p>{subtitle}</p>
          </div>
          <div className="bp-header-actions">
            {onBack && (
              <AnimatedBtn
                type="button"
                variant="ghost"
                size="md"
                label="Back to Studio"
                onClick={onBack}
              >
                <ArrowLeft size={15} /> Back
              </AnimatedBtn>
            )}
            {!editing && (
              <AnimatedBtn
                type="button"
                variant="default"
                size="md"
                label="New Profile"
                onClick={handleCreate}
              >
                <Plus size={16} /> New Profile
              </AnimatedBtn>
            )}
          </div>
        </div>
      </motion.div>

      {/* ── Content ── */}
      {loading ? (
        <div className="bp-loading">
          <Spinner size={26} />
        </div>
      ) : loadError ? (
        <Card style={{ padding: 0 }}>
          <div className="bp-state">
            <p>{loadError}</p>
            <AnimatedBtn type="button" variant="ghost" size="md" label="Retry" onClick={loadProfiles}>
              Try again
            </AnimatedBtn>
          </div>
        </Card>
      ) : editing ? (
        /* ── Create / edit form ── */
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
          className="bp-editor"
        >
          <Card style={{ padding: 26 }}>
            <div className="bp-editor__head">
              <div>
                <h2 style={{ fontSize: 18, fontWeight: 800, letterSpacing: '-0.02em' }}>
                  {creating ? 'Create Profile' : `Edit · ${editing.name || 'Untitled'}`}
                  {dirty && <span className="bp-dirty" title="Unsaved changes">● Unsaved changes</span>}
                </h2>
                <p style={{ fontSize: 13, color: 'var(--t3)', marginTop: 4 }}>
                  {creating
                    ? 'Configure the essentials first — everything else is optional and can be added any time.'
                    : 'Changes apply to future generations once saved.'}
                </p>
              </div>
              <div className="bp-completeness" title={`${completeness.configured} of ${completeness.total} fields configured`}>
                <div className="bp-progress" role="progressbar" aria-valuenow={completeness.percent} aria-valuemin={0} aria-valuemax={100}>
                  <span style={{ width: `${completeness.percent}%` }} />
                </div>
                <span className="bp-completeness__label">{completeness.percent}% configured</span>
              </div>
            </div>

            {/* ── Brand Intelligence editor tabs (Phase 1) ── */}
            {showReferencesTab && (
              <div className="bp-tabs" role="tablist" aria-label="Brand editor views">
                <button
                  type="button"
                  role="tab"
                  aria-selected={editorTab === 'profile'}
                  className={`bp-tab${editorTab === 'profile' ? ' bp-tab--active' : ''}`}
                  onClick={() => setEditorTab('profile')}
                >
                  Profile
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={editorTab === 'references'}
                  className={`bp-tab${editorTab === 'references' ? ' bp-tab--active' : ''}`}
                  disabled={creating}
                  title={creating ? 'Save the profile first, then add visual references' : undefined}
                  onClick={() => !creating && setEditorTab('references')}
                >
                  <ScanSearch size={13} /> Visual References
                </button>
              </div>
            )}

            {(!showReferencesTab || editorTab === 'profile') && (
            <div className="bp-form">
              {/* Required brand name — always visible */}
              <div className="bp-form__grid">
                <div className="bp-form__row bp-form__row--full">
                  <label className="bp-label" htmlFor="bp-name">
                    Brand Name <span className="bp-label__req">*</span>
                  </label>
                  <input
                    id="bp-name"
                    className="bp-input"
                    value={editing.name || ''}
                    maxLength={120}
                    onChange={e => setField('name', e.target.value)}
                    placeholder="e.g., Acme Studios"
                    autoFocus={creating}
                  />
                </div>
              </div>

              {/* Six collapsible sections — progressive disclosure */}
              <div className="bp-sections">
                {BRAND_SECTIONS.map(section => {
                  const open = openSections.includes(section.id)
                  const c = completeness.sections[section.id]
                  const Icon = SECTION_ICONS[section.id] || Fingerprint
                  return (
                    <div className="bp-section" key={section.id}>
                      <button
                        type="button"
                        className="bp-section__head"
                        aria-expanded={open}
                        aria-controls={`bp-sec-${section.id}`}
                        onClick={() => toggleSection(section.id)}
                      >
                        <span className="bp-section__icon" aria-hidden="true">
                          <Icon size={15} />
                        </span>
                        <span className="bp-section__titles">
                          <span className="bp-section__title">{section.title}</span>
                          <span className="bp-section__desc">{section.description}</span>
                        </span>
                        <span className={`bp-section__badge${c && c.configured === c.total ? ' bp-section__badge--done' : ''}`}>
                          {c ? `${c.configured}/${c.total}` : ''}
                        </span>
                        <ChevronDown
                          size={16}
                          className={`bp-section__chevron${open ? ' bp-section__chevron--open' : ''}`}
                          aria-hidden="true"
                        />
                      </button>
                      {open && (
                        <div className="bp-section__body" id={`bp-sec-${section.id}`}>
                          <div className="bp-form__grid">
                            {renderSectionFields(section)}
                          </div>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>

              <div className="bp-form__footer">
                <AnimatedBtn
                  type="button"
                  variant="ghost"
                  size="md"
                  label="Cancel"
                  disabled={saving}
                  onClick={attemptCancel}
                >
                  <X size={15} /> Cancel
                </AnimatedBtn>
                <AnimatedBtn
                  type="button"
                  variant="default"
                  size="md"
                  label={creating ? 'Create profile' : 'Save changes'}
                  loading={saving}
                  onClick={handleSave}
                >
                  <Save size={15} /> {creating ? 'Create Profile' : 'Save Changes'}
                </AnimatedBtn>
              </div>
            </div>
            )}

            {/* ── Visual References tab (Brand Intelligence, Phase 1) ── */}
            {showReferencesTab && editorTab === 'references' && editing.id && (
              <VisualReferencesPanel
                key={editing.id}
                profileId={editing.id}
                onProfileChanged={handleAssetProfileChanged}
              />
            )}
          </Card>

          {/* ── Brand Voice Preview (unsaved values, local Qwen) ── */}
          {(!showReferencesTab || editorTab === 'profile') && (
          <div className="bp-preview-wrap">
            <VoicePreviewPanel
              key={creating ? 'new' : editing.id || 'edit'}
              profile={editing}
            />
          </div>
          )}
        </motion.div>
      ) : profiles.length === 0 ? (
        /* ── Empty state ── */
        <Card style={{ padding: 0 }}>
          <div className="bp-empty">
            <div className="bp-empty__icon" aria-hidden="true">
              <Palette size={26} />
            </div>
            <h2 className="bp-empty__title">No brand profiles yet</h2>
            <p className="bp-empty__text">
              Brand profiles capture your voice, tone, vocabulary and content
              guidelines so every caption the Content Engine generates stays
              consistent and on-brand.
            </p>
            <div className="bp-empty__cta">
              <AnimatedBtn
                type="button"
                variant="default"
                size="md"
                label="Create your first profile"
                onClick={handleCreate}
              >
                <Plus size={16} /> Create your first profile
              </AnimatedBtn>
            </div>
          </div>
        </Card>
      ) : (
        /* ── Profile grid ── */
        <div className="bp-grid">
          {profiles.map(profile => {
            const vocab = profile.preferred_vocabulary || []
            const personality = profile.personality_traits || []
            const colors = profile.brand_colors || []
            const pc = profileCompleteness(profile)
            const logo = assetUrl(profile.logo_path)
            const identityBits = [profile.industry, profile.tagline].filter(Boolean)
            return (
            <motion.article
              key={profile.id}
              className="bp-card"
              layout
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
            >
              <div className="bp-card__head">
                {logo ? (
                  <div className="bp-avatar bp-avatar--logo">
                    <img src={logo} alt={`${profile.name} logo`} />
                  </div>
                ) : (
                  <div className="bp-avatar" aria-hidden="true">
                    {(profile.name || '?').trim().charAt(0).toUpperCase()}
                  </div>
                )}
                <div className="bp-card__title">
                  <h3 className="bp-card__name">{profile.name}</h3>
                  {identityBits.length > 0 && (
                    <p className="bp-card__identity">{identityBits.join(' · ')}</p>
                  )}
                  <p className="bp-card__desc">
                    {profile.description || 'No description added yet.'}
                  </p>
                </div>
              </div>

              <div className="bp-tags">
                {profile.tone_of_voice && <Tag label={profile.tone_of_voice} color="var(--accent)" />}
                {personality.slice(0, 3).map((trait: string) => (
                  <Tag key={`p-${trait}`} label={trait} color="var(--accent-light)" />
                ))}
                {personality.length === 0 && vocab.slice(0, 3).map((word: string) => (
                  <Tag key={word} label={word} color="var(--t2)" />
                ))}
                {personality.length > 3 && (
                  <span className="bp-tags__more">+{personality.length - 3} more</span>
                )}
              </div>

              {(metaRows(profile).length > 0 || colors.length > 0) && (
                <div className="bp-meta">
                  {metaRows(profile).map(row => (
                    <div className="bp-meta__row" key={row.label}>
                      <row.icon size={13} />
                      <span className="bp-meta__label">{row.label}</span>
                      <span className="bp-meta__value">{row.value}</span>
                    </div>
                  ))}
                  {colors.length > 0 && (
                    <div className="bp-meta__row">
                      <Palette size={13} />
                      <span className="bp-meta__label">Colors</span>
                      <div className="bp-swatches">
                        {colors.slice(0, 8).map((c: string) => (
                          <span key={c} className="bp-swatch" style={{ background: c }} title={c} />
                        ))}
                        {colors.length > 8 && (
                          <span className="bp-tags__more">+{colors.length - 8}</span>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}

              <div className="bp-card__progress" title={`${pc.percent}% of fields configured`}>
                <div className="bp-progress" role="progressbar" aria-valuenow={pc.percent} aria-valuemin={0} aria-valuemax={100}>
                  <span style={{ width: `${pc.percent}%` }} />
                </div>
                <span className="bp-completeness__label">{pc.percent}%</span>
              </div>

              <div className="bp-card__footer">
                <span className="bp-card__date">
                  <CalendarDays size={11} />
                  {profile.updated_at ? `Updated ${formatDate(profile.updated_at)}` : 'Brand profile'}
                </span>
                <div className="bp-card__actions">
                  <Tooltip content="Edit profile">
                    <AnimatedBtn
                      type="button"
                      variant="ghost"
                      size="sm"
                      label="Edit"
                      onClick={() => openEditor(profile, false)}
                    >
                      <Pencil size={14} />
                    </AnimatedBtn>
                  </Tooltip>
                  <Tooltip content="Duplicate profile">
                    <AnimatedBtn
                      type="button"
                      variant="ghost"
                      size="sm"
                      label="Duplicate"
                      onClick={() => handleDuplicate(profile.id!)}
                    >
                      <Copy size={14} />
                    </AnimatedBtn>
                  </Tooltip>
                  <Tooltip content="Delete profile">
                    <AnimatedBtn
                      type="button"
                      variant="danger"
                      size="sm"
                      label="Delete"
                      onClick={() => setDeleteTarget(profile)}
                    >
                      <Trash2 size={14} />
                    </AnimatedBtn>
                  </Tooltip>
                </div>
              </div>
            </motion.article>
            )
          })}
        </div>
      )}

      {/* ── Unsaved changes confirmation ── */}
      <Modal
        open={showUnsavedModal}
        onClose={() => { if (!saving) setShowUnsavedModal(false) }}
        title="Unsaved changes"
        width={440}
      >
        <p className="bp-modal-text">
          You have unsaved changes to <strong>{editing?.name || 'this profile'}</strong>.
          Leaving now discards them.
        </p>
        <div className="bp-modal-actions">
          <AnimatedBtn
            type="button"
            variant="ghost"
            size="md"
            label="Keep editing"
            disabled={saving}
            onClick={() => setShowUnsavedModal(false)}
          >
            Keep editing
          </AnimatedBtn>
          <AnimatedBtn
            type="button"
            variant="danger"
            size="md"
            label="Discard changes"
            disabled={saving}
            onClick={cancelEdit}
          >
            <X size={15} /> Discard changes
          </AnimatedBtn>
        </div>
      </Modal>

      {/* ── Delete confirmation ── */}
      <Modal
        open={!!deleteTarget}
        onClose={() => { if (!deleting) setDeleteTarget(null) }}
        title="Delete brand profile"
        width={440}
      >
        <p className="bp-modal-text">
          Delete <strong>{deleteTarget?.name}</strong>? The profile and its
          uploaded brand assets are removed permanently.
        </p>
        <p className="bp-modal-warn">
          Content already generated is unaffected, but these guidelines will no
          longer be available for future generations.
        </p>
        <div className="bp-modal-actions">
          <AnimatedBtn
            type="button"
            variant="ghost"
            size="md"
            label="Cancel"
            disabled={deleting}
            onClick={() => setDeleteTarget(null)}
          >
            <X size={15} /> Cancel
          </AnimatedBtn>
          <AnimatedBtn
            type="button"
            variant="danger"
            size="md"
            label="Delete profile"
            loading={deleting}
            onClick={handleDelete}
          >
            <Trash2 size={15} /> Delete Profile
          </AnimatedBtn>
        </div>
      </Modal>
    </div>
  )
}

// Re-exported for tests / other pages.
export { ALL_SECTION_FIELDS }
