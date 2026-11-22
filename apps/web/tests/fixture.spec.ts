import { expect, test, type Page } from './fixtures'
import { randomUUID } from 'node:crypto'
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
  return Number(await page.getByTestId('fixture-count').textContent())
}

async function openMeshStage(page: Page, revision: Revision) {
  await page.goto('/#workspace/' + revision.id)
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Mesh' })
    .click()
}

async function openReviewStage(page: Page) {
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Review / Run' })
    .click()
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toBeVisible()
}

/** Mounting owns the fixed-node controls; Mesh only produces the mesh. */
async function openMountingStage(page: Page) {
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Mounting' })
    .click()
  await expect(page.getByLabel('Fixed-node box mode')).toBeVisible()
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
  await openMountingStage(page)

  await openReviewStage(page)
  await openReviewStage(page)
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Review / Run' }).click()
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toBeDisabled()
  await openMountingStage(page)
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Mounting' }).click()
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
  await openMountingStage(page)
  expect(await count(page)).toBe(added - partial)

  // Clear, then select the whole model: rigid-panel nodes must be excluded.
  await page.getByRole('button', { name: 'Clear selection' }).click()
  await openMountingStage(page)
  expect(await count(page)).toBe(0)
  await page.getByRole('button', { name: 'Fit and reset view' }).click()
  await page.getByLabel('Rectangle operation').selectOption('replace')
  await dragBox(page, await at(page, -12, -1), await at(page, 12, 16))
  await openMountingStage(page)
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

  await openReviewStage(page)
  await openReviewStage(page)
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Review / Run' }).click()
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toBeEnabled()
  await openReviewStage(page)
  await page.getByRole('button', { name: 'Prepare input deck' }).click()
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
  await openMountingStage(page)
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
  await openMountingStage(page)
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Mounting' }).click()
  await page.getByLabel('Fixed-node box mode').check()
  await page.getByRole('button', { name: 'Fit and reset view' }).click()
  const at = projector(bounds.bounds)
  await dragBox(page, await at(page, -10, -0.6), await at(page, 10, 1.4))
  await page.getByRole('button', { name: 'Save fixed nodes' }).click()
  await openReviewStage(page)
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Review / Run' }).click()
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
  await openMountingStage(page)
  await expect(page.getByText('Fixed nodes (WSFIX)')).toBeVisible()
  await openMountingStage(page)
  expect(await count(page)).toBe(0)
  await openReviewStage(page)
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toBeDisabled()
})

test('a pending selection blocks preparation until it is saved or discarded', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Pending selection' } })
  ).json()
  const bounds: Display = await (await request.post('/api/display', { data: revision.setup })).json()
  await openMeshStage(page, revision)
  await generateMesh(page)
  await openMountingStage(page)
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Mounting' }).click()
  await page.getByLabel('Fixed-node box mode').check()
  await page.getByRole('button', { name: 'Fit and reset view' }).click()
  const at = projector(bounds.bounds)
  await dragBox(page, await at(page, -10, -0.6), await at(page, 10, 1.4))
  const selected = await count(page)
  expect(selected).toBeGreaterThan(0)

  // Deck actions live on Review; return there before each assertion.
  // Nothing is saved yet, so the deck cannot be prepared or submitted.
  await openReviewStage(page)
  await openReviewStage(page)
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Review / Run' }).click()
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toBeDisabled()
  await openMountingStage(page)
  // The pending count survives polling and a camera change.
  await page.getByRole('button', { name: 'Zoom in' }).click()
  await page.waitForTimeout(1600)
  await openMountingStage(page)
  expect(await count(page)).toBe(selected)
  await openReviewStage(page)
  await openReviewStage(page)
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toBeDisabled()
  await openMountingStage(page)

  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Mounting' }).click()
  await page.getByRole('button', { name: 'Save fixed nodes' }).click()
  await openReviewStage(page)
  await openReviewStage(page)
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Review / Run' }).click()
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toBeEnabled()

  // A changed selection blocks again until it is discarded.
  await page.getByRole('button', { name: 'Fit and reset view' }).click()
  await dragBox(page, await at(page, -10, 1.4), await at(page, 10, 3.3))
  await openReviewStage(page)
  await openReviewStage(page)
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toBeDisabled()
  await openMountingStage(page)
  await page.getByRole('button', { name: 'Discard selection' }).click()
  await openReviewStage(page)
  await openReviewStage(page)
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toBeEnabled()
  await openMountingStage(page)
  expect(await count(page)).toBe(selected)

  // The pending state also survives a language switch.
  await dragBox(page, await at(page, -10, 1.4), await at(page, 10, 3.3))
  await openReviewStage(page)
  await openReviewStage(page)
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toBeDisabled()
  await openMountingStage(page)
  await page.locator('.lang-button').click()
  await expect(page.getByRole('button', { name: 'å…¥åŠ›ãƒ‡ãƒƒã‚­ã‚’ä½œæˆ' })).toBeDisabled()
  await expect(page.getByText(/ç¯€ç‚¹ã‚’é¸æŠžä¸­ã§ã™ã€‚ä¿å­˜ã™ã‚‹ã¾ã§è§£æžã«ã¯ä½¿ã‚ã‚Œã¾ã›ã‚“ã€‚/)).toBeVisible()
})

