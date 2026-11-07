import { BriefcaseBusiness, Smile } from 'lucide-react'
import { motion } from 'framer-motion'

interface Props { value: number; onChange: (v: number) => void }

export default function BrandVoiceSlider({ value, onChange }: Props) {
  const label =
    value < 25 ? 'Very Professional'
    : value < 50 ? 'Professional'
    : value < 75 ? 'Balanced'
    : value < 90 ? 'Casual'
    : 'Very Casual'

  const color =
    value < 40 ? 'var(--blue)'
    : value < 70 ? 'var(--accent)'
    : 'var(--pink)'

  return (
    <div>
      {/* Header row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <span style={{
          fontSize: 10,
          color: 'var(--t3)',
          textTransform: 'uppercase',
          letterSpacing: '.08em',
          fontWeight: 600,
        }}>
          Brand Voice
        </span>
        <motion.span
          key={label}
          initial={{ opacity: 0, y: -3 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.15 }}
          style={{
            color,
            fontWeight: 600,
            fontSize: 11,
            background: `${color}12`,
            border: `1px solid ${color}25`,
            borderRadius: 20,
            padding: '2px 10px',
            transition: 'color .3s, background .3s, border-color .3s',
          }}
        >
          {label}
        </motion.span>
      </div>

      {/* Slider track */}
      <div style={{ position: 'relative', height: 4, background: 'var(--s4)', borderRadius: 999, marginBottom: 6 }}>
        {/* Fill */}
        <div style={{
          position: 'absolute',
          left: 0,
          top: 0,
          height: '100%',
          width: `${value}%`,
          background: `linear-gradient(90deg, var(--blue), ${color})`,
          borderRadius: 999,
          transition: 'width .12s, background .3s',
        }} />

        {/* Native range (invisible, handles interaction) */}
        <input
          type="range"
          min={0}
          max={100}
          value={value}
          onChange={e => onChange(Number(e.target.value))}
          aria-label="Brand voice"
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            opacity: 0,
            cursor: 'pointer',
            margin: 0,
          }}
        />

        {/* Thumb */}
        <div style={{
          position: 'absolute',
          top: '50%',
          left: `${value}%`,
          transform: 'translate(-50%, -50%)',
          width: 14,
          height: 14,
          borderRadius: '50%',
          background: '#fff',
          boxShadow: `0 0 0 2.5px ${color}, 0 1px 6px rgba(0,0,0,0.3)`,
          transition: 'left .12s, box-shadow .3s',
          pointerEvents: 'none',
        }} />
      </div>

      {/* Endpoints */}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
        <span style={{ fontSize: 10, color: 'var(--blue)', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <BriefcaseBusiness size={10} /> Professional
        </span>
        <span style={{ fontSize: 10, color: 'var(--pink)', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          Casual <Smile size={10} />
        </span>
      </div>

      {/* Hint */}
      <p style={{ fontSize: 11, color: 'var(--t4)', marginTop: 8, textAlign: 'center', lineHeight: 1.5 }}>
        {value < 40
          ? 'Formal language, insight-focused'
          : value < 70
          ? 'Balanced tone, concise and engaging'
          : 'Casual language, behind-the-scenes energy'}
      </p>
    </div>
  )
}
