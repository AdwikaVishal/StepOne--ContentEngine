import axios from 'axios'
import type { BrandProfile } from './lib/brandProfile'

export const api = axios.create({ baseURL: '', timeout: 300_000 })

export interface QualityScores { quality_score:number; aesthetic_score:number; blur_score:number; brightness_score:number; calibrated?:boolean }
export interface BBox { x1:number; y1:number; x2:number; y2:number }
export interface HighlightClip { start:number; end:number; score:number }

export interface QualityResult   { filename:string; file_url:string; scores:QualityScores }
export interface FaceResult      { filename:string; file_url:string; face_count:number; confidences:number[]; bboxes:BBox[]; image_width:number; image_height:number }
export interface ContentResult   { filename:string; file_url:string; scene_concepts:string[]; relevance_scores:Record<string,number>; concept_match_score:number }
export interface HighlightResult { filename:string; file_url:string; highlights:HighlightClip[]; total_selected_seconds:number }

// ── Crop intelligence ────────────────────────────────────────────────────────
export interface CropBox   { x1:number; y1:number; x2:number; y2:number }   // normalised 0-1
export interface CropMeta  {
  image_path: string
  target_w: number; target_h: number; target_ratio: number
  source_w: number; source_h: number
  crop_box: number[]; crop_box_norm: number[]
  crop_w: number; crop_h: number
  composition_score: number
  breakdown: Record<string,number>
  scene_type: string
  subjects_preserved: string[]
  faces_preserved: number; faces_total: number
  warnings: string[]; trade_off: string|null; manual_override: boolean
}
export interface CropAnalysis {
  width:number; height:number; orientation:string; face_count:number
  faces:Array<{label:string;bbox:number[];bbox_px:number[];confidence:number}>
  people:Array<{label:string;bbox:number[];bbox_px:number[];confidence:number}>
  objects:Array<{label:string;bbox:number[];bbox_px:number[];confidence:number}>
  salient_regions:number[][]
  main_subject:number[]|null; secondary_subjects:number[][]
  focal_point:number[]; focal_region:number[]
  scene_type:string; scene_type_confidence:number; confidence:number
  models_used:string[]
}
export interface CropAnalyzeResult { filename:string; file_url:string; analysis:CropAnalysis }
export interface CropComputeResult { filename:string; file_url:string; crop_url:string; crop:CropMeta }

export interface Selection {
  filename:string; file_url:string
  intended_use:'collage'|'reel'|'story'|'case_study'
  confidence:number; low_confidence:boolean; selection_reason:string
  scores:{ quality:number; aesthetic:number; final:number }
  face_count:number; bboxes:BBox[]; scene_concepts:string[]
  asset_type:'image'|'video'; duration:number; highlight_clips:HighlightClip[]
}
export interface PipelineResult { event:string; total:number; selections:Selection[] }
export interface GenerateResult {
  event: string
  output_dir: string
  files: Record<string, string>
  captions: Record<string, string>
  layouts?: string[]
  status?: string
}
export interface JobStatus      { job_id:string; status:string; progress?:{step?:string;pct?:number}; backend?:string; error?:string|null }

// Per-request timeout policies (ms). One global timeout is the wrong tool:
// health/status polls must fail fast, uploads may need minutes, and result
// retrieval is bounded by output size. Each call overrides the instance default.
export const TIMEOUT = {
  health:    15_000,   // health / model status
  submit:    120_000,  // multipart upload + validation (may be large)
  status:    15_000,   // job status polling
  result:    60_000,   // job result retrieval (text + file listing)
  ai_op:     60_000,   // individual synchronous ML operations
} as const

const fd = (files: File[], extra: Record<string,string> = {}) => {
  const f = new FormData()
  files.forEach(x => f.append('files', x))
  Object.entries(extra).forEach(([k,v]) => f.append(k,v))
  return f
}

