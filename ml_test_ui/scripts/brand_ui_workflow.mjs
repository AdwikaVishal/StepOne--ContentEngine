/**
 * Milestone 3 browser acceptance workflow.
 *
 * Creates two deliberately different brand profiles through the real UI,
 * uploads logos, exercises every form section, generates Brand Voice
 * Previews through the real local Qwen endpoint, verifies unsaved-change
 * handling, and captures screenshots to docs/brand-profiles-ui/.
 *
 * Run: node scripts/brand_ui_workflow.mjs   (vite dev on :5173, API on :8000)
 */
import { chromium } from 'playwright-core'
import { mkdirSync } from 'node:fs'

const EXE = 'C:/Users/ASUS/AppData/Local/ms-playwright/chromium-1161/chrome-win/chrome.exe'
const BASE = 'http://localhost:5173'
const SHOTS = 'C:/Users/ASUS/StepOne--ContentEngine/docs/brand-profiles-ui'
const LOGOS = 'C:/Users/ASUS/AppData/Local/Temp/ce-brand-assets'

mkdirSync(SHOTS, { recursive: true })

const browser = await chromium.launch({ executablePath: EXE, headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
page.setDefaultTimeout(20000)

const shot = name => page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true })
const wait = ms => page.waitForTimeout(ms)

async function gotoBrands() {
  await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  await page.getByRole('navigation').getByRole('button', { name: 'Brand Profiles' }).click()
  await page.waitForSelector('.bp-page')
  await wait(700)
}

const sectionHead = title => page.locator('.bp-section__head', { hasText: title })
async function openSection(title) {
  const head = sectionHead(title)
  if ((await head.getAttribute('aria-expanded')) !== 'true') await head.click()
  await wait(300)
}
async function closeSection(title) {
  const head = sectionHead(title)
  if ((await head.getAttribute('aria-expanded')) === 'true') await head.click()
  await wait(250)
}
const fill = (id, value) => page.locator(`#bp-${id}`).fill(value)
const select = (id, value) => page.locator(`#bp-${id}`).selectOption(value)
async function addChips(id, items) {
  const input = page.locator(`#bp-${id}`)
  for (const item of items) {
    await input.fill(item)
    await input.press('Enter')
  }
}
async function addColor(hex) {
  const input = page.locator('#bp-brand_colors')
  await input.fill(hex)
  await input.press('Enter')
  await wait(150)
}

const log = (...a) => console.log('[workflow]', ...a)

