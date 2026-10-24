/**
 * End-to-end UI smoke test against a running server.
 *
 * Drives a real browser through the whole journey — upload a demo, wait for processing,
 * open every dashboard tab — and fails on a console error or a missing element. Unit
 * tests cannot catch a chart that throws on real data or a tab that renders blank, and
 * this is cheap enough to run on demand.
 *
 *   node scripts/verify-ui.mjs <base-url> <demo-path> [out-dir]
 */

import { mkdirSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import puppeteer from 'puppeteer-core'

const CHROME = process.env.CHROME_PATH ?? '/usr/bin/chromium'
const [baseUrl = 'http://127.0.0.1:8000', demoPath, outDir = 'ui-shots'] = process.argv.slice(2)

if (!demoPath || !existsSync(demoPath)) {
  console.error(`usage: node scripts/verify-ui.mjs <base-url> <demo-path> [out-dir]`)
  process.exit(2)
}
mkdirSync(outDir, { recursive: true })

const failures = []
const consoleErrors = []

function check(name, condition, detail = '') {
  if (condition) {
    console.log(`  ok    ${name}`)
  } else {
    console.log(`  FAIL  ${name}${detail ? ` — ${detail}` : ''}`)
    failures.push(name)
  }
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: true,
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--force-color-profile=srgb'],
})

