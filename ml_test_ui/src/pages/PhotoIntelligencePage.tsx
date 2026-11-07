import { useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { 
  Camera, Sparkles, Image as ImageIcon, CheckCircle, XCircle, 
  ArrowRight, ArrowLeft, Grid, List, AlertTriangle 
} from 'lucide-react'
import { Card } from '../components/ui'
import { AnimatedBtn } from '../components/ui/AnimatedBtn'
import { Spinner } from '../components/ui'
import { toast } from '../components/ui/Toast'
import { useDropzone } from 'react-dropzone'
import { api } from '../api'

interface AssetAnalysis {
  asset_id: string
  original_filename: string
  url?: string
  path: string
  sharpness: number
  exposure: number
  resolution_score: number
  width: number
  height: number
  phash: string | null
  similarity_group_id: string | null
  description: string
  scene_concepts: string[]
  embeddings_available: boolean
  component_scores: Record<string, number>
  overall_score: number
  confidence: number
  reasons: string[]
  is_recommended: boolean
  user_accepted: boolean | null
  user_rejected: boolean | null
}

interface RankedGroup {
  group_id: string
  assets: AssetAnalysis[]
  recommended_asset_id: string
  group_reason: string
  similarity_threshold: number
}

interface CarouselRecommendation {
  sequence: string[]
  rationale: string
  diversity_score: number
  coverage_score: number
}

interface PhotoIntelligenceResult {
  assets: AssetAnalysis[]
  groups: RankedGroup[]
  carousel_recommendation: CarouselRecommendation
  warnings: string[]
  metadata: Record<string, any>
}

type Step = 'upload' | 'analyze' | 'review' | 'sequence'

export function PhotoIntelligencePage({ onBack }: { onBack?: () => void }) {
  const [step, setStep] = useState<Step>('upload')
  const [files, setFiles] = useState<File[]>([])
  const [previews, setPreviews] = useState<string[]>([])
  const [brief, setBrief] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<PhotoIntelligenceResult | null>(null)
  const [viewMode, setViewMode] = useState<'grid' | 'groups'>('grid')
  
  const onDrop = useCallback((acceptedFiles: File[]) => {
    setFiles(prev => [...prev, ...acceptedFiles])
    acceptedFiles.forEach(file => {
      const reader = new FileReader()
      reader.onload = () => {
        setPreviews(prev => [...prev, reader.result as string])
      }
      reader.readAsDataURL(file)
    })
  }, [])
  
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      'image/*': ['.jpeg', '.jpg', '.png', '.webp', '.bmp', '.tiff']
    },
    multiple: true
  })
  
  const removeFile = (index: number) => {
    setFiles(prev => prev.filter((_, i) => i !== index))
    setPreviews(prev => prev.filter((_, i) => i !== index))
  }
  
  const analyzePhotos = async () => {
    if (files.length === 0) return
    setLoading(true)
    try {
      const formData = new FormData()
      files.forEach(f => formData.append('files', f))
      formData.append('brief', brief)
      
      const res = await api.post('/api/photo-intelligence/analyze', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      setResult(res.data)
      setStep('review')
      toast.success('Analysis complete', `${res.data.assets.length} images analyzed`)
    } catch (e: any) {
      toast.error('Analysis failed', e.response?.data?.detail || e.message)
    } finally {
      setLoading(false)
    }
  }
  
  const toggleAccept = (assetId: string) => {
    if (!result) return
    setResult({
      ...result,
      assets: result.assets.map(a => 
        a.asset_id === assetId 
          ? { ...a, user_accepted: !a.user_accepted, user_rejected: a.user_accepted ? a.user_rejected : false }
          : a
      )
    })
  }
  
  const toggleReject = (assetId: string) => {
    if (!result) return
    setResult({
      ...result,
      assets: result.assets.map(a => 
        a.asset_id === assetId 
          ? { ...a, user_rejected: !a.user_rejected, user_accepted: a.user_rejected ? a.user_accepted : false }
          : a
      )
    })
  }
  
  const getAssetById = (assetId: string) => result?.assets.find(a => a.asset_id === assetId)
  
  const steps: Step[] = ['upload', 'analyze', 'review', 'sequence']
  const stepIndex = steps.indexOf(step)
  
  return (
    <div className="studio-container fade-in" style={{ maxWidth: 1100, margin: '0 auto', padding: '24px' }}>
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 32 }}>
          <div>
            <h1 style={{ fontSize: 28, fontWeight: 800, display: 'flex', alignItems: 'center', gap: 12 }}>
              <Sparkles size={28} color="var(--accent-light)" />
              AI Photo Intelligence
            </h1>
            <p style={{ color: 'var(--t3)', marginTop: 4 }}>Smart curation • Duplicate detection • Carousel sequencing</p>
          </div>
          {onBack && <AnimatedBtn onClick={onBack} variant="ghost"><ArrowLeft size={16} /> Back</AnimatedBtn>}
        </div>
        
        <div style={{ display: 'flex', gap: 8, marginBottom: 32, overflowX: 'auto' }}>
          {steps.map((s, i) => (
            <div key={s} style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 100 }}>
              <div style={{
                width: 32, height: 32, borderRadius: '50%',
                background: i <= stepIndex ? 'var(--accent)' : 'var(--b2)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                color: '#fff', fontWeight: 700, flexShrink: 0
              }}>
                {i < stepIndex ? <CheckCircle size={18} /> : i + 1}
              </div>
              <span style={{ fontSize: 12, color: i <= stepIndex ? 'var(--t1)' : 'var(--t4)', fontWeight: i === stepIndex ? 600 : 400, textTransform: 'capitalize' }}>{s}</span>
              {i < steps.length - 1 && <div style={{ flex: 1, height: 1, background: i < stepIndex ? 'var(--accent)' : 'var(--b2)' }} />}
            </div>
          ))}
        </div>
      </motion.div>
      
      <AnimatePresence mode="wait">
        {step === 'upload' && (
          <motion.div key="upload" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -20 }}>
            <Card style={{ padding: 24 }}>
              <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
                <Camera size={20} /> Upload Photos
              </h2>
              <div {...getRootProps()} style={{
                border: `2px dashed ${isDragActive ? 'var(--accent)' : 'var(--b3)'}`,
                borderRadius: 12,
                padding: 48,
                textAlign: 'center',
                cursor: 'pointer',
                background: isDragActive ? 'rgba(99,102,241,0.05)' : 'var(--b1)',
                transition: 'all 0.2s'
              }}>
                <input {...getInputProps()} />
                <ImageIcon size={48} style={{ margin: '0 auto 16px', color: 'var(--t3)' }} />
                <p style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>
                  {isDragActive ? 'Drop photos here' : 'Drag & drop photos here'}
                </p>
                <p style={{ color: 'var(--t3)', fontSize: 14 }}>or click to select files</p>
              </div>
              
              {files.length > 0 && (
                <div style={{ marginTop: 20 }}>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 12 }}>
                    {previews.map((prev, idx) => (
                      <div key={idx} style={{ position: 'relative', aspectRatio: '1', borderRadius: 8, overflow: 'hidden' }}>
                        <img src={prev} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                        <button
                          onClick={() => removeFile(idx)}
                          style={{ position: 'absolute', top: 4, right: 4, background: 'rgba(0,0,0,0.7)', border: 'none', borderRadius: '50%', width: 24, height: 24, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                        >
                          <XCircle size={16} color="#fff" />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              
              <div style={{ marginTop: 16 }}>
                <input
                  value={brief}
                  onChange={e => setBrief(e.target.value)}
                  placeholder="Campaign brief (optional) - helps with sequencing"
                  style={{ width: '100%', padding: '10px 14px', background: 'var(--b1)', border: '1px solid var(--b2)', borderRadius: 10, color: 'var(--t1)', fontSize: 14 }}
                />
              </div>
              
              <div style={{ marginTop: 16, display: 'flex', justifyContent: 'flex-end' }}>
                <AnimatedBtn onClick={analyzePhotos} disabled={loading || files.length === 0} variant="default">
                  {loading ? <><Spinner size={16} /> Analyzing...</> : <>Analyze Photos <ArrowRight size={16} /></>}
                </AnimatedBtn>
              </div>
            </Card>
          </motion.div>
        )}
        
        {step === 'review' && result && (
          <motion.div key="review" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -20 }}>
            <Card style={{ padding: 24, marginBottom: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
                <h2 style={{ fontSize: 18, fontWeight: 700 }}>Analysis Results</h2>
                <div style={{ display: 'flex', gap: 8 }}>
                  <AnimatedBtn onClick={() => setViewMode('grid')} variant={viewMode === 'grid' ? 'default' : 'ghost'} size="sm">
                    <Grid size={16} />
                  </AnimatedBtn>
                  <AnimatedBtn onClick={() => setViewMode('groups')} variant={viewMode === 'groups' ? 'default' : 'ghost'} size="sm">
                    <List size={16} />
                  </AnimatedBtn>
                </div>
              </div>
              
              <div style={{ padding: 12, background: 'rgba(251,191,36,0.1)', border: '1px solid rgba(251,191,36,0.3)', borderRadius: 8, marginBottom: 16, display: 'flex', gap: 8 }}>
                <AlertTriangle size={16} color="var(--orange)" style={{ flexShrink: 0, marginTop: 2 }} />
                <p style={{ fontSize: 12, color: 'var(--t2)' }}>{result.metadata.note}</p>
              </div>
              
              {result.warnings.length > 0 && (
                <div style={{ padding: 12, background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', borderRadius: 8, marginBottom: 16 }}>
                  {result.warnings.map((w, i) => (
                    <p key={i} style={{ fontSize: 12, color: 'var(--t2)' }}>• {w}</p>
                  ))}
                </div>
              )}
            </Card>
            
            {viewMode === 'groups' && result.groups.length > 0 && (
              <Card style={{ padding: 24, marginBottom: 16 }}>
                <h3 style={{ fontSize: 16, fontWeight: 700, marginBottom: 12 }}>Similar Groups</h3>
                {result.groups.map(group => (
                  <div key={group.group_id} style={{ marginBottom: 16, padding: 12, background: 'var(--b1)', borderRadius: 10 }}>
                    <p style={{ fontSize: 13, color: 'var(--t2)', marginBottom: 10 }}>{group.group_reason}</p>
                    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                      {group.assets.map(asset => (
                        <div key={asset.asset_id} style={{ 
                          width: 100, position: 'relative', borderRadius: 8, overflow: 'hidden',
                          border: asset.asset_id === group.recommended_asset_id ? '2px solid var(--accent)' : '1px solid var(--b2)'
                        }}>
                          <div style={{ aspectRatio: '1', background: 'var(--b2)' }} />
                          {asset.asset_id === group.recommended_asset_id && (
                            <div style={{ position: 'absolute', top: 4, left: 4, background: 'var(--accent)', padding: '2px 6px', borderRadius: 4, fontSize: 10 }}>Best</div>
                          )}
                          <div style={{ padding: 4, fontSize: 10, textAlign: 'center', color: 'var(--t3)' }}>{asset.overall_score.toFixed(2)}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </Card>
            )}
            
            <Card style={{ padding: 24 }}>
              <h3 style={{ fontSize: 16, fontWeight: 700, marginBottom: 16 }}>All Images ({result.assets.length})</h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 16 }}>
                {result.assets.map(asset => (
                  <div key={asset.asset_id} style={{ 
                    border: asset.user_rejected ? '2px solid var(--red)' : asset.user_accepted ? '2px solid var(--green)' : '1px solid var(--b2)',
                    borderRadius: 12, overflow: 'hidden', background: 'var(--b1)'
                  }}>
                    <div style={{ aspectRatio: '4/3', background: 'var(--b2)', position: 'relative' }}>
                      {asset.is_recommended && (
                        <div style={{ position: 'absolute', top: 8, left: 8, background: 'var(--accent)', padding: '4px 8px', borderRadius: 6, fontSize: 11, fontWeight: 600 }}>
                          <Sparkles size={12} style={{ display: 'inline', marginRight: 4 }} /> Recommended
                        </div>
                      )}
                    </div>
                    <div style={{ padding: 12 }}>
                      <p style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {asset.original_filename}
                      </p>
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
                        <span style={{ fontSize: 10, padding: '2px 6px', background: 'var(--b2)', borderRadius: 4 }}>Score: {asset.overall_score.toFixed(2)}</span>
                        <span style={{ fontSize: 10, padding: '2px 6px', background: 'var(--b2)', borderRadius: 4 }}>Conf: {(asset.confidence * 100).toFixed(0)}%</span>
                        {asset.scene_concepts.slice(0, 2).map(c => (
                          <span key={c} style={{ fontSize: 10, padding: '2px 6px', background: 'var(--b2)', borderRadius: 4 }}>{c}</span>
                        ))}
                      </div>
                      <p style={{ fontSize: 11, color: 'var(--t3)', marginBottom: 10, minHeight: 32 }}>
                        {asset.reasons.slice(0, 2).join(' • ')}
                      </p>
                      <div style={{ display: 'flex', gap: 6 }}>
                        <button
                          onClick={() => toggleAccept(asset.asset_id)}
                          style={{ flex: 1, padding: '6px', background: asset.user_accepted ? 'var(--green)' : 'var(--b2)', border: 'none', borderRadius: 6, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4, color: asset.user_accepted ? '#fff' : 'var(--t1)', fontSize: 11 }}
                        >
                          <CheckCircle size={14} /> Accept
                        </button>
                        <button
                          onClick={() => toggleReject(asset.asset_id)}
                          style={{ flex: 1, padding: '6px', background: asset.user_rejected ? 'var(--red)' : 'var(--b2)', border: 'none', borderRadius: 6, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4, color: asset.user_rejected ? '#fff' : 'var(--t1)', fontSize: 11 }}
                        >
                          <XCircle size={14} /> Reject
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              
              <div style={{ marginTop: 24, display: 'flex', justifyContent: 'space-between' }}>
                <AnimatedBtn onClick={() => setStep('upload')} variant="ghost"><ArrowLeft size={16} /> Back</AnimatedBtn>
                <AnimatedBtn onClick={() => setStep('sequence')} variant="default">View Carousel Recommendation <ArrowRight size={16} /></AnimatedBtn>
              </div>
            </Card>
          </motion.div>
        )}
        
        {step === 'sequence' && result && (
          <motion.div key="sequence" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -20 }}>
            <Card style={{ padding: 24 }}>
              <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
                <Sparkles size={20} /> Recommended Carousel Sequence
              </h2>
              <p style={{ color: 'var(--t3)', marginBottom: 16 }}>{result.carousel_recommendation.rationale}</p>
              
              <div style={{ display: 'flex', gap: 8, marginBottom: 20, flexWrap: 'wrap' }}>
                <span style={{ padding: '6px 12px', background: 'var(--b2)', borderRadius: 8, fontSize: 12 }}>Diversity: {(result.carousel_recommendation.diversity_score * 100).toFixed(0)}%</span>
                <span style={{ padding: '6px 12px', background: 'var(--b2)', borderRadius: 8, fontSize: 12 }}>Coverage: {(result.carousel_recommendation.coverage_score * 100).toFixed(0)}%</span>
                <span style={{ padding: '6px 12px', background: 'var(--b2)', borderRadius: 8, fontSize: 12 }}>Images: {result.carousel_recommendation.sequence.length}</span>
              </div>
              
              <div style={{ display: 'flex', gap: 12, overflowX: 'auto', paddingBottom: 12 }}>
                {result.carousel_recommendation.sequence.map((assetId, idx) => {
                  const asset = getAssetById(assetId)
                  if (!asset) return null
                  return (
                    <div key={assetId} style={{ flexShrink: 0, width: 200 }}>
                      <div style={{ position: 'relative', aspectRatio: '4/3', background: 'var(--b2)', borderRadius: 10, overflow: 'hidden', marginBottom: 8 }}>
                        <div style={{ position: 'absolute', top: 8, left: 8, background: 'rgba(0,0,0,0.7)', padding: '4px 8px', borderRadius: 6, fontSize: 12, fontWeight: 700 }}>
                          #{idx + 1}
                        </div>
                      </div>
                      <p style={{ fontSize: 11, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{asset.original_filename}</p>
                      <p style={{ fontSize: 10, color: 'var(--t3)' }}>{asset.reasons[0]}</p>
                    </div>
                  )
                })}
              </div>
              
              <div style={{ marginTop: 24, display: 'flex', justifyContent: 'space-between' }}>
                <AnimatedBtn onClick={() => setStep('review')} variant="ghost"><ArrowLeft size={16} /> Back to Review</AnimatedBtn>
                <AnimatedBtn onClick={() => toast.success('Sequence ready', 'Use this order in your carousel')} variant="default">Apply to Carousel <ArrowRight size={16} /></AnimatedBtn>
              </div>
            </Card>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
