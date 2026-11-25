/** Gate 3/4 and partial-opening browser acceptance on manufactured results.
 *
 * The `.aqresult` fixtures are written by
 * `scripts/manufactured_result_fixtures.py` and are explicitly labelled as
 * manufactured test evidence. They exercise display behaviour only.
 */
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { test, expect, type Page } from './fixtures'
import type { Job } from '../src/api'

const here = fileURLToPath(new URL('.', import.meta.url))
const root = resolve(here, '../../..')
const python =
  process.env.SEAL_TEST_PYTHON || join(root, '.venv', 'Scripts', 'python.exe')
let folder = ''

test.beforeAll(() => {
  folder = mkdtempSync(join(tmpdir(), 'aqol-manufactured-'))
  execFileSync(python, [
    join(root, 'scripts', 'manufactured_result_fixtures.py'),
    '--folder',
    folder,
  ])
})

async function openFixture(
  request: import('@playwright/test').APIRequestContext,
  name: string,
) {
  const response = await request.post('/api/files/result/open', {
    data: { path: join(folder, name + '.aqresult') },
  })
  expect(response.ok()).toBeTruthy()
  return (await response.json()) as Job
}

type Projection = {
  origin: [number, number]
  ax: [number, number, number]
  ay: [number, number, number]
  dpr: number
  width: number
  height: number
  modelPerPixel: number
}

async function projectionOf(page: Page): Promise<Projection> {
  const host = page.locator('.seal-vtk-host')
  await expect
    .poll(async () => host.getAttribute('data-projection'))
    .not.toBeNull()
  return JSON.parse((await host.getAttribute('data-projection'))!) as Projection
}

function project(p: Projection, x: number, y: number): [number, number] {
  // Independent affine projection from the exposed camera basis (CSS pixels).
  return [
    p.origin[0] + p.ax[0] * x + p.ay[0] * y,
    p.origin[1] + p.ax[1] * x + p.ay[1] * y,
  ]
}

async function geometry(page: Page) {
  const host = page.locator('.seal-vtk-host')
  await expect
    .poll(async () => host.getAttribute('data-pressure-geometry'))
    .not.toBe('')
  return JSON.parse((await host.getAttribute('data-pressure-geometry'))!) as {
    tail: [number, number]
    tip: [number, number]
    lengthPx: number
    lengthMm: number
    pressureKpa: number
    mode: string
  }
}

function downloadText(page: Page, testId: string) {
  return Promise.all([
    page.waitForEvent('download'),
    page.getByTestId(testId).click(),
  ]).then(async ([download]) => ({
    name: download.suggestedFilename(),
    text: readFileSync((await download.path())!, 'utf8'),
  }))
}

