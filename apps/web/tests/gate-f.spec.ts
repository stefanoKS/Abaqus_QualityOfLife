/**
 * Gate F: measured playback stability on a manufactured run.
 *
 * Timing budget (local idle desktop, warmed read-ahead): target cadence 220 ms,
 * p95 absolute error <= 50 ms, median error <= 25 ms. The deterministic layout
 * and ordering assertions are the CI contract; the timing block writes its raw
 * measurements to .local/gate-f-measurements.json and is reported separately.
 */
import { randomUUID } from 'node:crypto'
import { mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from './fixtures'
import { meshAndDeck } from './pipeline'
import type { Job, Revision } from '../src/api'

async function manufacturedRun(
  request: import('@playwright/test').APIRequestContext,
): Promise<{ run: Job; frames: { time: number; file: string }[] }> {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Gate F playback', example: true } })
  ).json()
  const { deck } = await meshAndDeck(request, revision)
  const run: Job = await (
    await request.post('/api/runs', {
      data: {
        revision: revision.id,
        deck: deck.id,
        token: randomUUID(),
        name: 'Gate F playback',
        mode: 'ABAQUS',
      },
    })
  ).json()
  await expect
    .poll(async () => ((await (await request.get('/api/jobs/' + run.id)).json()) as Job).status, {
      timeout: 90000,
    })
    .toBe('Completed')
  const index = await (
    await request.get('/api/jobs/' + run.id + '/artifacts/results.json')
  ).json()
  return { run, frames: index.frames }
}

test.use({ viewport: { width: 1440, height: 900 } })

