import { expect, test, type Page } from './fixtures'
import type { Revision } from '../src/api'

async function create(request: import('@playwright/test').APIRequestContext, name: string) {
  return (await (
    await request.post('/api/projects', { data: { name, example: true } })
  ).json()) as Revision
}

async function openStage(page: Page, name: string) {
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name })
    .click()
}

test('user-facing text has no mojibake after the encoding repair', async ({ page, request }) => {
  await create(request, 'Encoding check')
  await page.goto('/#dashboard')
  await expect(page.getByText('Encoding check').first()).toBeVisible()
  const text = await page.locator('body').innerText()
  expect(text).not.toContain('Â·')
  expect(text).not.toContain('â€”')
  expect(text).not.toContain('ï¿½')
  // Separators that remain are real middle dots, not corrupted bytes.
  expect(text).toContain('·')
})

test('middle-button drag pans the camera without scrolling the page', async ({
  page,
  request,
}) => {
  const revision = await create(request, 'Middle pan')
  await page.goto('/#workspace/' + revision.id)
  const host = page.getByTestId('vtk-viewport').locator('.seal-vtk-host')
  await expect(host).toBeVisible()
  await expect.poll(async () => (await host.getAttribute('data-camera')) ?? '').not.toBe('')
  const before = (await host.getAttribute('data-camera'))!
  expect(await page.evaluate(() => window.scrollY)).toBe(0)

  const box = (await host.boundingBox())!
  const x = box.x + box.width / 2
  const y = box.y + box.height / 2
  await page.mouse.move(x, y)
  await page.mouse.down({ button: 'middle' })
  await page.mouse.move(x + 70, y + 45, { steps: 6 })
  await page.mouse.up({ button: 'middle' })

  await expect.poll(async () => (await host.getAttribute('data-camera')) ?? '').not.toBe(before)
  expect(await page.evaluate(() => window.scrollY)).toBe(0)

  // Wheel zoom still works and does not scroll the page.
  const beforeWheel = (await host.getAttribute('data-camera'))!
  await page.mouse.move(x, y)
  await page.mouse.wheel(0, -240)
  await expect
    .poll(async () => (await host.getAttribute('data-camera')) ?? '')
    .not.toBe(beforeWheel)
  expect(await page.evaluate(() => window.scrollY)).toBe(0)
})

test('mesh review shows structured component rows and hides the mesh digest', async ({
  page,
  request,
}) => {
  const revision = await create(request, 'Component rows')
  await page.goto('/#workspace/' + revision.id)
  await openStage(page, 'Mesh')
  await page.getByRole('button', { name: 'Generate mesh', exact: true }).click()
  await expect(page.getByTestId('mesh-status')).toContainText('Mesh ready', { timeout: 60000 })

  const seal = page.locator('[data-component="seal"]')
  await expect(seal).toHaveAttribute('data-status', 'included')
  await expect(seal).toContainText('Role')
  await expect(seal).toContainText('Element type')
  await expect(seal).toContainText('Elements')
  await expect(seal).toContainText('CPS')
  await expect(seal).not.toContainText('?')

  const door = page.locator('[data-component="panel"]')
  await expect(door).toHaveAttribute('data-status', 'included')
  await expect(door).toContainText('R2D2')

  const total = await page.getByTestId('included-total').innerText()
  expect(total).toMatch(/Included components: [\d,]+ of [\d,]+ mesh elements/)

  const jobs = (await (await request.get('/api/meshes')).json()) as {
    revision: string
    mesh_digest: string
  }[]
  const digest = jobs.find((job) => job.revision === revision.id)!.mesh_digest.slice(0, 12)
  expect(await page.locator('body').innerText()).not.toContain(digest)
})

test('an assembly-tree rename is persisted without changing CAD identity', async ({
  page,
  request,
}) => {
  const revision = await create(request, 'Rename component')
  const originalCompat = revision.mesh_compat
  await page.goto('/#workspace/' + revision.id)

  const tree = page.locator('.tree')
  await tree.getByRole('button', { name: 'Rename Weatherstrip' }).click()
  const input = page.getByLabel('New display name for Weatherstrip')
  await input.fill('Seal renamed')
  await input.press('Enter')
  await expect(
    tree.getByRole('button', { name: 'Seal renamed', exact: true }),
  ).toBeVisible()

  // Cancel on another component keeps its name.
  await tree.getByRole('button', { name: 'Rename Closing panel' }).click()
  const panelInput = page.getByLabel('New display name for Closing panel')
  await panelInput.fill('Should not persist')
  await panelInput.press('Escape')
  await expect(
    tree.getByRole('button', { name: 'Closing panel', exact: true }),
  ).toBeVisible()

  await page.getByRole('button', { name: 'Save revision' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 02')
  const projects = (await (await request.get('/api/projects')).json()) as {
    id: string
    revision: string
  }[]
  const head = projects.find((entry) => entry.id === revision.project)!
  const stored = (await (await request.get('/api/revisions/' + head.revision)).json()) as Revision
  const seal = stored.setup.components.find((component) => component.role === 'seal')!
  expect(seal.alias).toBe('Seal renamed')
  expect(seal.name).toBe('Weatherstrip')
  expect(stored.mesh_compat).toBe(originalCompat)

  await page.reload()
  await expect(
    tree.getByRole('button', { name: 'Seal renamed', exact: true }),
  ).toBeVisible()
  await tree.getByRole('button', { name: 'Seal renamed', exact: true }).click()
  await expect(page.locator('.statusbar')).toContainText('Seal renamed')
})
