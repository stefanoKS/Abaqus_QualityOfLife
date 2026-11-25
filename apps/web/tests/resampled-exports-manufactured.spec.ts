/**
 * Manufactured resampling cases: invalid intervals, multivalued curves and the
 * recorded force basis. These run without a licensed package; only the results
 * index transport is modified in the browser route.
 */
import { randomUUID } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { expect, test } from './fixtures'
import { meshAndDeck } from './pipeline'
import type { Job, Revision } from '../src/api'

async function completedRun(
  request: import('@playwright/test').APIRequestContext,
  revision: Revision,
  name: string,
) {
  const { deck } = await meshAndDeck(request, revision)
  const run: Job = await (
    await request.post('/api/runs', {
      data: {
        revision: revision.id,
        deck: deck.id,
        token: randomUUID(),
        name,
        mode: 'ABAQUS',
      },
    })
  ).json()
  await expect
    .poll(async () => ((await (await request.get('/api/jobs/' + run.id)).json()) as Job).status, {
      timeout: 90000,
    })
    .toBe('Completed')
  return run
}

async function exportLoad(page: import('@playwright/test').Page) {
  const pending = page.waitForEvent('download')
  await page.getByTestId('export-curve').click()
  const download = await pending
  return {
    rows: readFileSync((await download.path())!, 'utf8').trim().split(/\r?\n/).map((line) => line.split(',')),
    name: download.suggestedFilename(),
  }
}

test('invalid intervals are refused and a multivalued curve falls back to ordered samples', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Resample guard', example: true } })
  ).json()
  const run = await completedRun(request, revision, 'Resample guard run')
  await page.goto('/#results/' + run.id)
  await expect(page.getByRole('heading', { name: 'Force–displacement' })).toBeVisible()

  const interval = page.getByTestId('stroke-interval')
  for (const value of ['', '0', '-1', '1e-12']) {
    await interval.fill(value)
    await expect(page.getByTestId('load-export-issue')).toBeVisible()
    await expect(page.getByTestId('export-curve')).toBeDisabled()
  }
  await interval.fill('1')
  await expect(page.getByTestId('export-curve')).toBeEnabled()
  const plain = await exportLoad(page)
  expect(plain.rows).toHaveLength(2)
  expect(plain.rows[0][0]).toBe('stroke(mm)')

  // Repeat the first nonzero stroke with a materially different load: the
  // uniform grid is ambiguous and must not average or sort it silently.
  const index = await (
    await request.get('/api/jobs/' + run.id + '/artifacts/results.json')
  ).json()
  const doubled = structuredClone(index)
  const closing = doubled.history.filter(
    (row: { step_id?: string }) => row.step_id === 'closing',
  )
  expect(closing.length).toBeGreaterThan(4)
  const source = closing.find(
    (row: { u2?: number | null; force?: number | null }) =>
      row.u2 !== null && row.force !== null && Math.abs(row.u2) > 0.5,
  )
  doubled.history.push({ ...structuredClone(source), time: source.time + 0.001, force: source.force + 5 })
  await page.unroute('**/results.json')
  await page.route('**/results.json', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: { 'cache-control': 'no-store' },
      body: JSON.stringify(doubled),
    }),
  )
  await page.reload()
  await expect(page.getByTestId('load-export-issue')).toContainText(
    'more than one measured load at the same stroke',
  )
  await expect(page.getByTestId('export-curve')).toBeDisabled()
  await page.getByTestId('load-sampling').selectOption('original')
  await expect(page.getByTestId('export-curve')).toBeEnabled()
  const ordered = await exportLoad(page)
  expect(ordered.rows[0].length).toBe(doubled.history.filter((row: { step_id?: string }) => row.step_id === 'closing').length + 1)
})

test('identical repeated strokes coalesce and the uniform grid stays unambiguous', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Repeat coalesce', example: true } })
  ).json()
  const run = await completedRun(request, revision, 'Repeat coalesce run')
  const index = await (
    await request.get('/api/jobs/' + run.id + '/artifacts/results.json')
  ).json()
  const modified = structuredClone(index)
  const closing = modified.history.filter(
    (row: { step_id?: string }) => row.step_id === 'closing',
  )
  const source = closing.find(
    (row: { u2?: number | null; force?: number | null }) =>
      row.u2 !== null && row.force !== null && Math.abs(row.u2) > 0.5,
  )
  modified.history.push({ ...structuredClone(source), time: source.time + 0.001 })
  await page.route('**/results.json', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(modified),
    }),
  )
  await page.goto('/#results/' + run.id)
  await expect(page.getByRole('heading', { name: 'Force–displacement' })).toBeVisible()
  await expect(page.getByTestId('load-export-issue')).toHaveCount(0)
  const exported = await exportLoad(page)
  expect(exported.rows).toHaveLength(2)
})

test('the export names the recorded width and unit without rescaling', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Basis labels', example: true } })
  ).json()
  const run = await completedRun(request, revision, 'Basis labels run')
  const base = await (
    await request.get('/api/jobs/' + run.id + '/artifacts/results.json')
  ).json()
  const width = structuredClone(base)
  width.reporting_width_mm = 80
  width.force_basis = 'total_width'
  width.reporting_width_basis = 'default_100_mm'
  width.force_normalization = 'total'
  width.force_unit = 'N'
  const original = base.history.map(
    (row: { step_id?: string; force?: number | null }) => row.force,
  )
  await page.route('**/results.json', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(width),
    }),
  )
  await page.goto('/#results/' + run.id)
  await expect(page.getByRole('heading', { name: 'Force–displacement' })).toBeVisible()
  await page.getByTestId('load-sampling').selectOption('original')
  const eighty = await exportLoad(page)
  expect(eighty.rows[1][0]).toBe('F (N/80mm)')
  expect(eighty.name).toContain('W80mm')
  // The same stored forces are written, not multiplied by 0.8 again.
  expect(eighty.rows[1].slice(1)).toEqual(
    original.filter((value: number | null) => value !== null).map((value: number) => String(Number(value.toPrecision(12)))),
  )

  await page.unroute('**/results.json')
  const perMm = structuredClone(base)
  perMm.reporting_width_mm = 1
  perMm.force_normalization = 'per_mm'
  perMm.force_unit = 'N/mm'
  perMm.force_basis = 'per_mm'
  await page.route('**/results.json', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(perMm),
    }),
  )
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Force–displacement' })).toBeVisible()
  await page.getByTestId('load-sampling').selectOption('original')
  const mm = await exportLoad(page)
  expect(mm.rows[1][0]).toBe('F (N/mm)')
  expect(mm.name).toContain('per-mm')
})
