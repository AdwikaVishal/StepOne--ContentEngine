import { useEffect, useState, useRef } from 'react'
import { motion } from 'framer-motion'
import { FileDown, Download, Image as ImageIcon, AlertTriangle, TrendingUp, Sparkles } from 'lucide-react'

import { Card, Spinner, Btn } from './ui'
import { toast } from './ui/Toast'
import html2canvas from 'html2canvas'
import { jsPDF } from 'jspdf'

interface Asset {
  id: string
  url: string
  filename: string
  score: number
  quality_score: number
  aesthetic_score: number
  faces: number
  concepts: string[]
  category: string
  low_confidence: boolean
}

interface CaseStudyData {
  job_id: string
  event_name: string
  date: string
  total_assets: number
  selected_assets_count: number
  avg_quality_score: number
  avg_aesthetic_score: number
  avg_face_count: number
  category_distribution: Record<string, number>
  duplicates_removed: number
  low_confidence_count: number
  top_assets: Asset[]
  rejected_assets_sample: Asset[]
  brand_segregation: any
  processing_time_seconds: number
  selection_logic_summary: string
  has_real_scores: boolean
}

interface Props {
  jobId: string
  eventName: string
  onDownloadMarkdown?: () => void
}

export default function CaseStudyReport({ jobId, eventName, onDownloadMarkdown }: Props) {
  const [data, setData] = useState<CaseStudyData | null>(null)
  const [loading, setLoading] = useState(true)
  const reportRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await fetch(`/api/jobs/${jobId}/case-study/enriched`)
        if (!res.ok) throw new Error('Failed to fetch case study data')
        setData(await res.json())
      } catch (e) {
        console.error('Error fetching case study:', e)
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [jobId])

  const handleDownloadPDF = async () => {
    if (!reportRef.current) return
    toast.loading('Generating PDF...')
    try {
      const canvas = await html2canvas(reportRef.current, {
        scale: 2,
        useCORS: true,
        backgroundColor: '#0f0f1a',
      })
      const imgData = canvas.toDataURL('image/jpeg', 0.95)
      const pdf = new jsPDF({
        orientation: 'portrait',
        unit: 'mm',
        format: 'a4',
      })
      const imgWidth = 210
      const pageHeight = 297
      const imgHeight = (canvas.height * imgWidth) / canvas.width
      let heightLeft = imgHeight
      let position = 0

      pdf.addImage(imgData, 'JPEG', 0, position, imgWidth, imgHeight)
      heightLeft -= pageHeight

      while (heightLeft >= 0) {
        position = heightLeft - imgHeight
        pdf.addPage()
        pdf.addImage(imgData, 'JPEG', 0, position, imgWidth, imgHeight)
        heightLeft -= pageHeight
      }

      pdf.save(`${eventName.replace(/\s+/g, '_')}_Case_Study.pdf`)
      toast.dismiss()
      toast.success('PDF downloaded!')
    } catch (e) {
      console.error('PDF generation failed:', e)
      toast.dismiss()
      toast.error('Failed to generate PDF')
    }
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: '60px 0' }}>
        <Spinner size={40} />
      </div>
    )
  }

  if (!data) {
    return (
      <Card>
        <p style={{ color: 'var(--t3)', textAlign: 'center', padding: '40px' }}>
          No case study data available
        </p>
      </Card>
    )
  }

  const stats = [
    { label: 'Total Assets', value: data.total_assets, icon: ImageIcon, color: '#60a5fa' },
    { label: 'Selected', value: data.selected_assets_count, icon: TrendingUp, color: '#10b981' },
    { label: 'Avg Quality', value: `${Math.round(data.avg_quality_score * 100)}%`, icon: Sparkles, color: '#f59e0b' },
    { label: 'Low Confidence', value: data.low_confidence_count, icon: AlertTriangle, color: '#ef4444' },
  ]

  return (
    <div ref={reportRef}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h2 style={{ fontSize: 20, fontWeight: 800, letterSpacing: '-0.02em', color: 'var(--t1)' }}>{data.event_name}</h2>
          <p style={{ fontSize: 13, color: 'var(--t3)', marginTop: 4 }}>Generated {new Date(data.date).toLocaleDateString()}</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {onDownloadMarkdown && (
            <Btn size="sm" variant="ghost" onClick={onDownloadMarkdown}>
              <FileDown size={14} /> Download .md
            </Btn>
          )}
          <Btn size="sm" onClick={handleDownloadPDF}>
            <Download size={14} /> Download PDF
          </Btn>
        </div>
      </div>

      {/* Summary Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(150px,1fr))', gap: 12, marginBottom: 24 }}>
        {stats.map((stat, i) => {
          const StatIcon = stat.icon
          return (
            <motion.div key={i} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.1 }}>
              <Card style={{ padding: 16, textAlign: 'center' }}>
                <div style={{ width: 40, height: 40, borderRadius: 10, background: `${stat.color}15`, border: `1px solid ${stat.color}25`, display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 10px' }}>
                  <StatIcon size={20} color={stat.color} />
                </div>
                <div style={{ fontSize: 24, fontWeight: 800, color: stat.color }}>{stat.value}</div>
                <div style={{ fontSize: 11, color: 'var(--t3)', marginTop: 4, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.05em' }}>{stat.label}</div>
              </Card>
            </motion.div>
          )
        })}
      </div>

      {/* Selection Logic */}
      <Card style={{ marginBottom: 24 }}>
        <p style={{ fontSize: 11, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '.07em', marginBottom: 10, fontWeight: 700 }}>Selection Logic</p>
        <p style={{ fontSize: 13, color: 'var(--t2)', lineHeight: 1.7 }}>
          {data.selection_logic_summary}
        </p>
        <div style={{ marginTop: 16, display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(140px,1fr))', gap: 10 }}>
          {[
            { label: 'Technical Quality', pct: 30 },
            { label: 'Aesthetic Quality', pct: 20 },
            { label: 'Face Presence', pct: 30 },
            { label: 'Concept Relevance', pct: 20 },
          ].map((item, i) => (
            <div key={i} style={{ background: 'var(--s3)', padding: 12, borderRadius: 'var(--rs)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                <span style={{ fontSize: 12, color: 'var(--t2)', fontWeight: 600 }}>{item.label}</span>
                <span style={{ fontSize: 12, color: 'var(--accent)', fontWeight: 700 }}>{item.pct}%</span>
              </div>
              <div style={{ height: 4, background: 'var(--s4)', borderRadius: 4, overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${item.pct}%`, background: 'var(--accent)', borderRadius: 4 }} />
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Top Assets Gallery */}
      {data.top_assets.length > 0 && (
        <Card style={{ marginBottom: 24 }}>
          <p style={{ fontSize: 11, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '.07em', marginBottom: 14, fontWeight: 700 }}>Top Assets</p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(120px,1fr))', gap: 12 }}>
            {data.top_assets.map((asset, i) => (
              <motion.div key={asset.id} whileHover={{ y: -3 }}>
                <div style={{ position: 'relative', borderRadius: 10, overflow: 'hidden', aspectRatio: '4/5', border: '1px solid var(--b1)' }}>
                  <img src={asset.url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  <div style={{ position: 'absolute', top: 8, right: 8, background: 'rgba(16,185,129,0.9)', color: '#fff', fontSize: 11, fontWeight: 700, padding: '3px 8px', borderRadius: 6 }}>
                    {Math.round(asset.score * 100)}%
                  </div>
                </div>
                <div style={{ marginTop: 6, fontSize: 11, color: 'var(--t3)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
                    <span style={{ fontWeight: 600, color: 'var(--t2)' }}>#{i + 1}</span>
                    <span>{asset.faces} face{asset.faces !== 1 ? 's' : ''}</span>
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        </Card>
      )}

      {/* Category Distribution */}
      {Object.keys(data.category_distribution).length > 0 && (
        <Card style={{ marginBottom: 24 }}>
          <p style={{ fontSize: 11, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '.07em', marginBottom: 14, fontWeight: 700 }}>Category Distribution</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {Object.entries(data.category_distribution).sort((a, b) => b[1] - a[1]).map(([cat, count]) => {
              const total = Object.values(data.category_distribution).reduce((a, b) => a + b, 0)
              const pct = total > 0 ? Math.round((count / total) * 100) : 0
              return (
                <div key={cat}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <span style={{ fontSize: 12, color: 'var(--t2)', fontWeight: 600, textTransform: 'capitalize' }}>{cat}</span>
                    <span style={{ fontSize: 12, color: 'var(--t3)', fontWeight: 700 }}>{count} ({pct}%)</span>
                  </div>
                  <div style={{ height: 8, background: 'var(--s4)', borderRadius: 4, overflow: 'hidden' }}>
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${pct}%` }}
                      transition={{ duration: 0.8, ease: 'easeOut' }}
                      style={{ height: '100%', background: 'linear-gradient(90deg, var(--accent), var(--accent-light))', borderRadius: 4 }}
                    />
                  </div>
                </div>
              )
            })}
          </div>
        </Card>
      )}

      {/* Rejected Assets */}
      {data.rejected_assets_sample.length > 0 && (
        <Card>
          <p style={{ fontSize: 11, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '.07em', marginBottom: 14, fontWeight: 700 }}>Low Confidence Assets</p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(100px,1fr))', gap: 10 }}>
            {data.rejected_assets_sample.map((asset) => (
              <div key={asset.id} style={{ opacity: 0.7 }}>
                <div style={{ borderRadius: 8, overflow: 'hidden', aspectRatio: '4/5', border: '1px solid rgba(239,68,68,0.3)', filter: 'grayscale(50%)' }}>
                  <img src={asset.url} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                </div>
                <div style={{ marginTop: 4, fontSize: 11, color: '#fca5a5', textAlign: 'center', fontWeight: 600 }}>
                  {Math.round(asset.score * 100)}%
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}
