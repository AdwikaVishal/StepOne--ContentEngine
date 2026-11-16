/**
 * Milestone 3 tests — brand profile form definitions and helpers.
 *
 * Verifies the six sections cover exactly the 48-field backend schema
 * (45 original + 3 Brand Intelligence additive fields), completeness
 * scoring reflects meaningful configuration (not default empty strings),
 * and stored asset paths map to servable URLs.
 */
import { describe, expect, it } from 'vitest'
import {
  ALL_SECTION_FIELDS,
  BRAND_SECTIONS,
  assetUrl,
  emptyBrandProfile,
  isFieldConfigured,
  profileCompleteness,
  sectionCompleteness,
} from './brandProfile'

// Mirror of content_engine/studio/storage.py BRAND_PROFILE_DEFAULTS keys.
const BACKEND_SCHEMA_FIELDS = [
  'name', 'description', 'target_audience', 'campaign_objectives',
  'tone_of_voice', 'preferred_vocabulary', 'avoid_words_claims',
  'preferred_cta', 'hashtag_guidance', 'logo_path', 'brand_colors',
  'fonts', 'visual_references',
  'industry', 'website', 'tagline', 'mission', 'core_values',
  'tone_description', 'personality_traits', 'formality_level',
  'writing_style', 'sentence_length', 'person_preference',
  'secondary_audience', 'audience_demographics', 'audience_interests',
  'audience_pain_points', 'technical_level', 'communication_expectations',
  'industry_vocabulary', 'emoji_preference', 'capitalization_preferences',
  'linkedin_style', 'instagram_style', 'story_style', 'reel_style',
  'preferred_caption_length', 'preferred_hook_style', 'cta_style',
  'content_themes', 'topics_to_avoid',
  'visual_style', 'logo_usage_guidelines', 'text_overlay_preferences',
  // Brand Intelligence (additive v3)
  'brand_category', 'known_text_aliases', 'reference_notes',
]

describe('section coverage', () => {
  it('has six sections', () => {
    expect(BRAND_SECTIONS).toHaveLength(6)
    expect(BRAND_SECTIONS.map(s => s.id)).toEqual([
      'identity', 'voice', 'audience', 'language', 'content', 'visual',
    ])
  })

  it('covers all 48 backend schema fields exactly once', () => {
    expect(ALL_SECTION_FIELDS).toHaveLength(48)
    expect(new Set(ALL_SECTION_FIELDS).size).toBe(48)
    expect([...ALL_SECTION_FIELDS].sort()).toEqual([...BACKEND_SCHEMA_FIELDS].sort())
  })

  it('every field has a label and a supported control kind', () => {
    const kinds = new Set(['text', 'textarea', 'select', 'chips', 'color', 'logo', 'refs'])
    for (const section of BRAND_SECTIONS) {
      for (const field of section.fields) {
        expect(field.label, `${field.name} label`).toBeTruthy()
        expect(kinds.has(field.kind), `${field.name} kind`).toBe(true)
        if (field.kind === 'text' || field.kind === 'textarea') {
          expect(field.max, `${field.name} max`).toBeGreaterThan(0)
        }
        if (field.kind === 'select') {
          expect(field.options?.length, `${field.name} options`).toBeGreaterThan(0)
        }
      }
    }
  })

  it('exactly one required field (brand name)', () => {
    const required = ALL_SECTION_FIELDS.filter(name => {
      const field = BRAND_SECTIONS.flatMap(s => s.fields).find(f => f.name === name)
      return field?.required
    })
    expect(required).toEqual(['name'])
  })
})

describe('emptyBrandProfile', () => {
  it('matches backend defaults for all 48 fields', () => {
    const profile = emptyBrandProfile()
    expect(Object.keys(profile).sort()).toEqual([...BACKEND_SCHEMA_FIELDS].sort())
    expect(profile.name).toBe('')
    expect(profile.tone_of_voice).toBe('professional')
    expect(profile.logo_path).toBeNull()
    expect(profile.brand_colors).toEqual([])
    expect(profile.personality_traits).toEqual([])
    expect(profile.brand_category).toBe('')
    expect(profile.known_text_aliases).toEqual([])
    expect(profile.reference_notes).toBe('')
  })
})

