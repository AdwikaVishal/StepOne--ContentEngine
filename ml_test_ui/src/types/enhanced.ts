// Enhanced types for frontend enhancements
export interface WizardStep {
  id: string
  title: string
  component: React.ComponentType
}

export type Platform = 'linkedin' | 'instagram' | 'stories' | 'reel'

export interface CaptionEdit {
  platform: Platform
  text: string
  charCount: number
  readability: number
  version: number
}

export type AnalyticsEvent = {
  type: 'job_start' | 'job_complete' | 'feedback' | 'export' | 'upload' | 'regen'
  jobId?: string
  duration?: number
  score?: number
  platform?: Platform | string
}

