import { Skeleton } from '../ui/Skeleton'

export function SkeletonMediaDeck({ count = 12 }: { count?: number }) {
  return (
    <div style={{ marginTop: 18 }}>
      <div style={{ display: 'flex', gap: 10, justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap' }}>
        <p style={{ fontSize: 12, color: 'var(--t3)', textTransform: 'uppercase', letterSpacing: '.08em' }}>Ingesting</p>
        <p style={{ fontSize: 12, color: 'var(--t3)' }}>Preparing previews</p>
      </div>
      <div
        style={{
          marginTop: 12,
          display: 'grid',
          gridTemplateColumns: 'repeat(6, minmax(0, 1fr))',
          gap: 10,
        }}
      >
        {Array.from({ length: count }).map((_, i) => (
          <div key={i} style={{ aspectRatio: '1/1' }}>
            <Skeleton height={90} borderRadius="16px" />
          </div>
        ))}
      </div>
    </div>
  )
}

