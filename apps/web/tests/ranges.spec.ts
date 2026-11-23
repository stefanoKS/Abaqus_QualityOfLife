/**
 * Gate 3b: independent displacement/stress ranges, clipping cues, unclipped
 * probes and loop playback that wraps after the last displayed frame.
 *
 * Uses a manufactured run from the isolated test-data worker.
 */
import { expect, test, type Page } from './fixtures'
import { randomUUID } from 'node:crypto'
import { meshAndDeck } from './pipeline'
import type { Job, Revision } from '../src/api'

async function completedRun(page: Page, revision: Revision) {
  const { deck } = await meshAndDeck(page.request, revision)
  const run: Job = await (
    await page.request.post('/api/runs', {
      data: {
        revision: revision.id,
        deck: deck.id,
        token: randomUUID(),
        name: 'Range evidence',
        mode: 'ABAQUS',
      },
    })
  ).json()
  await expect
    .poll(
      async () => ((await (await page.request.get('/api/jobs/' + run.id)).json()) as Job).status,
      { timeout: 90000 },
    )
    .toBe('Completed')
  return run
}

async function project(request: import('@playwright/test').APIRequestContext) {
  return (await (
    await request.post('/api/projects', { data: { name: 'Range evidence', example: true } })
  ).json()) as Revision
}

async function at(page: Page, bounds: number[], x: number, y: number) {
  const box = (await page.getByRole('application').boundingBox())!
  const [xmin, xmax, ymin, ymax] = bounds
  const scale = Math.min(box.width / (xmax - xmin), box.height / (ymax - ymin)) / 1.2
  const cx = (xmin + xmax) / 2
  const cy = (ymin + ymax) / 2
  return {
    x: box.x + box.width / 2 + (x - cx) * scale,
    y: box.y + box.height / 2 - (y - cy) * scale,
  }
}

test('displacement and stress keep independent defaults, auto/manual limits and clipping cues', async ({
  page,
  request,
}) => {
  const revision = await project(request)
  const run = await completedRun(page, revision)
  const metadata = await (
    await request.get('/api/jobs/' + run.id + '/display-metadata')
  ).json()
  await page.goto('/#results/' + run.id)
  await expect(page.getByRole('heading', { name: 'Force–displacement' })).toBeVisible()
  const field = page.getByLabel('Field')
  const mode = page.getByLabel('Range mode')
  const legend = page.locator('.seal-vtk-legend')
  const summary = page.getByTestId('range-summary')

  // Displacement defaults to 0–5 mm; the stress default is 0–0.5 MPa.
  await field.selectOption('Umag')
  await expect(summary).toContainText('0 – 5 mm')
  await expect(page.getByTestId('legend-limits')).toContainText('0 mm')
  await expect(page.getByTestId('legend-limits')).toContainText('5 mm')
  await mode.selectOption('auto')
  await expect(page.getByTestId('legend-limits')).toContainText(
    String(Number((metadata.ranges.magnitude as number).toPrecision(4))),
  )
  // Values are measured per displayed frame: use the final frame for clipping.
  const frames = await (
    await request.get('/api/jobs/' + run.id + '/artifacts/results.json')
  ).json()
  await page.getByRole('slider').fill(String(frames.frames.length - 1))
  await mode.selectOption('manual')
  await page.getByLabel('Minimum (mm)').fill('9.5')
  await page.getByLabel('Maximum (mm)').fill('10.001')
  // Most displacement values lie below a high minimum: clamp cue, not a blank view.
  await expect(page.getByTestId('legend-underflow')).toBeVisible()
  await page.getByLabel('Minimum (mm)').fill('0')
  await page.getByLabel('Maximum (mm)').fill('1')
  await expect(page.getByTestId('legend-saturated')).toBeVisible()
  // A blank or inverted draft is rejected locally and the last valid render holds.
  const lastLimits = await page.getByTestId('legend-limits').innerText()
  await page.getByLabel('Maximum (mm)').fill('0')
  await expect(page.getByTestId('range-error')).toBeVisible()
  expect(await page.getByTestId('legend-limits').innerText()).toBe(lastLimits)
  await page.getByLabel('Maximum (mm)').fill('1')
  await expect(page.getByTestId('range-error')).toHaveCount(0)

  // The probe keeps the unclipped signed value even under a saturated range.
  await field.selectOption('U2')
  await expect(page.getByLabel('Probe mode')).toHaveValue('node')
  const index = await (
    await request.get('/api/jobs/' + run.id + '/artifacts/results.json')
  ).json()
  // Inspect the final frame so clicked coordinates and reported U agree.
  await page.getByRole('slider').fill(String(index.frames.length - 1))
  await expect
    .poll(async () => Number(await page.getByTestId('vtk-viewport').getAttribute('data-frame-time')))
    .toBeCloseTo(index.frames.at(-1).time)
  const frameFile = index.frames.at(-1).file
  const frame = await (
    await request.get('/api/jobs/' + run.id + '/artifacts/' + frameFile)
  ).json()
  const rows = (frame.displacements?.['WS-1'] ?? []) as number[][]
  const ws = (index.instances as { name: string; nodes: number[][] }[]).find(
    (item) => item.name === 'WS-1',
  )!
  let probe: { x: number; y: number; u2: number } | null = null
  for (const node of ws.nodes) {
    const row = rows.find((entry) => entry[0] === node[0])
    if (!row) continue
    const u2 = row[2] as number | undefined
    if (u2 === undefined || u2 === null) continue
    if (!probe || Math.abs(u2) > Math.abs(probe.u2)) {
      const point = await at(page, metadata.bounds.extent, node[1] + (row[1] as number), node[2] + u2)
      probe = { ...point, u2 }
    }
  }
  expect(probe).not.toBeNull()
  await page.mouse.click(probe!.x, probe!.y)
  await expect(page.locator('.legend')).toContainText(String(Number(probe!.u2.toPrecision(4))))

  // Displacement components share displacement range state; switching does not
  // rewrite it, and Reset restores the fixed default.
  await field.selectOption('U1')
  await expect(summary).toContainText('1 mm')
  await page.getByRole('button', { name: 'Reset range' }).click()
  await expect(summary).toContainText('0 – 5 mm')
  expect(await legend.innerText()).toBeTruthy()
})

