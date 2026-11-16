export const fmtBytes = (b: number) =>
  b < 1024 ? `${b}B` : b < 1024**2 ? `${(b/1024).toFixed(1)}KB` : `${(b/1024**2).toFixed(1)}MB`

export const fmtDuration = (s: number) =>
  s < 60 ? `${Math.round(s)}s` : `${Math.floor(s/60)}m ${Math.round(s%60)}s`

export const slug = (s: string) => s.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '')

export const charCount = (text: string) => ({
  chars: text.length,
  words: text.trim() ? text.trim().split(/\s+/).length : 0,
})

export const readabilityGrade = (text: string): number => {
  // Flesch-Kincaid grade level (simplified)
  const sentences = text.split(/[.!?]+/).filter(Boolean).length || 1
  const words = text.trim().split(/\s+/).filter(Boolean).length || 1
  const syllables = text.split(/[aeiouAEIOU]/).length - 1
  return Math.round(0.39 * (words / sentences) + 11.8 * (syllables / words) - 15.59)
}

/**
 * Insert hashtags into a caption without duplicating a group that already
 * exists. Generated captions already carry hashtags, so inserting must not
 * append an existing hashtag a second time. Comparison is case-insensitive.
 */
export const insertHashtags = (current: string, tags: string): string => {
  const existing = new Set((current.match(/#[A-Za-z0-9_]+/g) || []).map((t: string) => t.toLowerCase()))
  const incoming = tags
    .split(/\s+/)
    .filter((t: string) => t.startsWith('#') && t.length > 1 && !existing.has(t.toLowerCase()))
  if (!incoming.length) return current
  return current.trimEnd() + (current.trimEnd() ? '\n\n' : '') + incoming.join(' ')
}
