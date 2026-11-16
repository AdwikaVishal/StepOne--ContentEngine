/**
 * Brand profile form definitions and helpers.
 *
 * Central source of truth for the six-section form layout, field controls,
 * backend character limits and profile completeness scoring. Field names and
 * data types match the backend flat schema exactly
 * (content_engine/studio/storage.py — BRAND_PROFILE_DEFAULTS, 48 fields:
 * 13 v1 + 32 v2 + 3 Brand Intelligence v3).
 */

export interface BrandFieldDef {
  name: string
  label: string
  kind: 'text' | 'textarea' | 'select' | 'chips' | 'color' | 'logo' | 'refs'
  placeholder?: string
  hint?: string
  /** Backend character limit (BRAND_PROFILE_TEXT_LIMITS). */
  max?: number
  options?: string[]
  required?: boolean
  /** Visual width in the section grid (default: half). */
  full?: boolean
}

export interface BrandSectionDef {
  id: string
  title: string
  description: string
  fields: BrandFieldDef[]
}

export interface BrandProfile {
  id?: string
  name: string
  description?: string
  target_audience?: string
  campaign_objectives?: string
  tone_of_voice?: string
  preferred_vocabulary?: string[]
  avoid_words_claims?: string[]
  preferred_cta?: string
  hashtag_guidance?: string
  brand_colors?: string[]
  fonts?: string[]
  logo_path?: string | null
  visual_references?: string[]
  // Brand Intelligence (additive v3)
  brand_category?: string
  known_text_aliases?: string[]
  reference_notes?: string
  created_at?: string
  updated_at?: string
  [key: string]: any
}

export const TONE_OPTIONS = ['professional', 'casual', 'friendly', 'bold', 'authentic']

export const FORMALITY_OPTIONS = ['', 'formal', 'semi-formal', 'casual']
export const SENTENCE_OPTIONS = ['', 'short', 'medium', 'long', 'mixed']
export const PERSON_OPTIONS = ['', 'first-person', 'third-person', 'neutral']
export const EMOJI_OPTIONS = ['', 'none', 'minimal', 'moderate', 'frequent']
export const TECHNICAL_OPTIONS = ['', 'general', 'familiar', 'technical', 'expert']