test('an explicit remesh in the same revision starts a fresh review', async ({ page, request }) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Remesh review' } })
  ).json()
  const bounds: Display = await (await request.post('/api/display', { data: revision.setup })).json()
  await openMeshStage(page, revision)
  await generateMesh(page)
  await openMountingStage(page)
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Mounting' }).click()
  await page.getByLabel('Fixed-node box mode').check()
  await page.getByRole('button', { name: 'Fit and reset view' }).click()
  const at = projector(bounds.bounds)
  await dragBox(page, await at(page, -10, -0.6), await at(page, 10, 1.4))
  await page.getByRole('button', { name: 'Save fixed nodes' }).click()
  await openReviewStage(page)
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Review / Run' }).click()
  await page.getByRole('button', { name: 'Prepare input deck' }).click()
  await expect(page.getByTestId('deck-status')).toContainText('Input ready', { timeout: 60000 })

  // Remesh the same revision without touching any mesh input. The mesh bytes are
  // identical, but the reviewed fixture belongs to the superseded mesh.
  const jobs = async () =>
    ((await (await request.get('/api/meshes')).json()) as Job[]).filter(
      (j) => j.revision === revision.id,
    ).length
  const before = await jobs()
  await page.getByRole('button', { name: 'Generate mesh', exact: true }).click()
  await expect.poll(jobs, { timeout: 60000 }).toBe(before + 1)
  await expect.poll(async () => count(page), { timeout: 60000 }).toBe(0)
  await openReviewStage(page)
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toBeDisabled()
  await expect(page.getByTestId('deck-status')).toHaveCount(0)

  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Review / Run' })
    .click()
  await expect(page.getByRole('button', { name: 'Submit demo run' })).toBeDisabled()
})

test('a submitted setup replays the fixed nodes archived in its deck', async ({ page, request }) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Archived fixture' } })
  ).json()
  const bounds: Display = await (await request.post('/api/display', { data: revision.setup })).json()
  await openMeshStage(page, revision)
  await generateMesh(page)
  await openMountingStage(page)
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Mounting' }).click()
  await page.getByLabel('Fixed-node box mode').check()
  await page.getByRole('button', { name: 'Fit and reset view' }).click()
  const at = projector(bounds.bounds)
  await dragBox(page, await at(page, -10, -0.6), await at(page, 10, 1.4))
  const archived = await count(page)
  await page.getByRole('button', { name: 'Save fixed nodes' }).click()
  await openReviewStage(page)
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Review / Run' }).click()
  await page.getByRole('button', { name: 'Prepare input deck' }).click()
  await expect(page.getByTestId('deck-status')).toContainText('Input ready', { timeout: 60000 })
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Review / Run' })
    .click()
  await page.getByLabel('Run name').fill('Archived fixture run')
  await page.getByRole('button', { name: 'Submit demo run' }).click()
  await page.waitForURL('**/#diagnostics/*')
  const runId = page.url().split('/').pop()!
  await expect
    .poll(async () => ((await (await request.get('/api/jobs/' + runId)).json()) as Job).status, {
      timeout: 60000,
    })
    .toBe('Completed')

  // Change the live fixture and add a new mesh, then reopen the submitted setup.
  const meshes: Job[] = await (await request.get('/api/meshes')).json()
  const mesh = meshes.find((j) => j.revision === revision.id && j.status === 'Completed')!
  const next = await (
    await request.put('/api/meshes/' + mesh.id + '/fixture', {
      data: { labels: ['WS-1:1', 'WS-1:2'] },
    })
  ).json()
  expect(next.fixture.count).toBe(2)
  await request.post('/api/meshes', { data: { revision: revision.id, token: randomUUID() } })

  await page.goto('/#setup/' + runId)
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Mesh' })
    .click()
  await expect(page.getByText('Archived in the submitted deck').first()).toBeVisible()
  await openMountingStage(page)
  expect(await count(page)).toBe(archived)
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Mounting' }).click()
  await expect(page.getByRole('button', { name: 'Save fixed nodes' })).toHaveCount(0)
  const job: Job = await (await request.get('/api/jobs/' + runId)).json()
  expect(job.fixture_labels).toHaveLength(archived)
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
  await openMountingStage(page)
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Mounting' }).click()
    await page.getByLabel('Fixed-node box mode').check()
    await page.getByRole('button', { name: 'Fit and reset view' }).click()
    const at = projector(bounds.bounds)
    await dragBox(page, await at(page, -10, -0.6), await at(page, 10, 1.4))
  await openMountingStage(page)
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
  await openMountingStage(page)
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Mounting' }).click()
  await page.getByLabel('Fixed-node box mode').check()
  await page.getByRole('button', { name: 'Fit and reset view' }).click()
  const at = projector(bounds.bounds)
  await dragBox(page, await at(page, -10, -0.6), await at(page, 10, 1.4))
  const selected = await count(page)
  expect(selected).toBeGreaterThan(0)
  expect(await page.getByText(/nodes selected\. They are not used until you save\./).count()).toBe(1)
  await page.locator('.lang-button').click()

  await expect(page.getByRole('heading', { name: 'å›ºå®šç¯€ç‚¹ï¼ˆWSFIXï¼‰' })).toBeVisible()
  await expect(page.getByLabel('çŸ©å½¢é¸æŠžãƒ¢ãƒ¼ãƒ‰')).toBeChecked()
  await expect(
    page.getByText(selected + ' ç¯€ç‚¹ã‚’é¸æŠžä¸­ã§ã™ã€‚ä¿å­˜ã™ã‚‹ã¾ã§è§£æžã«ã¯ä½¿ã‚ã‚Œã¾ã›ã‚“ã€‚'),
  ).toBeVisible()
  await expect(page.getByRole('button', { name: 'å›ºå®šç¯€ç‚¹ã‚’ä¿å­˜' })).toBeEnabled()
  // The pending count is unchanged by the language switch.
  expect(
    Number(
      await page
        .locator('.property-body dl div')
        .filter({ hasText: 'é¸æŠžç¯€ç‚¹æ•°' })
        .locator('dd')
        .textContent(),
    ),
  ).toBe(selected)
})