export interface GenerateFastOptions {
  eventName: string
  eventDescription?: string
  mode?: 'standard' | 'gff'
  brands?: string[]
  selectedBrand?: string
  renderFilesByBrand?: File[][]
  generateReel?: boolean
}

export const checkHealth      = ()                                       => api.get<{status:string;version:string}>('/health', { timeout: TIMEOUT.health }).then(r=>r.data)
export const getModelStatus   = ()                                       => api.get<Record<string,string>>('/api/model-status', { timeout: TIMEOUT.health }).then(r=>r.data)
export const assessQuality    = (file:File)                              => { const f=new FormData(); f.append('file',file); return api.post<QualityResult>('/api/quality',f,{ timeout: TIMEOUT.ai_op }).then(r=>r.data) }
export const detectFaces      = (file:File)                              => { const f=new FormData(); f.append('file',file); return api.post<FaceResult>('/api/faces',f,{ timeout: TIMEOUT.ai_op }).then(r=>r.data) }
export const analyseContent   = (file:File)                              => { const f=new FormData(); f.append('file',file); return api.post<ContentResult>('/api/content',f,{ timeout: TIMEOUT.ai_op }).then(r=>r.data) }
export const extractHighlights= (file:File, dur=45)                     => { const f=new FormData(); f.append('file',file); return api.post<HighlightResult>(`/api/highlights?target_duration=${dur}`,f,{ timeout: TIMEOUT.ai_op }).then(r=>r.data) }
export const runPipeline      = (files:File[], desc:string)              => api.post<PipelineResult>('/api/pipeline', fd(files,{event_description:desc}), { timeout: TIMEOUT.submit }).then(r=>r.data)
export const runPipelineAsync = (files:File[], desc:string)              => api.post<{job_id:string;status:string;backend:string}>('/api/pipeline/async', fd(files,{event_description:desc}), { timeout: TIMEOUT.submit }).then(r=>r.data)
export const generateAsync    = (files:File[], name:string, desc:string) => api.post<{job_id:string;status:string;backend:string}>('/api/generate/async', fd(files,{event_name:name,event_description:desc}), { timeout: TIMEOUT.submit }).then(r=>r.data)
export const generateFast     = (files:File[], opts:GenerateFastOptions) => {
  const f = fd(files, {
    event_name: opts.eventName,
    event_description: opts.eventDescription ?? opts.eventName,
    mode: opts.mode ?? 'standard',
    brands: JSON.stringify(opts.brands ?? []),
    selected_brand: opts.selectedBrand ?? '',
    generate_reel: String(opts.generateReel ?? false),
  })
  const renderBrandIds: string[] = []
  ;(opts.renderFilesByBrand ?? []).forEach((brandFiles, idx) => {
    const brand = opts.brands?.[idx] ?? ''
    brandFiles.forEach(file => {
      f.append('render_files', file)
      renderBrandIds.push(brand)
    })
  })
  f.append('render_brand_ids', JSON.stringify(renderBrandIds))
  return api.post<{job_id:string;status:string;backend:string}>('/api/generate/fast', f).then(r=>r.data)
}
export const getJobStatus     = (id:string, config?:any)                 => api.get<JobStatus>(`/api/jobs/${id}/status`, { timeout: TIMEOUT.status, ...config }).then(r=>r.data)
export const getJobResult     = (id:string)                              => api.get<GenerateResult>(`/api/jobs/${id}/result`, { timeout: TIMEOUT.result }).then(r=>r.data)

export interface RegenerateOptions {
  eventName: string
  eventDescription?: string
  platform?: 'linkedin' | 'instagram' | 'reel' | 'stories' | 'all'
  sceneConcepts?: string[]
  faceCount?: number
}
export interface RegenerateResult {
  backend: 'torch_local' | 'local_llm' | 'template'
  event: string
  provider?: string
  model?: string
  model_path?: string
  local_only?: boolean
  remote_inference_disabled?: boolean
  provider_status?: any
  linkedin?: string
  instagram?: string
  reel?: string
  stories?: string[]
}

