import { expect, test, type Page } from './fixtures'
import type { Job, Revision } from '../src/api'
import type { Display, ViewMesh } from '../src/viewportModel'

async function openSection(page: Page) {
  const response = await page.request.post('/api/projects', {
    data: { name: 'Picking · ' + test.info().title, dimension: '2D' },
  })
  expect(response.ok()).toBeTruthy()
  const revision: Revision = await response.json()
  const displayResponse = await page.request.post('/api/display', {
    data: revision.setup,
  })
  const { bounds }: Display = await displayResponse.json()
  await page.goto('/#workspace/' + revision.id)
  await expect(
    page.getByRole('heading', { name: revision.setup.name })
  ).toBeVisible()
  const viewport = page.getByRole('application', {
    name: '2D engineering viewport',
  })
  await expect(viewport.locator('canvas')).toBeVisible()

  async function screen(x: number, y: number) {
    const box = (await viewport.boundingBox())!
    const [xmin, xmax, ymin, ymax] = bounds
    const scale =
      Math.min(box.width / (xmax - xmin), box.height / (ymax - ymin)) / 1.2
    return {
      x: box.x + box.width / 2 + (x - (xmin + xmax) / 2) * scale,
      y: box.y + box.height / 2 - (y - (ymin + ymax) / 2) * scale,
    }
  }
  async function pick(x: number, y: number) {
    const p = await screen(x, y)
    await page.mouse.click(p.x, p.y)
  }
  return { revision, viewport, pick, screen }
}

test('CAD picking honors the cavity, mount, camera and extruded region identity', async ({
  page,
}) => {
  const { pick, screen } = await openSection(page)
  const stage = page.getByRole('navigation', { name: 'Workflow' })
  const properties = page.locator('.property-body')
  await stage.getByRole('button', { name: 'Materials' }).click()

  // Pick a point within the crown, then the void bounded by the inner arc.
  await pick(0, 11.75)
  await expect(
    properties.getByRole('heading', { name: 'Hollow bulb' })
  ).toBeVisible()
  await expect(page.getByLabel('Material card')).toHaveValue('bulb_foam')
  await pick(0, 7)
  await expect(
    properties.getByRole('heading', { name: 'Select a region' })
  ).toBeVisible()

  await stage.getByRole('button', { name: 'Mounting / Contact' }).click()
  await pick(0, 4.5)
  await expect(page.getByLabel('Selected boundary')).toHaveValue('Cavity floor')
  // Within CSS-pixel tolerance of a thin boundary, outside the solid.
  const bottom = await screen(0, 0)
  await page.mouse.click(bottom.x, bottom.y + 4)
  await expect(page.getByLabel('Selected boundary')).toHaveValue(
    'Mounting foot'
  )
  await expect(page.getByLabel('Fix this edge')).toBeChecked()

  const foot = await screen(0, 1.6)
  await stage.getByRole('button', { name: 'Materials' }).click()
  // Move the camera, then click the translated position in screen space.
  await page.mouse.move(foot.x, foot.y)
  await page.mouse.down()
  await page.mouse.move(foot.x + 48, foot.y - 32, { steps: 4 })
  await page.mouse.up()
  await page.mouse.click(foot.x + 48, foot.y - 32)
  await expect(
    properties.getByRole('heading', { name: 'Mounting foot' })
  ).toBeVisible()
  await page.getByRole('button', { name: 'Zoom in', exact: true }).click()
  await page.getByRole('button', { name: 'Fit and reset view' }).click()
  await pick(0, 11.75)
  await expect(
    properties.getByRole('heading', { name: 'Hollow bulb' })
  ).toBeVisible()

  await page.getByRole('button', { name: '3D', exact: true }).click()
  const segment = page.getByRole('application', {
    name: '3D engineering viewport',
  })
  const box = (await segment.boundingBox())!
  // The frontmost longitudinal wall maps back to its source 2D material region.
  await expect(async () => {
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2)
    await expect(
      properties.getByRole('heading', { name: 'Hollow bulb' })
    ).toBeVisible({ timeout: 500 })
  }).toPass()
  await expect(page.getByLabel('Material card')).toHaveValue('bulb_foam')
})

test('both halves of a rendered quad probe the original FE element', async ({
  page,
}) => {
  const { pick, revision } = await openSection(page)
  await page
    .getByRole('navigation', { name: 'Workflow' })
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Mounting' }).click()
    .getByRole('button', { name: 'Mesh' })
    .click()
  await page.getByRole('button', { name: 'Generate mesh', exact: true }).click()
  await expect(page.getByTestId('mesh-status')).toContainText('Mesh ready', { timeout: 60000 })
  const meshes: Job[] = await (await page.request.get('/api/meshes')).json()
  const build = meshes.find(
    (b) => b.revision === revision.id && b.status === 'Completed'
  )!
  const mesh: ViewMesh = await (
    await page.request.get('/api/jobs/' + build.id + '/artifacts/mesh.json')
  ).json()
  const quad = mesh.elements.find((e) => e.type === 'CPS4R')!
  expect(quad).toBeTruthy()
  const coords = new Map(mesh.nodes.map((n) => [n.id, n.xyz]))
  await page.getByLabel('Selection mode').selectOption('element')
  for (const triangle of [
    [0, 1, 2],
    [0, 2, 3],
  ]) {
    const points = triangle.map((index) => coords.get(quad.nodes[index])!)
    await pick(
      points.reduce((s, p) => s + p[0], 0) / 3,
      points.reduce((s, p) => s + p[1], 0) / 3
    )
    await expect(page.getByRole('status')).toContainText('WS-1:' + quad.id)
  }
})
