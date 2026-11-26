/**
 * Gate 6: pressure, arrows, probe, chart and CSV bind by FE node identity.
 *
 * The manufactured `permuted` fixture stores its samples in native order
 * [2, 1] while the profile station axis is [1, 2]. A positional consumer shows
 * 10 kPa on node 1; the verified behaviour shows 0 kPa on node 1 and 10 kPa on
 * node 2, with the single arrow anchored to node 2.
 */
import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test, type Page } from './fixtures'
import type { Job } from '../src/api'

const here = fileURLToPath(new URL('.', import.meta.url))
const root = resolve(here, '../../..')
const python = process.env.SEAL_TEST_PYTHON || join(root, '.venv', 'Scripts', 'python.exe')
let folder = ''

test.beforeAll(() => {
  folder = mkdtempSync(join(tmpdir(), 'aqol-pressure-identity-'))
  execFileSync(python, [
    join(root, 'scripts', 'manufactured_result_fixtures.py'),
    '--folder',
    folder,
  ])
})

async function open(request: import('@playwright/test').APIRequestContext, name: string) {
  const response = await request.post('/api/files/result/open', {
    data: { path: join(folder, name + '.aqresult') },
  })
  expect(response.ok()).toBeTruthy()
  return (await response.json()) as Job
}

async function plotPoint(page: Page, x: number, y: number) {
  return page.evaluate(
    ({ x, y }) => {
      const element = document.querySelector(
        '[data-testid="pressure-chart"] .js-plotly-plot',
      ) as unknown as {
        _fullLayout: {
          xaxis: { _offset: number; _length: number; range: number[] }
          yaxis: { _offset: number; _length: number; range: number[] }
        }
        getBoundingClientRect: () => DOMRect
      }
      const layout = element._fullLayout
      const xa = layout.xaxis
      const ya = layout.yaxis
      const rect = element.getBoundingClientRect()
      return {
        x: rect.left + xa._offset + (xa._length * (x - xa.range[0])) / (xa.range[1] - xa.range[0]),
        y:
          rect.top +
          ya._offset +
          ya._length * (1 - (y - ya.range[0]) / (ya.range[1] - ya.range[0])),
      }
    },
    { x, y },
  )
}

async function download(page: Page) {
  const [event] = await Promise.all([
    page.waitForEvent('download'),
    page.getByTestId('export-pressure').click(),
  ])
  return readFileSync((await event.path())!, 'utf8')
}

