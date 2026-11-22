import { expect, test, type Page } from './fixtures'
import type { Display, Revision } from '../src/api'

async function actorCount(page: Page) {
  return Number(await page.locator('.seal-vtk-host').getAttribute('data-actors'))
}

function projector(bounds: number[]) {
  return async (page: Page, x: number, y: number) => {
    const viewport = page.getByRole('application', { name: '2D engineering viewport' })
    const box = (await viewport.boundingBox())!
    const [xmin, xmax, ymin, ymax] = bounds
    const scale = Math.min(box.width / (xmax - xmin), box.height / (ymax - ymin)) / 1.2
    return {
      x: box.x + box.width / 2 + (x - (xmin + xmax) / 2) * scale,
      y: box.y + box.height / 2 - (y - (ymin + ymax) / 2) * scale,
    }
  }
}

test('repeated display changes reuse or replace actors without leaking or mispicking', async ({
  page,
}) => {
  const revision: Revision = await (
    await page.request.post('/api/projects', {
      data: { name: 'Actor reuse', example: true },
    })
  ).json()
  const twoD: Display = await (
    await page.request.post('/api/display', { data: revision.setup })
  ).json()
  const threeD: Display = await (
    await page.request.post('/api/display', {
      data: { ...revision.setup, dimension: '3D', formulation: 'extrusion_preview' },
    })
  ).json()

  await page.goto('/#workspace/' + revision.id)
  const host = page.locator('.seal-vtk-host')
  await expect.poll(() => actorCount(page)).toBe(twoD.primitives.length)

  // Hiding and restoring a component changes the actor set exactly.
  const withoutPanel = twoD.primitives.filter((primitive) => primitive.component !== 'panel').length
  for (let i = 0; i < 3; i++) {
    await page.getByRole('button', { name: 'Toggle visibility Closing panel' }).click()
    await expect.poll(() => actorCount(page)).toBe(withoutPanel)
    await page.getByRole('button', { name: 'Toggle visibility Closing panel' }).click()
    await expect.poll(() => actorCount(page)).toBe(twoD.primitives.length)
  }

  // A mesh adds its own surfaces; removing it restores exactly the CAD set.
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Mesh' })
    .click()
  await page.getByRole('button', { name: 'Generate mesh', exact: true }).click()
  await expect(page.getByTestId('mesh-status')).toContainText('Mesh ready', { timeout: 60000 })
  const withMesh = await actorCount(page)
  expect(withMesh).toBeGreaterThan(0)
  await page.getByRole('button', { name: 'Toggle mesh' }).click()
  await expect.poll(() => actorCount(page)).toBe(twoD.primitives.length)
  await page.getByRole('button', { name: 'Toggle mesh' }).click()
  await expect.poll(() => actorCount(page)).toBe(withMesh)

  // The extruded display has its own primitive set and returns cleanly.
  await page.getByRole('button', { name: '3D', exact: true }).click()
  await expect.poll(() => actorCount(page)).toBe(threeD.primitives.length)
  await page.getByRole('button', { name: '2D', exact: true }).click()
  await expect.poll(() => actorCount(page)).toBe(twoD.primitives.length)

  // Picking still resolves the original CAD entity after all of the above.
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Materials' })
    .click()
  const at = projector(twoD.bounds)
  const crown = await at(page, 0, 11.75)
  await page.mouse.click(crown.x, crown.y)
  await expect(page.locator('.property-body').getByRole('heading', { name: 'Hollow bulb' })).toBeVisible()
  await expect(page.getByLabel('Material card')).toHaveValue('bulb_foam')
  // Repeat once more: the count is stable and the pick is unchanged.
  await page.getByRole('button', { name: 'Toggle visibility Closing panel' }).click()
  await expect.poll(() => actorCount(page)).toBe(withoutPanel)
  await page.getByRole('button', { name: 'Toggle visibility Closing panel' }).click()
  await expect.poll(() => actorCount(page)).toBe(twoD.primitives.length)
  await page.mouse.click(crown.x, crown.y)
  await expect(page.locator('.property-body').getByRole('heading', { name: 'Hollow bulb' })).toBeVisible()
})
