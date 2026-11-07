import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  BarChart3, BriefcaseBusiness, Camera, ChevronLeft, Download,
  File, FileDown, FileText, Film, Folder, Image, RefreshCw,
  Smartphone, Tag as TagIcon, AlertTriangle, Sparkles
} from 'lucide-react'
import { Card, Btn, Tag } from '../components/ui'
import { LinkedInPreview, InstagramCarousel, InstagramStories, InstagramReel } from '../components/PlatformPreview'
import CaptionEditor from '../components/results/CaptionEditor'
import HashtagGenerator from '../components/results/HashtagGenerator'
import BrandClusterMap from '../components/results/BrandClusterMap'
import BulkDownload from '../components/export/BulkDownload'
import SocialShareButtons from '../components/export/SocialShareButtons'
import { toast } from '../components/ui/Toast'
import { useAnalytics } from '../contexts/AnalyticsContext'
import { useIsMobile } from '../hooks/useMediaQuery'
import { regenerateCaptions } from '../api'
import CaseStudyReport from '../components/CaseStudyReport'

type Tab = 'linkedin' | 'instagram' | 'stories' | 'reel' | 'casestudy' | 'report'
interface Props { result: any; eventName: string; onBack: () => void; jobId?: string | null }

function Thumb({ url }: { url: string }) {
  return <img src={url} alt="" loading="lazy" style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }} />
}

const TABS = [
  { id: 'linkedin'  as const, label: 'LinkedIn',   icon: BriefcaseBusiness, color: '#0a66c2' },
  { id: 'instagram' as const, label: 'Instagram',  icon: Camera,            color: '#e1306c' },
  { id: 'stories'   as const, label: 'Stories',    icon: Smartphone,        color: '#833ab4' },
  { id: 'reel'      as const, label: 'Reel',       icon: Film,              color: '#fd1d1d' },
  { id: 'casestudy' as const, label: 'Case Study', icon: FileText,          color: 'var(--cyan)' },
  { id: 'report'    as const, label: 'AI Report',  icon: BarChart3,         color: 'var(--accent-light)' },
]

