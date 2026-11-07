/**
 * Horizontal score bar with label and numeric value.
 */
interface Props {
  label: string
  value: number   // 0–1
  color?: string
}

export default function ScoreBar({ label, value, color = '#6c63ff' }: Props) {
  const pct = Math.round(value * 100)
  const barColor =
    value >= 0.7 ? '#22c55e' : value >= 0.45 ? '#eab308' : '#ef4444'

  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ color: '#94a3b8', fontSize: 12 }}>{label}</span>
        <span style={{ fontWeight: 600, fontSize: 12 }}>{pct}%</span>
      </div>
      <div
        style={{
          height: 6,
          borderRadius: 3,
          background: '#2e3250',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            height: '100%',
            width: `${pct}%`,
            background: color || barColor,
            borderRadius: 3,
            transition: 'width 0.6s ease',
          }}
        />
      </div>
    </div>
  )
}
