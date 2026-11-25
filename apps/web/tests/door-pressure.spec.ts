/**
 * Gate D: door-panel pressure on a real result.
 *
 * Opt-in. Set SEAL_DOOR_REFERENCE to a portable `.aqresult` produced from the
 * supplied GENKOU reference ODB (and run against the isolated server that can
 * see that path). Without it the spec skips, so the license-free suite is
 * unaffected. The assertions are numeric, not screenshot-only.
 */
import { expect, test, type Page } from './fixtures'

async function openReference(page: Page, path: string) {
  const job = await (
    await page.request.post('/api/files/result/open', { data: { path } })
  ).json()
  await page.goto('/#results/' + job.id)
  await expect(page.getByTestId('run-complete')).toBeVisible({ timeout: 30000 })
  return job
}

async function setSlider(page: Page, index: number) {
  const slider = page.locator('.playback-slider')
  await slider.evaluate((element, value) => {
    const input = element as HTMLInputElement
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )?.set
    setter?.call(input, String(value))
    input.dispatchEvent(new Event('input', { bubbles: true }))
    input.dispatchEvent(new Event('change', { bubbles: true }))
  }, index)
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
      const px = rect.left + xa._offset + (xa._length * (x - xa.range[0])) / (xa.range[1] - xa.range[0])
      const py =
        rect.top +
        ya._offset +
        ya._length * (1 - (y - ya.range[0]) / (ya.range[1] - ya.range[0]))
      return { x: px, y: py }
    },
    { x, y },
  )
}

const reference = process.env.SEAL_DOOR_REFERENCE
const evidence = process.env.SEAL_DOOR_EVIDENCE || process.cwd()

