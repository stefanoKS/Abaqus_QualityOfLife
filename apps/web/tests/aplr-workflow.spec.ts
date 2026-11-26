/**
 * Gate 1: the original APLR drawing through the normal built-app workflow.
 *
 * Native DWG upload → Components (seal / upper door / lower body) → Materials
 * (filled seal only, both cavities empty) → Mesh → Mounting → Motion (upward
 * body / downward door, 10 mm) → Results → Prepare, plus component picking,
 * independent motion previews and a fresh `.aqmodel` reopen.
 *
 * This is input-deck evidence only. It launches no licensed solver.
 */
import { existsSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { expect, test, type Page } from './fixtures'
import { saveRevision } from './save'
import type { Revision } from '../src/api'
import type { Display } from '../src/viewportModel'

const drawing = resolve('../../examples/APLR.dwg')

async function currentRevision(
  page: Page,
  request: import('@playwright/test').APIRequestContext,
) {
  return (await (await request.get('/api/revisions/' + page.url().split('/').pop())).json()) as Revision
}

async function importDrawing(page: Page, file: string) {
  const input = page.locator('input[type=file]')
  await input.setInputFiles(file)
  await expect(page.locator('.subtitle')).toContainText('APLR.dwg', { timeout: 120000 })
  await expect(page.locator('.crumb')).toContainText('Revision 02', { timeout: 120000 })
  return page.url().split('/').pop()!
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

function longestLine(setup: Revision['setup'], component: string) {
  const vertices = new Map(setup.vertices.map((vertex) => [vertex.id, vertex.xyz]))
  let best: { x: number; y: number; length: number } | null = null
  for (const edge of setup.edges.filter((item) => item.component === component && item.kind === 'line')) {
    const a = vertices.get(edge.start)!
    const b = vertices.get(edge.end)!
    const length = Math.hypot(b[0] - a[0], b[1] - a[1])
    if (!best || length > best.length) {
      best = { x: (a[0] + b[0]) / 2, y: (a[1] + b[1]) / 2, length }
    }
  }
  return best!
}

function project(
  box: { x: number; y: number; width: number; height: number },
  camera: number[],
  x: number,
  y: number,
) {
  const scale = camera[6]
  const aspect = box.width / box.height
  return {
    x: box.x + box.width / 2 + ((x - camera[3]) / (scale * aspect)) * (box.width / 2),
    y: box.y + box.height / 2 - ((y - camera[4]) / scale) * (box.height / 2),
  }
}

test('original APLR imports one door and one body, keeps both cavities, and prepares', async ({
  page,
  request,
}) => {
  test.skip(!existsSync(drawing), 'original APLR drawing is not present locally')
  test.setTimeout(300000)

  const empty: Revision = await (
    await request.post('/api/projects', { data: { name: 'APLR workflow' } })
  ).json()
  await page.goto('/#workspace/' + empty.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.locator('[data-stage="import"]').click()
  const revisionId = await importDrawing(page, drawing)
  const revision: Revision = await (await request.get('/api/revisions/' + revisionId)).json()
  const setup = revision.setup

  // Exactly one filled seal region and its two cavities; three components.
  expect(setup.components).toHaveLength(3)
  expect(setup.faces.filter((face) => face.cavity)).toHaveLength(2)
  const filled = setup.faces.filter((face) => !face.cavity)
  expect(filled).toHaveLength(1)
  const seal = filled[0].component
  const panels = setup.components.filter((component) => component.id !== seal)
  expect(panels).toHaveLength(2)
  const ordered = [...panels].sort((a, b) => meanY(setup, b.id) - meanY(setup, a.id))
  const door = ordered[0].id
  const body = ordered[1].id
  expect(meanY(setup, door)).toBeGreaterThan(meanY(setup, body))
  const names = new Map(setup.components.map((component) => [component.id, component.name]))

  // --- Components: assign the actual seal, upper door and lower body.
  await workflow.locator('[data-stage="components"]').click()
  const tree = page.locator('.tree')
  const assignRole = async (component: string, role: string) => {
    await tree
      .getByRole('button', { name: new RegExp(names.get(component)!.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ' · Unassigned') })
      .click()
    await page.getByLabel('Role').selectOption(role)
  }
  await assignRole(seal, 'seal')
  await assignRole(door, 'moving_panel')
  await assignRole(body, 'vehicle_body')
  await saveRevision(page)
  await expect(workflow.locator('[data-stage="components"]')).toHaveAttribute('data-state', 'complete')

  // --- Pick the upper door and the lower body from their rendered positions.
  await expect
    .poll(async () => page.locator('.seal-vtk-host').getAttribute('data-camera'))
    .toBeTruthy()
  const viewport = page.getByRole('application', { name: '2D engineering viewport' })
  const box = (await viewport.boundingBox())!
  const camera = (await page.locator('.seal-vtk-host').getAttribute('data-camera'))!
    .split(',')
    .map(Number)
  const status = page.getByRole('status')
  const doorPoint = project(box, camera, longestLine(setup, door).x, longestLine(setup, door).y)
  await page.mouse.click(doorPoint.x, doorPoint.y)
  await expect(status).toContainText('Selected · ' + names.get(door))
  const bodyPoint = project(box, camera, longestLine(setup, body).x, longestLine(setup, body).y)
  await page.mouse.click(bodyPoint.x, bodyPoint.y)
  await expect(status).toContainText('Selected · ' + names.get(body))

  // --- Materials: the one filled weatherstrip region only; both cavities empty.
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
  expect(saved.setup.faces.filter((face) => !face.cavity)).toHaveLength(1)
  expect(saved.setup.faces.filter((face) => !face.cavity)[0].material).toBeTruthy()
  expect(saved.setup.faces.filter((face) => face.cavity).every((face) => !face.material)).toBe(true)
  expect(saved.setup.edges.filter((edge) => edge.source_handle === 'FA')).toHaveLength(1)
  expect(saved.setup.edges.filter((edge) => ['FA', 'FB', 'FC', 'FD', 'FE', 'FF', '100', '101'].includes(edge.source_handle!)).length).toBeGreaterThanOrEqual(8)

  // --- Mesh.
  await workflow.getByRole('button', { name: 'Mesh' }).click()
  await page.getByRole('button', { name: 'Generate mesh', exact: true }).click()
  await expect(page.getByTestId('mesh-status')).toContainText('Mesh ready', { timeout: 120000 })

  // --- Mounting: a reviewed node band on the lowest seal boundary.
  await workflow.getByRole('button', { name: 'Mounting' }).click()
  const display: Display = await (await request.post('/api/display', { data: saved.setup })).json()
  await page.getByLabel('Fixed-node box mode').check()
  await page.getByRole('button', { name: 'Fit and reset view' }).click()
  await expect
    .poll(async () => page.locator('.seal-vtk-host').getAttribute('data-camera'))
    .toBeTruthy()
  const mountBox = (await viewport.boundingBox())!
  const mountCamera = (await page.locator('.seal-vtk-host').getAttribute('data-camera'))!
    .split(',')
    .map(Number)
  const sealVertices = saved.setup.vertices.filter((vertex) =>
    saved.setup.edges.some((edge) => edge.component === seal && (edge.start === vertex.id || edge.end === vertex.id)),
  )
  const lowest = Math.min(...sealVertices.map((vertex) => vertex.xyz[1]))
  const [xmin, xmax] = display.bounds
  const at = (x: number, y: number) => project(mountBox, mountCamera, x, y)
  const a = at(xmin - 0.5, lowest + 0.9)
  const b = at(xmax + 0.5, lowest - 0.1)
  await page.mouse.move(a.x, a.y)
  await page.mouse.down()
  await page.mouse.move(b.x, b.y, { steps: 8 })
  await page.mouse.up()
  await page.getByRole('button', { name: 'Save fixed nodes' }).click()
  await expect(page.getByTestId('fixture-count')).not.toHaveText('0')
  await expect(workflow.locator('[data-stage="mounting"]')).toHaveAttribute('data-state', 'complete')

  // --- Motion: independent previews of the whole upper profile and the lower body.
  await workflow.getByRole('button', { name: 'Motion' }).click()
  await page.getByLabel('Door panel stroke (mm)').fill('10')
  await page.getByLabel('Door panel direction angle (°)').fill('-90')
  await page.getByLabel('Body panel stroke (mm)').fill('10')
  await page.getByLabel('Body panel direction angle (°)').fill('90')
  await page.getByLabel('Body panel direction angle (°)').press('Tab')
  await saveRevision(page)
  const final = await currentRevision(page, request)
  const translation = () => page.getByTestId('vtk-viewport').getAttribute('data-preview-translation')
  const cameraBefore = await page.locator('.seal-vtk-host').getAttribute('data-camera')
  await page.getByTestId('preview-door').click()
  await expect(page.getByRole('button', { name: 'Stop preview' })).toBeVisible()
  await expect.poll(translation).toContain('"' + door + '"')
  const doorPreview = JSON.parse((await translation())!) as Record<string, [number, number]>
  expect(Object.keys(doorPreview)).toEqual([door])
  expect(doorPreview[door][1]).toBeLessThan(0)
  await expect.poll(translation, { timeout: 10000 }).toBe('')
  await page.getByTestId('preview-body').click()
  await expect.poll(translation).toContain('"' + body + '"')
  const bodyPreview = JSON.parse((await translation())!) as Record<string, [number, number]>
  expect(Object.keys(bodyPreview)).toEqual([body])
  expect(bodyPreview[body][1]).toBeGreaterThan(0)
  await expect.poll(translation, { timeout: 10000 }).toBe('')
  expect(await page.locator('.seal-vtk-host').getAttribute('data-camera')).toBe(cameraBefore)

  // --- Prepare, inspect and download the actual two-step deck.
  await workflow.locator('[data-stage="results"]').click()
  const prepare = page.getByRole('button', { name: 'Prepare input deck' })
  await expect(prepare).toBeEnabled({ timeout: 30000 })
  await prepare.click()
  await expect(page.getByTestId('deck-status')).toContainText('Input ready', { timeout: 120000 })
  const inspect = page.getByRole('link', { name: 'Inspect input deck' })
  const href = await inspect.getAttribute('href')
  const inp = await (await request.get(href!)).text()
  expect(inp).toContain('*Step, name=Body seating')
  expect(inp).toContain('*Step, name=Closing')
  expect(inp.match(/\*Solid Section/g)?.length).toBe(1)
  expect(inp).toContain('*Contact Output, nset=DOOR_PROFILE_NODES')
  expect(inp).not.toContain('*Element, type=CONN')
  const panel = /\*Part, name=PANEL([\s\S]*?)\*End Part/.exec(inp)
  const bodyPart = /\*Part, name=BODY([\s\S]*?)\*End Part/.exec(inp)
  expect(panel).not.toBeNull()
  expect(bodyPart).not.toBeNull()
  const countR2D2 = (text: string) =>
    (/\*Element, type=R2D2[^\n]*\r?\n([\s\S]*?)(?=\r?\n\*)/.exec(text)?.[1].trim().split(/\r?\n/).length ?? 0)
  expect(countR2D2(panel![1])).toBe(58)
  expect(countR2D2(bodyPart![1])).toBe(122)
  const wsfix = /\*Nset, nset=WSFIX, instance=WS-1\r?\n([^\r\n]+)/.exec(inp)
  expect(wsfix).not.toBeNull()
  expect(wsfix![1].split(',').length).toBeGreaterThan(1)

  // --- Save a fresh `.aqmodel` and reopen it in the same tab.
  const folder = mkdtempSync(join(tmpdir(), 'aplr-aqmodel-'))
  await page.getByTestId('model-save-as').click()
  await page.getByTestId('save-as-dialog').getByLabel(/Folder|フォルダ/).fill(folder)
  await page.getByTestId('save-as-dialog').getByLabel(/File name|ファイル名/).fill('APLR.aqmodel')
  await page.getByTestId('save-as-confirm').click()
  const modelPath = join(folder, 'APLR.aqmodel')
  await expect.poll(() => existsSync(modelPath), { timeout: 30000 }).toBe(true)
  await page.getByRole('button', { name: /Dashboard|ダッシュボード/ }).first().click()
  await page.getByTestId('file-open-model').click()
  await page.getByTestId('file-bar').getByLabel(/Model file|モデルファイル/).fill(modelPath)
  await page.getByTestId('file-bar').getByRole('button', { name: /^Open$|^開く$/ }).click()
  await expect(page.getByTestId('model-file')).toContainText('APLR.aqmodel')
  const reopenedId = page.url().split('/').pop()!
  await expect
    .poll(async () => (await request.get('/api/revisions/' + reopenedId)).ok())
    .toBe(true)
  const reopened: Revision = await (await request.get('/api/revisions/' + reopenedId)).json()
  const beforeRoles = Object.fromEntries(final.setup.components.map((component) => [component.id, component.role]))
  const afterRoles = Object.fromEntries(reopened.setup.components.map((component) => [component.id, component.role]))
  expect(afterRoles).toEqual(beforeRoles)
  expect(reopened.setup.faces.filter((face) => face.cavity)).toHaveLength(2)
  const reopenedFilled = reopened.setup.faces.filter((face) => !face.cavity)
  expect(reopenedFilled).toHaveLength(1)
  expect(reopenedFilled[0].material).toBe(final.setup.faces.filter((face) => !face.cavity)[0].material)
  expect(reopened.setup.vertices).toHaveLength(final.setup.vertices.length)
  expect(reopened.setup.edges).toHaveLength(final.setup.edges.length)
  expect(reopened.setup.motion.stroke).toBe(10)
  expect(reopened.setup.motion.body.stroke).toBe(10)
  expect(reopened.setup.mesh.size).toBe(final.setup.mesh.size)
  expect(reopened.setup.faces.filter((face) => !face.cavity)[0].component).toBe(seal)
})