test('manual arrow geometry is physical and the multiplier scales it once', async ({
  page,
  request,
}) => {
  const job = await openFixture(request, 'arrows')
  await page.goto('/#results/' + job.id)
  await expect(page.getByTestId('arrow-controls')).toBeVisible()
  await page.getByTestId('arrow-mode').selectOption('manual')
  await expect(page.getByTestId('arrow-manual-mm')).toHaveValue('5')

  let projection = await projectionOf(page)
  let geom = await geometry(page)
  const tail = project(projection, 2, 3)
  const tip = project(projection, 5, 7)
  expect(Math.hypot(geom.tail[0] - tail[0], geom.tail[1] - tail[1])).toBeLessThan(1)
  expect(Math.hypot(geom.tip[0] - tip[0], geom.tip[1] - tip[1])).toBeLessThan(1)
  expect(geom.lengthMm).toBeCloseTo(5, 6)
  expect(geom.pressureKpa).toBeCloseTo(10, 6)

  // ×2: 10 kPa becomes 20 kPa, so the same calibration doubles the length.
  await page.getByTestId('result-multiplier-input').fill('2')
  await page.getByTestId('result-multiplier-input').blur()
  geom = await geometry(page)
  projection = await projectionOf(page)
  const doubled = project(projection, 8, 11)
  expect(geom.pressureKpa).toBeCloseTo(20, 6)
  expect(geom.lengthMm).toBeCloseTo(10, 6)
  expect(
    Math.hypot(geom.tip[0] - doubled[0], geom.tip[1] - doubled[1]),
  ).toBeLessThan(1)

  // Automatic mode keeps a constant screen length through zoom, responds to a
  // viewport resize, and doubles with ×2.
  await page.getByTestId('multiplier-reset').click()
  await page.getByTestId('arrow-mode').selectOption('auto')
  geom = await geometry(page)
  const autoLength = geom.lengthPx
  expect(autoLength).toBeGreaterThan(23.5)
  await page.getByRole('button', { name: /Zoom in|æ‹¡å¤§/ }).click()
  await expect
    .poll(async () => (await geometry(page)).lengthPx)
    .toBeCloseTo(autoLength, 1)
  const host = page.locator('.seal-vtk-host')
  const beforePx = Number(await host.getAttribute('data-pressure-auto-px'))
  await page.setViewportSize({ width: 1440, height: 340 })
  await expect
    .poll(async () => Number(await host.getAttribute('data-pressure-auto-px')))
    .not.toBe(beforePx)
  const resized = await geometry(page)
  expect(resized.lengthPx).toBeLessThan(autoLength)
  await page.getByTestId('result-multiplier-input').fill('2')
  await page.getByTestId('result-multiplier-input').blur()
  const autoDoubled = await geometry(page)
  expect(autoDoubled.lengthPx).toBeCloseTo(resized.lengthPx * 2, 1)

  // Off removes shafts and the scale key, leaves the graph usable and survives
  // playback and a step change.
  await page.getByTestId('pressure-arrows-toggle').uncheck()
  await expect(page.locator('.seal-vtk-host')).toHaveAttribute(
    'data-pressure-arrows',
    '0',
  )
  await expect(page.locator('.seal-vtk-host')).toHaveAttribute(
    'data-pressure-geometry',
    '',
  )
  await expect(page.getByTestId('pressure-chart')).toBeVisible()
  await expect(page.getByTestId('pressure-scale')).toHaveCount(0)
  await page.getByTestId('playback').getByRole('button').first().click()
  await page.waitForTimeout(600)
  await expect(page.locator('.seal-vtk-host')).toHaveAttribute(
    'data-pressure-arrows',
    '0',
  )
  await page.getByTestId('pressure-arrows-toggle').check()
  await expect(page.locator('.seal-vtk-host')).toHaveAttribute(
    'data-pressure-mode',
    'auto',
  )
})

test('DPR 2 keeps the same physical manual arrow geometry', async ({
  browser,
  request,
}) => {
  const job = await openFixture(request, 'arrows')
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 2,
  })
  await context.addInitScript(() => {
    window.localStorage.setItem('abaqus-qol.language', 'en')
  })
  const page = await context.newPage()
  await page.goto('/#results/' + job.id)
  await page.getByTestId('arrow-mode').selectOption('manual')
  const projection = await projectionOf(page)
  expect(projection.dpr).toBe(2)
  const geom = await geometry(page)
  const tip = project(projection, 5, 7)
  expect(
    Math.hypot(geom.tip[0] - tip[0], geom.tip[1] - tip[1]),
  ).toBeLessThan(1)
  expect(geom.lengthMm).toBeCloseTo(5, 6)
  await context.close()
})

