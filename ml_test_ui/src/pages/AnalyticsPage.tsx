import { useState } from 'react'
import { motion } from 'framer-motion'
import { BarChart3, TrendingUp, Calendar, Download, Star, Clock, Folder, Check, Sparkles } from 'lucide-react'
import { Card, Btn } from '../components/ui'
import { useAnalytics } from '../contexts/AnalyticsContext'
import { loadJobs } from '../lib/cache'
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar } from 'recharts'
import { format } from 'date-fns'

function buildChartData(jobs: ReturnType<typeof loadJobs>) {
  const byDay: Record<string, number> = {}
  jobs.forEach(j => {
    const day = format(new Date(j.timestamp), 'MMM d')
    byDay[day] = (byDay[day] ?? 0) + 1
  })
  return Object.entries(byDay).map(([date, count]) => ({ date, count }))
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div style={{ background: 'var(--s3)', border: '1px solid var(--b1)', borderRadius: 10, padding: '10px 14px', fontSize: 12, boxShadow: 'var(--shadow-card)' }}>
        <p style={{ color: 'var(--t3)', marginBottom: 4 }}>{label}</p>
        <p style={{ color: 'var(--accent-light)', fontWeight: 700 }}>{payload[0].value} jobs</p>
      </div>
    )
  }
  return null
}