export interface LLMStatus {
  provider: string
  model: string
  model_path: string
  local_only: boolean
  remote_inference_disabled: boolean
  device: string | null
  loaded: boolean
  offline_enforcement: Record<string, string | null>
  last_load_error: string | null
}

export const getLLMStatus = () =>
  api.get<LLMStatus>('/api/llm/status', { timeout: TIMEOUT.health }).then(r => r.data)

export interface BrandClusterPoint {
  path: string
  brand_id: string
  confidence: number
  x: number
  y: number
  similarity_scores: Record<string, number>
  confidence_band: string
  margin_to_second: number
}

export interface BrandClusterCentroid {
  x: number
  y: number
  count: number
  avg_confidence: number
}

export interface BrandClustersResponse {
  event_name: string
  total_points: number
  points: BrandClusterPoint[]
  centroids: Record<string, BrandClusterCentroid>
  filters: { min_confidence: number }
}

export const regenerateCaptions = (opts: RegenerateOptions): Promise<RegenerateResult> => {
  const f = new FormData()
  f.append('event_name',        opts.eventName)
  f.append('event_description', opts.eventDescription ?? opts.eventName)
  f.append('platform',          opts.platform ?? 'all')
  f.append('scene_concepts',    (opts.sceneConcepts ?? []).join(','))
  f.append('face_count',        String(opts.faceCount ?? 0))
  return api.post<RegenerateResult>('/api/captions/regenerate', f).then(r => r.data)
}

export const getBrandClusters = (eventName: string, minConfidence = 0) =>
  api.get<BrandClustersResponse>('/api/gff/brand-clusters', {
    params: { event_name: eventName, min_confidence: minConfidence },
  }).then(r => r.data)

// New types for asset selection
export interface CategorizedAsset {
  id: string
  url: string
  score: number
  face_count: number
  concepts: string[]
  category: string
}

export interface CategorizedAssetsResponse {
  job_id: string
  categories: Record<string, CategorizedAsset[]>
  category_counts: Record<string, number>
  top_assets: CategorizedAsset[]
  total_assets: number
}

export const getCategorizedAssets = (jobId: string) => 
  api.get<CategorizedAssetsResponse>(`/api/assets/categorized/${jobId}`).then(r => r.data)

export interface GenerateFromSelectedRequest {
  job_id: string
  selected_asset_ids: string[]
}

export const generateFromSelected = (jobId: string, selectedAssetIds: string[]) => 
  api.post<any>('/api/generate/from-selected', { job_id: jobId, selected_asset_ids: selectedAssetIds }).then(r => r.data)

// Enhanced types for new features
export interface EnhancedAsset {
  id: string
  url: string
  score: number
  faces: number
  concepts: string[]
}

export interface CategoryAssets {
  name: string
  icon: string
  color?: string
  confidence?: number
  assets: EnhancedAsset[]
}

export interface EnhancedAssetsResponse {
  job_id: string
  top_overall: EnhancedAsset[]
  per_category: Record<string, CategoryAssets>
  stats: { total: number; unique: number; deduped?: number; duplicates_removed?: number; pending_processing?: boolean; has_real_scores?: boolean }
}

export interface CustomGenerateRequest {
  job_id: string
  asset_ids: string[]
  linkedin_layout?: string
  story_layout?: string
  reel_layout?: string
}

