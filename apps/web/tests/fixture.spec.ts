import { expect, test, type Page } from './fixtures'
import type { Display, ViewMesh } from '../src/viewportModel'
import type { Job, Revision } from '../src/api'

/** Screen mapping of the fitted 2D viewport, as the picking tests use it. */
function projector(bounds: number[]) {
  return async (page: Page, x: number, y: number, dx = 0, dy = 0) => {
    const viewport = page.getByRole('application', { name: '2D engineering viewport' })
    const box = (await viewport.boundingBox())!
    const [xmin, xmax, ymin, ymax] = bounds
    const scale = Math.min(box.width / (xmax - xmin), box.height / (ymax - ymin)) / 1.2
    return {
      x: box.x + box.width / 2 + (x - (xmin + xmax) / 2) * scale + dx,
      y: box.y + box.height / 2 - (y - (ymin + ymax) / 2) * scale + dy,
    }
  }
}

async function dragBox(page: Page, a: { x: number; y: number }, b: { x: number; y: number }) {
  await page.mouse.move(a.x, a.y)
  await page.mouse.down()
  await page.mouse.move(b.x, b.y, { steps: 8 })
  await page.mouse.up()
}

async function count(page: Page) {
  const text = await page
    .locator('.property-body dl div')
    .filter({ hasText: 'Selected nodes' })
    .locator('dd')
    .textContent()
  return Number(text)
}

async function openMeshStage(page: Page, revision: Revision) {
  await page.goto('/#workspace/' + revision.id)
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Mesh' })
    .click()
}

async function generateMesh(page: Page) {
  await page.getByRole('button', { name: 'Generate mesh', exact: true }).click()
  await expect(page.getByTestId('mesh-status')).toContainText('Mesh ready', { timeout: 60000 })
}

async function meshJob(request: import('@playwright/test').APIRequestContext, revision: Revision) {
  const all: Job[] = await (await request.get('/api/meshes')).json()
  return all.find((j) => j.revision === revision.id && j.status === 'Completed')!
}

async function meshModel(request: import('@playwright/test').APIRequestContext, job: Job) {
  return (await (await request.get('/api/jobs/' + job.id + '/artifacts/mesh.json')).json()) as ViewMesh
}

