/**
 * Gates 1 and 2: live progress keeps its content readable, and a completed
 * result gives the recovered height to the geometry viewport.
 *
 * Gate 1 mounts a manufactured live two-step run (frontend transport only, not
 * solver evidence) and measures real child bounds at four sizes in both
 * languages, plus a short window where the named detail region scrolls by
 * keyboard. Gate 2 uses a manufactured completed run and measures the result
 * grid and viewport before/after opening Diagnostics.
 */
import { randomUUID } from 'node:crypto'
import { expect, test, type Page } from './fixtures'
import { meshAndDeck } from './pipeline'
import type { Job, Revision } from '../src/api'

const JOB_ID = '11111111-1111-4111-8111-111111111111'
const REVISION_ID = '22222222-2222-4222-8222-222222222222'

const setup = {
  analysis: { mode: 'body_then_door' },
  motion: {
    duration: 1.3,
    travel: -5.5,
    offset: 0,
    body: { duration: 1.0, travel: -3.0, offset: 0 },
  },
}

function baseJob(overrides: Partial<Job>): Job {
  const now = Date.now() / 1000
  return {
    id: JOB_ID,
    revision: REVISION_ID,
    project: '33333333-3333-4333-8333-333333333333',
    number: 1,
    project_name: 'Run layout model',
    name: 'Run layout job',
    dimension: '2D',
    mode: 'ABAQUS',
    status: 'Running',
    solver: 'Running',
    extraction: 'Pending',
    scenario: 'success',
    phase: 'Solving',
    created: now - 30,
    started: now - 20,
    ended: null,
    heartbeat: now,
    pid: 4242,
    process_started: now - 20,
    step: 'Body seating',
    increment: 12,
    step_time: 0.5,
    exit_code: null,
    extraction_exit: null,
    cpus: 1,
    build: null,
    mesh: null,
    mesh_digest: null,
    mesh_compat: null,
    fixture_hash: null,
    fixture: null,
    fixture_labels: null,
    diagnostic: '',
    manifest: [],
    input_hash: 'a'.repeat(64),
    ...overrides,
  } as Job
}

async function mountLive(page: Page, job: Job) {
  await page.unroute('**/api/jobs/' + JOB_ID).catch(() => undefined)
  await page.unroute('**/api/jobs/' + JOB_ID + '/tail/**').catch(() => undefined)
  await page.route('**/api/jobs/' + JOB_ID, (route) => route.fulfill({ json: job }))
  await page.route('**/api/jobs/' + JOB_ID + '/tail/**', (route) =>
    route.fulfill({ json: { text: '' } }),
  )
  await page.route('**/api/revisions/' + REVISION_ID, (route) =>
    route.fulfill({ json: { setup } }),
  )
  await page.goto('/#diagnostics/' + JOB_ID)
  await expect(page.getByTestId('run-progress')).toBeVisible()
}

async function setLanguage(page: Page, language: 'ja' | 'en') {
  await page.addInitScript((value) => {
    try {
      localStorage.setItem('abaqus-qol.language', value)
    } catch {
      // A private-mode browser keeps the Japanese default; the test then fails
      // loudly on the language attribute instead of silently testing Japanese.
    }
  }, language)
}

async function cardOverflow(page: Page) {
  return page.getByTestId('run-progress').evaluate((element) => ({
    scroll: element.scrollHeight,
    client: element.clientHeight,
    top: element.getBoundingClientRect().top,
    bottom: element.getBoundingClientRect().bottom,
  }))
}

async function withinCard(page: Page, selector: string) {
  return page.evaluate((query) => {
    const card = document.querySelector('[data-testid="run-progress"]')!.getBoundingClientRect()
    const item = document.querySelector(query)?.getBoundingClientRect()
    return item ? { top: item.top, bottom: item.bottom, cardTop: card.top, cardBottom: card.bottom } : null
  }, selector)
}

// ---------------------------------------------------------------- Gate 1

