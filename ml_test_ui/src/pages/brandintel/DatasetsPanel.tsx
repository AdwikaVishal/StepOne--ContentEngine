/**
 * DatasetsPanel — Brand Intelligence Phase 2 (Dataset Upload).
 *
 * Dataset CRUD, drag-and-drop / file-picker / ZIP ingestion, resumable
 * chunked uploads with per-file progress, validation errors, duplicate
 * indicators, dataset summary/detail and a paginated image browser.
 *
 * All data flows through the real /api/brand-intel/datasets endpoints —
 * no mock data. Memory discipline: only File references are kept (never
 * their contents); large files are sliced chunk-by-chunk server-contract
 * sized, small files ride batches of ≤10 — the browser never holds the
 * whole dataset.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  AlertTriangle, CheckCircle2, ChevronLeft, Clock, Database, FileArchive,
  ImagePlus, Layers, Plus, RefreshCw, Search, Trash2, Upload, X, XCircle,
} from 'lucide-react'
import { Card, Spinner, AnimatedBtn } from '../../components/ui'
import { Modal } from '../../components/ui/Modal'
import { toast } from '../../components/ui/Toast'
import {
  completeUpload, createDataset, createUploadSession, deleteDataset,
  discardUpload, finalizeDataset, getDataset, listDatasetImages,
  listDatasets, listUploadSessions, sendUploadChunk, uploadDatasetFiles,
  uploadDatasetZip,
  type DatasetImage, type DatasetSummary, type IngestOutcome,
  type UploadResultItem, type UploadSession,
} from '../../api'
import { assetUrl } from '../../lib/brandProfile'
import {
  CHUNK_RETRY_ATTEMPTS, DATASET_BATCH_SIZE, DATASET_CHUNK_BYTES,
  chunkRange, formatBytes, isSupportedImageName, isZipFile,
  planChunkCount, rejectionLabel, uploadErrorMessage,
} from '../../lib/datasetUpload'
import './DatasetsPanel.css'

type QueueStatus =
  | 'queued' | 'uploading' | 'accepted' | 'duplicate' | 'rejected' | 'error'

interface QueueItem {
  key: string
  name: string
  size: number
  status: QueueStatus
  /** 0..1 */
  progress: number
  detail?: string
  shared?: boolean
}

interface PendingEntry { file: File; key: string }

const QUEUE_STATUS_LABEL: Record<QueueStatus, string> = {
  queued: 'Queued',
  uploading: 'Uploading',
  accepted: 'Stored',
  duplicate: 'Duplicate',
  rejected: 'Rejected',
  error: 'Failed',
}

const DATASET_STATUS_LABEL: Record<string, string> = {
  ingesting: 'Ingesting',
  ready: 'Ready',
  running: 'Running',
  classified: 'Classified',
}

const newKey = () =>
  `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`