test('quantities, colours, probes and exports apply the factor once', async ({
  page,
  request,
}) => {
  const job = await openFixture(request, 'arrows')
  await page.goto('/#results/' + job.id)

  // ×1 retained: the displayed force starts at the measured 8 N.
  await page.getByTestId('result-multiplier-input').fill('2')
  await page.getByTestId('result-multiplier-input').blur()
  await expect(page.getByTestId('multiplier-active')).toContainText('2')
  await expect(page.getByTestId('force-caption')).toContainText('×2')

  // An unsaturated von Mises sample changes colour at ×2 while the Auto
  // reference stays the unscaled run maximum.
  await page.getByTestId('multiplier-reset').click()
  await page.getByLabel('Range mode').selectOption('auto')
  await page.getByLabel('Field').selectOption('mises')
  await expect(page.getByTestId('range-summary')).toContainText('0.2')
  const host = page.locator('.seal-vtk-host')
  await expect
    .poll(async () => {
      const raw = await host.getAttribute('data-field-sample')
      return raw ? JSON.parse(raw).maximum : null
    })
    .toBeCloseTo(0.2, 6)
  const before = JSON.parse(
    (await host.getAttribute('data-field-sample'))!,
  ) as { value: number; maximum: number; ratio: number; color: number[] }
  expect(before.value).toBeCloseTo(0.1, 6)
  expect(before.maximum).toBeCloseTo(0.2, 6)
  expect(before.ratio).toBeCloseTo(0.5, 3)
  await page.getByTestId('result-multiplier-input').fill('2')
  await page.getByTestId('result-multiplier-input').blur()
  const scaled = JSON.parse(
    (await host.getAttribute('data-field-sample'))!,
  ) as { value: number; maximum: number; ratio: number; color: number[] }
  expect(scaled.maximum).toBeCloseTo(0.2, 6)
  expect(scaled.value).toBeCloseTo(0.2, 6)
  expect(scaled.color).not.toEqual(before.color)

  // Export files carry the factor exactly once and a marker in the name.
  await page.getByTestId('stroke-interval').fill('1')
  const doubled = await downloadText(page, 'export-curve')
  expect(doubled.name).toContain('-x2')
  expect(doubled.text.split(/\r?\n/)[1]).toBe('F (N) ×2,16,24')
  await page.getByTestId('multiplier-reset').click()
  const reset = await downloadText(page, 'export-curve')
  expect(reset.name).not.toContain('-x2')
  expect(reset.text.split(/\r?\n/)[1]).toBe('F (N),8,12')

  // ×0 displays zero for measured responses; missing stays missing.
  await page.getByTestId('result-multiplier-input').fill('0')
  await page.getByTestId('result-multiplier-input').blur()
  const zero = await downloadText(page, 'export-curve')
  expect(zero.name).toContain('-x0')
  expect(zero.text.split(/\r?\n/)[1]).toBe('F (N) ×0,0,0')

  // ×0.5 is a normal factor, not an error.
  await page.getByTestId('result-multiplier-input').fill('0.5')
  await page.getByTestId('result-multiplier-input').blur()
  const half = await downloadText(page, 'export-curve')
  expect(half.name).toContain('-x0.5')
  expect(half.text.split(/\r?\n/)[1]).toBe('F (N) ×0.5,4,6')

  // Invalid values are rejected with a reason and the last valid factor stays.
  await page.getByTestId('result-multiplier-input').fill('-2')
  await expect(page.getByTestId('multiplier-error')).toBeVisible()
  await expect(page.getByTestId('multiplier-active')).toContainText('0.5')

  // CNORMF components and magnitude scale once; the probe names both.
  await page.getByTestId('result-multiplier-input').fill('2')
  await page.getByTestId('result-multiplier-input').blur()
  await page.getByLabel('Field').selectOption('CNormf')
  const projection = await projectionOf(page)
  const node = project(projection, 2, 3)
  await page
    .locator('.seal-vtk-host')
    .click({ position: { x: node[0], y: node[1] } })
  await expect(page.locator('.legend')).toContainText('|CNORMF| 10')
  await expect(page.locator('.legend')).toContainText('Fx 6')
  await expect(page.locator('.legend')).toContainText('Fy 8')

  // Door pressure export also carries the factor once.
  const pressure = await downloadText(page, 'export-pressure')
  expect(pressure.name).toContain('-x2')
  expect(pressure.text.split(/\r?\n/)[1]).toContain('20')
})

test('missing stroke and station arrays stay gaps and disable spatial export', async ({
  page,
  request,
}) => {
  const job = await openFixture(request, 'gaps')
  await page.goto('/#results/' + job.id)
  await expect(page.getByTestId('pressure-stations-unavailable')).toBeVisible()
  await expect(page.getByTestId('export-pressure')).toBeDisabled()

  await page.getByTestId('stroke-interval').fill('1')
  const uniform = await downloadText(page, 'export-curve')
  expect(uniform.text.split(/\r?\n/)[1]).toBe('F (N),0,,40')

  await page.getByTestId('load-sampling').selectOption('original')
  const original = await downloadText(page, 'export-curve')
  expect(original.text.split(/\r?\n/)[0]).toBe('stroke(mm),0,,2')
  expect(original.text.split(/\r?\n/)[1]).toBe('F (N),0,123,40')

  await page.getByTestId('result-multiplier-input').fill('2')
  await page.getByTestId('result-multiplier-input').blur()
  await page.getByTestId('load-sampling').selectOption('uniform')
  const scaled = await downloadText(page, 'export-curve')
  expect(scaled.text.split(/\r?\n/)[1]).toBe('F (N) ×2,0,,80')
})