describe('completeness scoring', () => {
  it('an empty profile is 0% despite having default values', () => {
    const pc = profileCompleteness(emptyBrandProfile())
    expect(pc.configured).toBe(0)
    expect(pc.percent).toBe(0)
    // tone_of_voice defaults to "professional" — a default is not configured.
    expect(isFieldConfigured(emptyBrandProfile(), 'tone_of_voice')).toBe(false)
  })

  it('counts meaningful values only', () => {
    const profile = emptyBrandProfile()
    profile.name = 'Aurora'
    profile.industry = 'Developer tools'
    profile.core_values = ['Craft']
    profile.brand_colors = ['#7C6AFF']
    profile.logo_path = 'output/studio/brand_assets/x/logo.png'
    profile.description = '   ' // whitespace is not configured
    expect(isFieldConfigured(profile, 'name')).toBe(true)
    expect(isFieldConfigured(profile, 'industry')).toBe(true)
    expect(isFieldConfigured(profile, 'core_values')).toBe(true)
    expect(isFieldConfigured(profile, 'logo_path')).toBe(true)
    expect(isFieldConfigured(profile, 'description')).toBe(false)
    const pc = profileCompleteness(profile)
    expect(pc.configured).toBe(5)
    expect(pc.percent).toBe(Math.round((5 / 48) * 100))
  })

  it('tone changed from default counts as configured', () => {
    const profile = emptyBrandProfile()
    profile.tone_of_voice = 'friendly'
    expect(isFieldConfigured(profile, 'tone_of_voice')).toBe(true)
    expect(sectionCompleteness(profile, BRAND_SECTIONS[1]).configured).toBe(1)
  })

  it('a fully populated profile is 100%', () => {
    const profile = emptyBrandProfile()
    for (const section of BRAND_SECTIONS) {
      for (const field of section.fields) {
        if (field.kind === 'chips' || field.kind === 'color' || field.kind === 'refs') {
          profile[field.name] = ['x']
        } else if (field.kind === 'logo') {
          profile[field.name] = 'output/logo.png'
        } else if (field.kind === 'select') {
          profile[field.name] = (field.options ?? ['v'])[1] ?? 'v'
        } else {
          profile[field.name] = 'value'
        }
      }
    }
    profile.tone_of_voice = 'bold' // must differ from default
    const pc = profileCompleteness(profile)
    expect(pc.configured).toBe(48)
    expect(pc.percent).toBe(100)
  })

  it('handles null/undefined profiles', () => {
    expect(profileCompleteness(null).percent).toBe(0)
    expect(isFieldConfigured(undefined, 'name')).toBe(false)
  })
})

describe('assetUrl', () => {
  it('maps relative output/ paths', () => {
    expect(assetUrl('output/studio/brand_assets/a/logo.png'))
      .toBe('/output/studio/brand_assets/a/logo.png')
  })

  it('maps Windows relative paths', () => {
    expect(assetUrl('output\\studio\\brand_assets\\a\\logo.png'))
      .toBe('/output/studio/brand_assets/a/logo.png')
  })

  it('maps absolute paths containing /output/', () => {
    expect(assetUrl('C:/repo/output/studio/brand_assets/a/logo.png'))
      .toBe('/output/studio/brand_assets/a/logo.png')
    expect(assetUrl('C:\\repo\\output\\studio\\brand_assets\\a\\logo.png'))
      .toBe('/output/studio/brand_assets/a/logo.png')
  })

  it('returns null for unmappable paths', () => {
    expect(assetUrl(null)).toBeNull()
    expect(assetUrl('')).toBeNull()
    expect(assetUrl('/etc/passwd')).toBeNull()
  })
})
