/**
 * Reusable Results verification for an existing licensed app run.
 * Opt-in via SEAL_DOOR_JOB; no solver is started.
 */
import { writeFileSync } from 'node:fs'
import { expect, test, type Page } from './fixtures'

const JOB = process.env.SEAL_DOOR_JOB
const EVIDENCE = process.env.SEAL_DOOR_EVIDENCE || process.cwd()

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
      const xa = element._fullLayout.xaxis
      const ya = element._fullLayout.yaxis
      const rect = element.getBoundingClientRect()
      return {
        x: rect.left + xa._offset + (xa._length * (x - xa.range[0])) / (xa.range[1] - xa.range[0]),
        y: rect.top + ya._offset + ya._length * (1 - (y - ya.range[0]) / (ya.range[1] - ya.range[0])),
      }
    },
    { x, y },
  )
}

test('licensed app run: same nonzero node in Results, CNORMF and pressure graph', async ({
  page,
}) => {
  test.skip(!JOB, 'SEAL_DOOR_JOB is not set')
  test.setTimeout(180000)
  await page.goto('/#results/' + JOB)
  await expect(page.getByTestId('run-complete')).toBeVisible({ timeout: 60000 })
  const field = page.getByLabel('Field')
  await expect(field.locator('option', { hasText: 'CNORMF (contact normal force)' })).toHaveCount(1)
  const slider = page.locator('.playback-slider')
  const sliderMax = await slider.evaluate((element) => Number((element as HTMLInputElement).max))
  await slider.evaluate((element, value) => {
    const input = element as HTMLInputElement
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set?.call(
      input,
      String(value),
    )
    input.dispatchEvent(new Event('input', { bubbles: true }))
    input.dispatchEvent(new Event('change', { bubbles: true }))
  }, sliderMax)
  await expect(page.getByTestId('pressure-chart')).toBeVisible({ timeout: 30000 })
  await expect(page.getByTestId('pressure-chart')).toHaveAttribute('data-positive', /[1-9]/)

  const measured = await page.evaluate(async ({ jobId }) => {
    const index = await (await fetch('/api/jobs/' + jobId + '/artifacts/results.json')).json()
    const last = index.frames[index.frames.length - 1]
    const frame = await (await fetch('/api/jobs/' + jobId + '/artifacts/' + last.file)).json()
    let best: null | {
      node: number
      station: number
      pressure: number
      native: number
      force: number[]
    } = null
    for (const profile of index.door_pressure.profiles) {
      const data = frame.door_pressure.profiles[profile.id]
      if (!data) continue
      data.pressure_kpa.forEach((pressure: number | null, position: number) => {
        if (pressure === null || pressure <= 0) return
        if (!best || pressure > best.pressure) {
          best = {
            node: data.labels[position],
            station: profile.stations_mm[position],
            pressure,
            native: data.pressure_mpa[position],
            force: data.cnormf_n[position],
          }
        }
      })
    }
    return best
  }, { jobId: JOB })
  expect(measured).not.toBeNull()
  const peak = measured as NonNullable<typeof measured>

  await page.getByTestId('pressure-chart').scrollIntoViewIfNeeded()
  const point = await plotPoint(page, peak.station, peak.pressure)
  await page.mouse.click(point.x, point.y)
  const readout = page.getByTestId('pressure-readout')
  await expect(readout).toHaveAttribute('data-node', String(peak.node), { timeout: 10000 })
  expect(Number(await readout.getAttribute('data-station'))).toBeCloseTo(peak.station, 4)
  expect(Number(await readout.getAttribute('data-pressure'))).toBeCloseTo(peak.pressure, 4)
  expect(Number(await readout.getAttribute('data-native-mpa'))).toBeCloseTo(peak.native, 7)
  const arrows = Number(await page.locator('.seal-vtk-host').getAttribute('data-pressure-arrows'))
  expect(arrows).toBeGreaterThan(0)

  // Reverse Y is a display choice for the force curve only: the spatial station
  // and the measured pressure stay unchanged.
  const pressureBefore = await readout.getAttribute('data-pressure')
  const stationBefore = await readout.getAttribute('data-station')
  await page.getByLabel('Reverse Y sign').check()
  await expect(readout).toHaveAttribute('data-pressure', pressureBefore!)
  await expect(readout).toHaveAttribute('data-station', stationBefore!)
  await expect(page.getByTestId('pressure-chart')).toHaveAttribute('data-profile', /.+/)
  await page.getByLabel('Reverse Y sign').uncheck()

  await field.selectOption('CNormf')
  await page.locator('.seal-vtk-host').scrollIntoViewIfNeeded()
  const hostBox = (await page.locator('.seal-vtk-host').boundingBox())!
  const anchor = (await page.locator('.seal-vtk-host').getAttribute('data-pressure-anchor'))!
    .split(',')
    .map(Number)
  await page.mouse.click(hostBox.x + anchor[0], hostBox.y + anchor[1])
  const magnitude = Math.hypot(...peak.force)
  await expect(page.locator('.legend')).toContainText('CNORMF', { timeout: 10000 })
  await expect(page.locator('.legend')).toContainText(magnitude.toPrecision(4))
  await field.selectOption('mises')
  await expect(field).toHaveValue('mises')
  await expect(page.locator('.seal-vtk-legend')).toContainText('von Mises')
  await field.selectOption('Umag')
  await expect(field).toHaveValue('Umag')
  await expect(page.locator('.seal-vtk-legend')).toContainText('Displacement magnitude')

  await page.getByTestId('pressure-chart').scrollIntoViewIfNeeded()
  await page.screenshot({ path: EVIDENCE + '/gate-c-app-pressure-en.png' })
  await page.locator('.lang-button').click()
  await page.screenshot({ path: EVIDENCE + '/gate-c-app-pressure-ja.png' })
  writeFileSync(
    EVIDENCE + '/gate-c-app-ui.json',
    JSON.stringify(
      {
        job: JOB,
        peak,
        arrows,
        ui: {
          node: Number(await readout.getAttribute('data-node')),
          station: Number(await readout.getAttribute('data-station')),
          pressure_kpa: Number(await readout.getAttribute('data-pressure')),
          native_mpa: Number(await readout.getAttribute('data-native-mpa')),
          fx: Number(await readout.getAttribute('data-fx')),
          fy: Number(await readout.getAttribute('data-fy')),
        },
      },
      null,
      2,
    ),
  )
})