const CATEGORY_DEFINITIONS: Record<string, { name: string; icon: string; color: string; keywords: string[] }> = {
  stage: {
    name: 'Stage',
    icon: '🎤',
    color: '#e3f2fd',
    keywords: ['stage', 'presentation', 'podium', 'speaker', 'keynote', 'talk', 'lecture', 'platform'],
  },
  booth: {
    name: 'Booth',
    icon: '🏪',
    color: '#e8f5e9',
    keywords: ['booth', 'exhibit', 'display', 'stand', 'kiosk', 'table', 'setup', 'counter'],
  },
  crowd: {
    name: 'Crowd',
    icon: '👥',
    color: '#fff3e0',
    keywords: ['crowd', 'audience', 'people', 'attendees', 'mass', 'gathering', 'spectators', 'viewers', 'event', 'conference'],
  },
  speakers: {
    name: 'Speakers',
    icon: '🎙️',
    color: '#f3e5f5',
    keywords: ['speaker', 'presenter', 'host', 'moderator', 'panel', 'lecturer', 'guest'],
  },
  networking: {
    name: 'Networking',
    icon: '🤝',
    color: '#e0f7fa',
    keywords: ['networking', 'conversation', 'handshake', 'meeting', 'chat', 'discussion', 'interaction'],
  },
  awards: {
    name: 'Awards',
    icon: '🏆',
    color: '#ffebee',
    keywords: ['award', 'trophy', 'winner', 'prize', 'ceremony', 'medal', 'recognition'],
  },
}

const generateSmartCategories = (assets: EnhancedAsset[]): Record<string, CategoryAssets> => {
  const categories: Record<string, CategoryAssets> = {}

  for (const asset of assets) {
    const searchable = [asset.url, ...(asset.concepts ?? [])].join(' ').toLowerCase()

    for (const [id, definition] of Object.entries(CATEGORY_DEFINITIONS)) {
      if (!definition.keywords.some(keyword => searchable.includes(keyword))) continue

      categories[id] ??= {
        name: definition.name,
        icon: definition.icon,
        color: definition.color,
        confidence: 0,
        assets: [],
      }
      categories[id].assets.push(asset)
      break
    }
  }

  for (const category of Object.values(categories)) {
    const averageScore = category.assets.reduce((sum, asset) => sum + asset.score, 0) / category.assets.length
    category.confidence = Math.round(Math.min(1, averageScore || 0) * 100)
  }

  return categories
}

export const getEnhancedAssets = (jobId: string) =>
  api.get<EnhancedAssetsResponse>(`/api/assets/enhanced/${jobId}`).then(r => {
    const data = r.data
    const hasCategories = Object.values(data.per_category ?? {}).some(category => category.assets?.length > 0)

    if (!hasCategories && data.top_overall?.length > 0) {
      data.per_category = generateSmartCategories(data.top_overall)
    }

    return data
  })

export const generateCustom = (req: CustomGenerateRequest) => 
  api.post<any>('/api/generate/custom', req).then(r => r.data)

export interface LayoutPreviewRequest {
  layout_type: 'linkedin' | 'story' | 'reel'
  layout_id: string
  asset_ids: string[]
  job_id: string
}

export const getLayoutPreview = (req: LayoutPreviewRequest) => 
  api.post<any>('/api/layout/preview', req).then(r => r.data)


// Studio API
export const createStudioProject = (data: { name?: string; brief?: string; platforms?: string[] }) => {
  const f = new FormData()
  f.append('name', data.name || '')
  f.append('brief', data.brief || '')
  f.append('platforms', JSON.stringify(data.platforms || ['linkedin', 'instagram']))
  return api.post<any>('/api/studio/projects', f).then(r => r.data)
}

export const listStudioProjects = () => api.get<any>('/api/studio/projects').then(r => r.data)
export const getStudioProject = (projectId: string) => api.get<any>(`/api/studio/projects/${projectId}`).then(r => r.data)

export const uploadStudioImages = (projectId: string, files: File[]) => {
  const f = new FormData()
  files.forEach(x => f.append('files', x))
  return api.post<any>(`/api/studio/projects/${projectId}/upload`, f).then(r => r.data)
}

export const analyzeStudioProject = (projectId: string, brief: string = '') => {
  const f = new FormData()
  f.append('brief', brief)
  return api.post<any>(`/api/studio/projects/${projectId}/analyze`, f).then(r => r.data)
}

export const updateStudioSelection = (projectId: string, selectedAssetIds: string[]) =>
  api.post<any>(`/api/studio/projects/${projectId}/select`, { selected_asset_ids: selectedAssetIds }).then(r => r.data)

