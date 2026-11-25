/**
 * Gate C/D: licensed app run from Dashboard, then the same measured node in
 * the ODB, the live Results view and the reopened `.aqresult`.
 *
 * Opt-in: set SEAL_DOOR_LICENSED=1 against an isolated server configured with
 * the real Abaqus launcher. It creates a model through the normal UI, imports
 * the DXF, configures roles/materials/mesh/fixture/motion, prepares the deck
 * with default outputs, submits, and reads the result back.
 */
import { writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test, type Page } from './fixtures'
import { saveRevision } from './save'
import type { Display } from '../src/viewportModel'

const LICENSED = process.env.SEAL_DOOR_LICENSED === '1'
const RUN_FILE = process.env.SEAL_DOOR_RUN_FILE
const EVIDENCE = process.env.SEAL_DOOR_EVIDENCE || process.cwd()
const OUTPUT = process.env.SEAL_DOOR_OUTPUT || ''
const STROKE = process.env.SEAL_DOOR_STROKE || '2.5'
const DURATION = process.env.SEAL_DOOR_DURATION || '0.5'

async function revisionId(page: Page) {
  return page.url().split('/').pop()!
}

async function assign(page: Page, region: string, card: string) {
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.getByRole('button', { name: 'Components' }).click()
  await page.locator('.region-list button', { hasText: region }).first().click()
  await page.getByTestId('assign-material').click()
  await page.getByLabel('Material card').selectOption({ label: card })
  await saveRevision(page)
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

test('licensed door pressure: deck, solve, CNORMF probe and spatial pressure', async ({
  page,
  request,
}) => {
  test.skip(!LICENSED, 'SEAL_DOOR_LICENSED is not set')
  test.setTimeout(900000)

  // --- Dashboard -> New project -> Import DXF.
  await page.goto('/#dashboard')
  await page.getByRole('button', { name: 'New project' }).click()
  await page.getByLabel('Project name').fill('Door pressure licensed')
  await page.getByRole('button', { name: 'Create project' }).click()
  await expect(page.locator('.subtitle')).toBeVisible()
  await page.locator('input[type=file]').setInputFiles(resolve('../../examples/hollow-section.dxf'))
  await expect(page.locator('.subtitle')).toContainText('hollow-section.dxf', { timeout: 60000 })
  await saveRevision(page)

  // --- Components: seal and moving door.
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  const tree = page.locator('.tree')
  await tree.getByRole('button', { name: /Imported section · Unassigned/ }).click()
  await page.getByLabel('Role').selectOption('seal')
  await tree.getByRole('button', { name: /Panel profile · Unassigned/ }).click()
  await page.getByLabel('Role').selectOption('moving_panel')
  await saveRevision(page)

  // --- Materials for both filled regions.
  await assign(page, 'Region 1', 'Cellular EPDM')
  await assign(page, 'Region 2', 'Dense EPDM')

  // --- Mesh.
  await workflow.getByRole('button', { name: 'Mesh' }).click()
  await page.getByRole('button', { name: 'Generate mesh', exact: true }).click()
  await expect(page.getByTestId('mesh-status')).toContainText('Mesh ready', { timeout: 90000 })

  // --- Mounting: box-select the weatherstrip foot exactly as an engineer would.
  const revision = await (await request.get('/api/revisions/' + (await revisionId(page)))).json()
  const display: Display = await (await request.post('/api/display', { data: revision.setup })).json()
  await workflow.getByRole('button', { name: 'Mounting' }).click()
  await page.getByLabel('Fixed-node box mode').check()
  await page.getByRole('button', { name: 'Fit and reset view' }).click()
  const viewport = page.getByRole('application')
  const box = (await viewport.boundingBox())!
  const [xmin, xmax, ymin, ymax] = display.bounds
  const scale = Math.min(box.width / (xmax - xmin), box.height / (ymax - ymin)) / 1.2
  const at = (x: number, y: number) => ({
    x: box.x + box.width / 2 + (x - (xmin + xmax) / 2) * scale,
    y: box.y + box.height / 2 - (y - (ymin + ymax) / 2) * scale,
  })
  const a = at(-10, -0.5)
  const b = at(10, 3.3)
  await page.mouse.move(a.x, a.y)
  await page.mouse.down()
  await page.mouse.move(b.x, b.y, { steps: 6 })
  await page.mouse.up()
  await page.getByRole('button', { name: 'Save fixed nodes' }).click()
  await expect(page.getByTestId('fixture-count')).not.toHaveText('0')
  await saveRevision(page)

  // --- Motion: a closing stroke that reaches the seal.
  await workflow.getByRole('button', { name: 'Motion' }).click()
  await page.getByLabel('Door panel stroke (mm)').fill(STROKE)
  await page.getByLabel('Door panel stroke (mm)').press('Tab')
  await page.getByLabel('Step duration (s)').fill(DURATION)
  await page.getByLabel('Step duration (s)').press('Tab')
  await saveRevision(page)
  // The default output plan is on; the control is visible and checked.
  await expect(page.getByTestId('door-pressure-output')).toBeChecked()

  // --- Prepare with the default output settings and inspect the deck.
  await workflow.locator('[data-stage="results"]').click()
  const prepare = page.getByRole('button', { name: 'Prepare input deck' })
  await expect(prepare).toBeEnabled({ timeout: 30000 })
  await prepare.click()
  await expect(page.getByTestId('deck-status')).toContainText('Input ready', { timeout: 90000 })
  const href = await page.getByRole('link', { name: 'Inspect input deck' }).getAttribute('href')
  const inp = await (await request.get(href!)).text()
  expect(inp).toContain('DOOR_PROFILE_NODES')
  expect(inp).toMatch(/\*Contact Output, nset=DOOR_PROFILE_NODES\r?\nCFORCE/)
  expect(inp).toMatch(/\*Contact Output\r?\nCSTRESS/)
  expect(inp).toMatch(/\*Node Output, nset=PANEL_RP\r?\nU1, U2, RF1, RF2/)

  // --- Submit through the normal action group.
  await page.getByLabel('Run name').fill('Door pressure licensed')
  if (OUTPUT) await page.getByTestId('output-dir').fill(OUTPUT)
  const submit = page.getByRole('button', { name: 'Submit Abaqus analysis' })
  await expect(submit).toBeEnabled()
  await submit.click()
  await page.waitForURL('**/#diagnostics/*')
  const jobId = page.url().split('/').pop()!
  if (RUN_FILE) writeFileSync(RUN_FILE, jobId)
  await expect
    .poll(
      async () => ((await (await request.get('/api/jobs/' + jobId)).json()) as { status: string }).status,
      { timeout: 600000, intervals: [2000] },
    )
    .toBe('Completed')
  const job = await (await request.get('/api/jobs/' + jobId)).json()
  expect(job.solver).toBe('Succeeded')
  expect(job.extraction).toBe('Succeeded')

  // --- Results: the default field is von Mises; CNORMF is selectable.
  await page.goto('/#results/' + jobId)
  await expect(page.getByTestId('run-complete')).toBeVisible({ timeout: 60000 })
  const field = page.getByLabel('Field')
  await expect(field.locator('option', { hasText: 'CNORMF (contact normal force)' })).toHaveCount(1)
  await expect(field.locator('option', { hasText: 'von Mises' })).toHaveCount(1)
  await expect(field.locator('option', { hasText: 'Displacement magnitude' })).toHaveCount(1)
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

  // Find the measured nonzero node in the last extracted frame.
  const peak = await page.evaluate(async ({ jobId }) => {
    const index = await (await fetch('/api/jobs/' + jobId + '/artifacts/results.json')).json()
    const last = index.frames[index.frames.length - 1]
    const frame = await (await fetch('/api/jobs/' + jobId + '/artifacts/' + last.file)).json()
    let best: Record<string, unknown> | null = null
    for (const profile of index.door_pressure.profiles) {
      const data = frame.door_pressure.profiles[profile.id]
      if (!data) continue
      data.pressure_kpa.forEach((pressure: number | null, position: number) => {
        if (pressure === null || pressure <= 0) return
        if (!best || pressure > (best.pressure as number)) {
          best = {
            profile: profile.alias,
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
  }, { jobId })
  expect(peak).not.toBeNull()
  const measured = peak as {
    profile: string
    node: number
    station: number
    pressure: number
    native: number
    force: number[]
  }
  expect(measured.pressure).toBeGreaterThan(0)
  const profileSelect = page.getByTestId('pressure-profile')
  if (await profileSelect.count()) await profileSelect.selectOption({ label: measured.profile })
  await expect(page.getByTestId('pressure-chart')).toHaveAttribute('data-positive', /[1-9]/)

  // Select the measured peak station on the spatial graph and read the same
  // node, station, kPa, native MPa and signed CNORMF components.
  await page.getByTestId('pressure-chart').scrollIntoViewIfNeeded()
  const point = await plotPoint(page, measured.station, measured.pressure)
  await page.mouse.click(point.x, point.y)
  const readout = page.getByTestId('pressure-readout')
  await expect(readout).toHaveAttribute('data-node', String(measured.node), { timeout: 10000 })
  expect(Number(await readout.getAttribute('data-station'))).toBeCloseTo(measured.station, 4)
  expect(Number(await readout.getAttribute('data-pressure'))).toBeCloseTo(measured.pressure, 4)
  expect(Number(await readout.getAttribute('data-native-mpa'))).toBeCloseTo(measured.native, 7)
  const arrows = Number(
    await page.locator('.seal-vtk-host').getAttribute('data-pressure-arrows'),
  )
  expect(arrows).toBeGreaterThan(0)

  // The same node as a live CNORMF probe: signed components in N.
  await field.selectOption('CNormf')
  await page.locator('.seal-vtk-host').scrollIntoViewIfNeeded()
  const hostBox = (await page.locator('.seal-vtk-host').boundingBox())!
  const anchor = (await page.locator('.seal-vtk-host').getAttribute('data-pressure-anchor'))!
    .split(',')
    .map(Number)
  await page.mouse.click(hostBox.x + anchor[0], hostBox.y + anchor[1])
  const magnitude = Math.hypot(...measured.force)
  await expect(page.locator('.legend')).toContainText('CNORMF', { timeout: 10000 })
  await expect(page.locator('.legend')).toContainText(magnitude.toPrecision(4))
  await field.selectOption('mises')
  await expect(field).toHaveValue('mises')
  await expect(page.locator('.seal-vtk-legend')).toContainText('von Mises')
  await field.selectOption('Umag')
  await expect(field).toHaveValue('Umag')
  await expect(page.locator('.seal-vtk-legend')).toContainText('Displacement magnitude')

  await page.screenshot({ path: EVIDENCE + '/gate-c-app-en.png', fullPage: false })
  await page.locator('.lang-button').click()
  await expect(page.getByRole('heading', { name: 'ドアパネル接触圧' })).toBeVisible()
  await page.screenshot({ path: EVIDENCE + '/gate-c-app-ja.png', fullPage: false })

  if (RUN_FILE) {
    writeFileSync(
      RUN_FILE + '.json',
      JSON.stringify(
        {
          job: jobId,
          input_hash: job.input_hash,
          measured,
          arrows,
          ui_pressure: Number(await readout.getAttribute('data-pressure')),
          ui_force: [
            Number(await readout.getAttribute('data-fx')),
            Number(await readout.getAttribute('data-fy')),
          ],
        },
        null,
        2,
      ),
    )
  }
})