/** Six logical sections covering all 48 schema fields. */
export const BRAND_SECTIONS: BrandSectionDef[] = [
  {
    id: 'identity',
    title: 'Brand Identity',
    description: 'Who the brand is and what it stands for.',
    fields: [
      { name: 'name', label: 'Brand Name', kind: 'text', required: true, max: 120, full: true, placeholder: 'e.g., Acme Studios' },
      { name: 'description', label: 'Description', kind: 'textarea', max: 2000, full: true, placeholder: 'What this brand is about and how it should sound.', hint: 'The single source of truth the engine uses to keep every caption on-brand.' },
      { name: 'industry', label: 'Industry', kind: 'text', max: 200, placeholder: 'e.g., Developer tools' },
      { name: 'brand_category', label: 'Brand Category', kind: 'text', max: 200, placeholder: 'e.g., Beverages, SaaS, Retail', hint: 'Used by Brand Intelligence to group brands when classifying images.' },
      { name: 'website', label: 'Website', kind: 'text', max: 500, placeholder: 'https://example.com' },
      { name: 'tagline', label: 'Tagline', kind: 'text', max: 300, placeholder: 'e.g., Ship faster, sleep better' },
      { name: 'mission', label: 'Mission', kind: 'textarea', max: 1000, full: true, placeholder: 'Why the brand exists — one or two sentences.' },
      { name: 'core_values', label: 'Core Values', kind: 'chips', full: true, placeholder: 'e.g., Craft, Simplicity, Transparency', hint: 'Press Enter or comma to add. Up to 50 values.' },
      { name: 'known_text_aliases', label: 'Known Brand Text & Aliases', kind: 'chips', full: true, placeholder: 'e.g., Acme, ACME Co, acme-store', hint: 'Names, spellings and taglines OCR should recognize on photos — case-insensitive matching.' },
    ],
  },
  {
    id: 'voice',
    title: 'Brand Voice',
    description: 'How the brand sounds — this drives every generated caption.',
    fields: [
      { name: 'tone_of_voice', label: 'Tone', kind: 'select', options: TONE_OPTIONS, placeholder: 'professional' },
      { name: 'formality_level', label: 'Formality', kind: 'select', options: FORMALITY_OPTIONS, placeholder: 'Not set' },
      { name: 'tone_description', label: 'Tone Description', kind: 'textarea', max: 1000, full: true, placeholder: 'e.g., Professional and approachable — like a knowledgeable colleague.', hint: 'Free-form description of how the tone should feel in practice.' },
      { name: 'personality_traits', label: 'Personality Traits', kind: 'chips', placeholder: 'e.g., Curious, innovative', hint: 'Press Enter or comma to add.' },
      { name: 'writing_style', label: 'Writing Style', kind: 'text', max: 500, placeholder: 'e.g., concise technical prose' },
      { name: 'sentence_length', label: 'Sentence Length', kind: 'select', options: SENTENCE_OPTIONS, placeholder: 'Not set' },
      { name: 'person_preference', label: 'Person', kind: 'select', options: PERSON_OPTIONS, placeholder: 'Not set', hint: 'First-person (“we”) or third-person (“they”).' },
    ],
  },
  {
    id: 'audience',
    title: 'Target Audience',
    description: 'Who the brand speaks to and what that audience needs.',
    fields: [
      { name: 'target_audience', label: 'Primary Audience', kind: 'text', max: 1000, full: true, placeholder: 'e.g., Mid-market fintech buyers' },
      { name: 'secondary_audience', label: 'Secondary Audience', kind: 'text', max: 1000, full: true, placeholder: 'e.g., Engineering managers' },
      { name: 'audience_demographics', label: 'Demographics', kind: 'textarea', max: 1000, placeholder: 'e.g., 25-40, urban, mobile-first' },
      { name: 'audience_interests', label: 'Interests', kind: 'textarea', max: 1000, placeholder: 'e.g., Open source, developer experience' },
      { name: 'audience_pain_points', label: 'Pain Points', kind: 'textarea', max: 1000, placeholder: 'e.g., Slow releases, noisy alerts' },
      { name: 'technical_level', label: 'Technical Level', kind: 'select', options: TECHNICAL_OPTIONS, placeholder: 'Not set', hint: 'How much jargon the audience understands.' },
      { name: 'communication_expectations', label: 'Communication Expectations', kind: 'textarea', max: 1000, full: true, placeholder: 'e.g., No fluff — lead with specifics and evidence.' },
    ],
  },
  {
    id: 'language',
    title: 'Language Guidelines',
    description: 'Words to use, words to avoid, and formatting rules.',
    fields: [
      { name: 'preferred_vocabulary', label: 'Preferred Vocabulary', kind: 'chips', full: true, placeholder: 'e.g., thoughtful, durable, community', hint: 'Words and phrases the brand prefers — the engine will lean on these.' },
      { name: 'avoid_words_claims', label: 'Words / Claims to Avoid', kind: 'chips', full: true, placeholder: 'e.g., best, #1, revolutionary', hint: 'Hard rules: these must never appear in generated content.' },
      { name: 'industry_vocabulary', label: 'Industry Vocabulary', kind: 'textarea', max: 1000, placeholder: 'e.g., Prefer CI/CD, SLO, PR over vague equivalents.' },
      { name: 'emoji_preference', label: 'Emoji Preference', kind: 'select', options: EMOJI_OPTIONS, placeholder: 'Not set', hint: 'none = emojis are prohibited.' },
      { name: 'capitalization_preferences', label: 'Capitalization', kind: 'text', max: 500, placeholder: 'e.g., Sentence case everywhere' },
      { name: 'hashtag_guidance', label: 'Hashtag Guidance', kind: 'text', max: 500, placeholder: 'e.g., Use 3-5 relevant hashtags' },
      { name: 'preferred_cta', label: 'Preferred CTA', kind: 'text', max: 500, placeholder: 'e.g., Learn more, Get started' },
      { name: 'cta_style', label: 'CTA Style', kind: 'text', max: 500, placeholder: 'e.g., Formal invitation, question-based' },
    ],
  },
  {
    id: 'content',
    title: 'Content Strategy',
    description: 'Platform-specific styles, hooks, themes and topics.',
    fields: [
      { name: 'campaign_objectives', label: 'Campaign Objectives', kind: 'textarea', max: 1000, full: true, placeholder: 'e.g., Awareness, leads, product launches' },
      { name: 'linkedin_style', label: 'LinkedIn Style', kind: 'textarea', max: 1000, placeholder: 'e.g., Insight-led, one idea per post, ends with a question.' },
      { name: 'instagram_style', label: 'Instagram Style', kind: 'textarea', max: 1000, placeholder: 'e.g., Visual-first, short lines, light emoji.' },
      { name: 'story_style', label: 'Story Style', kind: 'textarea', max: 1000, placeholder: 'e.g., Behind-the-scenes, casual, direct.' },
      { name: 'reel_style', label: 'Reel Style', kind: 'textarea', max: 1000, placeholder: 'e.g., Fast cuts, bold text hooks, punchy script.' },
      { name: 'preferred_caption_length', label: 'Caption Length', kind: 'text', max: 200, placeholder: 'e.g., 120 words' },
      { name: 'preferred_hook_style', label: 'Hook Style', kind: 'text', max: 500, placeholder: 'e.g., Start with a question or a bold claim' },
      { name: 'content_themes', label: 'Content Themes', kind: 'chips', placeholder: 'e.g., Engineering, Culture', hint: 'Recurring themes the brand posts about.' },
      { name: 'topics_to_avoid', label: 'Topics to Avoid', kind: 'chips', placeholder: 'e.g., Politics, Pricing rumors', hint: 'Broader than word-level bans — whole topics are off-limits.' },
    ],
  },
  {
    id: 'visual',
    title: 'Visual Identity',
    description: 'Colors, fonts, logo usage and overlay preferences.',
    fields: [
      { name: 'brand_colors', label: 'Brand Colors', kind: 'color', full: true, hint: 'Pick a color or type a hex value like #7C6AFF.' },
      { name: 'fonts', label: 'Fonts', kind: 'chips', placeholder: 'e.g., Inter, Georgia', hint: 'Press Enter or comma to add.' },
      { name: 'visual_style', label: 'Visual Style', kind: 'text', max: 500, placeholder: 'e.g., Dark minimal photography' },
      { name: 'logo_usage_guidelines', label: 'Logo Usage', kind: 'textarea', max: 1000, placeholder: 'e.g., Clear space of 1x logo height; never on busy areas.' },
      { name: 'text_overlay_preferences', label: 'Text Overlay Preferences', kind: 'textarea', max: 1000, full: true, placeholder: 'e.g., Bottom third only; never over faces.' },
      { name: 'logo_path', label: 'Logo', kind: 'logo', full: true, hint: 'PNG, JPG, WEBP or SVG. Shown on profile cards and used in compositions.' },
      { name: 'visual_references', label: 'Visual References', kind: 'refs', full: true, hint: 'Images or PDFs that show the brand’s look and feel.' },
      { name: 'reference_notes', label: 'Reference Notes', kind: 'textarea', max: 1000, full: true, placeholder: 'e.g., Prioritize packaging and storefront photos; avoid event selfies.', hint: 'Guidance for anyone adding reference photographs to this brand.' },
    ],
  },
]