export const generateStudioPost = (projectId: string, data: any) =>
  api.post<any>(`/api/studio/projects/${projectId}/generate`, data).then(r => r.data)

export const updateStudioContent = (projectId: string, data: any) =>
  api.put<any>(`/api/studio/projects/${projectId}/content`, data).then(r => r.data)

export const saveStudioDraft = (projectId: string, data: any = {}) =>
  api.post<any>(`/api/studio/projects/${projectId}/draft`, data).then(r => r.data)

export const listStudioDrafts = (projectId?: string) => {
  const params = projectId ? { project_id: projectId } : {}
  return api.get<any>('/api/studio/drafts', { params }).then(r => r.data)
}

export const getStudioDraft = (draftId: string) => api.get<any>(`/api/studio/drafts/${draftId}`).then(r => r.data)

export const getPublishingStatus = () => api.get<any>('/api/studio/publishing/status').then(r => r.data)

export const publishToPlatform = (platform: 'linkedin' | 'instagram', projectId: string) =>
  api.post<any>(`/api/studio/publish/${platform}`, { project_id: projectId }).then(r => r.data)


// Brand Profiles
export const createBrandProfile = (data: any) => api.post<any>('/api/studio/brand-profiles', data).then(r => r.data)
export const listBrandProfiles = () => api.get<any>('/api/studio/brand-profiles').then(r => r.data)
export const getBrandProfile = (id: string) => api.get<any>(`/api/studio/brand-profiles/${id}`).then(r => r.data)
export const updateBrandProfile = (id: string, data: any) => api.put<any>(`/api/studio/brand-profiles/${id}`, data).then(r => r.data)
export const deleteBrandProfile = (id: string) => api.delete<any>(`/api/studio/brand-profiles/${id}`).then(r => r.data)
export const duplicateBrandProfile = (id: string, name?: string) => api.post<any>(`/api/studio/brand-profiles/${id}/duplicate`, { name }).then(r => r.data)
export const setProjectBrandProfile = (projectId: string, brandProfileId: string | null) => api.post<any>(`/api/studio/projects/${projectId}/brand-profile`, { brand_profile_id: brandProfileId }).then(r => r.data)
export const previewBrandVoice = (data: any) => api.post<any>('/api/studio/brand-profiles/voice-preview', data, { timeout: 240_000 }).then(r => r.data)
export const uploadBrandAsset = (
  profileId: string,
  file: File,
  assetKind: 'logo' | 'reference',
  category?: string,
  notes?: string,
) => {
  const form = new FormData()
  form.append('file', file)
  form.append('asset_kind', assetKind)
  if (category) form.append('category', category)
  if (notes) form.append('notes', notes)
  return api.post<any>(`/api/studio/brand-profiles/${profileId}/assets`, form).then(r => r.data)
}

// ── Brand Intelligence Studio API ─────────────────────────────────────────────
export interface BrandAssetEntry {
  asset_id: string
  kind: 'logo' | 'reference'
  category: string
  stored_name: string
  original_name: string
  sha256: string
  bytes: number
  width: number | null
  height: number | null
  format: string | null
  uploaded_at: string
  notes: string
}

export interface BrandAssetWarning {
  code: string
  severity: 'error' | 'warning' | 'info'
  message: string
}

export interface ReferenceQualityReport {
  profile_id: string
  brand_name: string
  counts: { logos: number; references: number; total: number }
  categories: Record<string, number>
  diversity: {
    score: number
    pairs: number
    near_duplicate_pairs: string[][]
  } | null
  assets: {
    asset_id: string
    kind: string
    category: string
    width: number | null
    height: number | null
    sharpness: number | null
    near_duplicate_of: string | null
    status: string
  }[]
  warnings: BrandAssetWarning[]
  readiness: number
}

export const listBrandAssets = (profileId: string) =>
  api.get<{ assets: BrandAssetEntry[] }>(`/api/brand-intel/brands/${profileId}/assets`).then(r => r.data)