export function DatasetsPanel() {
  // ── List state ─────────────────────────────────────────────────────────────
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [listLoaded, setListLoaded] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [createBusy, setCreateBusy] = useState(false)

  // ── Detail state ───────────────────────────────────────────────────────────
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<DatasetSummary | null>(null)
  const [detailLoadedId, setDetailLoadedId] = useState<string | null>(null)
  const [images, setImages] = useState<DatasetImage[]>([])
  const [imageTotal, setImageTotal] = useState(0)
  const [imageQuery, setImageQuery] = useState('')
  const [activeQuery, setActiveQuery] = useState('')
  const [pending, setPending] = useState<UploadSession[]>([])
  const [finalizing, setFinalizing] = useState(false)

  // ── Upload state ───────────────────────────────────────────────────────────
  const [queue, setQueue] = useState<QueueItem[]>([])
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)

  // ── Delete state ───────────────────────────────────────────────────────────
  const [deleteTarget, setDeleteTarget] = useState<DatasetSummary | null>(null)
  const [deleteConfirmText, setDeleteConfirmText] = useState('')
  const [deleteBusy, setDeleteBusy] = useState(false)

  const fileInput = useRef<HTMLInputElement>(null)
  const zipInput = useRef<HTMLInputElement>(null)

  // ── Loaders ────────────────────────────────────────────────────────────────

  const reloadList = useCallback(async () => {
    try {
      const res = await listDatasets()
      setDatasets(res?.datasets ?? [])
      setLoadError(null)
    } catch (e) {
      setLoadError(uploadErrorMessage(e, 'Datasets could not be loaded.'))
    } finally {
      setListLoaded(true)
    }
  }, [])

  useEffect(() => {
    // Async data load: every setState below happens after `await` resolves,
    // never synchronously in this effect (same pattern as Phase 1 panel).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    reloadList()
  }, [reloadList])

  const reloadDetail = useCallback(async (id: string) => {
    try {
      const [d, imgs, sess] = await Promise.all([
        getDataset(id),
        listDatasetImages(id, 0, 60, ''),
        listUploadSessions(id),
      ])
      setDetail(d)
      setImages(imgs?.images ?? [])
      setImageTotal(imgs?.total ?? 0)
      setActiveQuery('')
      setPending(sess?.uploads ?? [])
      setDetailLoadedId(id)
    } catch (e) {
      toast.error(
        'Load failed',
        uploadErrorMessage(e, 'Dataset details could not be loaded.'))
    }
  }, [])

  useEffect(() => {
    if (!selectedId) return
    // Async data load: all state updates occur after the awaited requests.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    reloadDetail(selectedId)
  }, [selectedId, reloadDetail])

  // ── Queue helpers ──────────────────────────────────────────────────────────

  const pushItem = (item: QueueItem) =>
    setQueue(prev => [...prev, item])

  const markQueue = (key: string, patch: Partial<QueueItem>) =>
    setQueue(prev => prev.map(
      item => (item.key === key ? { ...item, ...patch } : item)))

  const applyResult = (key: string, result: UploadResultItem | undefined) => {
    if (!result) {
      markQueue(key, {
        status: 'error', progress: 1, detail: 'No result returned',
      })
      return
    }
    if (result.status === 'accepted') {
      const meta = [
        result.format,
        result.width && result.height
          ? `${result.width}×${result.height}` : null,
        result.shared ? 'shared asset' : null,
      ].filter(Boolean).join(' · ')
      markQueue(key, {
        status: 'accepted', progress: 1, shared: result.shared, detail: meta,
      })
    } else if (result.status === 'duplicate') {
      markQueue(key, {
        status: 'duplicate',
        progress: 1,
        detail: 'Identical content already in this dataset',
      })
    } else {
      markQueue(key, {
        status: 'rejected',
        progress: 1,
        detail: rejectionLabel(result.reason),
      })
    }
  }

  // ── Upload strategies ──────────────────────────────────────────────────────

  const uploadMany = async (dsId: string, entries: PendingEntry[]) => {
    entries.forEach(e => markQueue(e.key, { status: 'uploading', progress: 0.3 }))
    const outcome: IngestOutcome = await uploadDatasetFiles(
      dsId, entries.map(e => e.file))
    entries.forEach((e, idx) => applyResult(e.key, outcome.results?.[idx]))
  }

  const uploadChunked = async (dsId: string, entry: PendingEntry) => {
    markQueue(entry.key, { status: 'uploading', progress: 0 })
    const session = await createUploadSession(dsId, {
      filename: entry.file.name,
      total_bytes: entry.file.size,
      total_chunks: planChunkCount(entry.file.size),
    })
    const received = new Set(session.received_chunks)
    for (let i = 0; i < session.total_chunks; i++) {
      if (!received.has(i)) {
        // Slice with the SERVER's chunk size — the last chunk depends on it.
        const [start, end] = chunkRange(
          entry.file.size, session.chunk_size, i)
        const blob = entry.file.slice(start, end)
        let sent = false
        let lastErr: unknown = null
        for (let attempt = 0;
          attempt < CHUNK_RETRY_ATTEMPTS && !sent;
          attempt++) {
          try {
            await sendUploadChunk(dsId, session.upload_id, i, blob)
            sent = true
          } catch (e) {
            lastErr = e
            await new Promise(resolve =>
              setTimeout(resolve, 400 * (attempt + 1)))
          }
        }
        if (!sent) throw lastErr ?? new Error('Chunk upload failed')
      }
      markQueue(entry.key, {
        progress: Math.round(((i + 1) / session.total_chunks) * 100) / 100,
      })
    }
    const outcome = await completeUpload(dsId, session.upload_id)
    applyResult(entry.key, outcome.results?.[0])
  }

  const uploadZipItem = async (dsId: string, entry: PendingEntry) => {
    markQueue(entry.key, { status: 'uploading', progress: 0.15 })
    const outcome = await uploadDatasetZip(dsId, entry.file)
    const s = outcome.stats
    const skipped = outcome.skipped?.length ?? 0
    const parts = [
      `${s.accepted} added`,
      s.duplicate ? `${s.duplicate} duplicates` : null,
      s.rejected ? `${s.rejected} rejected` : null,
      skipped ? `${skipped} entries skipped` : null,
    ].filter(Boolean).join(' · ')
    const status: QueueStatus = s.accepted > 0
      ? 'accepted'
      : (s.rejected > 0 ? 'rejected' : 'duplicate')
    markQueue(entry.key, { status, progress: 1, detail: parts })
  }

  const refreshAfterUpload = async (dsId: string) => {
    await reloadList()
    await reloadDetail(dsId)
    try {
      const fin = await finalizeDataset(dsId)
      toast.success(
        'Dataset verified',
        `${fin.image_count} images stored — dataset is ready`)
      await reloadList()
      await reloadDetail(dsId)
    } catch {
      // Pending sessions or verification needed: the banner + manual
      // Finalize button surface it — never mark ready without verification.
    }
  }

  const runUploads = async (dsId: string, files: File[]) => {
    if (files.length === 0) return
    setUploading(true)
    try {
      // ZIP archives first, one at a time (server enforces ZIP security).
      for (const file of files.filter(f => isZipFile(f.name))) {
        const key = newKey()
        pushItem({
          key, name: file.name, size: file.size,
          status: 'queued', progress: 0,
        })
        await uploadZipItem(dsId, { file, key })
      }

      // Images: small files batched (≤10/request), large files chunked.
      const imageFiles = files.filter(f => !isZipFile(f.name))
      let i = 0
      while (i < imageFiles.length) {
        const file = imageFiles[i]
        const key = newKey()
        pushItem({
          key, name: file.name, size: file.size,
          status: 'queued', progress: 0,
        })
        if (file.size > DATASET_CHUNK_BYTES) {
          await uploadChunked(dsId, { file, key })
          i += 1
        } else {
          const group: PendingEntry[] = [{ file, key }]
          i += 1
          while (i < imageFiles.length
            && group.length < DATASET_BATCH_SIZE
            && imageFiles[i].size <= DATASET_CHUNK_BYTES) {
            const gfile = imageFiles[i]
            const gkey = newKey()
            pushItem({
              key: gkey, name: gfile.name, size: gfile.size,
              status: 'queued', progress: 0,
            })
            group.push({ file: gfile, key: gkey })
            i += 1
          }
          await uploadMany(dsId, group)
        }
      }
      await refreshAfterUpload(dsId)
    } catch (e) {
      toast.error(
        'Upload interrupted',
        uploadErrorMessage(
          e,
          'The upload did not complete — retrying resumes from the '
          + 'server-side checkpoint.'))
      await reloadDetail(dsId).catch(() => undefined)
    } finally {
      setUploading(false)
    }
  }

  const handleFiles = (list: FileList | null) => {
    if (!list || list.length === 0) return
    if (!selectedId) {
      toast.error(
        'No dataset selected',
        'Create or open a dataset before uploading.')
      return
    }
    if (uploading) return
    const files = Array.from(list)
    // Types are validated by content on the server — the client only
    // pre-filters obvious misses for fast feedback.
    const ok = files.filter(
      f => isZipFile(f.name) || isSupportedImageName(f.name))
    const bad = files.length - ok.length
    if (bad > 0) {
      toast.error(
        `${bad} file${bad > 1 ? 's' : ''} skipped`,
        'Only .jpg / .jpeg / .png / .webp images and .zip archives are '
        + 'accepted.')
    }
    if (ok.length > 0) runUploads(selectedId, ok)
    if (fileInput.current) fileInput.current.value = ''
    if (zipInput.current) zipInput.current.value = ''
  }

  // ── Dataset actions ────────────────────────────────────────────────────────

  const openDataset = (id: string) => {
    setSelectedId(id)
    setDetail(null)
    setDetailLoadedId(null)
    setImages([])
    setImageTotal(0)
    setImageQuery('')
    setActiveQuery('')
    setPending([])
    setQueue([])
  }

  const handleCreate = async () => {
    const name = newName.trim()
    if (!name) return
    setCreateBusy(true)
    try {
      const ds = await createDataset({
        name, description: newDesc.trim(),
      })
      toast.success('Dataset created', ds.name)
      setShowCreate(false)
      setNewName('')
      setNewDesc('')
      await reloadList()
      openDataset(ds.id)
    } catch (e) {
      toast.error(
        'Create failed', uploadErrorMessage(e, 'The dataset was not created.'))
    } finally {
      setCreateBusy(false)
    }
  }

  const handleDelete = async () => {
    const target = deleteTarget
    if (!target || deleteConfirmText !== target.name) return
    setDeleteBusy(true)
    try {
      await deleteDataset(target.id, target.name)
      toast.success(
        'Dataset deleted', 'Shared image assets were left intact.')
      setDeleteTarget(null)
      setDeleteConfirmText('')
      if (selectedId === target.id) {
        setSelectedId(null)
        setDetail(null)
        setDetailLoadedId(null)
        setImages([])
        setPending([])
        setQueue([])
      }
      await reloadList()
    } catch (e) {
      toast.error(
        'Delete failed',
        uploadErrorMessage(e, 'The dataset was not deleted.'))
    } finally {
      setDeleteBusy(false)
    }
  }

  const handleFinalize = async () => {
    if (!selectedId) return
    setFinalizing(true)
    try {
      const fin = await finalizeDataset(selectedId)
      setDetail(fin)
      toast.success(
        'Verified', `${fin.image_count} images — dataset is ready`)
      await reloadList()
    } catch (e) {
      toast.error(
        'Cannot finalize',
        uploadErrorMessage(e, 'Verification did not pass.'))
      await reloadDetail(selectedId).catch(() => undefined)
    } finally {
      setFinalizing(false)
    }
  }

  const handleDiscard = async (session: UploadSession) => {
    if (!selectedId) return
    try {
      await discardUpload(selectedId, session.upload_id)
      setPending(prev =>
        prev.filter(p => p.upload_id !== session.upload_id))
      toast.success('Discarded', `${session.filename} upload removed`)
    } catch (e) {
      toast.error(
        'Discard failed',
        uploadErrorMessage(e, 'The upload could not be discarded.'))
    }
  }

  const runSearch = async () => {
    if (!selectedId) return
    const q = imageQuery.trim()
    try {
      const page = await listDatasetImages(selectedId, 0, 60, q)
      setImages(page?.images ?? [])
      setImageTotal(page?.total ?? 0)
      setActiveQuery(q)
    } catch (e) {
      toast.error(
        'Search failed', uploadErrorMessage(e, 'Search did not complete.'))
    }
  }

  const loadMoreImages = async () => {
    if (!selectedId) return
    try {
      const page = await listDatasetImages(
        selectedId, images.length, 60, activeQuery)
      setImages(prev => [...prev, ...(page?.images ?? [])])
      setImageTotal(page?.total ?? images.length)
    } catch (e) {
      toast.error(
        'Load failed', uploadErrorMessage(e, 'More images could not load.'))
    }
  }

  // ── Render helpers ─────────────────────────────────────────────────────────

  const statusChip = (status: string) => (
    <span className={`dsp-status dsp-status--${status}`}>
      {DATASET_STATUS_LABEL[status] ?? status}
    </span>
  )

  const queueIcon = (status: QueueStatus) => {
    switch (status) {
      case 'accepted': return <CheckCircle2 size={14} />
      case 'duplicate': return <Layers size={14} />
      case 'rejected': return <XCircle size={14} />
      case 'error': return <AlertTriangle size={14} />
      case 'uploading': return <RefreshCw size={14} className="dsp-spin" />
      default: return <Clock size={14} />
    }
  }

  const finishedCount = queue.filter(
    q => q.status === 'accepted' || q.status === 'duplicate'
      || q.status === 'rejected' || q.status === 'error').length

  const detailReady = selectedId && detail && detailLoadedId === selectedId
  const rejectedEntries = detail
    ? Object.entries(detail.rejected_reasons ?? {})
    : []

  // ── View: dataset list ─────────────────────────────────────────────────────

  if (!selectedId) {
    return (
      <div className="dsp">
        <div className="dsp-head">
          <div>
            <h2>Datasets</h2>
            <p>
              Mixed, unlabelled photo collections stored immutably and
              content-addressed — ready for brand detection in Phase 3.
            </p>
          </div>
          <AnimatedBtn
            type="button"
            variant="default"
            size="md"
            label="New dataset"
            onClick={() => setShowCreate(v => !v)}
          >
            <Plus size={15} /> New dataset
          </AnimatedBtn>
        </div>

        {showCreate && (
          <Card className="dsp-create">
            <label className="dsp-field">
              <span>Dataset name *</span>
              <input
                className="bp-input"
                value={newName}
                maxLength={200}
                placeholder="e.g., Trade Show 2026 — Day 1"
                onChange={e => setNewName(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') handleCreate() }}
              />
            </label>
            <label className="dsp-field">
              <span>Description</span>
              <textarea
                className="bp-textarea"
                value={newDesc}
                rows={2}
                maxLength={2000}
                placeholder="Where these photos came from and what they contain…"
                onChange={e => setNewDesc(e.target.value)}
              />
            </label>
            <div className="dsp-create__actions">
              <AnimatedBtn
                type="button"
                variant="ghost"
                size="md"
                label="Cancel"
                onClick={() => { setShowCreate(false); setNewName(''); setNewDesc('') }}
              >
                <X size={14} /> Cancel
              </AnimatedBtn>
              <AnimatedBtn
                type="button"
                variant="default"
                size="md"
                label="Create dataset"
                disabled={!newName.trim()}
                loading={createBusy}
                onClick={handleCreate}
              >
                <Plus size={14} /> Create dataset
              </AnimatedBtn>
            </div>
          </Card>
        )}

        {loadError && (
          <div className="dsp-error">
            <p>{loadError}</p>
            <AnimatedBtn
              type="button" variant="ghost" size="sm" label="Retry"
              onClick={reloadList}
            >
              <RefreshCw size={13} /> Try again
            </AnimatedBtn>
          </div>
        )}

        {!listLoaded && <div className="dsp-center"><Spinner size={26} /></div>}

        {listLoaded && !loadError && datasets.length === 0 && (
          <div className="dsp-empty">
            <div className="dsp-empty__icon"><Database size={24} /></div>
            <h3>No datasets yet</h3>
            <p>
              Create a dataset, then drag in photos or a ZIP archive.
              Files are validated by content, hashed with SHA-256 and stored
              immutably — duplicates are detected automatically.
            </p>
            <AnimatedBtn
              type="button" variant="default" size="md"
              label="Create your first dataset"
              onClick={() => setShowCreate(true)}
            >
              <Plus size={15} /> Create your first dataset
            </AnimatedBtn>
          </div>
        )}

        {listLoaded && datasets.length > 0 && (
          <div className="dsp-grid">
            {datasets.map(ds => (
              <button
                key={ds.id}
                type="button"
                className="dsp-card"
                onClick={() => openDataset(ds.id)}
              >
                <div className="dsp-card__top">
                  <span className="dsp-card__icon"><Database size={16} /></span>
                  <span className="dsp-card__name">{ds.name}</span>
                  {statusChip(ds.status)}
                </div>
                {ds.description && (
                  <p className="dsp-card__desc">{ds.description}</p>
                )}
                <div className="dsp-card__stats">
                  <span><strong>{ds.image_count}</strong> images</span>
                  <span><strong>{ds.duplicate_count}</strong> dups</span>
                  <span><strong>{ds.rejected_count}</strong> rejected</span>
                  <span>{formatBytes(ds.bytes_total)}</span>
                </div>
                <div className="dsp-card__foot">
                  <span>
                    {new Date(ds.created_at).toLocaleString(undefined, {
                      day: 'numeric', month: 'short', year: 'numeric',
                      hour: '2-digit', minute: '2-digit',
                    })}
                  </span>
                  {(ds.pending_uploads ?? 0) > 0 && (
                    <span className="dsp-card__pending">
                      {ds.pending_uploads} pending upload
                      {(ds.pending_uploads ?? 0) > 1 ? 's' : ''}
                    </span>
                  )}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    )
  }

  // ── View: dataset detail ───────────────────────────────────────────────────

  return (
    <div className="dsp">
      <button
        type="button"
        className="dsp-back"
        onClick={() => setSelectedId(null)}
      >
        <ChevronLeft size={15} /> All datasets
      </button>

      {!detailReady && (
        <div className="dsp-center"><Spinner size={26} /></div>
      )}

      {detailReady && detail && (
        <>
          {/* ── Header ── */}
          <Card className="dsp-detail-head">
            <div className="dsp-detail-head__row">
              <div className="dsp-detail-head__title">
                <h2>{detail.name}</h2>
                {statusChip(detail.status)}
              </div>
              <div className="dsp-detail-head__actions">
                <AnimatedBtn
                  type="button" variant="ghost" size="sm"
                  label="Refresh dataset"
                  onClick={() => reloadDetail(selectedId)}
                >
                  <RefreshCw size={13} /> Refresh
                </AnimatedBtn>
                <AnimatedBtn
                  type="button" variant="default" size="sm"
                  label="Finalize and verify dataset"
                  loading={finalizing}
                  onClick={handleFinalize}
                >
                  <CheckCircle2 size={13} /> Finalize & verify
                </AnimatedBtn>
                <AnimatedBtn
                  type="button" variant="danger" size="sm"
                  label="Delete dataset"
                  onClick={() => {
                    setDeleteTarget(detail)
                    setDeleteConfirmText('')
                  }}
                >
                  <Trash2 size={13} /> Delete
                </AnimatedBtn>
              </div>
            </div>
            {detail.description && (
              <p className="dsp-detail-head__desc">{detail.description}</p>
            )}
            <div className="dsp-stats">
              <div className="dsp-stat">
                <span className="dsp-stat__value">{detail.image_count}</span>
                <span className="dsp-stat__label">images</span>
              </div>
              <div className="dsp-stat">
                <span className="dsp-stat__value">{detail.duplicate_count}</span>
                <span className="dsp-stat__label">duplicates</span>
              </div>
              <div className="dsp-stat">
                <span className="dsp-stat__value">{detail.shared_count}</span>
                <span className="dsp-stat__label">shared assets</span>
              </div>
              <div className="dsp-stat">
                <span className="dsp-stat__value">{detail.rejected_count}</span>
                <span className="dsp-stat__label">rejected</span>
              </div>
              <div className="dsp-stat">
                <span className="dsp-stat__value">
                  {formatBytes(detail.bytes_total)}
                </span>
                <span className="dsp-stat__label">stored</span>
              </div>
              <div className="dsp-stat">
                <span className="dsp-stat__value dsp-stat__value--sm">
                  {new Date(detail.created_at).toLocaleString(undefined, {
                    day: 'numeric', month: 'short', year: 'numeric',
                    hour: '2-digit', minute: '2-digit',
                  })}
                </span>
                <span className="dsp-stat__label">created</span>
              </div>
            </div>
            {rejectedEntries.length > 0 && (
              <div className="dsp-rejects">
                {rejectedEntries.map(([reason, count]) => (
                  <span key={reason} className="dsp-reject">
                    {rejectionLabel(reason)} · {count}
                  </span>
                ))}
              </div>
            )}
          </Card>

          {/* ── Pending (interrupted) uploads ── */}
          {pending.length > 0 && (
            <div className="dsp-pending">
              <div className="dsp-pending__head">
                <AlertTriangle size={14} />
                <span>
                  {pending.length} incomplete upload
                  {pending.length > 1 ? 's' : ''} — resume by re-selecting
                  the file, or discard.
                </span>
              </div>
              {pending.map(p => (
                <div key={p.upload_id} className="dsp-pending__row">
                  <span className="dsp-pending__name">{p.filename}</span>
                  <span className="dsp-pending__progress">
                    {p.received_chunks.length}/{p.total_chunks} chunks ·{' '}
                    {formatBytes(p.total_bytes)}
                  </span>
                  <AnimatedBtn
                    type="button" variant="ghost" size="sm"
                    label={`Discard ${p.filename}`}
                    onClick={() => handleDiscard(p)}
                  >
                    <X size={13} /> Discard
                  </AnimatedBtn>
                </div>
              ))}
            </div>
          )}

          {/* ── Upload zone ── */}
          <div
            className={`dsp-drop${dragOver ? ' dsp-drop--over' : ''}${
              uploading ? ' dsp-drop--busy' : ''}`}
            onDragOver={e => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={e => {
              e.preventDefault()
              setDragOver(false)
              handleFiles(e.dataTransfer.files)
            }}
          >
            <Upload size={22} />
            <p className="dsp-drop__title">
              {uploading ? 'Uploading…' : 'Drag & drop photos or a ZIP'}
            </p>
            <p className="dsp-drop__sub">
              JPEG · PNG · WebP — validated by content, SHA-256 deduplicated.
              Large files upload in resumable chunks.
            </p>
            <div className="dsp-drop__actions">
              <AnimatedBtn
                type="button" variant="default" size="md"
                label="Choose image files"
                disabled={uploading}
                onClick={() => fileInput.current?.click()}
              >
                <Plus size={14} /> Choose images
              </AnimatedBtn>
              <AnimatedBtn
                type="button" variant="ghost" size="md"
                label="Choose a ZIP archive"
                disabled={uploading}
                onClick={() => zipInput.current?.click()}
              >
                <FileArchive size={14} /> Upload ZIP
              </AnimatedBtn>
            </div>
            <input
              ref={fileInput}
              type="file"
              multiple
              hidden
              accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
              onChange={e => handleFiles(e.target.files)}
            />
            <input
              ref={zipInput}
              type="file"
              hidden
              accept=".zip,application/zip"
              onChange={e => handleFiles(e.target.files)}
            />
          </div>

          {/* ── Upload queue ── */}
          {queue.length > 0 && (
            <Card className="dsp-queue">
              <div className="dsp-queue__head">
                <span>
                  Uploads — {finishedCount}/{queue.length} processed
                </span>
                <AnimatedBtn
                  type="button" variant="ghost" size="sm"
                  label="Clear finished items"
                  onClick={() => setQueue(prev => prev.filter(
                    q => q.status === 'queued' || q.status === 'uploading'))}
                >
                  <X size={13} /> Clear finished
                </AnimatedBtn>
              </div>
              <ul className="dsp-queue__list">
                {queue.map(item => (
                  <li key={item.key} className="dsp-queue__row">
                    <span className={`dsp-queue__icon dsp-queue__icon--${item.status}`}>
                      {queueIcon(item.status)}
                    </span>
                    <span className="dsp-queue__name" title={item.name}>
                      {item.name}
                    </span>
                    <span className="dsp-queue__size">
                      {formatBytes(item.size)}
                    </span>
                    <span className={`dsp-queue__status dsp-queue__status--${item.status}`}>
                      {QUEUE_STATUS_LABEL[item.status]}
                      {item.shared ? ' · shared' : ''}
                    </span>
                    {item.status === 'uploading' && (
                      <span className="dsp-bar">
                        <span
                          className="dsp-bar__fill"
                          style={{ width: `${Math.round(item.progress * 100)}%` }}
                        />
                      </span>
                    )}
                    {item.detail && (
                      <span className="dsp-queue__detail">{item.detail}</span>
                    )}
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {/* ── Stored images ── */}
          <section className="dsp-images">
            <header className="dsp-images__head">
              <div>
                <h3>Stored images</h3>
                <p>
                  {imageTotal} image{imageTotal === 1 ? '' : 's'}
                  {activeQuery ? ` matching “${activeQuery}”` : ''}
                  {' '}— originals are immutable copies.
                </p>
              </div>
              <form
                className="dsp-search"
                onSubmit={e => { e.preventDefault(); runSearch() }}
              >
                <Search size={14} />
                <input
                  value={imageQuery}
                  placeholder="Search filename or sha…"
                  onChange={e => setImageQuery(e.target.value)}
                />
                <button type="submit" aria-label="Search images">
                  Go
                </button>
              </form>
            </header>

            {images.length === 0 && (
              <div className="dsp-empty dsp-empty--sm">
                <ImagePlus size={20} />
                <p>
                  {activeQuery
                    ? 'No images match this search.'
                    : 'No images stored yet — upload some above.'}
                </p>
              </div>
            )}

            <div className="dsp-thumbs">
              {images.map(img => {
                const url = assetUrl(
                  `output/brand_intelligence/${img.stored_path}`)
                return (
                  <figure
                    key={img.image_id}
                    className="dsp-thumb"
                    title={
                      `${img.original_filename}\n${img.format} `
                      + `${img.width}×${img.height} · ${formatBytes(img.bytes)}`
                      + `\nsha256 ${img.sha256.slice(0, 16)}…`
                    }
                  >
                    {url
                      ? <img src={url} alt={img.original_filename} loading="lazy" />
                      : <span>{img.format}</span>}
                    <figcaption>{img.original_filename}</figcaption>
                  </figure>
                )
              })}
            </div>

            {images.length < imageTotal && (
              <div className="dsp-images__more">
                <AnimatedBtn
                  type="button" variant="ghost" size="sm"
                  label="Load more images"
                  onClick={loadMoreImages}
                >
                  Load more ({images.length}/{imageTotal})
                </AnimatedBtn>
              </div>
            )}
          </section>
        </>
      )}

      {/* ── Delete confirmation ── */}
      <Modal
        open={!!deleteTarget}
        onClose={() => {
          if (!deleteBusy) { setDeleteTarget(null); setDeleteConfirmText('') }
        }}
        title="Delete dataset"
        width={480}
      >
        <p className="dsp-modal-text">
          This permanently removes <strong>{deleteTarget?.name}</strong>,
          its manifest and its upload history. Images stored in the shared
          content-addressed store are <em>not</em> deleted — datasets that
          reference them keep working.
        </p>
        <p className="dsp-modal-text">
          Type the dataset name to confirm:
        </p>
        <input
          className="bp-input"
          value={deleteConfirmText}
          placeholder={deleteTarget?.name}
          onChange={e => setDeleteConfirmText(e.target.value)}
        />
        <div className="dsp-modal-actions">
          <AnimatedBtn
            type="button" variant="ghost" size="md"
            label="Cancel"
            disabled={deleteBusy}
            onClick={() => { setDeleteTarget(null); setDeleteConfirmText('') }}
          >
            <X size={15} /> Cancel
          </AnimatedBtn>
          <AnimatedBtn
            type="button" variant="danger" size="md"
            label="Delete dataset"
            disabled={deleteConfirmText !== (deleteTarget?.name ?? '')}
            loading={deleteBusy}
            onClick={handleDelete}
          >
            <Trash2 size={15} /> Delete forever
          </AnimatedBtn>
        </div>
      </Modal>
    </div>
  )
}

export default DatasetsPanel
