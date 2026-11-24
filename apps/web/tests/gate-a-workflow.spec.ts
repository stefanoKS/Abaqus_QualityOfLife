/**
 * Gate A: the integrated left-panel workflow from an empty model and a real
 * DXF import through roles, a projected cut, materials, mesh, fixed nodes,
 * contact, motion, deck inspection, submission and results.
 *
 * The solver is the test launcher. No Review/Run stage or header shortcut may
 * remain, and Prepare/Submit are owned once by the left action group.
 */
import { randomUUID } from 'node:crypto'
import { resolve } from 'node:path'
import { expect, test, type Page } from './fixtures'
import type { Job, Revision } from '../src/api'
import type { Display } from '../src/viewportModel'

async function saveRevision(page: Page) {
  const save = page.getByRole('button', { name: 'Save revision' })
  await expect(save).toBeEnabled({ timeout: 20000 })
  await save.click()
}
async function projectPoint(page: Page, x: number, y: number) {
  const viewport = page.getByRole('application')
  const box = (await viewport.boundingBox())!
  const camera = (await page.locator('.seal-vtk-host').getAttribute('data-camera'))!
    .split(',')
    .map(Number)
  const fx = camera[3],
    fy = camera[4],
    scale = camera[6]
  const aspect = box.width / box.height
  return {
    x: box.x + box.width / 2 + ((x - fx) / (scale * aspect)) * (box.width / 2),
    y: box.y + box.height / 2 - ((y - fy) / scale) * (box.height / 2),
  }
}

async function drawGuide(page: Page, a: [number, number], b: [number, number]) {
  const first = await projectPoint(page, a[0], a[1])
  await page.mouse.move(first.x, first.y, { steps: 3 })
  await page.mouse.click(first.x, first.y)
  const second = await projectPoint(page, b[0], b[1])
  await page.mouse.move(second.x, second.y, { steps: 4 })
  await page.mouse.click(second.x, second.y)
}

