import axios from 'axios'

export const api = axios.create({ baseURL: '', timeout: 300_000 })

export interface QualityScores { quality_score:number; aesthetic_score:number; blur_score:number; brightness_score:number; calibrated?:boolean }
export interface BBox { x1:number; y1:number; x2:number; y2:number }
export interface HighlightClip { start:number; end:number; score:number }

export interface QualityResult   { filename:string; file_url:string; scores:QualityScores }
export interface FaceResult      { filename:string; file_url:string; face_count:number; confidences:number[]; bboxes:BBox[]; image_width:number; image_height:number }
export interface ContentResult   { filename:string; file_url:string; scene_concepts:string[]; relevance_scores:Record<string,number>; concept_match_score:number }
export interface HighlightResult { filename:string; file_url:string; highlights:HighlightClip[]; total_selected_seconds:number }

export interface Selection {
  filename:string; file_url:string
  intended_use:'collage'|'reel'|'story'|'case_study'
  confidence:number; low_confidence:boolean; selection_reason:string
  scores:{ quality:number; aesthetic:number; final:number }
  face_count:number; bboxes:BBox[]; scene_concepts:string[]
  asset_type:'image'|'video'; duration:number; highlight_clips:HighlightClip[]
}
export interface PipelineResult { event:string; total:number; selections:Selection[] }
export interface GenerateResult { event:string; output_dir:string; files:Record<string,string> }
export interface JobStatus      { job_id:string; status:string; progress?:{step?:string;pct?:number}; backend?:string; error?:string|null }

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

export const checkHealth      = ()                                       => api.get<{status:string;version:string}>('/health').then(r=>r.data)
export const getModelStatus   = ()                                       => api.get<Record<string,string>>('/api/model-status').then(r=>r.data)
export const assessQuality    = (file:File)                              => { const f=new FormData(); f.append('file',file); return api.post<QualityResult>('/api/quality',f).then(r=>r.data) }
export const detectFaces      = (file:File)                              => { const f=new FormData(); f.append('file',file); return api.post<FaceResult>('/api/faces',f).then(r=>r.data) }
export const analyseContent   = (file:File)                              => { const f=new FormData(); f.append('file',file); return api.post<ContentResult>('/api/content',f).then(r=>r.data) }
export const extractHighlights= (file:File, dur=45)                     => { const f=new FormData(); f.append('file',file); return api.post<HighlightResult>(`/api/highlights?target_duration=${dur}`,f).then(r=>r.data) }
export const runPipeline      = (files:File[], desc:string)              => api.post<PipelineResult>('/api/pipeline', fd(files,{event_description:desc})).then(r=>r.data)
export const runPipelineAsync = (files:File[], desc:string)              => api.post<{job_id:string;status:string;backend:string}>('/api/pipeline/async', fd(files,{event_description:desc})).then(r=>r.data)
export const generateAsync    = (files:File[], name:string, desc:string) => api.post<{job_id:string;status:string;backend:string}>('/api/generate/async', fd(files,{event_name:name,event_description:desc})).then(r=>r.data)
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
export const getJobStatus     = (id:string)                              => api.get<JobStatus>(`/api/jobs/${id}/status`).then(r=>r.data)
export const getJobResult     = (id:string)                              => api.get<any>(`/api/jobs/${id}/result`).then(r=>r.data)

export interface RegenerateOptions {
  eventName: string
  eventDescription?: string
  platform?: 'linkedin' | 'instagram' | 'reel' | 'stories' | 'all'
  sceneConcepts?: string[]
  faceCount?: number
}
export interface RegenerateResult {
  backend: 'groq' | 'template' | 'local_llm'
  event: string
  linkedin?: string
  instagram?: string
  reel?: string
  stories?: string[]
}

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
export const uploadBrandAsset = (profileId: string, file: File, assetKind: 'logo' | 'reference') => {
  const form = new FormData()
  form.append('file', file)
  form.append('asset_kind', assetKind)
  return api.post<any>(`/api/studio/brand-profiles/${profileId}/assets`, form).then(r => r.data)
}