/** All 48 schema fields covered by the sections (sanity-checked in tests). */
export const ALL_SECTION_FIELDS: string[] = BRAND_SECTIONS.flatMap(s => s.fields.map(f => f.name))

/** Empty values for a brand-new profile (matches backend defaults). */
export function emptyBrandProfile(): BrandProfile {
  return {
    name: '',
    description: '',
    target_audience: '',
    campaign_objectives: '',
    tone_of_voice: 'professional',
    preferred_vocabulary: [],
    avoid_words_claims: [],
    preferred_cta: '',
    hashtag_guidance: '',
    brand_colors: [],
    fonts: [],
    logo_path: null,
    visual_references: [],
    industry: '',
    website: '',
    tagline: '',
    mission: '',
    core_values: [],
    tone_description: '',
    personality_traits: [],
    formality_level: '',
    writing_style: '',
    sentence_length: '',
    person_preference: '',
    secondary_audience: '',
    audience_demographics: '',
    audience_interests: '',
    audience_pain_points: '',
    technical_level: '',
    communication_expectations: '',
    industry_vocabulary: '',
    emoji_preference: '',
    capitalization_preferences: '',
    linkedin_style: '',
    instagram_style: '',
    story_style: '',
    reel_style: '',
    preferred_caption_length: '',
    preferred_hook_style: '',
    cta_style: '',
    content_themes: [],
    topics_to_avoid: [],
    visual_style: '',
    logo_usage_guidelines: '',
    text_overlay_preferences: '',
    brand_category: '',
    known_text_aliases: [],
    reference_notes: '',
  }
}

