import { Brain, CheckCircle, FileText, Package, Palette, PenLine, Search, Sparkles } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

/** Single source of truth for all hardcoded values */

export const PLATFORM_LIMITS = {
  linkedin:  { maxImages: 6,  maxChars: 3000, suggestChars: 1500, label: 'LinkedIn' },
  instagram: { maxImages: 10, maxChars: 2200, suggestChars: 500,  label: 'Instagram' },
  story:     { maxImages: 4,  maxChars: 100,  suggestChars: 80,   label: 'Stories' },
  reel:      { maxImages: 1,  maxChars: 2200, suggestChars: 150,  label: 'Reel' },
} as const

export const JOB_STEPS: Record<string, { label: string; icon: LucideIcon; pct: number }> = {
  queued:            { label: 'Queued',                    icon: Package, pct: 2  },
  loading_models:    { label: 'Loading AI models',         icon: Brain, pct: 10 },
  processing_assets: { label: 'Scoring assets',            icon: Search, pct: 30 },
  ml_selection:      { label: 'Selecting best assets',     icon: Sparkles, pct: 50 },
  layout_assembly:   { label: 'Assembling layouts',        icon: Palette, pct: 65 },
  copy_generation:   { label: 'Writing captions',          icon: PenLine, pct: 80 },
  case_study:        { label: 'Generating case study',     icon: FileText, pct: 90 },
  finalising:        { label: 'Finalising outputs',        icon: Package, pct: 95 },
  done:              { label: 'Complete',                  icon: CheckCircle, pct: 100 },
}

export const EVENT_TYPES = [
  { value: 'conference',     label: 'Conference / Summit' },
  { value: 'product_launch', label: 'Product Launch' },
  { value: 'networking',     label: 'Networking Event' },
  { value: 'workshop',       label: 'Workshop / Training' },
  { value: 'party',          label: 'Party / Celebration' },
  { value: 'webinar',        label: 'Webinar / Virtual' },
  { value: 'award',          label: 'Award Ceremony' },
  { value: 'other',          label: 'Other' },
]

export const MAX_FILE_SIZE_MB = 200
export const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
export const LARGE_FILE_WARNING_MB = 50

export const SUPPORTED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp']
export const SUPPORTED_VIDEO_TYPES = ['video/mp4', 'video/quicktime', 'video/x-msvideo']
export const SUPPORTED_TYPES = [...SUPPORTED_IMAGE_TYPES, ...SUPPORTED_VIDEO_TYPES]