for (const language of ['en', 'ja'] as const) {
  test(`live progress is not clipped at every size (${language})`, async ({ page }) => {
    await setLanguage(page, language)
    const sizes = [
      { width: 1874, height: 762 },
      { width: 1440, height: 900 },
      { width: 1280, height: 720 },
      { width: 390, height: 844 },
    ]
    for (const size of sizes) {
      await page.setViewportSize(size)
      // Determinate two-step progress plus a wrapped warning paragraph.
      await mountLive(
        page,
        baseJob({
          step: 'Body seating',
          step_time: 0.5,
          heartbeat: Date.now() / 1000 - 180,
        }),
      )
      await expect(page.locator('html')).toHaveAttribute('lang', language)
      await expect(page.locator('[data-testid="progress-steps"] li')).toHaveCount(2)
      await expect(page.getByTestId('stale-heartbeat')).toBeVisible()
      await expect(page.getByTestId('progress-current')).toBeVisible()
      // The card itself must not clip: available height >= content height.
      const overflow = await cardOverflow(page)
      expect(
        { size, clipped: overflow.scroll > overflow.client + 1 },
        `card ${overflow.client}px for ${overflow.scroll}px of content at ${size.width}x${size.height}`,
      ).toEqual({ size, clipped: false })
      // Every key child is either inside the card's visible box, or reachable
      // through the named detail scroller when the window is short.
      for (const selector of [
        '.progress-track',
        '[data-testid="progress-current"]',
        '[data-testid="stale-heartbeat"]',
      ]) {
        const box = await withinCard(page, selector)
        expect(box, selector).not.toBeNull()
        expect(
          { selector, inside: box!.bottom <= box!.cardBottom + 1 && box!.top >= box!.cardTop - 1 },
          `${selector} at ${size.width}x${size.height}`,
        ).toEqual({ selector, inside: true })
      }
      const factsVisible = await page.evaluate(() => {
        const card = document
          .querySelector('[data-testid="run-progress"]')!
          .getBoundingClientRect()
        const detail = document.querySelector('[data-testid="progress-detail"]') as HTMLElement
        const facts = document
          .querySelector('[data-testid="progress-facts"]')!
          .getBoundingClientRect()
        if (facts.bottom <= card.bottom + 1 && facts.top >= card.top - 1) return true
        // The detail region owns the overflow; scrolling it reveals the facts.
        detail.scrollTop = detail.scrollHeight
        const after = document
          .querySelector('[data-testid="progress-facts"]')!
          .getBoundingClientRect()
        return detail.scrollHeight > detail.clientHeight && after.bottom <= card.bottom + 1
      })
      expect(factsVisible, `facts at ${size.width}x${size.height}`).toBe(true)
      // Diagnostics and Cancel are reachable; Cancel is never activated here.
      await expect(page.getByRole('button', { name: /Cancel job|実行を中止/ })).toBeVisible()
      await expect(page.locator('.log-card')).toBeVisible()
    }
  })
}

test('unknown progress and a failed extraction stay visible without lying', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  await mountLive(page, baseJob({ solver: 'Waiting for license', phase: 'Waiting for license', step: null }))
  await expect(page.getByRole('progressbar')).toHaveAttribute('data-indeterminate', 'true')
  await expect(page.getByTestId('license-wait')).toBeVisible()
  const waitBox = await withinCard(page, '[data-testid="license-wait"]')
  expect(waitBox!.bottom).toBeLessThanOrEqual(waitBox!.cardBottom + 1)

  await mountLive(
    page,
    baseJob({
      status: 'Failed',
      solver: 'Succeeded',
      extraction: 'Failed',
      phase: 'Extraction failed',
      step: 'Closing',
      diagnostic: 'ODB extraction failed. See extract.log.',
    }),
  )
  await expect(page.getByTestId('extraction-failed')).toBeVisible()
  await expect(page.getByRole('progressbar')).not.toHaveAttribute('aria-valuenow', '100')
  const failedBox = await withinCard(page, '[data-testid="extraction-failed"]')
  expect(failedBox!.bottom).toBeLessThanOrEqual(failedBox!.cardBottom + 1)
})

test('a short window scrolls the named progress region by keyboard', async ({ page }) => {
  // 1280x520 is below the smallest supported desktop height: the card keeps
  // status, progress, current step and warning visible, and the detail region
  // becomes a labelled, focusable scroller rather than a clipped card.
  await page.setViewportSize({ width: 1280, height: 520 })
  await mountLive(
    page,
    baseJob({ step: 'Body seating', step_time: 0.5, heartbeat: Date.now() / 1000 - 180 }),
  )
  const overflow = await cardOverflow(page)
  expect(overflow.scroll).toBeLessThanOrEqual(overflow.client + 1)
  const detail = page.getByTestId('progress-detail')
  await expect(detail).toHaveAttribute('role', 'region')
  await expect(detail).toHaveAttribute('tabindex', '0')
  const scrollable = await detail.evaluate((element) => element.scrollHeight > element.clientHeight)
  expect(scrollable).toBe(true)
  // The usable part of the scroller is not a one-line sliver.
  expect(await detail.evaluate((element) => element.clientHeight)).toBeGreaterThanOrEqual(40)
  await detail.focus()
  await page.keyboard.press('End')
  await page.keyboard.press('End')
  await expect
    .poll(async () => detail.evaluate((element) => element.scrollTop))
    .toBeGreaterThan(0)
  // The scroller reaches its own end, so the last fact's bottom edge is visible.
  await expect
    .poll(async () =>
      detail.evaluate((element) => element.scrollHeight - element.clientHeight - element.scrollTop),
    )
    .toBeLessThanOrEqual(1)
  // The scroller reached its end, so the last fact's bottom edge is visible.
  const atEnd = await page.evaluate(() => {
    const detail = document.querySelector('[data-testid="progress-detail"]') as HTMLElement
    const region = detail.getBoundingClientRect()
    const row = document.querySelector('[data-testid="progress-facts"] > div:last-child')!
      .getBoundingClientRect()
    return {
      end: detail.scrollTop + detail.clientHeight >= detail.scrollHeight - 1,
      bottomVisible: row.bottom <= region.bottom + 1,
    }
  })
  const metrics = await detail.evaluate((element) => ({
    top: element.scrollTop,
    client: element.clientHeight,
    scroll: element.scrollHeight,
  }))
  expect(atEnd, JSON.stringify(metrics)).toEqual({ end: true, bottomVisible: true })
  await expect(page.getByTestId('progress-current')).toBeVisible()
  await expect(page.getByTestId('stale-heartbeat')).toBeVisible()
})

