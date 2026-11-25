/**
 * Gate A: both original OTR drawings through the normal built-app workflow.
 *
 * Import → Components (seal / upper door / lower body) → Materials (filled seal
 * only, cavities empty) → Mesh → Mounting (reviewed nodes) → Contact/Motion
 * (upward body / downward door, 10 mm) → Results → Prepare.
 *
 * This is input-deck evidence only. It does not launch a licensed solver; the
 * separate licensed packages are exercised by the export specs.
 */
import { resolve } from 'node:path'
import { expect, test, type Page } from './fixtures'
import { saveRevision } from './save'
import type { Revision } from '../src/api'
import type { Display } from '../src/viewportModel'

async function importDrawing(page: Page, file: string) {
  const input = page.locator('input[type=file]')
  await input.setInputFiles(resolve('../../examples/' + file))
  await expect(page.locator('.subtitle')).toContainText(file, { timeout: 90000 })
  await expect(page.locator('.crumb')).toContainText('Revision 02', { timeout: 90000 })
  return page.url().split('/').pop()!
}

async function currentRevision(
  page: Page,
  request: import('@playwright/test').APIRequestContext,
) {
  return (await (
    await request.get('/api/revisions/' + page.url().split('/').pop())
  ).json()) as Revision
}

function meanY(setup: Revision['setup'], component: string) {
  const vertices = new Map(setup.vertices.map((vertex) => [vertex.id, vertex.xyz]))
  const values: number[] = []
  for (const edge of setup.edges.filter((item) => item.component === component)) {
    for (const id of [edge.start, edge.end]) {
      const point = vertices.get(id)
      if (point) values.push(point[1])
    }
  }
  return values.reduce((sum, value) => sum + value, 0) / Math.max(1, values.length)
}

