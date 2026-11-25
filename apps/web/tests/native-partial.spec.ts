/**
 * Gate 2 browser evidence for a native partial result.
 *
 * Requires an isolated server serving a recovered native ODB and the packaged
 * `.aqresult`:
 *   SEAL_NATIVE_BASE=http://127.0.0.1:<port>
 *   SEAL_NATIVE_JOB=<job id>
 *   SEAL_NATIVE_REFERENCE=<path to reference.json>
 *   SEAL_NATIVE_PACKAGE=<path to .aqresult>
 *   SEAL_NATIVE_UI=<path to write measured UI coordinates>
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { expect, test, type Page } from './fixtures'
import type { Job } from '../src/api'

const BASE = process.env.SEAL_NATIVE_BASE
const JOB = process.env.SEAL_NATIVE_JOB
const REFERENCE = process.env.SEAL_NATIVE_REFERENCE
const PACKAGE = process.env.SEAL_NATIVE_PACKAGE
const UI = process.env.SEAL_NATIVE_UI

test.describe('native partial through Results and File Open', () => {
  test.skip(
    !BASE || !JOB || !REFERENCE || !PACKAGE || !UI,
    'native evidence environment is not configured',
  )

  test('last saved frame, reference measurement and portable reopen agree', async ({
    page,
    request,
  }) => {
    const reference = JSON.parse(readFileSync(REFERENCE!, 'utf8')) as {
      frames: number
      last_frame_ordinal: number
      last_time: number
      last_step: string
      reference: {
        node: number
        station_mm: number
        pressure_kpa: number
        pressure_mpa: number
        cnormf_n: number[]
      }
    }
    await page.goto(BASE + '/#results/' + JOB)
    await expect(page.getByTestId('partial-notice')).toBeVisible()
    await expect(page.getByTestId('partial-step')).toContainText(reference.last_step)
    await expect(page.getByTestId('partial-frame')).toContainText(
      String(reference.last_frame_ordinal),
    )
    await expect(page.getByTestId('frame-count')).toHaveText(
      `${reference.frames} / ${reference.frames}`,
    )
    await expect(page.getByTestId('frame-time')).toHaveText(
      reference.last_time.toFixed(3) + ' s',
    )

    const readout = page.getByTestId('pressure-readout')
    await clickPressurePoint(
      page,
      reference.reference.station_mm,
      reference.reference.pressure_kpa,
    )
    await expect(readout).toBeVisible()
    await expect(readout).toHaveAttribute(
      'data-node',
      String(reference.reference.node),
    )
    const ui = {
      job: JOB,
      frame_count: await page.getByTestId('frame-count').textContent(),
      frame_time: await page.getByTestId('frame-time').textContent(),
      partial_frame: await page.getByTestId('partial-frame').textContent(),
      node: Number(await readout.getAttribute('data-node')),
      station: Number(await readout.getAttribute('data-station')),
      pressure_kpa: Number(await readout.getAttribute('data-pressure')),
      native_mpa: Number(await readout.getAttribute('data-native-mpa')),
      fx: Number(await readout.getAttribute('data-fx')),
      fy: Number(await readout.getAttribute('data-fy')),
      canvas: await page.locator('.seal-vtk-host').boundingBox(),
    }
    expect(ui.station).toBeCloseTo(reference.reference.station_mm, 6)
    expect(ui.pressure_kpa).toBeCloseTo(reference.reference.pressure_kpa, 4)
    expect(ui.native_mpa).toBeCloseTo(reference.reference.pressure_mpa, 9)
    expect(ui.fx).toBeCloseTo(reference.reference.cnormf_n[0], 9)
    expect(ui.fy).toBeCloseTo(reference.reference.cnormf_n[1], 9)

    // The packaged result reopens in the local (fresh) data root with the same
    // partial badge, last frame and reference measurement.
    const opened = await request.post('/api/files/result/open', {
      data: { path: PACKAGE },
    })
    expect(opened.ok()).toBeTruthy()
    const job = (await opened.json()) as Job
    expect(job.result_state).toBe('partial')
    await page.goto('/#results/' + job.id)
    await expect(page.getByTestId('partial-notice')).toBeVisible()
    await expect(page.getByTestId('frame-count')).toHaveText(
      `${reference.frames} / ${reference.frames}`,
    )
    await expect(page.getByTestId('frame-time')).toHaveText(
      reference.last_time.toFixed(3) + ' s',
    )
    await clickPressurePoint(
      page,
      reference.reference.station_mm,
      reference.reference.pressure_kpa,
    )
    const reopened = page.getByTestId('pressure-readout')
    expect(Number(await reopened.getAttribute('data-pressure'))).toBeCloseTo(
      reference.reference.pressure_kpa,
      4,
    )
    writeFileSync(
      UI!,
      JSON.stringify(
        { live: ui, reopened_frames: await page.getByTestId('frame-count').textContent() },
        null,
        2,
      ),
    )
  })
})

async function clickPressurePoint(page: Page, x: number, y: number) {
  await expect(page.getByTestId('pressure-chart')).toBeVisible()
  await page.getByTestId('pressure-chart').scrollIntoViewIfNeeded()
  await expect
    .poll(async () =>
      page.evaluate(() => {
        const element = document.querySelector(
          '[data-testid="pressure-chart"] .js-plotly-plot',
        ) as unknown as { _fullLayout?: unknown } | null
        return Boolean(element?._fullLayout)
      }),
    )
    .toBe(true)
  const point = await page.evaluate(
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
      const px =
        rect.left +
        xa._offset +
        (xa._length * (x - xa.range[0])) / (xa.range[1] - xa.range[0])
      const py =
        rect.top +
        ya._offset +
        ya._length * (1 - (y - ya.range[0]) / (ya.range[1] - ya.range[0]))
      return { x: px, y: py }
    },
    { x, y },
  )
  await page.mouse.click(point.x, point.y)
}