test('box-select fixed nodes, save, reopen and write exactly that WSFIX', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Box selection' } })
  ).json()
  const bounds: Display = await (
    await request.post('/api/display', { data: revision.setup })
  ).json()
  await openMeshStage(page, revision)
  await generateMesh(page)

  const prepare = page.getByRole('button', { name: 'Prepare input deck' })
  await expect(prepare).toBeDisabled()
  await page.getByLabel('Fixed-node box mode').check()
  await page.getByRole('button', { name: 'Fit and reset view' }).click()

  const at = projector(bounds.bounds)
  const job = await meshJob(request, revision)
  const model = await meshModel(request, job)
  const deformable = new Set(
    model.elements.filter((e) => e.type !== 'R2D2').flatMap((e) => e.nodes),
  )

  // Zoom and pan first: camera gestures must stay usable and must not break the
  // screen mapping used by the selection rectangle.
  await page.getByRole('button', { name: 'Zoom in' }).click()
  await page.getByRole('button', { name: 'Zoom in' }).click()
  await page.getByRole('button', { name: 'Fit and reset view' }).click()
  const foot = page.getByRole('application', { name: '2D engineering viewport' })
  const box = (await foot.boundingBox())!
  await page.keyboard.down('Shift')
  await dragBox(page, { x: box.x + 40, y: box.y + 40 }, { x: box.x + 120, y: box.y + 90 })
  await page.keyboard.up('Shift')

  // Select the mounting-foot band, offset by the pan applied above.
  const PAN = { dx: 80, dy: 50 }
  await dragBox(
    page,
    await at(page, -10, -0.6, PAN.dx, PAN.dy),
    await at(page, 10, 1.4, PAN.dx, PAN.dy),
  )
  const partial = await count(page)
  expect(partial).toBeGreaterThan(0)

  // Add a second band, then subtract the first one again.
  await page.getByLabel('Rectangle operation').selectOption('add')
  await dragBox(
    page,
    await at(page, -10, 1.4, PAN.dx, PAN.dy),
    await at(page, 10, 3.3, PAN.dx, PAN.dy),
  )
  const added = await count(page)
  expect(added).toBeGreaterThan(partial)
  await page.getByLabel('Rectangle operation').selectOption('subtract')
  await dragBox(
    page,
    await at(page, -10, -0.6, PAN.dx, PAN.dy),
    await at(page, 10, 1.4, PAN.dx, PAN.dy),
  )
  expect(await count(page)).toBe(added - partial)

  // Clear, then select the whole model: rigid-panel nodes must be excluded.
  await page.getByRole('button', { name: 'Clear selection' }).click()
  expect(await count(page)).toBe(0)
  await page.getByRole('button', { name: 'Fit and reset view' }).click()
  await page.getByLabel('Rectangle operation').selectOption('replace')
  await dragBox(page, await at(page, -12, -1), await at(page, 12, 16))
  expect(await count(page)).toBe(deformable.size)

  // Redo the partial mounting-foot selection and save it.
  await page.getByRole('button', { name: 'Clear selection' }).click()
  await dragBox(page, await at(page, -10, -0.6), await at(page, 10, 1.4))
  const selected = await count(page)
  await page.getByRole('button', { name: 'Save fixed nodes' }).click()
  await expect(page.getByText('Saved ' + selected + ' fixed nodes.').first()).toBeVisible()

  const stored: Job = await (await request.get('/api/jobs/' + job.id)).json()
  expect(stored.fixture?.count).toBe(selected)
  expect(stored.fixture!.labels.every((l) => l.startsWith('WS-1:'))).toBe(true)
  // A partial region never expands to a whole CAD edge or to every seal node.
  expect(stored.fixture!.labels.length).toBeLessThan(deformable.size)

  await expect(prepare).toBeEnabled()
  await prepare.click()
  await expect(page.getByTestId('deck-status')).toContainText('Input ready', { timeout: 60000 })
  const href = await page.getByRole('link', { name: 'Inspect input deck' }).getAttribute('href')
  const deck = await (await request.get(href!)).text()
  const written = deck
    .split('*Nset, nset=WSFIX')[1]
    .split('\n')
    .slice(1)
    .join('\n')
    .split('*')[0]
    .split(/[,\n]/)
    .map((value) => value.trim())
    .filter(Boolean)
    .map(Number)
  expect(written.sort((a, b) => a - b)).toEqual(
    stored.fixture!.labels.map((l) => Number(l.split(':')[1])).sort((a, b) => a - b),
  )
  const unselected = [...deformable].filter((n) => !written.includes(n))
  expect(unselected.length).toBeGreaterThan(0)

  // Reopen: the reviewed fixture comes back, highlighted, without remeshing.
  await page.reload()
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Mesh' })
    .click()
  await expect(page.getByTestId('mesh-status')).toContainText('Mesh ready', { timeout: 30000 })
  expect(await count(page)).toBe(selected)
  await expect(page.getByText('Reviewed mesh nodes')).toBeVisible()
  const meshes: Job[] = await (await request.get('/api/meshes')).json()
  expect(meshes.filter((j) => j.revision === revision.id)).toHaveLength(1)
})