test('GENKOU reference: separated patches, station readout, direction and zero frame', async ({
  page,
}) => {
  test.skip(!reference, 'SEAL_DOOR_REFERENCE is not set')
  const job = await openReference(page, reference!)
  await expect(page.getByRole('heading', { name: 'Door contact pressure' })).toBeVisible()
  const sliderMax = await page
    .locator('.playback-slider')
    .evaluate((element) => Number((element as HTMLInputElement).max))
  await setSlider(page, sliderMax)
  await expect(page.getByTestId('frame-time')).toContainText('3.000', { timeout: 30000 })

  const profile = page.getByTestId('pressure-profile')
  await expect(profile.locator('option')).toHaveCount(6)
  await profile.selectOption({ label: 'UPPER_ROOFBARA-1' })
  await expect(page.getByTestId('pressure-chart')).toHaveAttribute(
    'data-profile',
    'UPPER_ROOFBARA-1:8',
  )
  // Two separated contact patches: six positive stations, the rest measured null
  // in the supplied final frame, with gaps preserved as breaks in the line.
  await expect(page.getByTestId('pressure-chart')).toHaveAttribute('data-samples', '124')
  await expect(page.getByTestId('pressure-chart')).toHaveAttribute('data-positive', '6')
  await expect(page.getByTestId('pressure-chart')).toHaveAttribute('data-patches', '2')
  await expect(page.getByTestId('pressure-chart')).toHaveAttribute('data-gaps', '0')
  await expect(page.getByTestId('pressure-reference')).toContainText('46.5')
  await expect(page.locator('.seal-vtk-host')).toHaveAttribute('data-pressure-profile', 'UPPER_ROOFBARA-1:8')

  // Node 17 at station 56.405592 mm, peak 45.509089 kPa.
  const point = await plotPoint(page, 56.405592461919184, 45.50908878445625)
  await page.mouse.move(point.x, point.y)
  await page.mouse.click(point.x, point.y)
  const readout = page.getByTestId('pressure-readout')
  await expect(readout).toHaveAttribute('data-node', '17', { timeout: 10000 })
  expect(Number(await readout.getAttribute('data-station'))).toBeCloseTo(56.405592, 4)
  expect(Number(await readout.getAttribute('data-pressure'))).toBeCloseTo(45.509089, 4)
  expect(Number(await readout.getAttribute('data-fx'))).toBeCloseTo(0.021603798, 7)
  expect(Number(await readout.getAttribute('data-fy'))).toBeCloseTo(0.014067459, 7)

  // Arrow direction is the measured normalized CNORMF in world coordinates.
  const direction = (await page.locator('.seal-vtk-host').getAttribute('data-pressure-direction'))!
    .split(',')
    .map(Number)
  const force = [0.021603798493742943, 0.014067458920180798]
  const length = Math.hypot(...force)
  const dot = direction[0] * (force[0] / length) + direction[1] * (force[1] / length)
  expect(dot).toBeGreaterThan(0.999)

  // The same node is a live CNORMF probe target: the signed components and the
  // magnitude come from the stored force field, not from a derived pressure.
  await page.getByLabel('Field').selectOption('CNormf')
  const hostBox = (await page.locator('.seal-vtk-host').boundingBox())!
  const anchorProbe = (await page.locator('.seal-vtk-host').getAttribute('data-pressure-anchor'))!
    .split(',')
    .map(Number)
  await page.mouse.click(hostBox.x + anchorProbe[0], hostBox.y + anchorProbe[1])
  await expect(page.locator('.legend')).toContainText('CNORMF', { timeout: 10000 })
  await expect(page.locator('.legend')).toContainText('0.02578')
  await page.getByLabel('Field').selectOption('Umag')

  // The glyph anchor is the rendered deformed node: recompute the same node's
  // projection from the frame and the camera, and require <= 2 CSS px.
  const anchor = (await page.locator('.seal-vtk-host').getAttribute('data-pressure-anchor'))!
    .split(',')
    .map(Number)
  const selectedNode = await page.locator('.seal-vtk-host').getAttribute('data-pressure-node')
  const expected = await page.evaluate(
    async ({ jobId }) => {
      const index = await (await fetch('/api/jobs/' + jobId + '/artifacts/results.json')).json()
      const last = index.frames[index.frames.length - 1]
      const frame = await (await fetch('/api/jobs/' + jobId + '/artifacts/' + last.file)).json()
      const definition = index.door_pressure.profiles.find(
        (entry: { alias: string }) => entry.alias === 'UPPER_ROOFBARA-1',
      )
      const position = definition.labels.indexOf(17)
      const xy = definition.points_mm[position]
      const u = (frame.displacements['UPPER_ROOFBARA-1'] as number[][]).find(
        (row) => row[0] === 17,
      )!
      const viewport = document.querySelector('.seal-vtk-host') as HTMLElement
      const camera = viewport.dataset.camera!.split(',').map(Number)
      const rect = viewport.getBoundingClientRect()
      const aspect = rect.width / rect.height
      return {
        x: rect.width / 2 + ((xy[0] + u[1] - camera[3]) / (camera[6] * aspect)) * (rect.width / 2),
        y: rect.height / 2 - ((xy[1] + u[2] - camera[4]) / camera[6]) * (rect.height / 2),
      }
    },
    { jobId: job.id },
  )
  expect(selectedNode).toBe('17')
  expect(Math.hypot(anchor[0] - expected.x, anchor[1] - expected.y)).toBeLessThanOrEqual(2)

  // Axis titles stay readable at 1280x720, after the pressure section is
  // scrolled into view. The axis text is the full engineering phrase.
  await page.setViewportSize({ width: 1280, height: 720 })
  await page.getByTestId('pressure-chart').scrollIntoViewIfNeeded()
  const axisTitles = await page.evaluate(() => {
    const element = document.querySelector(
      '[data-testid="pressure-chart"] .js-plotly-plot',
    ) as unknown as {
      _fullLayout: {
        xaxis: { title?: { text?: string } }
        yaxis: { title?: { text?: string } }
      }
    }
    const read = (className: string, axis: 'xaxis' | 'yaxis') => {
      const node = document.querySelector(
        `[data-testid="pressure-chart"] .js-plotly-plot .${className}`,
      )
      return {
        text: node?.textContent ?? '',
        rect: node?.getBoundingClientRect().toJSON() ?? null,
        layout: element._fullLayout[axis]?.title?.text ?? '',
      }
    }
    return { x: read('xtitle', 'xaxis'), y: read('ytitle', 'yaxis') }
  })
  expect(axisTitles.x.layout).toBe('Distance along door panel (mm)')
  expect(axisTitles.y.layout).toBe('Contact pressure (kPa)')
  expect(axisTitles.x.rect!.top).toBeGreaterThanOrEqual(0)
  expect(axisTitles.x.rect!.bottom).toBeLessThanOrEqual(720)
  expect(axisTitles.y.rect!.left).toBeGreaterThanOrEqual(0)
  expect(axisTitles.y.rect!.bottom).toBeLessThanOrEqual(720)
  await page.setViewportSize({ width: 1440, height: 960 })

  // A measured zero frame keeps the zero line and draws no arrows.
  await setSlider(page, 50)
  await expect(page.getByTestId('frame-count')).toContainText('51 / 152', { timeout: 30000 })
  await expect(page.locator('.seal-vtk-host')).toHaveAttribute('data-pressure-arrows', '0')
  await expect(page.getByTestId('pressure-chart')).toHaveAttribute('data-positive', '0')
  await expect(page.getByTestId('pressure-chart')).toHaveAttribute('data-patches', '0')
  await expect(page.getByTestId('pressure-chart')).toHaveAttribute('data-gaps', '0')

  // Step transition commits the new frame's arrays with the new geometry.
  await setSlider(page, 51)
  await expect(page.getByTestId('frame-count')).toContainText('52 / 152', { timeout: 30000 })

  // Delayed frame fetch: the previous frame stays on screen and its graph and
  // glyphs stay with it until the requested frame commits.
  await page.route(/\/artifacts\/frame-\d+\.json$/, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 3000))
    await route.continue()
  })
  await setSlider(page, 140)
  await expect(page.getByTestId('playback-status')).toHaveAttribute('data-displayed', '51')
  await expect(page.getByTestId('playback-status')).toContainText(/[Ll]oading/)
  await expect(page.getByTestId('frame-count')).toContainText('141 / 152', { timeout: 30000 })
  await page.unroute(/\/artifacts\/frame-\d+\.json$/)
  await setSlider(page, sliderMax)
  await expect(page.getByTestId('frame-count')).toContainText('152 / 152', { timeout: 30000 })
  await expect(page.getByTestId('frame-time')).toContainText('3.000', { timeout: 30000 })

  await page.locator('.lang-button').click()
  await expect(page.getByRole('heading', { name: 'ドアパネル接触圧' })).toBeVisible()
  await page.screenshot({ path: evidence + '/gate-d-genkou-ja.png', fullPage: false })
  await page.locator('.lang-button').click()
  await expect(page.getByRole('heading', { name: 'Door contact pressure' })).toBeVisible()
  await page.screenshot({ path: evidence + '/gate-d-genkou-en.png', fullPage: false })
})