test('native sample order is mapped to the profile station by node identity', async ({
  page,
  request,
}) => {
  test.setTimeout(120000)
  const job = await open(request, 'permuted')
  await page.goto('/#results/' + job.id)
  const chart = page.getByTestId('pressure-chart')
  await expect(chart).toBeVisible({ timeout: 30000 })
  await expect(chart).toHaveAttribute('data-samples', '2')
  await expect(chart).toHaveAttribute('data-positive', '1')
  await expect(chart).toHaveAttribute('data-gaps', '0')
  await expect(page.getByTestId('pressure-profile-basis')).toContainText('PANEL')
  await chart.scrollIntoViewIfNeeded()

  // Station 0 is node 1 measured 0 kPa; station 3 is node 2 measured 10 kPa.
  const first = await plotPoint(page, 0, 0)
  await page.mouse.click(first.x, first.y)
  const readout = page.getByTestId('pressure-readout')
  await expect(readout).toHaveAttribute('data-node', '1', { timeout: 10000 })
  await expect.poll(async () => Number(await readout.getAttribute('data-station'))).toBe(0)
  await expect.poll(async () => Number(await readout.getAttribute('data-pressure'))).toBe(0)
  await expect.poll(async () => Number(await readout.getAttribute('data-fx'))).toBe(0)
  const second = await plotPoint(page, 2.8, 9.9)
  await page.mouse.move(second.x, second.y, { steps: 8 })
  await expect(readout).toHaveAttribute('data-node', '2')
  await expect.poll(async () => Number(await readout.getAttribute('data-station'))).toBe(3)
  await expect.poll(async () => Number(await readout.getAttribute('data-pressure'))).toBe(10)
  await expect
    .poll(async () => Number(await readout.getAttribute('data-native-mpa')))
    .toBeCloseTo(0.01, 12)
  await expect.poll(async () => Number(await readout.getAttribute('data-fx'))).toBeCloseTo(3, 9)
  await expect.poll(async () => Number(await readout.getAttribute('data-fy'))).toBeCloseTo(4, 9)

  // Only node 2 carries a nonzero pressure, so the single arrow is anchored at
  // its undeformed point (2,3) with the measured (3,4) N direction. The manual
  // calibration is 10 kPa = 5 mm, so the model-space length is 5 mm.
  const host = page.locator('.seal-vtk-host')
  await expect(host).toHaveAttribute('data-pressure-node', '2')
  await page.getByTestId('arrow-mode').selectOption('manual')
  await expect(page.getByTestId('arrow-manual-mm')).toHaveValue('5')
  await expect
    .poll(async () => (await host.getAttribute('data-pressure-geometry')) ?? '')
    .not.toBe('')
  const geometry = JSON.parse((await host.getAttribute('data-pressure-geometry'))!) as {
    tail: [number, number]
    tip: [number, number]
    lengthMm: number
  }
  expect(geometry.lengthMm).toBeCloseTo(5, 6)
  const tailPx = geometry.tail
  const tipPx = geometry.tip
  const pixelLength = Math.hypot(tipPx[0] - tailPx[0], tipPx[1] - tailPx[1])
  expect(pixelLength).toBeGreaterThan(1)
  const direction = (await host.getAttribute('data-pressure-direction'))!
    .split(',')
    .map(Number)
  expect(direction[0]).toBeCloseTo(0.6, 9)
  expect(direction[1]).toBeCloseTo(0.8, 9)
  // Screen vector follows the measured physical direction (screen Y is down).
  expect((tipPx[0] - tailPx[0]) / pixelLength).toBeCloseTo(0.6, 2)
  expect((tipPx[1] - tailPx[1]) / pixelLength).toBeCloseTo(-0.8, 2)

  // The two-row CSV is emitted from the same mapped samples. Original sampling
  // makes the two measured stations explicit.
  await page.getByTestId('pressure-sampling').selectOption('original')
  const csv = await download(page)
  expect(csv.trim().split(/\r?\n/)).toEqual([
    'door station(mm),0,3',
    'CPRESS (kPa),0,10',
  ])

  // The single multiplier scales pressure, arrow and CSV exactly once.
  await page.getByTestId('result-multiplier-input').fill('2')
  await page.getByTestId('result-multiplier-input').press('Tab')
  await expect.poll(async () => (await host.getAttribute('data-pressure-geometry'))!).toContain(
    '"lengthMm":10',
  )
  const doubled = JSON.parse((await host.getAttribute('data-pressure-geometry'))!) as {
    tail: [number, number]
    tip: [number, number]
  }
  const doubledPixels = Math.hypot(
    doubled.tip[0] - doubled.tail[0],
    doubled.tip[1] - doubled.tail[1],
  )
  expect(doubledPixels / pixelLength).toBeCloseTo(2, 2)
  const scaled = await download(page)
  expect(scaled.trim().split(/\r?\n/)).toEqual(['door station(mm),0,3', 'CPRESS (kPa) ×2,0,20'])
})

test('duplicate or foreign identity suppresses spatial pressure with a reason', async ({
  page,
  request,
}) => {
  test.setTimeout(120000)
  const job = await open(request, 'permuted')
  // The frame route is the real artifact; mutate only this response to model a
  // duplicated native sample. The interface must not silently choose one.
  await page.route('**/frame-00000.json', async (route) => {
    const response = await route.fetch()
    const frame = await response.json()
    frame.door_pressure.profiles['profile-1'].labels = [2, 2]
    await route.fulfill({ response, json: frame })
  })
  await page.goto('/#results/' + job.id)
  const unavailable = page.getByTestId('pressure-identity-unavailable')
  await expect(unavailable).toBeVisible({ timeout: 30000 })
  await unavailable.scrollIntoViewIfNeeded()
  await expect(unavailable).toContainText('node identity')
  await expect(page.getByTestId('pressure-chart')).toHaveCount(0)
  await expect(page.locator('.seal-vtk-host')).not.toHaveAttribute('data-pressure-node', '2')
  await expect(page.getByTestId('export-pressure')).toBeDisabled()
})
