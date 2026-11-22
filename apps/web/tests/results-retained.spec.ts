import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test, type Page } from './fixtures'

/**
 * Gate F: the real Results view on a retained licensed result with S and U.
 * Opt-in: requires the isolated replay instance on 8891 and its seed file
 * (see .local/milestone/seed_retained.py). Skipped otherwise.
 */
const BASE = 'http://127.0.0.1:8891'
const seedPath = resolve('../../.local/milestone/results-seed.json')
const seed = existsSync(seedPath)
  ? (JSON.parse(readFileSync(seedPath, 'utf8')) as { run: string })
  : null

async function at(page: Page, bounds: number[], x: number, y: number) {
  const viewport = page.getByRole('application', { name: '2D engineering viewport' })
  const box = (await viewport.boundingBox())!
  const [xmin, xmax, ymin, ymax] = bounds
  const scale = Math.min(box.width / (xmax - xmin), box.height / (ymax - ymin)) / 1.2
  return {
    x: box.x + box.width / 2 + (x - (xmin + xmax) / 2) * scale,
    y: box.y + box.height / 2 - (y - (ymin + ymax) / 2) * scale,
  }
}

function mises(labels: string[], data: number[]) {
  const index = new Map(labels.map((label, position) => [label.toUpperCase(), position]))
  const value = (name: string) => (index.has(name) ? (data[index.get(name)!] ?? 0) : 0)
  const squared =
    0.5 *
      ((value('S11') - value('S22')) ** 2 +
        (value('S22') - value('S33')) ** 2 +
        (value('S33') - value('S11')) ** 2) +
    3 * (value('S12') ** 2 + value('S13') ** 2 + value('S23') ** 2)
  return Math.sqrt(Math.max(0, squared))
}

