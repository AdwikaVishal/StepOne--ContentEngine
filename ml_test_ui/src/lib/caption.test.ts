import { describe, it, expect } from 'vitest'
import { insertHashtags } from './formatters'

describe('insertHashtags — no duplicated hashtag groups', () => {
  it('does not append hashtags already present in the caption', () => {
    const caption = 'Great event recap. #EndToEnd #AcceptanceTesting'
    const result = insertHashtags(caption, '#EndToEnd #AcceptanceTesting #ContentCreator')
    expect(result).toBe('Great event recap. #EndToEnd #AcceptanceTesting\n\n#ContentCreator')
  })

  it('appends all hashtags when none exist yet', () => {
    const result = insertHashtags('Great event recap.', '#EventLife #BehindTheScenes')
    expect(result).toBe('Great event recap.\n\n#EventLife #BehindTheScenes')
  })

  it('is case-insensitive when detecting duplicates', () => {
    const result = insertHashtags('Caption #eventlife', '#EventLife #NewTag')
    expect(result).toBe('Caption #eventlife\n\n#NewTag')
  })

  it('returns the caption unchanged when all hashtags already exist', () => {
    const caption = 'Caption #a #b'
    expect(insertHashtags(caption, '#A #b')).toBe(caption)
  })

  it('handles an empty caption', () => {
    expect(insertHashtags('', '#EventLife')).toBe('#EventLife')
  })

  it('keeps only the new hashtags from a mixed existing/new list', () => {
    const caption = 'Recap #EventLife'
    const result = insertHashtags(caption, '#eventlife #BehindTheScenes #EventLife')
    expect(result).toBe('Recap #EventLife\n\n#BehindTheScenes')
  })
})