test('a motion edit reuses the mesh and a remesh forces fixture review', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Reuse and remesh' } })
  ).json()
  const bounds: Display = await (await request.post('/api/display', { data: revision.setup })).json()
  await openMeshStage(page, revision)
  await generateMesh(page)
  await page.getByLabel('Fixed-node box mode').check()
  await page.getByRole('button', { name: 'Fit and reset view' }).click()
  const at = projector(bounds.bounds)
  await dragBox(page, await at(page, -10, -0.6), await at(page, 10, 1.4))
  await page.getByRole('button', { name: 'Save fixed nodes' }).click()
  await page.getByRole('button', { name: 'Prepare input deck' }).click()
  await expect(page.getByTestId('deck-status')).toContainText('Input ready', { timeout: 60000 })

  // Panel travel does not change mesh identity.
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Motion' })
    .click()
  await page.getByLabel('Prescribed Y travel (mm)').fill('-5')
  await page.getByLabel('Prescribed Y travel (mm)').press('Tab')
  await page.getByRole('button', { name: 'Save revision' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 02')
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Mesh' })
    .click()
  await expect(page.getByTestId('mesh-status')).toContainText('Mesh ready', { timeout: 30000 })
  // The prepared deck was for the previous revision, so it is not submittable.
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Review / Run' })
    .click()
  await expect(page.getByRole('button', { name: 'Submit demo run' })).toBeDisabled()
  const before = await (await request.get('/api/meshes')).json()
  expect(before.filter((j: Job) => j.revision === revision.id)).toHaveLength(1)

  // Changing the mesh size invalidates the mesh and the reviewed fixture.
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Mesh' })
    .click()
  await page.getByLabel('Global size (mm)').fill('0.8')
  await page.getByLabel('Global size (mm)').press('Tab')
  await page.getByRole('button', { name: 'Save revision' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 03')
  await expect(page.getByTestId('mesh-status')).toContainText(
    'These mesh inputs changed. Generate the mesh again.',
    { timeout: 30000 },
  )
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toHaveCount(0)
  await expect(page.getByText('Fixed nodes (WSFIX)')).toHaveCount(0)

  await generateMesh(page)
  await expect(page.getByText('Fixed nodes (WSFIX)')).toBeVisible()
  expect(await count(page)).toBe(0)
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toBeDisabled()
})

test.describe('high-DPI selection', () => {
  test.use({ deviceScaleFactor: 2 })

  test('a selection rectangle still hits the nodes it covers', async ({ page, request }) => {
    const revision: Revision = await (
      await request.post('/api/projects', { data: { name: 'High DPI' } })
    ).json()
    const bounds: Display = await (
      await request.post('/api/display', { data: revision.setup })
    ).json()
    await openMeshStage(page, revision)
    await generateMesh(page)
    await page.getByLabel('Fixed-node box mode').check()
    await page.getByRole('button', { name: 'Fit and reset view' }).click()
    const at = projector(bounds.bounds)
    await dragBox(page, await at(page, -10, -0.6), await at(page, 10, 1.4))
    expect(await count(page)).toBeGreaterThan(0)
    await page.getByRole('button', { name: 'Save fixed nodes' }).click()
    const job = await meshJob(request, revision)
    const stored: Job = await (await request.get('/api/jobs/' + job.id)).json()
    expect(stored.fixture!.labels.every((l) => l.startsWith('WS-1:'))).toBe(true)
  })
})

test('an in-progress fixed-node selection survives a language switch', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Fixture locale' } })
  ).json()
  const bounds: Display = await (await request.post('/api/display', { data: revision.setup })).json()
  await openMeshStage(page, revision)
  await generateMesh(page)
  await page.getByLabel('Fixed-node box mode').check()
  await page.getByRole('button', { name: 'Fit and reset view' }).click()
  const at = projector(bounds.bounds)
  await dragBox(page, await at(page, -10, -0.6), await at(page, 10, 1.4))
  const selected = await count(page)
  expect(selected).toBeGreaterThan(0)
  expect(await page.getByText(/nodes selected\. They are not used until you save\./).count()).toBe(1)

  await page.locator('.lang-picker select').selectOption('ja')

  await expect(page.getByRole('heading', { name: '固定節点（WSFIX）' })).toBeVisible()
  await expect(page.getByLabel('矩形選択モード')).toBeChecked()
  await expect(
    page.getByText(selected + ' 節点を選択中です。保存するまで解析には使われません。'),
  ).toBeVisible()
  await expect(page.getByRole('button', { name: '固定節点を保存' })).toBeEnabled()
  // The pending count is unchanged by the language switch.
  expect(
    Number(
      await page
        .locator('.property-body dl div')
        .filter({ hasText: '選択節点数' })
        .locator('dd')
        .textContent(),
    ),
  ).toBe(selected)
})
