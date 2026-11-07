/**
 * StudioMultiImagePage — Multi-image social post creation flow
 */
import { useState, useCallback, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Camera, CheckCircle, ArrowRight, ArrowLeft, Sparkles, Image as ImageIcon,
  FileText, Share2, Save, AlertTriangle
} from 'lucide-react'
import StudioDropZone from '../components/upload/StudioDropZone'
import FileQueue from '../components/upload/FileQueue'
import { Card, Spinner, AnimatedBtn } from '../components/ui'
import { toast } from '../components/ui/Toast'
import {
  createStudioProject,
  uploadStudioImages,
  analyzeStudioProject,
  updateStudioSelection,
  generateStudioPost,
  saveStudioDraft,
  getPublishingStatus,
  publishToPlatform,
  listBrandProfiles,
  setProjectBrandProfile,
} from '../api'

interface Props {
  onBack?: () => void
}

type Step = 'upload' | 'analyze' | 'select' | 'brief' | 'generate' | 'edit' | 'publish'

export default function StudioMultiImagePage({ onBack }: Props) {
  const [step, setStep] = useState<Step>('upload')
  const [projectId, setProjectId] = useState<string | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [uploadedAssets, setUploadedAssets] = useState<any[]>([])
  const [selectedAssets, setSelectedAssets] = useState<any[]>([])
  const [brief, setBrief] = useState('')
  const [generationError, setGenerationError] = useState<string | null>(null)
  const [eventName, setEventName] = useState('')
  const [platforms, setPlatforms] = useState<string[]>(['linkedin', 'instagram'])
  const [content, setContent] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [pubStatus, setPubStatus] = useState<any>(null)
  const [brandProfiles, setBrandProfiles] = useState<any[]>([])
  const [brandProfileId, setBrandProfileId] = useState('')

  useEffect(() => { listBrandProfiles().then(res => setBrandProfiles(res.profiles || [])).catch(() => setBrandProfiles([])) }, [])
  
  const addFiles = useCallback((newFiles: File[]) => {
    setFiles(prev => [...prev, ...newFiles])
  }, [])
  
  const removeFile = (name: string) => setFiles(p => p.filter(f => f.name !== name))
  
  const createProject = async () => {
    if (!files.length) { toast.error('No files', 'Upload at least one image'); return }
    setLoading(true)
    try {
      const proj = await createStudioProject({ name: eventName || 'Social Post', brief })
      setProjectId(proj.id)
      if (brandProfileId) await setProjectBrandProfile(proj.id, brandProfileId)
      const up = await uploadStudioImages(proj.id, files)
      setUploadedAssets(up.uploaded || [])
      toast.success('Uploaded', `${up.uploaded?.length || files.length} images uploaded`)
      setStep('analyze')
    } catch (e: any) {
      toast.error('Error', e.message)
    } finally {
      setLoading(false)
    }
  }
  
  const runAnalysis = async () => {
    if (!projectId) return
    setLoading(true)
    try {
      const res = await analyzeStudioProject(projectId, brief)
      setSelectedAssets(res.selection?.selected || [])
      toast.success('Analysis complete', `Selected ${res.selection?.selected_count || 0} best images`)
      setStep('select')
    } catch (e: any) {
      toast.error('Error', e.message)
    } finally {
      setLoading(false)
    }
  }
  
  const confirmSelection = async () => {
    if (!projectId) return
    setLoading(true)
    try {
      await updateStudioSelection(projectId, selectedAssets.map((a: any) => a.asset_id))
      setStep('brief')
    } catch (e: any) {
      toast.error('Error', e.message)
    } finally {
      setLoading(false)
    }
  }
  
  const generateContent = async () => {
    if (!projectId) return
    setGenerationError(null)
    setLoading(true)
    try {
      const res = await generateStudioPost(projectId, { event_name: eventName || 'Event', brief, platforms, topic: brief })
      setContent(res.content)
      toast.success('Post generated', 'Review and edit below')
      setStep('edit')
      // Load publishing status
      try {
        const ps = await getPublishingStatus()
        setPubStatus(ps)
      } catch {}
    } catch (e: any) {
      const detail = e?.response?.data?.detail
      const message = typeof detail === 'string'
        ? detail
        : 'Content generation failed. Check that the local Qwen model is available, then try again.'
      setGenerationError(message)
      toast.error('Generation failed', message)
    } finally {
      setLoading(false)
    }
  }
  
  const saveDraft = async () => {
    if (!projectId) return
    setLoading(true)
    try {
      const d = await saveStudioDraft(projectId, { content })
      toast.success('Draft saved', `Draft ID: ${d.draft_id?.slice(0,8)}`)
    } catch (e: any) {
      toast.error('Error', e.message)
    } finally {
      setLoading(false)
    }
  }
  
  const publish = async (platform: 'linkedin' | 'instagram') => {
    if (!projectId) return
    setLoading(true)
    try {
      const res = await publishToPlatform(platform, projectId)
      if (res.success) {
        toast.success('Published', res.url ? `Published: ${res.url}` : 'Published successfully')
      } else {
        toast.warning('Not published', res.error)
      }
    } catch (e: any) {
      toast.error('Error', e.message)
    } finally {
      setLoading(false)
    }
  }
  
  const steps: Step[] = ['upload', 'analyze', 'select', 'brief', 'generate', 'edit', 'publish']
  const stepIndex = steps.indexOf(step)
  
  return (
    <div className="studio-container fade-in" style={{ maxWidth: 1000, margin: '0 auto', padding: '24px' }}>
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 32 }}>
          <div>
            <h1 style={{ fontSize: 28, fontWeight: 800, display: 'flex', alignItems: 'center', gap: 12 }}>
              <Sparkles size={28} color="var(--accent-light)" />
              AI Social Publishing Studio
            </h1>
            <p style={{ color: 'var(--t3)', marginTop: 4 }}>Multi-image → AI story → Platform-specific posts → Publish</p>
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
              <StudioDropZone onFiles={addFiles} files={files} isProcessing={loading} />
              <FileQueue files={files} onRemove={removeFile} />
              <div style={{ marginTop: 16 }}>
                <label style={{ display: 'block', color: 'var(--t3)', fontSize: 12, marginBottom: 6 }}>Brand profile</label>
                <select value={brandProfileId} onChange={e => setBrandProfileId(e.target.value)} style={{ width: '100%', padding: '10px 12px', background: 'var(--b1)', border: '1px solid var(--b2)', borderRadius: 8, color: 'var(--t1)' }}>
                  <option value="">No brand profile</option>
                  {brandProfiles.map(profile => <option key={profile.id} value={profile.id}>{profile.name}</option>)}
                </select>
              </div>
              <div style={{ marginTop: 16 }}>
                <input
                  value={eventName}
                  onChange={e => setEventName(e.target.value)}
                  placeholder="Event/Project name (e.g., College Event 2026)"
                  style={{ width: '100%', padding: '10px 14px', background: 'var(--b1)', border: '1px solid var(--b2)', borderRadius: 10, color: 'var(--t1)', fontSize: 14 }}
                />
              </div>
              <div style={{ marginTop: 16, display: 'flex', justifyContent: 'flex-end' }}>
                <AnimatedBtn onClick={createProject} disabled={loading || files.length === 0} variant="default">
                  {loading ? <><Spinner size={16} /> Uploading...</> : <>Create Project & Upload <ArrowRight size={16} /></>}
                </AnimatedBtn>
              </div>
            </Card>
          </motion.div>
        )}
        
        {step === 'analyze' && (
          <motion.div key="analyze" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -20 }}>
            <Card style={{ padding: 24, textAlign: 'center' }}>
              <Sparkles size={48} color="var(--accent-light)" style={{ margin: '0 auto 16px' }} />
              <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 8 }}>AI Analysis Ready (Qwen2.5-1.5B-Instruct)</h2>
              <p style={{ color: 'var(--t3)', marginBottom: 24 }}>{uploadedAssets.length} images uploaded. Image analysis + selection will pass grounded data to Qwen for post generation.</p>
              <AnimatedBtn onClick={runAnalysis} disabled={loading} variant="default">
                {loading ? <><Spinner size={16} /> Analyzing...</> : <><Sparkles size={16} /> Analyze & Select Best Images</>}
              </AnimatedBtn>
            </Card>
          </motion.div>
        )}
        
        {step === 'select' && (
          <motion.div key="select" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -20 }}>
            <Card style={{ padding: 24 }}>
              <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
                <ImageIcon size={20} /> AI Selected Images ({selectedAssets.length})
              </h2>
              <p style={{ color: 'var(--t3)', marginBottom: 16 }}>Review, remove, or reorder. You can adjust the selection before generating.</p>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12, marginBottom: 24 }}>
                {selectedAssets.map((asset: any, idx: number) => (
                  <div key={asset.asset_id} style={{ position: 'relative', borderRadius: 12, overflow: 'hidden', aspectRatio: '4/3' }}>
                    <img src={asset.url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                    <div style={{ position: 'absolute', top: 8, left: 8, background: 'rgba(0,0,0,0.7)', padding: '2px 8px', borderRadius: 6, fontSize: 11 }}>
                      #{idx + 1}
                    </div>
                    <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, background: 'linear-gradient(transparent, rgba(0,0,0,0.8))', padding: '20px 8px 8px', fontSize: 11 }}>
                      {asset.selection_reason?.slice(0, 60)}...
                    </div>
                  </div>
                ))}
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <AnimatedBtn onClick={() => setStep('analyze')} variant="ghost"><ArrowLeft size={16} /> Back</AnimatedBtn>
                <AnimatedBtn onClick={confirmSelection} disabled={loading} variant="default">Continue to Brief <ArrowRight size={16} /></AnimatedBtn>
              </div>
            </Card>
          </motion.div>
        )}
        
        {step === 'brief' && (
          <motion.div key="brief" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -20 }}>
            <Card style={{ padding: 24 }}>
              <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
                <FileText size={20} /> Add Brief & Choose Platforms
              </h2>
              <textarea
                value={brief}
                onChange={e => { setBrief(e.target.value); setGenerationError(null) }}
                placeholder="Tell the AI about this event - what happened, key moments, audience, call to action..."
                style={{ width: '100%', minHeight: 120, padding: '12px 14px', background: 'var(--b1)', border: '1px solid var(--b2)', borderRadius: 10, color: 'var(--t1)', fontSize: 14, resize: 'vertical' }}
              />
              {generationError && (
                <div role="alert" style={{ marginTop: 12, display: 'flex', gap: 10, alignItems: 'flex-start', padding: 12, border: '1px solid rgba(239,68,68,0.3)', borderRadius: 10, background: 'rgba(239,68,68,0.05)' }}>
                  <AlertTriangle size={16} color="var(--red)" style={{ flexShrink: 0, marginTop: 2 }} />
                  <div>
                    <p style={{ color: 'var(--red)', fontSize: 13, fontWeight: 700, marginBottom: 4 }}>This attempt was rejected; no new caption was saved.</p>
                    <p style={{ color: 'var(--t2)', fontSize: 13 }}>{generationError} Edit the brief and select Generate Post to retry.</p>
                  </div>
                </div>
              )}
              <div style={{ marginTop: 16, display: 'flex', gap: 12 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 16px', background: platforms.includes('linkedin') ? 'rgba(10,102,194,0.15)' : 'var(--b1)', border: `1px solid ${platforms.includes('linkedin') ? '#0a66c2' : 'var(--b2)'}`, borderRadius: 10, cursor: 'pointer' }}>
                  <input type="checkbox" checked={platforms.includes('linkedin')} onChange={() => setPlatforms(p => p.includes('linkedin') ? p.filter(x=>x!=='linkedin') : [...p, 'linkedin'])} style={{ display: 'none' }} />
                  <Share2 size={18} color="#0a66c2" /> LinkedIn
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 16px', background: platforms.includes('instagram') ? 'rgba(225,48,108,0.15)' : 'var(--b1)', border: `1px solid ${platforms.includes('instagram') ? '#e1306c' : 'var(--b2)'}`, borderRadius: 10, cursor: 'pointer' }}>
                  <input type="checkbox" checked={platforms.includes('instagram')} onChange={() => setPlatforms(p => p.includes('instagram') ? p.filter(x=>x!=='instagram') : [...p, 'instagram'])} style={{ display: 'none' }} />
                  <Share2 size={18} color="#e1306c" /> Instagram
                </label>
              </div>
              <div style={{ marginTop: 24, display: 'flex', justifyContent: 'space-between' }}>
                <AnimatedBtn onClick={() => setStep('select')} variant="ghost"><ArrowLeft size={16} /> Back</AnimatedBtn>
                <AnimatedBtn onClick={generateContent} disabled={loading || platforms.length === 0} variant="default">
                  {loading ? <><Spinner size={16} /> Generating...</> : <><Sparkles size={16} /> Generate Post</>}
                </AnimatedBtn>
              </div>
            </Card>
          </motion.div>
        )}
        
        {step === 'edit' && content && (
          <motion.div key="edit" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -20 }}>
            <Card style={{ padding: 24 }}>
              <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 16 }}>Edit Your Post</h2>
              <p style={{ color: 'var(--t3)', marginBottom: 16 }}>{content.narrative}</p>
              {Object.entries(content.platform_variants || {}).map(([platform, variant]: [string, any]) => (
                <div key={platform} style={{ marginBottom: 24, padding: 16, background: 'var(--b1)', borderRadius: 12 }}>
                  <h3 style={{ fontSize: 14, fontWeight: 700, marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8, textTransform: 'capitalize' }}>
                    {platform === 'linkedin' ? <Share2 size={16} color="#0a66c2" /> : <Share2 size={16} color="#e1306c" />}
                    {platform}
                  </h3>
                  <textarea
                    defaultValue={variant.caption || (Array.isArray(variant.captions) ? variant.captions.join('\n') : '')}
                    style={{ width: '100%', minHeight: 150, padding: '12px 14px', background: 'var(--b0)', border: '1px solid var(--b2)', borderRadius: 10, color: 'var(--t1)', fontSize: 13, resize: 'vertical' }}
                  />
                  <p style={{ fontSize: 11, color: 'var(--t4)', marginTop: 8 }}>{variant.format_notes}</p>
                </div>
              ))}
              <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
                <div style={{ display: 'flex', gap: 8 }}>
                  <AnimatedBtn onClick={() => setStep('brief')} variant="ghost"><ArrowLeft size={16} /> Back</AnimatedBtn>
                  <AnimatedBtn onClick={saveDraft} disabled={loading} variant="ghost"><Save size={16} /> Save Draft</AnimatedBtn>
                </div>
                <AnimatedBtn onClick={() => setStep('publish')} variant="default">Preview & Publish <ArrowRight size={16} /></AnimatedBtn>
              </div>
            </Card>
          </motion.div>
        )}
        
        {step === 'publish' && (
          <motion.div key="publish" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -20 }}>
            <Card style={{ padding: 24 }}>
              <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
                <Share2 size={20} /> Publish
              </h2>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: 16, marginBottom: 24 }}>
                <div style={{ padding: 16, background: 'var(--b1)', borderRadius: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                    <Share2 size={20} color="#0a66c2" />
                    <span style={{ fontWeight: 600 }}>LinkedIn</span>
                    {pubStatus?.linkedin?.configured ? <CheckCircle size={14} color="var(--green)" /> : <AlertTriangle size={14} color="var(--orange)" />}
                  </div>
                  <p style={{ fontSize: 12, color: 'var(--t3)', marginBottom: 12 }}>
                    {pubStatus?.linkedin?.configured ? 'Connected' : 'Not configured'}
                  </p>
                  <AnimatedBtn onClick={() => publish('linkedin')} disabled={loading} variant="default" style={{ width: '100%' }}>
                    {pubStatus?.linkedin?.configured ? 'Publish to LinkedIn' : 'Connect & Publish'}
                  </AnimatedBtn>
                </div>
                <div style={{ padding: 16, background: 'var(--b1)', borderRadius: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                    <Share2 size={20} color="#e1306c" />
                    <span style={{ fontWeight: 600 }}>Instagram</span>
                    {pubStatus?.instagram?.configured ? <CheckCircle size={14} color="var(--green)" /> : <AlertTriangle size={14} color="var(--orange)" />}
                  </div>
                  <p style={{ fontSize: 12, color: 'var(--t3)', marginBottom: 12 }}>
                    {pubStatus?.instagram?.configured ? 'Connected' : 'Not configured (Business account required)'}
                  </p>
                  <AnimatedBtn onClick={() => publish('instagram')} disabled={loading} variant="default" style={{ width: '100%' }}>
                    {pubStatus?.instagram?.configured ? 'Publish to Instagram' : 'Connect & Publish'}
                  </AnimatedBtn>
                </div>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <AnimatedBtn onClick={() => setStep('edit')} variant="ghost"><ArrowLeft size={16} /> Back to Edit</AnimatedBtn>
                <AnimatedBtn onClick={saveDraft} disabled={loading} variant="ghost"><Save size={16} /> Save as Draft</AnimatedBtn>
              </div>
            </Card>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