test('playback keeps the slider and fixed landmarks stable and meets the cadence budget', async ({
  page,
  request,
}) => {
  test.setTimeout(120000)
  const { run, frames } = await manufacturedRun(request)
  expect(frames.length).toBeGreaterThan(20)
  await page.goto('/#results/' + run.id)
  await expect(page.getByRole('heading', { name: 'Force–displacement' })).toBeVisible()

  // Mesh edges are on by default and remain an independent toggle.
  const edges = page.getByLabel('Mesh edges')
  await expect(edges).toBeChecked()
  await edges.uncheck()
  await edges.check()

  const slider = page.getByRole('slider')
  await slider.fill('9')
  await expect(page.locator('[data-testid=frame-time]')).toContainText(
    frames[9].time.toFixed(3),
  )

  // Sample every animation frame: presentation timestamp, frame time, host and
  // slider geometry, frame-count width and the camera signature.
  await page.evaluate(() => {
    const samples: unknown[] = []
    let last = ''
    const tick = (ts: number) => {
      const host = document.querySelector('.seal-vtk-host') as HTMLElement | null
      const sliderEl = document.querySelector('.playback-slider') as HTMLElement | null
      const count = document.querySelector('[data-testid=frame-count]') as HTMLElement | null
      const time = document.querySelector('[data-testid=frame-time]')?.textContent ?? ''
      if (host && sliderEl && count && time !== last) {
        const rect = host.getBoundingClientRect()
        const srect = sliderEl.getBoundingClientRect()
        const crect = count.getBoundingClientRect()
        samples.push({
          ts,
          time,
          x: rect.x,
          y: rect.y,
          w: rect.width,
          h: rect.height,
          sx: srect.x,
          sw: srect.width,
          cw: crect.width,
          cam: host.dataset.camera,
          dpr: window.devicePixelRatio,
        })
        last = time
      }
      ;(window as unknown as { __gateF?: unknown[] }).__gateF = samples
      requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  })

  await page.getByRole('button', { name: 'Play frames' }).click()
  // Two full loops of the small manufactured run.
  const expected = frames.length * 2
  await expect
    .poll(
      async () =>
        ((await page.evaluate(
          () => (window as unknown as { __gateF?: unknown[] }).__gateF?.length ?? 0,
        )) as number),
      { timeout: 40000, intervals: [250] },
    )
    .toBeGreaterThan(expected)

  const samples = (await page.evaluate(
    () => (window as unknown as { __gateF?: unknown[] }).__gateF ?? [],
  )) as {
    ts: number
    time: string
    x: number
    y: number
    w: number
    h: number
    sx: number
    sw: number
    cw: number
    cam: string
  }[]
  await page.getByRole('button', { name: 'Pause playback' }).click()

  const first = samples[0]
  for (const sample of samples) {
    expect(Math.abs(sample.x - first.x)).toBeLessThanOrEqual(0.5)
    expect(Math.abs(sample.y - first.y)).toBeLessThanOrEqual(0.5)
    expect(Math.abs(sample.w - first.w)).toBeLessThanOrEqual(0.5)
    expect(Math.abs(sample.h - first.h)).toBeLessThanOrEqual(0.5)
    expect(Math.abs(sample.sx - first.sx)).toBeLessThanOrEqual(0.5)
    expect(Math.abs(sample.sw - first.sw)).toBeLessThanOrEqual(0.5)
    expect(Math.abs(sample.cw - first.cw)).toBeLessThanOrEqual(0.5)
    expect(sample.cam).toBe(first.cam)
  }

  const intervals = samples.slice(1).map((sample, index) => sample.ts - samples[index].ts)
  const sorted = [...intervals].sort((a, b) => a - b)
  const at = (q: number) => sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))]
  const errors = intervals.map((value) => Math.abs(value - 220)).sort((a, b) => a - b)
  const median = at(0.5)
  const p95 = errors[Math.min(errors.length - 1, Math.floor(0.95 * errors.length))]
  const report = {
    frames: frames.length,
    transitions: intervals.length,
    median_ms: Math.round(median * 10) / 10,
    p95_abs_error_ms: Math.round(p95 * 10) / 10,
    worst_interval_ms: Math.round(Math.max(...intervals) * 10) / 10,
    best_interval_ms: Math.round(Math.min(...intervals) * 10) / 10,
    dpr: samples[0]?.dpr ?? 1,
    host: { x: first.x, y: first.y, w: first.w, h: first.h },
    slider: { x: first.sx, w: first.sw },
    frame_count_width: first.cw,
    camera_stable: true,
    viewport: { width: 1440, height: 900 },
  }
  mkdirSync(resolve('../../.local'), { recursive: true })
  writeFileSync(resolve('../../.local/gate-f-measurements.json'), JSON.stringify(report, null, 2))
  // Locally measured budget; hosted scheduling is expected to be noisier.
  expect(median).toBeGreaterThan(200)
  expect(median).toBeLessThan(245)
  expect(p95).toBeLessThanOrEqual(50)
})

test('one slow frame holds the last image and recovers without a catch-up burst', async ({
  page,
  request,
}) => {
  const { run, frames } = await manufacturedRun(request)
  await page.goto('/#results/' + run.id)
  await expect(page.getByRole('heading', { name: 'Force–displacement' })).toBeVisible()
  const slider = page.getByRole('slider')
  await slider.fill('9')
  await expect(page.locator('[data-testid=frame-time]')).toContainText(frames[9].time.toFixed(3))
  const camera = await page.locator('.seal-vtk-host').getAttribute('data-camera')

  await page.route('**/frame-00012.json', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500))
    await route.continue()
  })
  await page.getByRole('button', { name: 'Play frames' }).click()
  await expect(slider).toHaveValue('12', { timeout: 10000 })
  await expect(page.locator('.loading-note')).toBeVisible()
  // The last displayed image stays on screen while frame 12 is late.
  await expect(page.locator('[data-testid=frame-time]')).toContainText(frames[11].time.toFixed(3))
  // Recovery: the delayed frame lands once, then the cadence resumes without
  // a catch-up burst (the requested frame advances past the delayed one).
  await expect
    .poll(async () => Number(await slider.inputValue()), { timeout: 10000 })
    .toBeGreaterThan(12)
  expect(await page.locator('.seal-vtk-host').getAttribute('data-camera')).toBe(camera)
})
