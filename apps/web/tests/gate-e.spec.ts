/**
 * Gate E/D: projected viewport partition at DPR 2.
 *
 * Real pointer clicks (away from any snap band), Escape/cancel with zero
 * writes, exactly one Apply per committed revision, and a guide that splits
 * supported curved boundaries analytically.
 */
import { expect, test, type Page } from './fixtures'
import type { Revision } from '../src/api'

test.use({ deviceScaleFactor: 2, viewport: { width: 1440, height: 900 } })

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

async function openRegion(page: Page, revision: Revision, region: RegExp) {
  await page.goto('/#workspace/' + revision.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.getByRole('button', { name: 'Components' }).click()
  await page.locator('.region-list button', { hasText: region }).first().click()
  await expect(page.getByTestId('partition-editor')).toBeVisible()
}

async function clickAt(page: Page, x: number, y: number) {
  const point = await projectPoint(page, x, y)
  await page.mouse.move(point.x, point.y, { steps: 3 })
  await page.mouse.click(point.x, point.y)
}

test('a DPR-2 projected guide cancels without writes and applies exactly once', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Gate E click', example: true } })
  ).json()
  await openRegion(page, revision, /Mounting foot/)

  const writes: string[] = []
  page.on('request', (req) => {
    if (req.url().includes('/partition') && req.method() === 'POST') writes.push(req.url())
  })

  // Escape from the first-point phase writes nothing.
  await page.getByRole('button', { name: 'Partition region' }).click()
  await expect(page.getByTestId('cut-status')).toHaveAttribute('data-phase', 'start')
  await page.getByRole('application').focus()
  await page.keyboard.press('Escape')
  await expect(page.getByTestId('cut-status')).toHaveCount(0)
  expect(writes).toHaveLength(0)

  // Two arbitrary points after a DPR-2 pan and zoom: neither touches the
  // boundary, and the supporting line still projects to the true hits.
  await page.getByRole('button', { name: 'Partition region' }).click()
  const viewport = page.getByRole('application')
  const viewportBox = (await viewport.boundingBox())!
  await page.mouse.move(viewportBox.x + viewportBox.width / 2, viewportBox.y + viewportBox.height / 2)
  await page.mouse.down({ button: 'middle' })
  await page.mouse.move(
    viewportBox.x + viewportBox.width / 2 + 18,
    viewportBox.y + viewportBox.height / 2 + 9,
    { steps: 4 },
  )
  await page.mouse.up({ button: 'middle' })
  await page.getByRole('button', { name: 'Zoom out' }).click()
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
  await clickAt(page, 0, 0.5)
  await expect(page.getByTestId('cut-status')).toHaveAttribute('data-phase', 'end')
  await expect(page.getByTestId('cut-guides')).toContainText('Draft guide start')
  await clickAt(page, 0, 2.5)
  await expect(page.getByTestId('partition-plan')).toContainText('Cut preview ready')
  expect(writes.filter((url) => url.includes('/partition/preview'))).toHaveLength(1)
  expect(writes.filter((url) => !url.includes('/preview'))).toHaveLength(0)

  await page.getByRole('button', { name: 'Apply partition' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 02')
  expect(writes.filter((url) => !url.includes('/preview'))).toHaveLength(1)

  const stored: Revision = await (
    await request.get('/api/revisions/' + page.url().split('/').pop())
  ).json()
  const children = stored.setup.faces.filter((face) => face.name.startsWith('Mounting foot'))
  expect(children).toHaveLength(2)
  expect(children.every((face) => face.id.startsWith('p'))).toBeTruthy()
  // The committed seam is a real model edge, and the drawn points were
  // projected to the true boundary hits (0, 0) and (0, 3.2).
  expect(stored.setup.edges.some((edge) => edge.name === 'Mounting foot partition')).toBeTruthy()
  const seam = stored.setup.edges.find((edge) => edge.name === 'Mounting foot partition')!
  const byId = new Map(stored.setup.vertices.map((vertex) => [vertex.id, vertex.xyz]))
  const endpoints = [byId.get(seam.start)!, byId.get(seam.end)!]
  expect(endpoints.some((point) => Math.abs(point[0]) < 0.01 && Math.abs(point[1]) < 0.01)).toBeTruthy()
  expect(
    endpoints.some((point) => Math.abs(point[0]) < 0.01 && Math.abs(point[1] - 3.2) < 0.01),
  ).toBeTruthy()
})

test('a guide that splits supported curved boundaries is committed analytically', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Gate E curved', example: true } })
  ).json()
  await openRegion(page, revision, /Hollow bulb/)
  await page.getByRole('button', { name: 'Partition region' }).click()

  // x = 4 crosses the top arch wall and the floor wall; the seam endpoints lie
  // on the analytic outer/inner arcs and the floor line.
  await clickAt(page, 4, 14)
  await clickAt(page, 4, 4)
  await expect(page.getByTestId('partition-plan')).toHaveAttribute('data-status', 'valid')
  await page.getByRole('button', { name: 'Apply partition' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 02')

  const stored: Revision = await (
    await request.get('/api/revisions/' + page.url().split('/').pop())
  ).json()
  expect(stored.setup.faces.filter((face) => face.name.startsWith('Hollow bulb')).length).toBeGreaterThan(1)
  // The split preserves arc definitions rather than replacing them with chords.
  const originalArcs = stored.setup.edges.filter((edge) => edge.kind === 'arc')
  expect(originalArcs.length).toBeGreaterThanOrEqual(4)
})