test('stress is the default Results field on a real extracted result', async ({ page }) => {
  test.skip(!seed, 'retained-result replay seed is absent (.local is not in Git)')
  const health = await page.request.get(`${BASE}/api/health`).catch(() => null)
  test.skip(!health?.ok(), 'isolated replay instance is not running on 8891')
  const metadata = await (
    await page.request.get(`${BASE}/api/jobs/${seed!.run}/display-metadata`)
  ).json()
  const index = await (
    await page.request.get(`${BASE}/api/jobs/${seed!.run}/artifacts/results.json`)
  ).json()
  const bounds: number[] = metadata.bounds.extent

  await page.goto(`${BASE}/#results/${seed!.run}`)
  await expect(page.getByRole('heading', { name: 'Force–displacement' })).toBeVisible()

  // Stress, element probing, fixed 0.00–0.50 MPa limits and a white canvas.
  const field = page.getByLabel('Field')
  await expect(field).toHaveValue('mises')
  await expect(page.getByLabel('Probe mode')).toHaveValue('element')
  const probe = page.locator('.legend')
  const colorBar = page.locator('.seal-vtk-legend')
  await expect(colorBar).toContainText('MPa')
  await expect(page.getByTestId('legend-limits')).toContainText('0.5')
  await expect(page.getByTestId('vtk-viewport')).toHaveAttribute('data-plain', 'true')
  const background = await page.locator('.seal-vtk-host').evaluate((el) => ({
    image: getComputedStyle(el).backgroundImage,
    color: getComputedStyle(el).backgroundColor,
  }))
  expect(background.image).toBe('none')
  expect(background.color).toBe('rgb(255, 255, 255)')

  // Advance to the loaded frame, where the seal carries measurable stress.
  const last = (index.frames as { time: number }[]).length - 1
  await page.getByRole('slider').fill(String(last))
  await expect
    .poll(async () =>
      Number(await page.getByTestId('vtk-viewport').getAttribute('data-frame-time')),
    )
    .toBeCloseTo((index.frames as { time: number }[])[last].time)

  // Click the loaded bulb side; the probe reports the max-IP policy and samples.
  const foot = await at(page, bounds, 8.0, 5.0)
  await page.mouse.click(foot.x, foot.y)
  await expect(probe).toContainText('max IP')
  await expect(probe).toContainText('samples')
  const text = await probe.innerText()
  const element = Number(/element (\d+)/.exec(text)?.[1])
  const shown = Number(/max IP ([\d.eE+-]+)/.exec(text)?.[1])
  expect(element).toBeGreaterThan(0)
  expect(shown).toBeGreaterThan(0)

  // The displayed cell value equals the frame's max integration-point Mises.
  const time = Number(await page.getByTestId('vtk-viewport').getAttribute('data-frame-time'))
  const entry = (index.frames as { time: number; file: string }[]).reduce((best, frame) =>
    Math.abs(frame.time - time) < Math.abs(best.time - time) ? frame : best,
  )
  const frame = await (
    await page.request.get(`${BASE}/api/jobs/${seed!.run}/artifacts/${entry.file}`)
  ).json()
  const fields = frame.fields ?? {}
  const samples: number[] = []
  if (fields.Mises?.values) {
    for (const value of fields.Mises.values)
      if (value.instance === 'WS-1' && value.element === element) samples.push(value.data[0])
  } else if (fields.S?.values) {
    for (const value of fields.S.values)
      if (value.instance === 'WS-1' && value.element === element)
        samples.push(mises(fields.S.components ?? [], value.data ?? []))
  }
  expect(samples.length).toBeGreaterThan(0)
  expect(shown).toBeCloseTo(Math.max(...samples), 3)
  await page.screenshot({
    path: 'I:/GithubProjects/Abaqus_QualityOfLife/.local/milestone/results-after-stress.png',
  })

  // A saturated manual range keeps the actual probe value.
  await page.getByLabel('Range mode').selectOption('manual')
  await page.getByLabel('Minimum (MPa)').fill('0')
  await page.getByLabel('Maximum (MPa)').fill('0.000001')
  await expect(page.getByTestId('legend-saturated')).toBeVisible()
  await expect(probe).toContainText(String(shown))
  // An invalid range is rejected inline, not applied.
  await page.getByLabel('Minimum (MPa)').fill('1')
  await page.getByLabel('Maximum (MPa)').fill('0.5')
  await expect(page.getByTestId('range-error')).toBeVisible()
  await page.getByLabel('Minimum (MPa)').fill('0')
  await page.getByLabel('Maximum (MPa)').fill('0.5')
  await expect(page.getByTestId('range-error')).toHaveCount(0)

  // Edges and node markers are independent overlays.
  const actors = async () =>
    Number(await page.getByTestId('vtk-viewport').getAttribute('data-scene-actors'))
  const before = await actors()
  await page.getByLabel('Mesh edges').check()
  expect(await actors()).toBe(before)
  await page.getByLabel('Node markers').check()
  await expect.poll(actors).toBeGreaterThan(before)
  await page.getByLabel('Node markers').uncheck()
  await expect.poll(actors).toBe(before)

  // Deformation scaling changes only the displayed shape.
  await page.getByLabel('Deformation scale (×)').fill('5')
  await expect(probe).toContainText(String(shown))
  await page.getByLabel('Deformation scale (×)').fill('1')

  // A rigid line carries no stress: neutral and explicitly unavailable.
  const panel = await at(page, bounds, 0, 14.0)
  await page.mouse.click(panel.x, panel.y)
  await expect(probe).toContainText('Stress unavailable')

  // Displacement opens on node probing and still supports element inspection.
  await field.selectOption('Umag')
  await expect(page.getByLabel('Probe mode')).toHaveValue('node')
  const ws = (index.instances as { name: string; nodes: number[][] }[]).find(
    (instance) => instance.name === 'WS-1',
  )!
  const rows = (frame.displacements?.['WS-1'] ?? []) as number[][]
  const reachable = ws.nodes
    .map((node) => {
      const row = rows.find((entry) => entry[0] === node[0])
      const u = row ? row.slice(1) : [0, 0, 0]
      return { x: node[1] + u[0], y: node[2] + u[1] }
    })
    .reduce((best, current) =>
      Math.hypot(current.x, current.y) > Math.hypot(best.x, best.y) ? current : best,
    )
  const node = await at(page, bounds, reachable.x, reachable.y)
  await page.mouse.click(node.x, node.y)
  await expect(probe).toContainText('|U|')
  await page.getByLabel('Probe mode').selectOption('element')
  const elementPoint = await at(page, bounds, 8.0, 5.0)
  await page.mouse.click(elementPoint.x, elementPoint.y)
  await expect(probe).toContainText('source nodes')

  await page.screenshot({
    path: 'I:/GithubProjects/Abaqus_QualityOfLife/.local/milestone/results-after-displacement.png',
  })
})