test('a partial result opens on its last saved frame through File Open', async ({
  page,
}) => {
  await page.goto('/#dashboard')
  await expect(page.getByTestId('file-bar')).toBeVisible()
  await page.getByTestId('file-open-result').click()
  await page
    .getByTestId('file-bar')
    .getByLabel(/Result file|çµæžœãƒ•ã‚¡ã‚¤ãƒ«/)
    .fill(join(folder, 'partial.aqresult'))
  await page
    .getByTestId('file-bar')
    .getByRole('button', { name: /^Open$|^é–‹ã$/ })
    .click()

  await expect(page.getByTestId('partial-notice')).toBeVisible()
  await expect(page.getByTestId('partial-step')).toContainText('Closing')
  await expect(page.getByTestId('partial-frame')).toContainText('2')
  await expect(page.getByTestId('partial-time')).toContainText('0.600')
  await expect(page.getByTestId('partial-diagnostic')).toContainText(
    'Manufactured solver failure',
  )
  await expect(page.locator('.badge[data-status="Failed"]')).toBeVisible()
  await expect(page.getByTestId('frame-count')).toHaveText('3 / 3')
  await expect(page.getByTestId('frame-time')).toHaveText('0.600 s')
  await expect(page.getByTestId('run-complete')).toHaveCount(0)

  // Earlier saved frames remain available and the selection survives a visit to
  // Diagnostics.
  await page.locator('.playback-slider').fill('0')
  await expect(page.getByTestId('frame-count')).toHaveText('1 / 3')
  await page.getByTestId('open-diagnostics').click()
  await expect(page.locator('.error-text').first()).toContainText(
    'Manufactured solver failure',
  )
  await page.goBack()
  await expect(page.getByTestId('frame-count')).toHaveText('1 / 3', {
    timeout: 20000,
  })

  // The dashboard and the workspace expose the same partial result.
  await page.goto('/#dashboard')
  await expect(
    page.getByTestId('open-partial-results').first(),
  ).toBeVisible()
})

test('a two-panel failure before Closing selects the body step curve', async ({
  page,
  request,
}) => {
  const job = await openFixture(request, 'partial-body')
  await page.goto('/#results/' + job.id)
  await expect(page.getByTestId('partial-notice')).toBeVisible()
  await expect(page.getByTestId('partial-step')).toContainText('Body seating')
  await expect(page.getByTestId('frame-count')).toHaveText('1 / 1')
  // The curve belongs to the displayed step; the planned Closing step is
  // present in the selector but is not presented as having data.
  const select = page.getByTestId('curve-step')
  await expect(select).toHaveValue('bodyseating')
  await expect(page.getByTestId('selected-step')).toContainText('Body seating')
  await expect(page.getByTestId('force-caption')).toContainText('Body panel travel')
  await expect(select.locator('option', { hasText: 'Closing' })).toHaveCount(1)
})

test('the new controls are localized and fit a short Japanese window', async ({
  browser,
  request,
}) => {
  const job = await openFixture(request, 'arrows')
  // No English init script: Japanese is the product default.
  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 },
  })
  const page = await context.newPage()
  await page.goto('/#results/' + job.id)
  await expect(page.getByText('接触圧の矢印').first()).toBeVisible()
  await expect(page.getByLabel('結果倍率')).toBeVisible()
  await page.getByTestId('arrow-mode').selectOption('manual')
  await expect(page.getByTestId('arrow-mode')).toHaveValue('manual')
  await expect(
    page.getByTestId('arrow-mode').locator('option:checked'),
  ).toHaveText('手動（モデル mm）')
  await expect(page.getByTestId('arrow-manual-mm')).toBeVisible()
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
    )
    .toBe(true)
  await context.close()
})


