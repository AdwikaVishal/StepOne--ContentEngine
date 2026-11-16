/**
 * Milestone 3 — mobile layout screenshots (continuation of brand_ui_workflow).
 * Run: node scripts/brand_ui_mobile.mjs
 */
import { chromium } from 'playwright-core'
import { mkdirSync } from 'node:fs'

const EXE = 'C:/Users/ASUS/AppData/Local/ms-playwright/chromium-1161/chrome-win/chrome.exe'
const BASE = 'http://localhost:5173'
const SHOTS = 'C:/Users/ASUS/StepOne--ContentEngine/docs/brand-profiles-ui'
mkdirSync(SHOTS, { recursive: true })

const browser = await chromium.launch({ executablePath: EXE, headless: true })
const page = await browser.newPage({ viewport: { width: 390, height: 844 } })
page.setDefaultTimeout(20000)
const wait = ms => page.waitForTimeout(ms)

try {
  await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  await page.getByRole('navigation', { name: 'Mobile navigation' })
    .getByRole('button', { name: 'Brands' }).click()
  await page.waitForSelector('.bp-page')
  await wait(700)
  await page.screenshot({ path: `${SHOTS}/m3-14-mobile-list.png`, fullPage: true })

  await page.getByRole('button', { name: 'New Profile' }).click()
  await page.waitForSelector('#bp-name')
  await page.locator('.bp-section__head', { hasText: 'Brand Voice' }).click()
  await wait(400)
  await page.screenshot({ path: `${SHOTS}/m3-15-mobile-form.png`, fullPage: true })

  console.log('[mobile] screenshots captured')
} catch (err) {
  console.error('[mobile] FAILED:', err)
  process.exitCode = 1
} finally {
  await browser.close()
}