/**
 * Whether a field holds meaningful, user-configured content.
 * Fields with non-empty schema defaults (tone_of_voice) only count once
 * changed from the default — an untouched default is not "configured".
 */
export function isFieldConfigured(profile: BrandProfile | null | undefined, fieldName: string): boolean {
  if (!profile) return false
  const value = profile[fieldName]
  if (Array.isArray(value)) return value.length > 0
  if (value === null || value === undefined) return false
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (!trimmed) return false
    if (fieldName === 'tone_of_voice') return trimmed !== 'professional'
    return true
  }
  return true
}

export interface SectionCompleteness {
  configured: number
  total: number
  percent: number
}

export function sectionCompleteness(profile: BrandProfile | null | undefined, section: BrandSectionDef): SectionCompleteness {
  const configured = section.fields.filter(f => isFieldConfigured(profile, f.name)).length
  const total = section.fields.length
  return { configured, total, percent: total ? Math.round((configured / total) * 100) : 0 }
}

export function profileCompleteness(profile: BrandProfile | null | undefined): {
  configured: number
  total: number
  percent: number
  sections: Record<string, SectionCompleteness>
} {
  const sections: Record<string, SectionCompleteness> = {}
  let configured = 0
  let total = 0
  for (const section of BRAND_SECTIONS) {
    const c = sectionCompleteness(profile, section)
    sections[section.id] = c
    configured += c.configured
    total += c.total
  }
  return { configured, total, percent: total ? Math.round((configured / total) * 100) : 0, sections }
}

/**
 * Convert a stored asset path (relative `output/...` or absolute Windows/
 * POSIX path) into a URL served by the backend's /output static mount.
 * Returns null when the path cannot be mapped.
 */
export function assetUrl(path?: string | null): string | null {
  if (!path) return null
  const norm = String(path).replace(/\\/g, '/')
  const idx = norm.lastIndexOf('/output/')
  if (idx >= 0) return norm.slice(idx)
  if (norm.startsWith('output/')) return '/' + norm
  const studioIdx = norm.lastIndexOf('/studio/')
  if (studioIdx >= 0) return '/output' + norm.slice(studioIdx)
  return null
}

/** Compact identity summary for profile cards. */
export function identitySummary(profile: BrandProfile): string[] {
  const parts: string[] = []
  if (profile.industry) parts.push(profile.industry)
  if (profile.tagline) parts.push(profile.tagline)
  return parts
}
