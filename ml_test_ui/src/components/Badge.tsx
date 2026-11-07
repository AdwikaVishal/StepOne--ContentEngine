const COLORS: Record<string, { bg: string; text: string }> = {
  collage:    { bg: '#1e3a5f', text: '#60a5fa' },
  reel:       { bg: '#3b1f5e', text: '#c084fc' },
  story:      { bg: '#1a3a2a', text: '#4ade80' },
  case_study: { bg: '#3a2a10', text: '#fbbf24' },
  default:    { bg: '#1e293b', text: '#94a3b8' },
}

interface Props {
  label: string
  type?: string
}

export default function Badge({ label, type = 'default' }: Props) {
  const c = COLORS[type] ?? COLORS.default
  return (
    <span
      style={{
        background: c.bg,
        color: c.text,
        borderRadius: 6,
        padding: '2px 8px',
        fontSize: 11,
        fontWeight: 600,
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
      }}
    >
      {label}
    </span>
  )
}