async function runOtrWorkflow(page: Page, request: import('@playwright/test').APIRequestContext, file: string) {
  const empty: Revision = await (
    await request.post('/api/projects', { data: { name: 'OTR workflow ' + file } })
  ).json()
  await page.goto('/#workspace/' + empty.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.locator('[data-stage="import"]').click()
  const revisionId = await importDrawing(page, file)
  const revision: Revision = await (
    await request.get('/api/revisions/' + revisionId)
  ).json()
  const setup = revision.setup
  const names = new Map(setup.components.map((component) => [component.id, component.name]))
  const seal = setup.components.find((component) => component.id === 'section')!.id
  const panels = setup.components.filter((component) => component.id !== seal)
  const ordered = [...panels].sort((a, b) => meanY(setup, b.id) - meanY(setup, a.id))
  const door = ordered[0].id
  const body = ordered[1].id
  expect(meanY(setup, door)).toBeGreaterThan(meanY(setup, body))

  // --- Components: assign the actual seal, upper door and lower body.
  await workflow.locator('[data-stage="components"]').click()
  const tree = page.locator('.tree')
  const assignRole = async (component: string, role: string) => {
    await tree
      .getByRole('button', { name: new RegExp(names.get(component)! + ' · Unassigned') })
      .click()
    await page.getByLabel('Role').selectOption(role)
  }
  await assignRole(seal, 'seal')
  await assignRole(door, 'moving_panel')
  await assignRole(body, 'vehicle_body')
  await saveRevision(page)
  await expect(workflow.locator('[data-stage="components"]')).toHaveAttribute(
    'data-state',
    'complete',
  )

  // --- Materials: the filled seal region only; both cavities stay empty.
  // The region list belongs to the selected seal component, not the body.
  await tree
    .getByRole('button', {
      name: new RegExp(
        '^' + names.get(seal)!.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ' · ',
      ),
    })
    .click()
  await page.locator('.region-list button', { hasText: 'Region 1' }).first().click()
  await page.getByTestId('assign-material').click()
  await page.getByLabel('Material card').selectOption({ label: 'Cellular EPDM' })
  await saveRevision(page)
  const saved = await currentRevision(page, request)
  const filled = saved.setup.faces.filter((face) => !face.cavity)
  expect(filled).toHaveLength(1)
  expect(filled[0].material).toBeTruthy()
  expect(saved.setup.faces.filter((face) => face.cavity).every((face) => !face.material)).toBe(
    true,
  )

  // --- Mesh.
  await workflow.getByRole('button', { name: 'Mesh' }).click()
  await page.getByRole('button', { name: 'Generate mesh', exact: true }).click()
  await expect(page.getByTestId('mesh-status')).toContainText('Mesh ready', { timeout: 90000 })

  // --- Mounting: the lowest seal boundary is a reviewed node band.
  await workflow.getByRole('button', { name: 'Mounting' }).click()
  const display: Display = await (
    await request.post('/api/display', { data: saved.setup })
  ).json()
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
  const a = at(xmin - 0.2, 1.7)
  const b = at(xmax + 0.2, 2.4)
  await page.mouse.move(a.x, a.y)
  await page.mouse.down()
  await page.mouse.move(b.x, b.y, { steps: 8 })
  await page.mouse.up()
  await page.getByRole('button', { name: 'Save fixed nodes' }).click()
  await expect(page.getByTestId('fixture-count')).not.toHaveText('0')
  await expect(workflow.locator('[data-stage="mounting"]')).toHaveAttribute(
    'data-state',
    'complete',
  )

  // --- Motion: the operator's upward body and downward door, 10 mm each.
  await workflow.getByRole('button', { name: 'Motion' }).click()
  await page.getByLabel('Door panel stroke (mm)').fill('10')
  await page.getByLabel('Door panel direction angle (°)').fill('-90')
  await page.getByLabel('Body panel stroke (mm)').fill('10')
  await page.getByLabel('Body panel direction angle (°)').fill('90')
  await page.getByLabel('Body panel direction angle (°)').press('Tab')
  await saveRevision(page)

  // --- Prepare, inspect and download the actual deck.
  await workflow.locator('[data-stage="results"]').click()
  const prepare = page.getByRole('button', { name: 'Prepare input deck' })
  await expect(prepare).toBeEnabled({ timeout: 30000 })
  await prepare.click()
  await expect(page.getByTestId('deck-status')).toContainText('Input ready', {
    timeout: 90000,
  })
  const inspect = page.getByRole('link', { name: 'Inspect input deck' })
  const href = await inspect.getAttribute('href')
  const inp = await (await request.get(href!)).text()
  expect(inp).toContain('*Step, name=Body seating')
  expect(inp).toContain('*Step, name=Closing')
  expect(inp.match(/\*Solid Section/g)?.length).toBe(1)
  expect(inp).toContain('*Contact Output, nset=DOOR_PROFILE_NODES')
  const wsfix = /\*Nset, nset=WSFIX, instance=WS-1\r?\n([^\r\n]+)/.exec(inp)
  expect(wsfix).not.toBeNull()
  expect(wsfix![1].split(',').length).toBeGreaterThan(1)
  const download = page.waitForEvent('download')
  await page.getByRole('link', { name: 'Download INP' }).click()
  const downloaded = await download
  const path = await downloaded.path()
  expect(path).toBeTruthy()
  expect(downloaded.suggestedFilename()).toContain('.inp')
  const bytes = await (await request.get(href!)).body()
  expect(bytes.length).toBeGreaterThan(1000)

  // Submit becomes available only for the current deck with valid run fields.
  await page.getByLabel('Run name').fill('OTR ' + file)
  const submit = page.getByRole('button', { name: 'Submit Abaqus analysis' })
  await expect(submit).toBeEnabled({ timeout: 30000 })
  await expect(page.getByTestId('submit-reason')).not.toContainText('Prepare')
  return { revision: revisionId, deck: await page.getByTestId('deck-status').innerText() }
}

for (const file of ['OTR.dwg', 'OTR_single.dwg']) {
  test(`${file} completes the normal workflow and prepares a two-step deck`, async ({
    page,
    request,
  }) => {
    test.setTimeout(240000)
    const result = await runOtrWorkflow(page, request, file)
    expect(result.deck).toContain('Input ready')
  })
}