export default function AnalyticsPage() {
  const { analytics, exportCSV } = useAnalytics()
  const [rating, setRating] = useState(0)
  const [hoverRating, setHoverRating] = useState(0)
  const cachedJobs = loadJobs()
  const chartData = buildChartData(cachedJobs)

  const avgRating = analytics.feedbackScores.length
    ? (analytics.feedbackScores.reduce((a, b) => a + b, 0) / analytics.feedbackScores.length).toFixed(1)
    : '—'

  const stats = [
    { label: 'Total Jobs',   value: analytics.totalJobs || cachedJobs.length, icon: BarChart3, color: 'var(--accent-light)' },
    { label: 'Avg Gen Time', value: analytics.avgTime > 0 ? `${analytics.avgTime.toFixed(0)}s` : '—', icon: Clock, color: 'var(--cyan)' },
    { label: 'Recent Jobs',  value: Math.max(analytics.recentJobs.length, cachedJobs.length), icon: Folder, color: '#60a5fa' },
    { label: 'Avg Rating',   value: avgRating === '—' ? '—' : avgRating, icon: Star, color: 'var(--yellow)' },
  ]

  return (
    <div style={{ maxWidth: 1160, margin: '0 auto', padding: '32px 24px 60px' }}>

      {/* Header */}
      <motion.div initial={{ opacity: 0, y: -12 }} animate={{ opacity: 1, y: 0 }}
        style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 32, flexWrap: 'wrap' }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{ width: 48, height: 48, borderRadius: 14, background: 'linear-gradient(135deg,#7c6aff,#a855f7)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 0 24px rgba(124,106,255,0.35)' }}>
            <BarChart3 size={22} color="#fff" />
          </div>
          <div>
            <h1 style={{ fontSize: 24, fontWeight: 800, letterSpacing: '-0.02em' }}>Usage Analytics</h1>
            <p style={{ fontSize: 13, color: 'var(--t3)', marginTop: 2 }}>Your content generation stats</p>
          </div>
        </div>
        <motion.div style={{ marginLeft: 'auto' }} whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.97 }}>
          <Btn variant="ghost" size="sm" onClick={exportCSV}>
            <Download size={14} /> Export CSV
          </Btn>
        </motion.div>
      </motion.div>

      {/* Stat cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16, marginBottom: 32 }}>
        {stats.map(({ label, value, icon: StatIcon, color }, i) => (
          <motion.div key={label} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.07 }} whileHover={{ y: -4 }}>
            <Card style={{ textAlign: 'center', cursor: 'default', padding: '24px 20px' }}>
              <div style={{ width: 48, height: 48, borderRadius: 14, background: `${color}15`, border: `1px solid ${color}25`, display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 14px' }}>
                <StatIcon size={22} color={color} />
              </div>
              <div style={{ fontSize: 36, fontWeight: 900, color, marginBottom: 6, letterSpacing: '-0.03em' }} className="counter-anim">{value}</div>
              <div style={{ fontSize: 11, color: 'var(--t3)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.07em' }}>{label}</div>
            </Card>
          </motion.div>
        ))}
      </div>

      {/* Charts */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 20, marginBottom: 24 }}>
        <Card>
          <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 20, display: 'flex', alignItems: 'center', gap: 8 }}>
            <TrendingUp size={16} color="var(--accent)" /> Jobs over time
          </h3>
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={chartData}>
                <defs>
                  <linearGradient id="lineGrad" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0%" stopColor="#7c6aff" />
                    <stop offset="100%" stopColor="#a78bfa" />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--b1)" vertical={false} />
                <XAxis dataKey="date" tick={{ fill: 'var(--t3)', fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: 'var(--t3)', fontSize: 11 }} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip content={<CustomTooltip />} />
                <Line type="monotone" dataKey="count" stroke="url(#lineGrad)" strokeWidth={2.5} dot={{ fill: 'var(--accent)', r: 4, strokeWidth: 0 }} activeDot={{ r: 6, fill: 'var(--accent-light)' }} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div style={{ height: 220, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--t3)', gap: 10 }}>
              <TrendingUp size={32} style={{ opacity: 0.3 }} />
              <p style={{ fontSize: 13 }}>No data yet — run your first job to see trends</p>
            </div>
          )}
        </Card>

        <Card>
          <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 20 }}>Platform usage</h3>
          {Object.values(analytics.platformsUsed).some(v => v > 0) ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={Object.entries(analytics.platformsUsed).map(([k, v]) => ({ name: k, count: v }))}>
                <defs>
                  <linearGradient id="barGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#7c6aff" />
                    <stop offset="100%" stopColor="#a855f7" />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--b1)" vertical={false} />
                <XAxis dataKey="name" tick={{ fill: 'var(--t3)', fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: 'var(--t3)', fontSize: 11 }} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="count" fill="url(#barGrad)" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div style={{ height: 220, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--t3)', gap: 10 }}>
              <BarChart3 size={32} style={{ opacity: 0.3 }} />
              <p style={{ fontSize: 13 }}>No platform data yet</p>
            </div>
          )}
        </Card>
      </div>

      {/* Recent jobs */}
      <Card style={{ marginBottom: 24 }}>
        <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
          <Calendar size={16} color="var(--accent)" /> Recent jobs ({cachedJobs.length})
        </h3>
        {cachedJobs.length === 0 ? (
          <div style={{ textAlign: 'center', color: 'var(--t3)', padding: '48px 0' }}>
            <BarChart3 size={40} style={{ opacity: 0.2, marginBottom: 12 }} />
            <p style={{ fontSize: 13 }}>No jobs yet. Create your first content to see history here.</p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 320, overflowY: 'auto' }}>
            {cachedJobs.map((job, i) => (
              <motion.div key={job.id} initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.04 }}
                style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 14px', background: 'var(--s3)', borderRadius: 'var(--rs)', border: '1px solid var(--b1)' }}
              >
                <div style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--green)', flexShrink: 0, boxShadow: '0 0 6px var(--green)' }} />
                <div style={{ flex: 1 }}>
                  <p style={{ fontSize: 13, fontWeight: 600 }}>{job.eventName}</p>
                  <p style={{ fontSize: 11, color: 'var(--t3)' }}>{format(new Date(job.timestamp), 'MMM d, yyyy · h:mm a')} · {job.fileCount} files</p>
                </div>
                <span style={{ fontSize: 10, background: 'rgba(16,185,129,0.12)', color: 'var(--green)', borderRadius: 6, padding: '3px 10px', fontWeight: 700, border: '1px solid rgba(16,185,129,0.2)' }}>
                  Complete
                </span>
              </motion.div>
            ))}
          </div>
        )}
      </Card>

      {/* Feedback */}
      <Card>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <Sparkles size={16} color="var(--accent)" />
          <h3 style={{ fontSize: 15, fontWeight: 700 }}>Rate your last generation</h3>
        </div>
        <p style={{ fontSize: 13, color: 'var(--t3)', marginBottom: 16 }}>How satisfied are you with the generated content?</p>
        <div style={{ display: 'flex', gap: 8, marginBottom: 16, alignItems: 'center' }}>
          {[1, 2, 3, 4, 5].map(n => (
            <motion.button key={n} onMouseEnter={() => setHoverRating(n)} onMouseLeave={() => setHoverRating(0)}
              onClick={() => setRating(n)} aria-label={`Rate ${n} star${n > 1 ? 's' : ''}`}
              whileHover={{ scale: 1.2 }} whileTap={{ scale: 0.9 }}
              style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}
            >
              <Star size={28} fill={(hoverRating || rating) >= n ? 'var(--yellow)' : 'none'} color={(hoverRating || rating) >= n ? 'var(--yellow)' : 'var(--b2)'} style={{ transition: 'all .15s', filter: (hoverRating || rating) >= n ? 'drop-shadow(0 0 6px rgba(245,158,11,0.5))' : 'none' }} />
            </motion.button>
          ))}
          {rating > 0 && <span style={{ fontSize: 13, color: 'var(--t2)', marginLeft: 8, fontWeight: 600 }}>{['', 'Poor', 'Fair', 'Good', 'Great', 'Excellent!'][rating]}</span>}
        </div>
        {rating > 0 && (
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
            <p style={{ fontSize: 13, color: 'var(--green)', display: 'inline-flex', alignItems: 'center', gap: 6 }}><Check size={14} /> Thanks for your feedback.</p>
          </motion.div>
        )}
      </Card>
    </div>
  )
}
