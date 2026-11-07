import { useEffect, useMemo, useState } from 'react'
import { Loader2, AlertTriangle, Filter } from 'lucide-react'
import { Card, Btn } from '../../components/ui'
import { getBrandClusters, type BrandClustersResponse } from '../../api'

type Props = { eventName: string }

const COLORS = ['#a78bfa', '#60a5fa', '#34d399', '#f472b6', '#f59e0b', '#22d3ee']

export default function BrandClusterMap({ eventName }: Props) {
  const [data, setData] = useState<BrandClustersResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [minConfidence, setMinConfidence] = useState(0)

  const refresh = async () => {
    setLoading(true)
    setError('')
    try {
      const r = await getBrandClusters(eventName, minConfidence)
      setData(r)
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? e?.message ?? 'Failed to load cluster map')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { refresh() }, [eventName, minConfidence])

  const brandColors = useMemo(() => {
    const ids = Array.from(new Set((data?.points ?? []).map(p => p.brand_id)))
    return Object.fromEntries(ids.map((id, i) => [id, COLORS[i % COLORS.length]]))
  }, [data])

  return (
    <Card>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 10, flexWrap: 'wrap' }}>
        <div>
          <p style={{ fontSize: 12, fontWeight: 700, color: 'var(--t1)' }}>Brand Cluster Map</p>
          <p style={{ fontSize: 11, color: 'var(--t3)' }}>Confidence margin vs similarity spread</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Filter size={12} color="var(--t3)" />
          <input type="range" min={0} max={0.95} step={0.05} value={minConfidence}
            onChange={e => setMinConfidence(Number(e.target.value))} />
          <span style={{ fontSize: 11, color: 'var(--t2)', minWidth: 32 }}>{Math.round(minConfidence * 100)}%</span>
          <Btn size="sm" variant="ghost" onClick={refresh} disabled={loading}>Refresh</Btn>
        </div>
      </div>

      {loading && <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--t3)', fontSize: 12 }}><Loader2 size={14} className="spin" /> Loading clusters…</div>}
      {error && <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#fda4af', fontSize: 12 }}><AlertTriangle size={14} /> {error}</div>}

      {data && !loading && !error && (
        <>
          <div style={{ height: 260, borderRadius: 12, border: '1px solid var(--b1)', background: 'rgba(255,255,255,0.02)', position: 'relative', overflow: 'hidden' }}>
            {data.points.map((p, i) => {
              const x = Math.max(2, Math.min(98, p.x * 100))
              const y = Math.max(2, Math.min(98, (1 - p.y) * 100))
              const c = brandColors[p.brand_id] ?? '#a78bfa'
              return (
                <div key={`${p.path}-${i}`} title={`${p.brand_id} | conf ${Math.round(p.confidence * 100)}% | margin ${p.margin_to_second}`}
                  style={{ position: 'absolute', left: `${x}%`, top: `${y}%`, width: 9, height: 9, borderRadius: '50%', background: c, boxShadow: `0 0 10px ${c}90`, transform: 'translate(-50%, -50%)' }} />
              )
            })}
            {Object.entries(data.centroids).map(([bid, c]) => {
              const x = Math.max(2, Math.min(98, c.x * 100))
              const y = Math.max(2, Math.min(98, (1 - c.y) * 100))
              const color = brandColors[bid] ?? '#eab308'
              return <div key={bid} title={`${bid} centroid`} style={{ position: 'absolute', left: `${x}%`, top: `${y}%`, width: 16, height: 16, borderRadius: 4, border: `2px solid ${color}`, transform: 'translate(-50%, -50%) rotate(45deg)' }} />
            })}
          </div>

          <div style={{ marginTop: 10, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {Object.entries(data.centroids).map(([bid, c]) => (
              <div key={bid} style={{ display: 'flex', alignItems: 'center', gap: 6, border: '1px solid var(--b1)', borderRadius: 20, padding: '4px 10px', fontSize: 11, color: 'var(--t2)' }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: brandColors[bid] ?? '#a78bfa' }} />
                <span>{bid.replace(/_/g, ' ')}</span>
                <span style={{ color: 'var(--t3)' }}>{c.count} pts · {Math.round(c.avg_confidence * 100)}%</span>
              </div>
            ))}
          </div>
        </>
      )}
    </Card>
  )
}
