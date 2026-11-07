import { type ReactNode } from 'react'

interface Props {
  children: ReactNode
  style?: React.CSSProperties
}

export default function Card({ children, style }: Props) {
  return (
    <div
      style={{
        background: '#1a1d27',
        border: '1px solid #2e3250',
        borderRadius: 12,
        padding: 20,
        ...style,
      }}
    >
      {children}
    </div>
  )
}