try {
  const page = await browser.newPage()
  await page.setViewport({ width: 1600, height: 1000, deviceScaleFactor: 1 })

  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('pageerror', (error) => consoleErrors.push(`pageerror: ${error.message}`))

  const shot = async (name) => {
    await page.screenshot({ path: join(outDir, `${name}.png`) })
  }

  // --- library and upload -------------------------------------------------
  console.log('\nlibrary')
  await page.goto(baseUrl, { waitUntil: 'networkidle2' })
  await page.waitForSelector('text/Add a match')
  const heading = await page.$eval('h1, h2', (el) => el.textContent)
  check('library renders', Boolean(heading))
  check('upload panel present', await page.$('input[type=file]') !== null)
  await shot('01-library')

  console.log('\nupload')
  const input = await page.$('input[type=file]')
  await input.uploadFile(demoPath)

  // The app navigates to the match once the server accepts it.
  await page.waitForFunction(() => location.pathname.startsWith('/matches/'), { timeout: 120_000 })
  const matchUrl = page.url()
  check('navigated to the match', matchUrl.includes('/matches/'), matchUrl)
  await shot('02-processing')

  // --- processing -> completed --------------------------------------------
  console.log('\nprocessing')
  await page.waitForFunction(
    () => document.body.innerText.includes('Score progression') ||
          document.body.innerText.includes('Processing failed'),
    { timeout: 180_000 },
  )
  const failed = await page.evaluate(() => document.body.innerText.includes('Processing failed'))
  check('processing completed without failure', !failed)
  if (failed) {
    const text = await page.evaluate(() => document.body.innerText.slice(0, 600))
    console.log(text)
  }

  // --- each tab -----------------------------------------------------------
  const tabs = [
    { name: 'overview', expect: ['Score progression', 'Round outcomes', 'Match context'] },
    { name: 'players', expect: ['Player statistics', 'ADR', 'KAST'] },
    { name: 'rounds', expect: ['Rounds', 'Timeline'] },
    { name: 'events', expect: ['Events', 'matching event'] },
    { name: 'map', expect: ['Positions'] },
  ]

  /**
   * Click a tab with a real mouse press.
   *
   * A synthetic `element.click()` is not enough: the tab triggers are driven by pointer
   * events, so an injected click leaves the tab inactive and every assertion below it
   * fails for the wrong reason.
   */
  const clickTab = async (name) => {
    const handles = await page.$$('[role=tab]')
    for (const handle of handles) {
      const text = await handle.evaluate((el) => el.textContent.trim())
      if (text === name) {
        await handle.click()
        await page.waitForFunction(
          (tabName) =>
            [...document.querySelectorAll('[role=tab]')].some(
              (el) => el.textContent.trim() === tabName && el.dataset.state === 'active',
            ),
          { timeout: 10_000 },
          name,
        )
        return true
      }
    }
    return false
  }

  for (const [index, tab] of tabs.entries()) {
    console.log(`\ntab: ${tab.name}`)
    check(`${tab.name}: tab activates`, await clickTab(tab.name))
    await page.waitForFunction(
      (texts) => texts.every((text) => document.body.innerText.includes(text)),
      { timeout: 30_000 },
      tab.expect,
    ).catch(() => {})

    const body = await page.evaluate(() => document.body.innerText)
    for (const text of tab.expect) {
      check(`${tab.name}: shows "${text}"`, body.includes(text))
    }
    await shot(`0${index + 3}-${tab.name}`)
  }

  // --- specific correctness spot-checks in the rendered DOM ---------------
  console.log('\nrendered values')
  await clickTab('players')
  await page.waitForSelector('table.stat-table tbody tr')
  const rows = await page.$$eval('table.stat-table tbody tr', (trs) =>
    trs.map((tr) => [...tr.querySelectorAll('td')].map((td) => td.textContent.trim())),
  )
  check('scoreboard has rows', rows.length > 0, `${rows.length} rows`)
  check('top row is the top fragger', rows[0]?.[2] === '27', `kills cell = ${rows[0]?.[2]}`)
  check(
    'unknown metrics render as an em dash, not 0',
    rows.some((cells) => cells.includes('—')),
  )

  // Map tab: the radar image must actually load, and marks must be drawn.
  await clickTab('map')
  // Wait for the radar image itself, not for any `svg circle` — the loading spinner
  // contains circles too, so that selector would match before the plot has rendered.
  await page
    .waitForFunction(
      () => {
        const img = document.querySelector('img[alt$="radar"]')
        return Boolean(img && img.complete && img.naturalWidth > 0)
      },
      { timeout: 30_000 },
    )
    .catch(() => {})
  const radar = await page.evaluate(() => {
    const img = document.querySelector('img[alt$="radar"]')
    return img ? { complete: img.complete, width: img.naturalWidth, src: img.src } : null
  })
  check('radar image loaded', radar?.complete === true && radar?.width > 0, JSON.stringify(radar))

  // Count marks inside the plot's own svg, and cross-check the count against the legend.
  const plot = await page.evaluate(() => {
    const img = document.querySelector('img[alt$="radar"]')
    const svg = img?.parentElement?.querySelector('svg')
    const text = document.body.innerText
    const plotted = /·\s*(\d+)\s*plotted/.exec(text)?.[1]
    return { circles: svg?.querySelectorAll('circle').length ?? 0, plotted: Number(plotted ?? 0) }
  })
  check('position marks drawn', plot.circles > 0, `${plot.circles} circles`)
  check(
    'every plotted position is drawn',
    // Each mark is a surface ring plus a fill, so two circles per position.
    plot.plotted > 0 && plot.circles === plot.plotted * 2,
    `${plot.plotted} plotted, ${plot.circles} circles`,
  )
  await shot('08-map-detail')

  // --- responsive ---------------------------------------------------------
  console.log('\nresponsive')
  await clickTab('overview')
  await page.setViewport({ width: 834, height: 1112, deviceScaleFactor: 1 }) // tablet
  await new Promise((resolve) => setTimeout(resolve, 800))
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  check('no horizontal page overflow at tablet width', overflow <= 1, `${overflow}px`)
  await shot('09-tablet')

  // --- console ------------------------------------------------------------
  console.log('\nconsole')
  // React's dev-only act() warnings and the favicon 404 are noise; anything else is not.
  const real = consoleErrors.filter(
    (text) => !/favicon|Download the React DevTools/i.test(text),
  )
  check('no console errors', real.length === 0, real.slice(0, 3).join(' | '))
} finally {
  await browser.close()
}

console.log(
  `\n${failures.length === 0 ? 'UI VERIFICATION PASSED' : `UI VERIFICATION FAILED: ${failures.join(', ')}`}`,
)
process.exit(failures.length === 0 ? 0 : 1)