export default function ResultsPage({ result, eventName, onBack, jobId }: Props) {
  const { trackEvent } = useAnalytics()
  const isMobile = useIsMobile()
  const [regenLoading, setRegenLoading] = useState(false)
  const [groqBackend, setGroqBackend] = useState<string | null>(null)

  const files: Record<string, string>    = result?.files    ?? {}
  const captions: Record<string, string> = result?.captions ?? {}
  const fileNames = Object.keys(files)
  const isBrandMode = result?.mode === 'gff'
  const brandCounts: Record<string, number> = result?.brand_counts ?? {}
  const brandIds = Object.keys(brandCounts)
  const initialBrandId = result?.selected_brand && brandIds.includes(result.selected_brand)
    ? result.selected_brand : brandIds[0] ?? ''
  const [tab, setTab] = useState<Tab>('linkedin')
  const [activeBrandId, setActiveBrandId] = useState(initialBrandId)
  const activeFileNames = isBrandMode && activeBrandId
    ? fileNames.filter(n => n.startsWith(`${activeBrandId}/`)) : fileNames

  const getUrl  = (pat: RegExp) => { const k = activeFileNames.find(n => pat.test(n)); return k ? files[k] : undefined }
  const getUrls = (pat: RegExp) => activeFileNames.filter(n => pat.test(n)).sort().map(n => files[n])
  const caption = (key: string) => {
    if (isBrandMode && activeBrandId) return captions[`${activeBrandId}__${key}`] || captions[key] || ''
    return captions[key] || ''
  }

  const collageUrl   = getUrl(/linkedin_collage/)
  const carouselUrls = getUrls(/(?:instagram_carousel_\d+|carousel_\d+)/)
  const reelUrl      = getUrl(/(?:instagram_reel|reel)\.mp4$/)
  const storyUrls    = getUrls(/(?:instagram_story_\d+|story_\d+)/)

  const [liCaption,   setLiCaption]   = useState(caption('linkedin_caption') || caption('instagram_caption') || `Just wrapped ${eventName} — here's what stood out.\n\nThe energy in the room was electric.\n\nWhat's your biggest takeaway from recent events?\n\n#${eventName.replace(/\s+/g, '')} #EventInsights`)
  const [igCaption,   setIgCaption]   = useState(caption('instagram_caption') || `POV: You attend ${eventName} and forget to eat.\n\nSwipe for the moments that did not make the recap.\n\n#${eventName.replace(/\s+/g, '')} #EventLife`)
  const [reelCaption, setReelCaption] = useState(caption('instagram_reel_caption') || caption('reel_caption') || `24 hours at ${eventName}.\n\nTag someone who needs to be in the room next year.\n\n#${eventName.replace(/\s+/g, '')}`)
  const [storyCaps, setStoryCaps]     = useState<string[]>(() => {
    const raw = caption('story_captions') || caption('stories__story_captions') || ''
    if (raw) {
      const lines = raw.split('\n').filter(Boolean).map((l: string) => l.replace(/^Story \d+:\s*/i, '').trim()).filter(Boolean)
      if (lines.length) return lines
    }
    return [`We are at ${eventName}`, 'The main stage', 'Best moment of the day', 'See you next year']
  })

  useEffect(() => {
    if (!isBrandMode) return
    setLiCaption(caption('linkedin_caption') || caption('instagram_caption') || '')
    setIgCaption(caption('instagram_caption') || '')
    setReelCaption(caption('instagram_reel_caption') || caption('reel_caption') || '')
    const rawStories = caption('story_captions') || caption('stories__story_captions') || ''
    const nextStories = rawStories.split('\n').filter(Boolean).map((line: string) => line.replace(/^Story \d+:\s*/i, '').trim()).filter(Boolean)
    setStoryCaps(nextStories.length ? nextStories : [`${activeBrandId.replace(/_/g, ' ')} at ${eventName}`])
  }, [activeBrandId])

  const dl = (webUrl: string, filename: string) => {
    const a = document.createElement('a'); a.href = webUrl; a.download = filename
    document.body.appendChild(a); a.click(); document.body.removeChild(a)
    toast.success('Download started', filename); trackEvent({ type: 'export' })
  }

  const handleRegen = async (platform: 'linkedin' | 'instagram' | 'reel' | 'stories') => {
    setRegenLoading(true)
    const loadId = toast.loading('Regenerating with Groq AI…')
    try {
      const r = await regenerateCaptions({ eventName, eventDescription: result?.event_description ?? eventName, platform, sceneConcepts: result?.scene_concepts ?? [], faceCount: result?.face_count ?? 0 })
      setGroqBackend(r.backend)
      if (platform === 'linkedin'  && r.linkedin)  setLiCaption(r.linkedin)
      if (platform === 'instagram' && r.instagram) setIgCaption(r.instagram)
      if (platform === 'reel'      && r.reel)      setReelCaption(r.reel)
      toast.dismiss(loadId)
      toast.success(`Caption regenerated (${r.backend === 'groq' ? 'Groq AI' : 'Template'})`)
      trackEvent({ type: 'regen', platform })
    } catch (e: any) {
      toast.dismiss(loadId); toast.error('Regeneration failed', e?.response?.data?.detail ?? e.message)
    } finally { setRegenLoading(false) }
  }

  const gridCols = isMobile ? '1fr' : '1fr 1fr'

  return (
    <div style={{ maxWidth: 1160, margin: '0 auto', padding: '32px 24px 60px' }}>

      {/* Header */}
      <motion.div initial={{ opacity: 0, y: -12 }} animate={{ opacity: 1, y: 0 }} style={{ marginBottom: 28 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap', marginBottom: 16 }}>
          <motion.button
            onClick={onBack}
            whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}
            style={{ background: 'var(--s3)', border: '1px solid var(--b1)', borderRadius: 'var(--rs)', padding: '8px 14px', color: 'var(--t2)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, fontWeight: 600 }}
          >
            <ChevronLeft size={14} /> New Event
          </motion.button>
          <div style={{ flex: 1 }}>
            <h1 style={{ fontSize: 22, fontWeight: 800, letterSpacing: '-0.02em', color: 'var(--t1)' }}>{eventName}</h1>
            <p style={{ fontSize: 13, color: 'var(--t3)', marginTop: 2 }}>{fileNames.length} files generated</p>
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'rgba(16,185,129,0.1)', border: '1px solid rgba(16,185,129,0.25)', borderRadius: 20, padding: '5px 12px' }}>
              <div style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--green)', boxShadow: '0 0 6px var(--green)' }} />
              <span style={{ fontSize: 12, color: 'var(--green)', fontWeight: 600 }}>Generation complete</span>
            </div>
            <BulkDownload files={files} />
          </div>
        </div>

        {/* Brand switcher */}
        {isBrandMode && brandIds.length > 0 && (
          <Card style={{ padding: 14 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 11, color: 'var(--t3)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.07em' }}>Brand outputs</span>
              {brandIds.map(id => (
                <motion.button key={id} onClick={() => setActiveBrandId(id)} whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}
                  style={{ border: `1px solid ${activeBrandId === id ? 'var(--accent)' : 'var(--b1)'}`, background: activeBrandId === id ? 'rgba(124,106,255,.15)' : 'var(--s3)', color: activeBrandId === id ? 'var(--accent-light)' : 'var(--t2)', borderRadius: 8, padding: '6px 12px', cursor: 'pointer', fontSize: 12, fontWeight: 700, boxShadow: activeBrandId === id ? '0 0 12px rgba(124,106,255,0.2)' : 'none' }}>
                  {id.replace(/_/g, ' ')} · {brandCounts[id]} photos
                </motion.button>
              ))}
              {typeof result?.unmatched_count === 'number' && <Tag label={`${result.unmatched_count} unmatched`} color="var(--yellow)" />}
            </div>
          </Card>
        )}

        {/* Layout tags */}
        {!isBrandMode && (result.linkedin_layout || result.story_layout || result.reel_layout) && (
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginTop: 10 }}>
            <span style={{ fontSize: 11, color: 'var(--t3)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.07em' }}>Layouts:</span>
            {result.linkedin_layout && <Tag label={`LinkedIn: ${result.linkedin_layout}`} color="var(--accent)" />}
            {result.story_layout    && <Tag label={`Stories: ${result.story_layout}`}    color="var(--accent)" />}
            {result.reel_layout     && <Tag label={`Reel: ${result.reel_layout}`}         color="var(--accent)" />}
          </div>
        )}
      </motion.div>

      {/* Tab bar */}
      <div
        role="tablist" aria-label="Content platforms"
        style={{ display: 'flex', gap: 3, marginBottom: 28, background: 'var(--s2)', border: '1px solid var(--b1)', borderRadius: 'var(--r)', padding: 5, overflowX: 'auto' }}
      >
        {TABS.map(t => {
          const TabIcon = t.icon
          const isActive = tab === t.id
          return (
            <motion.button
              key={t.id} role="tab" aria-selected={isActive}
              onClick={() => setTab(t.id)}
              whileHover={isActive ? {} : { scale: 1.02 }}
              whileTap={{ scale: 0.97 }}
              style={{
                flex: 1, minWidth: 80, padding: '9px 10px', borderRadius: 10, border: 'none',
                cursor: 'pointer', fontSize: 12, fontWeight: isActive ? 700 : 500, transition: 'all .2s',
                background: isActive ? `${t.color}18` : 'transparent',
                color: isActive ? t.color : 'var(--t2)',
                boxShadow: isActive ? `0 0 16px ${t.color}25` : 'none',
                borderColor: isActive ? `${t.color}35` : 'transparent',
                borderWidth: 1, borderStyle: 'solid',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
                whiteSpace: 'nowrap',
              }}
            >
              <TabIcon size={14} /> {!isMobile && t.label}
            </motion.button>
          )
        })}
      </div>

      {/* Tab content */}
      <AnimatePresence mode="wait">
        <motion.div key={tab} initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -12 }} transition={{ duration: 0.2 }}>

          {/* LinkedIn */}
          {tab === 'linkedin' && (
            <div style={{ display: 'grid', gridTemplateColumns: gridCols, gap: 24, alignItems: 'start' }}>
              <div>
                <p style={{ fontSize: 11, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '.07em', marginBottom: 12, fontWeight: 700 }}>Live Preview</p>
                <LinkedInPreview images={collageUrl ? [collageUrl] : carouselUrls.slice(0, 6)} caption={liCaption} name={isBrandMode ? activeBrandId.replace(/_/g, ' ') : eventName} />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <Card>
                  <p style={{ fontSize: 11, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '.07em', marginBottom: 12, fontWeight: 700 }}>Caption</p>
                  <CaptionEditor value={liCaption} onChange={setLiCaption} platform="linkedin" />
                  <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    <HashtagGenerator eventName={eventName} onInsert={tags => setLiCaption(v => v + '\n\n' + tags)} />
                    <Btn size="sm" variant="ghost" onClick={() => handleRegen('linkedin')} disabled={regenLoading} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                      {regenLoading ? <RefreshCw size={12} className="spin" /> : <Sparkles size={12} color="var(--accent)" />}
                      Regenerate with AI
                    </Btn>
                  </div>
                  {groqBackend && <p style={{ fontSize: 10, color: 'var(--t3)', marginTop: 6 }}>Last generated by: {groqBackend === 'groq' ? 'Groq (llama-3.3-70b)' : 'Template'}</p>}
                </Card>
                <Card><SocialShareButtons platform="linkedin" caption={liCaption} /></Card>
                {(collageUrl || carouselUrls[0]) && (
                  <Card>
                    <p style={{ fontSize: 11, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '.07em', marginBottom: 12, fontWeight: 700 }}>Download</p>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, background: 'var(--s3)', borderRadius: 'var(--rs)', padding: '12px 14px' }}>
                      <div style={{ width: 52, height: 52, borderRadius: 10, overflow: 'hidden', flexShrink: 0 }}><Thumb url={collageUrl || carouselUrls[0]} /></div>
                      <div style={{ flex: 1 }}>
                        <p style={{ fontSize: 13, fontWeight: 600 }}>{isBrandMode ? 'Brand hero slide' : 'LinkedIn Collage'}</p>
                        <p style={{ fontSize: 11, color: 'var(--t3)' }}>1080×1080 JPEG</p>
                      </div>
                      <Btn size="sm" onClick={() => dl(collageUrl || carouselUrls[0], isBrandMode ? `${activeBrandId}_hero.jpg` : 'linkedin_collage.jpg')}><Download size={13} /> Download</Btn>
                    </div>
                  </Card>
                )}
              </div>
            </div>
          )}

          {/* Instagram */}
          {tab === 'instagram' && (
            <div style={{ display: 'grid', gridTemplateColumns: gridCols, gap: 24, alignItems: 'start' }}>
              <div>
                <p style={{ fontSize: 11, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '.07em', marginBottom: 12, fontWeight: 700 }}>Live Preview</p>
                <InstagramCarousel images={carouselUrls} caption={igCaption} name={eventName} />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <Card>
                  <p style={{ fontSize: 11, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '.07em', marginBottom: 12, fontWeight: 700 }}>Caption</p>
                  <CaptionEditor value={igCaption} onChange={setIgCaption} platform="instagram" />
                  <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    <HashtagGenerator eventName={eventName} onInsert={tags => setIgCaption(v => v + '\n\n' + tags)} />
                    <Btn size="sm" variant="ghost" onClick={() => handleRegen('instagram')} disabled={regenLoading} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                      {regenLoading ? <RefreshCw size={12} className="spin" /> : <Sparkles size={12} color="var(--accent)" />}
                      Regenerate with AI
                    </Btn>
                  </div>
                </Card>
                <Card><SocialShareButtons platform="instagram" caption={igCaption} /></Card>
                {carouselUrls.length > 0 && (
                  <Card>
                    <p style={{ fontSize: 11, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '.07em', marginBottom: 12, fontWeight: 700 }}>Slides ({carouselUrls.length})</p>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(68px,1fr))', gap: 8 }}>
                      {carouselUrls.map((url, i) => (
                        <motion.div key={i} whileHover={{ scale: 1.05, y: -2 }}
                          style={{ aspectRatio: '4/5', borderRadius: 8, overflow: 'hidden', cursor: 'pointer', position: 'relative', border: '1px solid var(--b1)' }}
                          onClick={() => dl(url, `instagram_carousel_${i + 1}.jpg`)} title={`Download slide ${i + 1}`}
                        >
                          <Thumb url={url} />
                          <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0)', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'background .2s' }}
                            onMouseEnter={e => (e.currentTarget.style.background = 'rgba(0,0,0,.5)')}
                            onMouseLeave={e => (e.currentTarget.style.background = 'rgba(0,0,0,0)')}
                          >
                            <Download size={14} color="#fff" style={{ opacity: 0 }} />
                          </div>
                        </motion.div>
                      ))}
                    </div>
                  </Card>
                )}
              </div>
            </div>
          )}

          {/* Stories */}
          {tab === 'stories' && (
            <div style={{ display: 'grid', gridTemplateColumns: gridCols, gap: 24, alignItems: 'start' }}>
              <div>
                <p style={{ fontSize: 11, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '.07em', marginBottom: 12, fontWeight: 700 }}>Preview — tap to advance</p>
                <InstagramStories images={storyUrls} captions={storyCaps} name={eventName} />
              </div>
              <Card>
                <p style={{ fontSize: 11, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '.07em', marginBottom: 16, fontWeight: 700 }}>Story frames ({storyUrls.length})</p>
                {storyUrls.length === 0 && <p style={{ color: 'var(--t3)', fontSize: 13 }}>No story frames generated.</p>}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {storyUrls.map((url, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, background: 'var(--s3)', borderRadius: 'var(--rs)', padding: '10px 14px' }}>
                      <div style={{ width: 36, height: 64, borderRadius: 6, overflow: 'hidden', flexShrink: 0 }}><Thumb url={url} /></div>
                      <div style={{ flex: 1 }}>
                        <p style={{ fontSize: 13, fontWeight: 600 }}>Frame {i + 1}</p>
                        <p style={{ fontSize: 12, color: 'var(--t2)' }}>{storyCaps[i] ?? ''}</p>
                        <p style={{ fontSize: 11, color: 'var(--t3)', marginTop: 2 }}>1080×1920 · 9:16</p>
                      </div>
                      <Btn size="sm" onClick={() => dl(url, `instagram_story_${i + 1}.jpg`)}><Download size={13} /></Btn>
                    </div>
                  ))}
                </div>
              </Card>
            </div>
          )}

          {/* Reel */}
          {tab === 'reel' && (
            <div style={{ display: 'grid', gridTemplateColumns: gridCols, gap: 24, alignItems: 'start' }}>
              <div>
                <p style={{ fontSize: 11, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '.07em', marginBottom: 12, fontWeight: 700 }}>Preview</p>
                <InstagramReel videoUrl={reelUrl} caption={reelCaption} name={eventName} />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                <Card>
                  <p style={{ fontSize: 11, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '.07em', marginBottom: 12, fontWeight: 700 }}>Reel caption</p>
                  <CaptionEditor value={reelCaption} onChange={setReelCaption} platform="reel" />
                  <div style={{ marginTop: 10 }}>
                    <Btn size="sm" variant="ghost" onClick={() => handleRegen('reel')} disabled={regenLoading} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                      {regenLoading ? <RefreshCw size={12} className="spin" /> : <Sparkles size={12} color="var(--accent)" />}
                      Regenerate with AI
                    </Btn>
                  </div>
                </Card>
                <Card><SocialShareButtons platform="reel" caption={reelCaption} /></Card>
                {reelUrl
                  ? <Card>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 12, background: 'var(--s3)', borderRadius: 'var(--rs)', padding: '12px 14px' }}>
                        <div style={{ width: 36, height: 36, borderRadius: 8, background: 'rgba(131,58,180,0.15)', border: '1px solid rgba(131,58,180,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><Film size={16} color="#c084fc" /></div>
                        <div style={{ flex: 1 }}>
                          <p style={{ fontSize: 13, fontWeight: 600 }}>instagram_reel.mp4</p>
                          <p style={{ fontSize: 11, color: 'var(--t3)' }}>1080×1920 · H.264</p>
                        </div>
                        <Btn size="sm" onClick={() => dl(reelUrl, 'instagram_reel.mp4')}><Download size={13} /> Download</Btn>
                      </div>
                    </Card>
                  : <Card style={{ borderColor: 'rgba(245,158,11,0.25)', background: 'rgba(245,158,11,0.04)' }}>
                      <p style={{ fontSize: 13, color: '#fde68a', display: 'flex', alignItems: 'center', gap: 8 }}><AlertTriangle size={14} /> No video assets uploaded. Add MP4/MOV files to generate a Reel.</p>
                    </Card>
                }
              </div>
            </div>
          )}

          {/* Case Study */}
          {tab === 'casestudy' && (
            <div>
              {jobId ? (
                <CaseStudyReport
                  jobId={jobId}
                  eventName={eventName}
                  onDownloadMarkdown={getUrl(/case_study/) ? () => dl(getUrl(/case_study/)!, 'case_study.md') : undefined}
                />
              ) : (
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20, flexWrap: 'wrap', gap: 12 }}>
                    <div>
                      <h2 style={{ fontSize: 18, fontWeight: 800, letterSpacing: '-0.02em' }}>Case Study Draft</h2>
                      <p style={{ fontSize: 13, color: 'var(--t3)', marginTop: 4 }}>Structured, post-ready document</p>
                    </div>
                    {getUrl(/case_study/) && <Btn onClick={() => dl(getUrl(/case_study/)!, 'case_study.md')}><FileDown size={14} /> Download .md</Btn>}
                  </div>
                  <Card>
                    <pre style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace", fontSize: 13, color: 'var(--t2)', lineHeight: 1.8, whiteSpace: 'pre-wrap', maxHeight: 600, overflowY: 'auto' }}>
                      {caption('case_study') || `# Case Study: ${eventName}\n\nGenerated by Content & Design Engine.\nDownload the .md file to view the full document.`}
                    </pre>
                  </Card>
                </div>
              )}
            </div>
          )}

          {/* AI Report */}
          {tab === 'report' && (
            <div>
              <div style={{ marginBottom: 24 }}>
                <h2 style={{ fontSize: 18, fontWeight: 800, letterSpacing: '-0.02em' }}>AI Selection Report</h2>
                <p style={{ fontSize: 13, color: 'var(--t3)', marginTop: 4 }}>Why each asset was selected</p>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(150px,1fr))', gap: 12, marginBottom: 24 }}>
                {[
                  { label: 'Files Generated', value: fileNames.length,    icon: Folder,     color: 'var(--accent-light)' },
                  { label: 'Carousel Slides', value: carouselUrls.length, icon: Image,      color: '#60a5fa' },
                  { label: 'Story Frames',    value: storyUrls.length,    icon: Smartphone, color: '#c084fc' },
                  { label: 'Has Reel',        value: reelUrl ? 'Yes' : 'No', icon: Film,    color: '#f472b6' },
                  ...(isBrandMode ? [{ label: 'Brands Matched', value: brandIds.length, icon: TagIcon, color: 'var(--cyan)' }] : []),
                ].map(({ label, value, icon: StatIcon, color }) => (
                  <motion.div key={label} whileHover={{ y: -3 }}
                    style={{ background: 'var(--glass-card)', backdropFilter: 'blur(16px)', border: '1px solid var(--b1)', borderRadius: 'var(--r)', padding: '18px 16px', textAlign: 'center', cursor: 'default' }}
                  >
                    <div style={{ width: 40, height: 40, borderRadius: 10, background: `${color}15`, border: `1px solid ${color}25`, display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 10px' }}>
                      <StatIcon size={20} color={color} />
                    </div>
                    <div style={{ fontSize: 24, fontWeight: 800, color }} className="counter-anim">{value}</div>
                    <div style={{ fontSize: 11, color: 'var(--t3)', marginTop: 4, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.05em' }}>{label}</div>
                  </motion.div>
                ))}
              </div>
              <Card>
                <p style={{ fontSize: 13, fontWeight: 700, marginBottom: 14 }}>All Generated Files</p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {fileNames.map(name => {
                    const ext = name.split('.').pop()?.toLowerCase() ?? ''
                    const isImg = ['jpg', 'jpeg', 'png'].includes(ext)
                    const isVid = ['mp4', 'mov'].includes(ext)
                    return (
                      <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 10, background: 'var(--s3)', borderRadius: 'var(--rs)', padding: '9px 14px' }}>
                        {isImg
                          ? <div style={{ width: 32, height: 32, borderRadius: 6, overflow: 'hidden', flexShrink: 0 }}><Thumb url={files[name]} /></div>
                          : <span style={{ color: 'var(--t2)' }}>{isVid ? <Film size={16} /> : <File size={16} />}</span>
                        }
                        <span style={{ flex: 1, fontSize: 13, color: 'var(--t2)' }}>{name}</span>
                        <span style={{ fontSize: 10, background: isImg ? 'rgba(59,130,246,0.15)' : isVid ? 'rgba(192,132,252,0.15)' : 'rgba(74,222,128,0.15)', color: isImg ? '#60a5fa' : isVid ? '#c084fc' : '#4ade80', borderRadius: 5, padding: '2px 8px', fontWeight: 700, textTransform: 'uppercase' }}>
                          {ext}
                        </span>
                        <Btn size="sm" variant="ghost" onClick={() => dl(files[name], name)}><Download size={12} /></Btn>
                      </div>
                    )
                  })}
                </div>
              </Card>
              {isBrandMode && (
                <div style={{ marginTop: 16 }}>
                  <BrandClusterMap eventName={eventName} />
                </div>
              )}
            </div>
          )}

        </motion.div>
      </AnimatePresence>
    </div>
  )
}