try {
  /* ── 0. Initial list (existing profiles incl. Crackers) ── */
  await gotoBrands()
  await shot('m3-00-list-initial')
  log('initial list captured')

  /* ── 1. Create Brand A — Northwind Analytics (formal, no emojis) ── */
  await page.getByRole('button', { name: 'New Profile' }).click()
  await page.waitForSelector('#bp-name')
  await wait(400)
  await shot('m3-01-create-form-identity')
  log('create form open')

  // Brand Identity
  await fill('name', 'Northwind Analytics')
  await fill('description', 'Northwind Analytics helps operations teams spot anomalies before they become incidents. The brand sounds precise, calm and evidence-led.')
  await fill('industry', 'Data analytics')
  await fill('website', 'https://northwind.example')
  await fill('tagline', 'See trouble coming')
  await fill('mission', 'Give operations teams reliable signals they can act on.')
  await addChips('core_values', ['Precision', 'Reliability', 'Transparency'])
  await shot('m3-02-section-identity')
  await closeSection('Brand Identity')

  // Brand Voice
  await openSection('Brand Voice')
  await select('tone_of_voice', 'professional')
  await select('formality_level', 'formal')
  await fill('tone_description', 'Professional and approachable — like a knowledgeable colleague presenting findings.')
  await addChips('personality_traits', ['Authoritative', 'Technical', 'Calm'])
  await fill('writing_style', 'concise, evidence-led prose')
  await select('sentence_length', 'short')
  await select('person_preference', 'third-person')
  await shot('m3-03-section-voice')
  await closeSection('Brand Voice')

  // Target Audience
  await openSection('Target Audience')
  await fill('target_audience', 'Enterprise operations and SRE leaders')
  await fill('secondary_audience', 'Data engineers')
  await fill('audience_interests', 'Observability, SLOs, incident postmortems')
  await fill('audience_pain_points', 'Noisy alerts, dashboard sprawl, slow root-cause analysis')
  await select('technical_level', 'expert')
  await fill('communication_expectations', 'Lead with specifics and evidence; no hyperbole.')
  await shot('m3-04-section-audience')
  await closeSection('Target Audience')

  // Language Guidelines
  await openSection('Language Guidelines')
  await addChips('preferred_vocabulary', ['signal', 'anomaly', 'reliable'])
  await addChips('avoid_words_claims', ['game-changer', 'revolutionary', 'magic'])
  await select('emoji_preference', 'none')
  await fill('preferred_cta', 'Request a briefing')
  await fill('hashtag_guidance', '2-3 hashtags, always including #Operations')
  await shot('m3-05-section-language')
  await closeSection('Language Guidelines')

  // Content Strategy
  await openSection('Content Strategy')
  await fill('linkedin_style', 'Insight-led posts with one finding and one takeaway.')
  await fill('preferred_hook_style', 'Start with a surprising operational statistic.')
  await addChips('content_themes', ['Reliability', 'Observability'])
  await addChips('topics_to_avoid', ['Politics', 'Competitor gossip'])
  await shot('m3-06-section-content')
  await closeSection('Content Strategy')

  // Visual Identity + logo upload
  await openSection('Visual Identity')
  await addColor('#12263F')
  await addColor('#4EA8DE')
  await addChips('fonts', ['Inter'])
  await fill('visual_style', 'dark data-heavy dashboards with navy accents')
  await page.locator('#bp-sec-visual input[type="file"]').first().setInputFiles(`${LOGOS}/logo-a.png`)
  await wait(500)
  await shot('m3-07-section-visual')

  await page.getByRole('button', { name: 'Create Profile' }).click()
  await page.locator('.bp-card__name', { hasText: 'Northwind Analytics' }).waitFor({ timeout: 30000 })
  await wait(500)
  log('Brand A saved')

  /* ── 2. Edit Brand A, change tone WITHOUT saving, preview (unsaved values) ── */
  const cardA = page.locator('.bp-card', { hasText: 'Northwind Analytics' })
  await cardA.getByRole('button', { name: 'Edit' }).click()
  await page.waitForSelector('#bp-name')
  await wait(400)
  await shot('m3-08-edit-mode')

  await openSection('Brand Voice')
  await select('tone_of_voice', 'friendly') // unsaved change
  await fill('tone_description', 'Warm and encouraging, still precise.') // unsaved change
  await wait(200)
  log('tone changed to friendly (unsaved) — generating voice preview…')
  await page.locator('.bp-preview-btn').click()
  await page.waitForSelector('.bp-preview-sample', { timeout: 300000 })
  await wait(300)
  await shot('m3-09-voice-preview-unsaved')
  const sampleA = await page.locator('.bp-preview-sample').innerText()
  log('preview A captured, length:', sampleA.length)

  // Cancel → unsaved-changes modal → discard
  await page.getByRole('button', { name: 'Cancel' }).click()
  await page.waitForSelector('.bp-modal-text', { timeout: 5000 })
  await shot('m3-10-unsaved-changes-modal')
  await page.getByRole('button', { name: 'Discard changes' }).click()
  await page.waitForSelector('.bp-grid', { timeout: 10000 })
  log('edits discarded; saved profile untouched')

  /* ── 3. Create Brand B — Sunny Side Social (friendly, emojis) ── */
  await page.getByRole('button', { name: 'New Profile' }).click()
  await page.waitForSelector('#bp-name')
  await fill('name', 'Sunny Side Social')
  await fill('description', 'Sunny Side Social helps small creators build audiences they love showing up for. The brand is warm, energetic and community-driven.')
  await fill('industry', 'Social media marketing')
  await fill('tagline', 'Make every post a good one')
  await closeSection('Brand Identity')

  await openSection('Brand Voice')
  await select('tone_of_voice', 'friendly')
  await select('formality_level', 'casual')
  await fill('tone_description', 'Playful, upbeat and encouraging — like a cheerleader with a content calendar.')
  await addChips('personality_traits', ['Energetic', 'Community-driven', 'Playful'])
  await fill('writing_style', 'conversational, warm, exclamatory')
  await closeSection('Brand Voice')

  await openSection('Target Audience')
  await fill('target_audience', 'Small business owners and solo creators')
  await fill('audience_pain_points', 'Posting consistently, finding their voice, beating the algorithm')
  await select('technical_level', 'general')
  await closeSection('Target Audience')

  await openSection('Language Guidelines')
  await addChips('preferred_vocabulary', ['grow', 'together', 'your audience'])
  await addChips('avoid_words_claims', ['guaranteed', 'overnight success'])
  await select('emoji_preference', 'moderate')
  await fill('preferred_cta', 'Come build with us')
  await closeSection('Language Guidelines')

  await openSection('Visual Identity')
  await addColor('#FFD166')
  await page.locator('#bp-sec-visual input[type="file"]').first().setInputFiles(`${LOGOS}/logo-b.png`)
  await wait(500)
  await shot('m3-11-visual-brand-b')

  await page.getByRole('button', { name: 'Create Profile' }).click()
  await page.locator('.bp-card__name', { hasText: 'Sunny Side Social' }).waitFor({ timeout: 30000 })
  await wait(500)
  await shot('m3-12-list-both-profiles')
  log('Brand B saved; both cards visible')

  /* ── 4. Voice preview for Brand B ── */
  const cardB = page.locator('.bp-card', { hasText: 'Sunny Side Social' })
  await cardB.getByRole('button', { name: 'Edit' }).click()
  await page.waitForSelector('#bp-name')
  await wait(400)
  log('Brand B preview generating…')
  await page.locator('.bp-preview-btn').click()
  await page.waitForSelector('.bp-preview-sample', { timeout: 300000 })
  await wait(300)
  await shot('m3-13-voice-preview-brand-b')
  const sampleB = await page.locator('.bp-preview-sample').innerText()
  log('preview B captured, length:', sampleB.length)

  await page.getByRole('button', { name: 'Cancel' }).click()
  await wait(400)

  /* ── 5. Mobile layout ── */
  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } })
  await mobile.goto(BASE, { waitUntil: 'domcontentloaded' })
  await mobile.getByRole('navigation').getByRole('button', { name: 'Brand Profiles' }).click()
  await mobile.waitForSelector('.bp-page')
  await wait(700)
  await mobile.screenshot({ path: `${SHOTS}/m3-14-mobile-list.png`, fullPage: true })
  await mobile.getByRole('button', { name: 'New Profile' }).click()
  await mobile.waitForSelector('#bp-name')
  await mobile.locator('.bp-section__head', { hasText: 'Brand Voice' }).click()
  await wait(400)
  await mobile.screenshot({ path: `${SHOTS}/m3-15-mobile-form.png`, fullPage: true })
  log('mobile screenshots captured')

  console.log('\n=== WORKFLOW COMPLETE ===')
  console.log('--- SAMPLE A (unsaved friendly tone) ---')
  console.log(sampleA)
  console.log('--- SAMPLE B (friendly/emoji brand) ---')
  console.log(sampleB)
} catch (err) {
  console.error('[workflow] FAILED:', err)
  try { await shot('m3-error-state') } catch { /* ignore */ }
  process.exitCode = 1
} finally {
  await browser.close()
}