test('empty model → DXF import → roles → cut → material → mesh → fixture → deck → run → results', async ({
  page,
  request,
}) => {
  const empty: Revision = await (
    await request.post('/api/projects', { data: { name: 'Gate A journey' } })
  ).json()
  expect(empty.setup.source.kind).toBe('empty')
  await page.goto('/#workspace/' + empty.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await expect(workflow.locator('[data-stage="review"]')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Review / Run' })).toHaveCount(0)
  await expect(page.getByTestId('action-group')).toHaveCount(1)
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toBeDisabled()

  // --- Import owns the chooser; Import is not complete while the model is empty.
  await expect(workflow.locator('[data-stage="import"]')).toHaveAttribute('data-state', 'incomplete')
  await page.locator('input[type=file]').setInputFiles(resolve('../../examples/hollow-section.dxf'))
  await expect(page.locator('.subtitle')).toContainText('hollow-section.dxf', { timeout: 60000 })
  await expect(page.locator('.crumb')).toContainText('Revision 02')
  await expect(workflow.locator('[data-stage="import"]')).toHaveAttribute('data-state', 'complete')

  // --- Components owns roles and the region list.
  const tree = page.locator('.tree')
  await tree.getByRole('button', { name: /Imported section · Unassigned/ }).click()
  await page.getByLabel('Role').selectOption('seal')
  await tree.getByRole('button', { name: /Panel profile · Unassigned/ }).click()
  await page.getByLabel('Role').selectOption('moving_panel')
  await tree.getByRole('button', { name: /Section 2 · Unassigned/ }).click()
  await page.getByLabel('Role').selectOption('seal')
  // Roles are a saved-revision state; Save before the badge can say complete.
  await saveRevision(page)
  await expect(page.locator('.crumb')).toContainText('Revision 03')
  await expect(workflow.locator('[data-stage="components"]')).toHaveAttribute('data-state', 'complete')

  // --- Materials: each material region gets a card via the explicit link.
  const assignedMaterial: Record<string, string> = {}
  const assign = async (region: string, material: string) => {
    await workflow.getByRole('button', { name: 'Components' }).click()
    await page.locator('.region-list button', { hasText: region }).first().click()
    await page.getByTestId('assign-material').click()
    await page.getByLabel('Material card').selectOption({ label: material })
    assignedMaterial[region] = material
  }
  await assign('Region 1', 'Cellular EPDM')
  await assign('Region 2', 'Dense EPDM')
  await saveRevision(page)
  await expect(page.locator('.crumb')).toContainText('Revision 04')
  await expect(workflow.locator('[data-stage="materials"]')).toHaveAttribute('data-state', 'complete')

  // --- Components owns the projected partition and keeps the operator there.
  // Face IDs/names from a DXF import are not guaranteed to pair the foot with a
  // fixed name, so identify the foot by its real y-extent and use that face.
  const currentRevision = (await (
    await request.get('/api/revisions/' + page.url().split('/').pop())
  ).json()) as Revision
  const display: Display = await (
    await request.post('/api/display', { data: currentRevision.setup })
  ).json()
  const foot = display.primitives
    .filter((primitive) => primitive.kind === 'face')
    .map((primitive) => ({
      entity: primitive.entity,
      ymax: Math.max(...primitive.points.map((point) => point[1])),
    }))
    .sort((first, second) => first.ymax - second.ymax)[0]
  const targetName = currentRevision.setup.faces.find((face) => face.id === foot.entity)!.name
  await workflow.getByRole('button', { name: 'Components' }).click()
  await page.locator('.region-list button', { hasText: targetName }).first().click()
  await expect(page.getByTestId('partition-target')).toContainText(targetName)
  await expect
    .poll(
      async () => {
        const first = await page.locator('.seal-vtk-host').getAttribute('data-camera')
        await page.waitForTimeout(120)
        return first === (await page.locator('.seal-vtk-host').getAttribute('data-camera'))
      },
      { timeout: 5000 },
    )
    .toBe(true)
  await page.getByRole('button', { name: 'Partition region' }).click()
  await drawGuide(page, [0, -1], [0, 4])
  await expect(page.getByTestId('partition-plan')).toHaveAttribute('data-status', 'valid')
  await page.getByRole('button', { name: 'Apply partition' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 05')
  // Still in Components after the cut; the region list now shows both children.
  const regionList = page.locator('.region-list')
  await expect(regionList).toContainText(targetName + ' A')
  await expect(regionList).toContainText(targetName + ' B')
  await workflow.getByRole('button', { name: 'Components' }).click()
  await page.locator('.region-list button', { hasText: targetName + ' A' }).first().click()
  await page.getByTestId('assign-material').click()
  const childMaterial =
    assignedMaterial[targetName] === 'Cellular EPDM' ? 'Dense EPDM' : 'Cellular EPDM'
  await page.getByLabel('Material card').selectOption({ label: childMaterial })
  await saveRevision(page)
  await expect(page.locator('.crumb')).toContainText('Revision 06')

  // --- Mesh.
  await workflow.getByRole('button', { name: 'Mesh' }).click()
  await page.getByRole('button', { name: 'Generate mesh', exact: true }).click()
  await expect(page.getByTestId('mesh-status')).toContainText('Mesh ready', { timeout: 60000 })

  // --- Mounting: FE box selection, save and reviewed-node status.
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
  await expect(workflow.locator('[data-stage="mounting"]')).toHaveAttribute('data-state', 'complete')

  // --- Contact and Motion are independent owners.
  await workflow.getByRole('button', { name: 'Contact' }).click()
  await expect(page.getByLabel('Door panel ↔ seal coefficient')).toHaveValue('0.7')
  await workflow.getByRole('button', { name: 'Motion' }).click()
  await page.getByLabel('Door panel stroke (mm)').fill('6.5')
  await page.getByLabel('Door panel stroke (mm)').press('Tab')
  await saveRevision(page)
  await expect(page.locator('.crumb')).toContainText('Revision 07')

  // --- Prepare by keyboard from the action group; inspect the deck.
  const prepare = page.getByRole('button', { name: 'Prepare input deck' })
  await expect(prepare).toBeEnabled({ timeout: 20000 })
  await prepare.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByTestId('deck-status')).toContainText('Input ready', { timeout: 60000 })
  const href = await page.getByRole('link', { name: 'Inspect input deck' }).getAttribute('href')
  const inp = await (await request.get(href!)).text()
  expect(inp).toMatch(/PANEL_RP,\s*2,\s*2,\s*-6\.5/)
  // One section per material region: Region 1 plus the two Region 2 children.
  expect(inp.match(/\*Solid Section/g)?.length).toBe(3)

  // --- Submit by keyboard, then open Results.
  await page.getByLabel('Run name').fill('Gate A run')
  const submit = page.getByRole('button', { name: 'Submit Abaqus analysis' })
  await expect(submit).toBeEnabled()
  await submit.focus()
  await page.keyboard.press('Enter')
  await page.waitForURL('**/#diagnostics/*')
  const runId = page.url().split('/').pop()!
  await expect
    .poll(async () => ((await (await request.get('/api/jobs/' + runId)).json()) as Job).status, {
      timeout: 90000,
    })
    .toBe('Completed')
  await page.reload()
  await page.getByRole('button', { name: 'Results', exact: true }).click({ timeout: 30000 })
  await expect(page.getByRole('heading', { name: 'Force–displacement' })).toBeVisible()
  await expect(page.locator('.run-banner')).toContainText('ABAQUS')
  await expect(page.locator('.js-plotly-plot')).toBeVisible()

  // The prepared deck is archived with the submitted revision and remains readable.
  await page.goto('/#setup/' + runId)
  await expect(page.getByTestId('action-locked')).toBeVisible()
  await expect(page.getByTestId('action-group')).toContainText('Submitted setup')
  await expect(workflow.locator('[data-stage="review"]')).toHaveCount(0)
})

test('the setup action group is reachable in both locales at desktop, narrow and 200% zoom', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Gate A layout', example: true } })
  ).json()
  // A mesh and fixture make the action group meaningful without a deck.
  const mesh: Job = await (
    await request.post('/api/meshes', { data: { revision: revision.id, token: randomUUID() } })
  ).json()
  await expect
    .poll(async () => ((await (await request.get('/api/jobs/' + mesh.id)).json()) as Job).status, {
      timeout: 60000,
    })
    .toBe('Completed')
  const fixture = await (
    await request.post('/api/meshes/' + mesh.id + '/fixture/edges', { data: {} })
  ).json()
  await request.put('/api/meshes/' + mesh.id + '/fixture', { data: { labels: fixture.labels } })

  for (const size of [
    { width: 1440, height: 900 },
    { width: 1280, height: 720 },
    { width: 720, height: 450 },
  ]) {
    await page.setViewportSize(size)
    await page.goto('/#workspace/' + revision.id)
    const group = page.getByTestId('action-group')
    await group.scrollIntoViewIfNeeded()
    await expect(group).toBeVisible()
    await expect(page.getByRole('button', { name: 'Prepare input deck' })).toBeEnabled()
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow).toBeLessThanOrEqual(1)
    await page.locator('.lang-button').click()
    await expect(page.getByRole('button', { name: '入力デッキを作成' })).toBeVisible()
    await page.locator('.lang-button').click()
    await expect(page.getByRole('button', { name: 'Prepare input deck' })).toBeVisible()
  }

  // Narrow layout uses the existing pane drawer rather than a duplicate toolbar.
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/#workspace/' + revision.id)
  const toggle = page.getByRole('button', { name: 'Workflow & properties' })
  await toggle.click()
  await toggle.click()
  await expect(page.locator('.workgrid > .left')).toBeVisible()
  await page.getByTestId('action-group').scrollIntoViewIfNeeded()
  await expect(page.getByTestId('action-group')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toHaveCount(1)
})

test('a migrated numeric stage index opens a useful setup stage, never a Review row', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Stage migration', example: true } })
  ).json()
  await page.addInitScript((id) => {
    sessionStorage.setItem('stage:' + id, '7')
    sessionStorage.setItem('stage-project:' + id, '7')
  }, revision.id)
  await page.goto('/#workspace/' + revision.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await expect(workflow.locator('[data-stage="motion"]')).toHaveAttribute('aria-current', 'step')
  await expect(workflow.locator('[data-stage="review"]')).toHaveCount(0)

  await page.addInitScript((id) => {
    sessionStorage.setItem('stage:' + id, '8')
  }, revision.id)
  await page.reload()
  await expect(workflow.locator('[data-stage="results"]')).toHaveAttribute('aria-current', 'step')
})
