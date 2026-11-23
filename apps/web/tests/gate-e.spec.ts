/**
 * Gate E: the section cut is acquired by real viewport clicks.
 *
 * Covers DPR 2, pan/zoom, snapping to the canonical boundary, Escape/cancel
 * with zero writes, a click away from the boundary, one Apply per preview and a
 * valid cut whose endpoint lies on a supported curved outer arc.
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

async function openFootCut(page: Page, revision: Revision) {
  await page.goto('/#workspace/' + revision.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.getByRole('button', { name: 'Components' }).click()
  await page.getByRole('button', { name: /Mounting foot/ }).click()
  await expect(page.getByTestId('partition-editor')).toBeVisible()
}

test('a DPR-2 viewport click cut snaps, cancels and applies exactly once', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Gate E click', example: true } })
  ).json()
  await openFootCut(page, revision)

  const writes: string[] = []
  page.on('request', (req) => {
    if (req.url().includes('/partition') && req.method() === 'POST') writes.push(req.url())
  })

  // Escape from the first-point phase writes nothing.
  await page.getByRole('button', { name: 'Cut region' }).click()
  await expect(page.getByTestId('cut-status')).toHaveAttribute('data-phase', 'start')
  await page.getByRole('application').focus()
  await page.keyboard.press('Escape')
  await expect(page.getByTestId('cut-status')).toHaveCount(0)
  expect(writes).toHaveLength(0)

  // A click away from the boundary does not place a point.
  await page.getByRole('button', { name: 'Cut region' }).click()
  const viewport = page.getByRole('application')
  const box = (await viewport.boundingBox())!
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2)
  await expect(page.getByTestId('cut-status')).toHaveAttribute('data-phase', 'start')
  expect(writes).toHaveLength(0)

  // DPR 2 with the default fitted camera. Pan/zoom acquisition at DPR 1 is
  // covered by partition.spec.ts.
  const a = await projectPoint(page, 0, 0)
  await page.mouse.move(a.x, a.y, { steps: 3 })
  await expect(page.getByTestId('cut-hover')).toContainText('Snapped boundary point')
  await page.mouse.click(a.x, a.y)
  await expect(page.getByTestId('cut-status')).toHaveAttribute('data-phase', 'end')
  const b = await projectPoint(page, 0, 3.2)
  await page.mouse.move(b.x, b.y, { steps: 4 })
  await page.mouse.click(b.x, b.y)
  await expect(page.getByTestId('partition-plan')).toContainText('Cut preview ready')
  // Exactly one preview request so far, no apply.
  expect(writes.filter((url) => url.includes('/partition/preview'))).toHaveLength(1)
  expect(writes.filter((url) => !url.includes('/preview'))).toHaveLength(0)

  await page.getByRole('button', { name: 'Apply partition' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 02')
  expect(writes.filter((url) => !url.includes('/preview'))).toHaveLength(1)

  // Child IDs and the cut endpoints are the committed ones, not preview IDs.
  const stored: Revision = await (
    await request.get('/api/revisions/' + page.url().split('/').pop())
  ).json()
  const children = stored.setup.faces.filter((face) => face.name.startsWith('Mounting foot'))
  expect(children).toHaveLength(2)
  expect(children.every((face) => face.id.startsWith('p'))).toBeTruthy()
  // The committed setup carries the cut edge as a real model edge.
  expect(stored.setup.edges.some((edge) => edge.name === 'Mounting foot partition')).toBeTruthy()
})

test('a valid cut acquired on a curved outer arc is committed', async ({ page, request }) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Gate E curved', example: true } })
  ).json()
  await page.goto('/#workspace/' + revision.id)
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Components' }).click()
  await page.getByRole('button', { name: /Hollow bulb/ }).click()
  await expect(page.getByTestId('partition-editor')).toBeVisible()
  await page.getByRole('button', { name: 'Cut region' }).click()

  // Outer bulb arc, centre (0, 3.2), R = 9: 90 degrees and 75 degrees.
  const a = await projectPoint(page, 0, 12.2)
  await page.mouse.move(a.x, a.y, { steps: 3 })
  await page.mouse.click(a.x, a.y)
  const angle = (75 * Math.PI) / 180
  const b = await projectPoint(page, 9 * Math.cos(angle), 3.2 + 9 * Math.sin(angle))
  await page.mouse.move(b.x, b.y, { steps: 4 })
  await page.mouse.click(b.x, b.y)
  await expect(page.getByTestId('partition-plan')).toContainText('Cut preview ready')
  await page.getByRole('button', { name: 'Apply partition' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 02')
  const stored: Revision = await (
    await request.get('/api/revisions/' + page.url().split('/').pop())
  ).json()
  expect(stored.setup.faces.filter((face) => face.name.startsWith('Hollow bulb'))).toHaveLength(2)
})
