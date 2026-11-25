/**
 * Portability and history for the resampled exports.
 *
 * A live licensed result and the same `.aqresult` reopened in a disposable root
 * must produce numerically identical bytes for matching selections and
 * settings. Opening/exporting must never rewrite the immutable package, its
 * frames or the original `history.csv`.
 *
 * Live comparison is opt-in:
 *   SEAL_LIVE_BASE=http://127.0.0.1:<port> SEAL_LIVE_JOB=<retained job id>
 *   SEAL_LICENSED_AQRESULT=<same job's .aqresult>
 */
import { createHash, randomUUID } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test, type Page } from './fixtures'
import { meshAndDeck } from './pipeline'
import type { Job } from '../src/api'

const AQRESULT =
  process.env.SEAL_LICENSED_AQRESULT ??
  resolve(process.cwd(), '../../.local/gate-c/results/Door-pressure-licensed-Door-pressure-licensed-20261125-221400-9efc065a.aqresult')
const LIVE_BASE = process.env.SEAL_LIVE_BASE
const LIVE_JOB = process.env.SEAL_LIVE_JOB

function digest(path: string) {
  return createHash('sha256').update(readFileSync(path)).digest('hex')
}

async function download(page: Page, testid: string) {
  const pending = page.waitForEvent('download')
  await page.getByTestId(testid).click()
  const file = await pending
  return readFileSync((await file.path())!, 'utf8')
}

async function seekLast(page: Page) {
  const slider = page.locator('.playback-slider')
  const maximum = await slider.evaluate((element) => Number((element as HTMLInputElement).max))
  await slider.evaluate((element, value) => {
    const input = element as HTMLInputElement
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(
      input,
      String(value),
    )
    input.dispatchEvent(new Event('input', { bubbles: true }))
    input.dispatchEvent(new Event('change', { bubbles: true }))
  }, maximum)
  return maximum
}

async function bothDownloads(page: Page, base: string, job: string) {
  await page.goto(base + '/#results/' + job)
  await expect(page.getByTestId('run-complete')).toBeVisible({ timeout: 90000 })
  await expect(page.getByTestId('pressure-chart')).toBeVisible({ timeout: 60000 })
  await page.getByTestId('stroke-interval').fill('0.65')
  const load = await download(page, 'export-curve')
  await seekLast(page)
  const pressure = await download(page, 'export-pressure')
  return { load, pressure }
}

test.describe('live result and reopened package', () => {
  test.skip(
    !LIVE_BASE || !LIVE_JOB || !existsSync(AQRESULT),
    'SEAL_LIVE_BASE / SEAL_LIVE_JOB / SEAL_LICENSED_AQRESULT are not all set',
  )

  test('matching settings produce byte-identical CSVs', async ({ page, request }) => {
    const before = digest(AQRESULT)
    // Live evidence is read from the configured live-copy origin, never from the
    // local test server: a 404 whose body happens to match would otherwise pass.
    const liveIndexResponse = await request.get(
      LIVE_BASE + '/api/jobs/' + LIVE_JOB + '/artifacts/results.json',
    )
    expect(liveIndexResponse.status()).toBe(200)
    const liveHistoryResponse = await request.get(
      LIVE_BASE + '/api/jobs/' + LIVE_JOB + '/artifacts/history.csv',
    )
    expect(liveHistoryResponse.status()).toBe(200)
    const liveIndexText = await liveIndexResponse.text()
    const liveHistoryText = await liveHistoryResponse.text()
    expect(liveIndexText.length).toBeGreaterThan(100)
    expect(JSON.parse(liveIndexText).frames.length).toBeGreaterThan(0)
    expect(liveHistoryText.split(/\r?\n/).length).toBeGreaterThan(2)
    const live = await bothDownloads(page, LIVE_BASE!, LIVE_JOB!)
    const opened: Job = await (
      await request.post('/api/files/result/open', { data: { path: AQRESULT } })
    ).json()
    expect(opened.id).not.toBe(LIVE_JOB)
    const reopened = await bothDownloads(page, '', opened.id)
    expect(reopened.load).toBe(live.load)
    expect(reopened.pressure).toBe(live.pressure)
    // The immutable package, the retained result index and history.csv are
    // byte-identical after both reads and downloads.
    expect(digest(AQRESULT)).toBe(before)
    const afterIndex = await request.get(
      LIVE_BASE + '/api/jobs/' + LIVE_JOB + '/artifacts/results.json',
    )
    const afterHistory = await request.get(
      LIVE_BASE + '/api/jobs/' + LIVE_JOB + '/artifacts/history.csv',
    )
    expect(afterIndex.status()).toBe(200)
    expect(afterHistory.status()).toBe(200)
    expect(await afterIndex.text()).toBe(liveIndexText)
    expect(await afterHistory.text()).toBe(liveHistoryText)
  })
})

test('a legacy load-only result exports load and explains missing pressure', async ({
  page,
  request,
}) => {
  const revision = await (
    await request.post('/api/projects', { data: { name: 'Legacy load only', example: true } })
  ).json()
  const { deck } = await meshAndDeck(request, revision)
  const run: Job = await (
    await request.post('/api/runs', {
      data: {
        revision: revision.id,
        deck: deck.id,
        token: randomUUID(),
        name: 'Legacy load only run',
        mode: 'ABAQUS',
      },
    })
  ).json()
  await expect
    .poll(async () => ((await (await request.get('/api/jobs/' + run.id)).json()) as Job).status, {
      timeout: 90000,
    })
    .toBe('Completed')
  // Remove the pressure metadata from the transport only; solver artifacts and
  // the on-disk index are untouched.
  const index = await (
    await request.get('/api/jobs/' + run.id + '/artifacts/results.json')
  ).json()
  const legacy = structuredClone(index)
  delete legacy.door_pressure
  legacy.door_pressure = null
  // A retained result whose force is in N but whose represented width is the
  // old solver thickness: the label must be F (N), never a borrowed 100 mm.
  legacy.reporting_width_basis = 'legacy_thickness'
  legacy.force_basis = 'legacy_unscaled'
  legacy.force_normalization = 'total'
  legacy.force_unit = 'N'
  delete legacy.reporting_width_mm
  await page.route('**/results.json', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(legacy) }),
  )
  await page.goto('/#results/' + run.id)
  await expect(page.getByRole('heading', { name: 'Force–displacement' })).toBeVisible()
  await expect(page.getByTestId('pressure-unavailable')).toBeVisible()
  const csv = await download(page, 'export-curve')
  const rows = csv.trim().split(/\r?\n/)
  expect(rows).toHaveLength(2)
  expect(rows[0].startsWith('stroke(mm),')).toBeTruthy()
  // A legacy total force with unknown represented width is named F (N), and the
  // values are never rescaled a second time.
  expect(rows[1].startsWith('F (N),')).toBe(true)
})