export const updateBrandAsset = (profileId: string, assetId: string, data: { category?: string; notes?: string }) =>
  api.patch<{ asset: BrandAssetEntry }>(`/api/brand-intel/brands/${profileId}/assets/${assetId}`, data).then(r => r.data)

export const deleteBrandAsset = (profileId: string, assetId: string) =>
  api.delete<{ status: string; asset: BrandAssetEntry; profile: BrandProfile }>(`/api/brand-intel/brands/${profileId}/assets/${assetId}`).then(r => r.data)

export const replaceBrandAsset = (profileId: string, assetId: string, file: File) => {
  const form = new FormData()
  form.append('file', file)
  return api.post<{ asset: BrandAssetEntry; profile: BrandProfile }>(`/api/brand-intel/brands/${profileId}/assets/${assetId}/replace`, form).then(r => r.data)
}

export const getReferenceQuality = (profileId: string) =>
  api.get<ReferenceQualityReport>(`/api/brand-intel/brands/${profileId}/reference-quality`).then(r => r.data)

// ── Crop intelligence API ────────────────────────────────────────────────────
export const cropAnalyze = (file: File) => {
  const f = new FormData(); f.append('file', file)
  return api.post<CropAnalyzeResult>('/api/crop/analyze', f, { timeout: TIMEOUT.ai_op }).then(r => r.data)
}

export const cropCompute = (
  file: File,
  target_w: number,
  target_h: number,
  focal_x?: number | null,
  focal_y?: number | null,
) => {
  const f = new FormData()
  f.append('file', file)
  f.append('target_w', String(target_w))
  f.append('target_h', String(target_h))
  if (focal_x != null) f.append('focal_x', String(focal_x))
  if (focal_y != null) f.append('focal_y', String(focal_y))
  return api.post<CropComputeResult>('/api/crop/compute', f, { timeout: TIMEOUT.ai_op }).then(r => r.data)
}

export const cropInspect = (image_path: string, target_w: number, target_h: number) =>
  api.get<{ crop: CropMeta }>('/api/crop/inspect', {
    params: { image_path, target_w, target_h },
    timeout: TIMEOUT.ai_op,
  }).then(r => r.data)

export const cropComputeFromPath = (
  image_path: string,
  target_w: number,
  target_h: number,
  focal_x?: number | null,
  focal_y?: number | null,
) =>
  api.post<CropComputeResult>('/api/crop/compute-from-path', {
    image_path,
    target_w,
    target_h,
    focal_x,
    focal_y,
  }, { timeout: TIMEOUT.ai_op }).then(r => r.data)

export interface CropOverride {
  focal_point: [number, number]
  crop_box_norm: [number, number, number, number]
}
export const cropSaveOverride = (
  image_path: string,
  format_key: string,
  focal_point: [number, number],
  crop_box_norm?: [number, number, number, number],
) =>
  api.post<{ status: string; image_path: string; format_key: string }>(
    '/api/crop/save-override',
    { image_path, format_key, focal_point, crop_box_norm },
    { timeout: TIMEOUT.ai_op },
  ).then(r => r.data)

export const cropGetOverride = (image_path: string, format_key: string) =>
  api.get<{ override: CropOverride | null }>('/api/crop/override', {
    params: { image_path, format_key },
    timeout: TIMEOUT.ai_op,
  }).then(r => r.data)


// ── Brand Intelligence — Datasets (Phase 2) ──────────────────────────────────

export type DatasetStatus = 'ingesting' | 'ready' | 'running' | 'classified'

export interface DatasetSummary {
  id: string
  name: string
  description: string
  created_at: string
  updated_at: string
  status: DatasetStatus
  source: { kind: string; original_name?: string }
  image_count: number
  duplicate_count: number
  shared_count: number
  rejected_count: number
  rejected_reasons: Record<string, number>
  bytes_total: number
  pending_uploads?: number
  finalized_at?: string
}