test('stress opens on its own fixed 0–0.5 MPa range', async ({ page, request }) => {
  const revision = await project(request)
  const run = await completedRun(page, revision)
  // The manufactured launcher publishes displacement only. Add a measured
  // run-wide Mises range to the display metadata so the stress default is
  // exercised without claiming solver stress evidence.
  await page.route('**/display-metadata', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    body.ranges = { ...body.ranges, mises: 0.2 }
    await route.fulfill({ response, json: body })
  })
  await page.goto('/#results/' + run.id)
  await expect(page.getByLabel('Field')).toHaveValue('mises')
  await expect(page.getByTestId('range-summary')).toContainText('0 – 0.5 MPa')
  await expect(page.getByTestId('legend-limits')).toContainText('MPa')
  await expect(page.getByLabel('Minimum (MPa)')).toBeDisabled()
  await page.getByLabel('Range mode').selectOption('manual')
  await expect(page.getByLabel('Minimum (MPa)')).toBeEnabled()
})

test('playback loops by default, holds the last frame, and stops when Loop is off', async ({
  page,
  request,
}) => {
  const revision = await project(request)
  const run = await completedRun(page, revision)
  const index = await (
    await request.get('/api/jobs/' + run.id + '/artifacts/results.json')
  ).json()
  const last = index.frames.length - 1
  await page.goto('/#results/' + run.id)
  await expect(page.getByRole('heading', { name: 'Force–displacement' })).toBeVisible()
  const slider = page.getByRole('slider')
  const camera = () =>
    page.locator('.seal-vtk-host').getAttribute('data-camera')
  const frameTime = async () =>
    Number(await page.getByTestId('vtk-viewport').getAttribute('data-frame-time'))
  const before = await camera()
  expect(await page.getByLabel('Loop').isChecked()).toBe(true)

  // From the penultimate frame, playback reaches the last one, holds it for one
  // cadence and wraps to frame 0; the run-wide scale and camera stay fixed.
  await slider.fill(String(last - 1))
  await page.getByRole('button', { name: 'Play frames' }).click()
  let seenRunning = false
  await expect
    .poll(async () => {
      const value = Number(await slider.inputValue())
      if (value > 0) seenRunning = true
      return seenRunning && value === 0
    }, { timeout: 20000, intervals: [50] })
    .toBe(true)
  // A second wrap proves the wrap is repeatable, not a one-off reset.
  seenRunning = false
  await expect
    .poll(async () => {
      const value = Number(await slider.inputValue())
      if (value > 0) seenRunning = true
      return seenRunning && value === 0
    }, { timeout: 25000, intervals: [50] })
    .toBe(true)
  await page.getByRole('button', { name: 'Pause playback' }).click()
  expect(await camera()).toEqual(before)

  // Loop off: playback stops on the final frame and keeps it displayed.
  await page.getByLabel('Loop').uncheck()
  await slider.fill(String(last - 1))
  await page.getByRole('button', { name: 'Play frames' }).click()
  await expect(slider).toHaveValue(String(last), { timeout: 10000 })
  await expect(page.getByRole('button', { name: 'Play frames' })).toBeVisible({
    timeout: 10000,
  })
  expect(await frameTime()).toBeCloseTo(index.frames[last].time)

  // A slow response across the loop boundary keeps the last valid scene visible.
  await page.getByLabel('Loop').check()
  await page.route('**/' + index.frames[0].file, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 900))
    await route.continue()
  })
  await slider.fill(String(last))
  await page.getByRole('button', { name: 'Play frames' }).click()
  await expect(slider).toHaveValue('0', { timeout: 10000 })
  await expect(page.getByTestId('vtk-viewport')).toHaveAttribute(
    'data-frame-time',
    String(index.frames[last].time),
  )
  await expect.poll(frameTime, { timeout: 10000 }).toBeCloseTo(index.frames[0].time)
  await page.getByRole('button', { name: 'Pause playback' }).click()
})