// ---------------------------------------------------------------- Gate 2

test('a completed result gives the recovered height to the viewport and response panes', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Completed layout', example: true } })
  ).json()
  const { deck } = await meshAndDeck(request, revision)
  const run: Job = await (
    await request.post('/api/runs', {
      data: {
        revision: revision.id,
        deck: deck.id,
        token: randomUUID(),
        name: 'Completed layout run',
        mode: 'ABAQUS',
      },
    })
  ).json()
  await expect
    .poll(async () => ((await (await request.get('/api/jobs/' + run.id)).json()) as Job).status, {
      timeout: 90000,
    })
    .toBe('Completed')

  for (const size of [
    { width: 1280, height: 720 },
    { width: 1874, height: 762 },
  ]) {
    await page.setViewportSize(size)
    await page.goto('/#results/' + run.id)
    await expect(page.getByTestId('vtk-viewport')).toBeVisible()
    // The large progress card is gone on Results, and the compact completion
    // strip keeps the status and a Diagnostics link.
    await expect(page.getByTestId('run-complete')).toBeVisible()
    await expect(page.getByTestId('run-progress')).toHaveCount(0)
    await expect(page.getByTestId('open-diagnostics')).toBeVisible()

    const measured = await page.evaluate(() => {
      const box = (selector: string) => {
        const element = document.querySelector(selector)!.getBoundingClientRect()
        return { top: element.top, bottom: element.bottom, height: element.height }
      }
      return {
        grid: box('.result-grid'),
        viewport: box('.result-viewport'),
        playback: box('[data-testid="playback"]'),
        controls: box('[data-testid="result-controls"]'),
        aside: box('.result-grid > aside.card'),
        pageHeight: document.documentElement.scrollHeight,
      }
    })
    // The field pane grows with the recovered grid instead of staying pinned at
    // the reported 302/320 px clipping baseline.
    expect(measured.viewport.height, `${size.width}x${size.height} viewport`).toBeGreaterThan(315)
    expect(measured.grid.height, `${size.width}x${size.height} grid`).toBeGreaterThan(430)
    // The recovered height is used by the panes, not left as a blank strip:
    // the viewport ends exactly where playback begins, and playback is fully
    // visible inside the grid.
    expect(measured.playback.top - measured.viewport.bottom).toBeLessThanOrEqual(1)
    expect(measured.playback.bottom).toBeLessThanOrEqual(measured.grid.bottom + 1)
    expect(measured.aside.height).toBeGreaterThanOrEqual(measured.grid.height - 1)
    // Playback and the force response stay reachable and are drawn.
    await expect(page.getByTestId('playback')).toBeVisible()
    await expect(page.getByTestId('force-caption')).toBeVisible()
    // The remaining display controls are reachable by scrolling the field card.
    await page.locator('.result-grid > section.card').evaluate((element) => {
      element.scrollTop = element.scrollHeight
    })
    const controlsVisible = await page.evaluate(() => {
      const card = document.querySelector('.result-grid > section.card')!.getBoundingClientRect()
      const controls = document
        .querySelector('[data-testid="result-controls"]')!
        .getBoundingClientRect()
      return controls.bottom <= card.bottom + 1 && controls.top >= card.top - 1
    })
    expect(controlsVisible).toBe(true)
    // The response pane scrolls; its export action is reachable at the bottom.
    await page.locator('.result-grid > aside.card').evaluate((element) => {
      element.scrollTop = element.scrollHeight
    })
    await expect(page.getByTestId('export-curve')).toBeVisible()
    // Camera stays put while playback and resizing run.
    const camera = () => page.locator('.seal-vtk-host').getAttribute('data-camera')
    const before = await camera()
    await page.getByTestId('playback').getByRole('button').first().click()
    await page.waitForTimeout(700)
    await page.getByTestId('playback').getByRole('button').first().click()
    expect(await camera()).toBe(before)

    // Diagnostics still shows the full live card, including solver/extraction
    // facts and the DEMO/provenance distinction.
    await page.goto('/#diagnostics/' + run.id)
    await expect(page.getByTestId('run-progress')).toBeVisible()
    await expect(page.getByTestId('run-complete')).toHaveCount(0)
    const diagnosticsOverflow = await cardOverflow(page)
    expect(diagnosticsOverflow.scroll).toBeLessThanOrEqual(diagnosticsOverflow.client + 1)
    await page.goto('/#results/' + run.id)
    await expect(page.getByTestId('run-complete')).toBeVisible()
  }
})