export interface UploadResultItem {
  filename: string
  status: 'accepted' | 'duplicate' | 'rejected'
  reason?: string
  detail?: string
  sha256?: string
  shared?: boolean
  stored_path?: string
  width?: number
  height?: number
  format?: string
  bytes?: number
}

export interface IngestOutcome {
  results: UploadResultItem[]
  stats: { accepted: number; duplicate: number; rejected: number; shared: number }
  manifest: DatasetSummary
  skipped?: { name: string; reason: string; detail?: string }[]
  upload_id?: string
  filename?: string
}

export interface UploadSession {
  upload_id: string
  filename: string
  total_bytes: number
  chunk_size: number
  total_chunks: number
  status: 'pending' | 'complete'
  created_at: string
  received_chunks: number[]
  missing_chunks: number[]
}

export interface DatasetImage {
  image_id: string
  stored_path: string
  original_filename: string
  sha256: string
  bytes: number
  width: number
  height: number
  format: string
  uploaded_at: string
  duplicate_of: string | null
}

export const createDataset = (data: { name: string; description?: string }) =>
  api.post<DatasetSummary>('/api/brand-intel/datasets', data).then(r => r.data)

export const listDatasets = () =>
  api.get<{ datasets: DatasetSummary[] }>('/api/brand-intel/datasets').then(r => r.data)

export const getDataset = (id: string) =>
  api.get<DatasetSummary>(`/api/brand-intel/datasets/${id}`).then(r => r.data)

export const deleteDataset = (id: string, confirm: string) =>
  api.delete<{ status: string; note?: string }>(
    `/api/brand-intel/datasets/${id}`, { params: { confirm } },
  ).then(r => r.data)

export const uploadDatasetFiles = (id: string, files: File[]) => {
  const form = new FormData()
  files.forEach(f => form.append('files', f))
  return api.post<IngestOutcome>(
    `/api/brand-intel/datasets/${id}/upload`, form,
  ).then(r => r.data)
}

export const uploadDatasetZip = (id: string, file: File) => {
  const form = new FormData()
  form.append('file', file)
  return api.post<IngestOutcome>(
    `/api/brand-intel/datasets/${id}/upload-zip`, form,
  ).then(r => r.data)
}

export const createUploadSession = (
  id: string,
  body: { filename: string; total_bytes: number; total_chunks: number; upload_id?: string },
) =>
  api.post<UploadSession>(
    `/api/brand-intel/datasets/${id}/uploads`, body,
  ).then(r => r.data)

export const listUploadSessions = (id: string) =>
  api.get<{ uploads: UploadSession[] }>(
    `/api/brand-intel/datasets/${id}/uploads`,
  ).then(r => r.data)

export const sendUploadChunk = (
  id: string, uploadId: string, index: number, chunk: Blob,
) => {
  const form = new FormData()
  form.append('file', chunk, `chunk_${index}`)
  return api.post<{ duplicate: boolean; already_complete?: boolean; session: UploadSession }>(
    `/api/brand-intel/datasets/${id}/uploads/${uploadId}/chunks/${index}`, form,
  ).then(r => r.data)
}

export const completeUpload = (id: string, uploadId: string) =>
  api.post<IngestOutcome>(
    `/api/brand-intel/datasets/${id}/uploads/${uploadId}/complete`,
  ).then(r => r.data)

export const discardUpload = (id: string, uploadId: string) =>
  api.delete<{ status: string }>(
    `/api/brand-intel/datasets/${id}/uploads/${uploadId}`,
  ).then(r => r.data)

export const finalizeDataset = (id: string) =>
  api.post<DatasetSummary>(
    `/api/brand-intel/datasets/${id}/finalize`,
  ).then(r => r.data)

export const listDatasetImages = (id: string, offset = 0, limit = 50, q = '') =>
  api.get<{ total: number; offset: number; limit: number; images: DatasetImage[] }>(
    `/api/brand-intel/datasets/${id}/images`,
    { params: { offset, limit, q } },
  ).then(r => r.data)
