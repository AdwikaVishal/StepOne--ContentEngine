/** Skeleton loaders for all async content */
import { type CSSProperties } from 'react'

interface SkeletonProps {
  width?: string | number
  height?: string | number
  borderRadius?: string | number
  style?: CSSProperties
}

export function Skeleton({ width = '100%', height = 16, borderRadius = 'var(--rs)', style }: SkeletonProps) {
  return (
    <div
      className="skeleton"
      style={{ width, height, borderRadius, flexShrink: 0, ...style }}
      aria-hidden="true"
    />
  )
}

export function SkeletonCard() {
  return (
    <div style={{ background: 'var(--s1)', border: '1px solid var(--b1)', borderRadius: 'var(--r)', padding: 20 }}>
      <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
        <Skeleton width={44} height={44} borderRadius="50%" />
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <Skeleton width="60%" height={14} />
          <Skeleton width="40%" height={12} />
        </div>
      </div>
      <Skeleton height={12} style={{ marginBottom: 8 }} />
      <Skeleton height={12} width="85%" style={{ marginBottom: 8 }} />
      <Skeleton height={12} width="70%" />
    </div>
  )
}

export function SkeletonImage({ aspectRatio = '4/5' }: { aspectRatio?: string }) {
  return <div className="skeleton" style={{ width: '100%', aspectRatio, borderRadius: 'var(--rs)' }} aria-hidden="true" />
}

export function SkeletonText({ lines = 3, lastWidth = '70%' }: { lines?: number; lastWidth?: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} height={13} width={i === lines - 1 ? lastWidth : '100%'} />
      ))}
    </div>
  )
}

export function SkeletonResults() {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
      <SkeletonImage aspectRatio="1/1" />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <SkeletonCard />
        <SkeletonCard />
      </div>
    </div>
  )
}
