/**
 * Gate 1: the compact engineering workstation is a fixed shell on desktop.
 *
 * Measurements use the rendered layout, not stylesheet expectations. Fictional
 * synthetic models only.
 */
import { expect, test } from './fixtures'
import { resolve } from 'node:path'
import type { Revision } from '../src/api'

async function example(request: import('@playwright/test').APIRequestContext, name: string) {
  return (await (
    await request.post('/api/projects', { data: { name, example: true } })
  ).json()) as Revision
}

async function documentMetrics(page: import('@playwright/test').Page) {
  return page.evaluate(() => ({
    scrollW: document.documentElement.scrollWidth,
    clientW: document.documentElement.clientWidth,
    scrollH: document.documentElement.scrollHeight,
    clientH: document.documentElement.clientHeight,
  }))
}

test('desktop shell fits the viewport, keeps panes adjacent and the viewport fixed', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const revision = await example(request, 'Layout desktop')
  await page.goto('/#workspace/' + revision.id)
  await expect(page.getByTestId('vtk-viewport')).toBeVisible()

  const metrics = await documentMetrics(page)
  expect(Math.abs(metrics.scrollW - metrics.clientW)).toBeLessThanOrEqual(1)
  expect(Math.abs(metrics.scrollH - metrics.clientH)).toBeLessThanOrEqual(1)

  const left = (await page.locator('.workgrid > .left').boundingBox())!
  const right = (await page.locator('.workgrid > .right').boundingBox())!
  const canvas = (await page.locator('.canvas-card').boundingBox())!
  // Workflow and properties are adjacent on the left of the drawing field.
  expect(left.x + left.width).toBeLessThanOrEqual(right.x + 1)
  expect(right.x + right.width).toBeLessThanOrEqual(canvas.x + 1)
  expect(canvas.width).toBeGreaterThan(left.width + right.width)
  expect(canvas.height).toBeGreaterThan(300)

  // The drawing field is white under the transparent WebGL canvas.
  const background = await page.locator('.seal-vtk-host').evaluate((element) => ({
    color: getComputedStyle(element).backgroundColor,
    image: getComputedStyle(element).backgroundImage,
  }))
  expect(background.color).toBe('rgb(255, 255, 255)')
  expect(background.image).toBe('none')

  // A long property pane scrolls on its own; the canvas does not move.
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Motion' })
    .click()
  const before = (await page.locator('.canvas-card').boundingBox())!
  await page.locator('.workgrid > .right').evaluate((element) => {
    element.scrollTop = 500
  })
  const after = (await page.locator('.canvas-card').boundingBox())!
  expect(Math.abs(after.y - before.y)).toBeLessThanOrEqual(1)
  expect(Math.abs(after.height - before.height)).toBeLessThanOrEqual(1)

  // Prepare and Submit are one compact group beneath the left workflow, and are
  // reachable without changing the stage.
  const leftPane = (await page.locator('.workgrid > .left').boundingBox())!
  const steps = (await page.locator('.workgrid > .left .steps').boundingBox())!
  const actions = (await page.getByTestId('action-group').boundingBox())!
  const prepare = (await page.getByRole('button', { name: 'Prepare input deck' }).boundingBox())!
  const submit = (await page
    .getByRole('button', { name: 'Submit Abaqus analysis' })
    .boundingBox())!
  expect(actions.x).toBeGreaterThanOrEqual(leftPane.x - 1)
  expect(actions.x + actions.width).toBeLessThanOrEqual(leftPane.x + leftPane.width + 1)
  expect(actions.y).toBeGreaterThan(steps.y + steps.height - 1)
  expect(prepare.y).toBeLessThan(submit.y)
  expect(prepare.x).toBeGreaterThanOrEqual(leftPane.x - 1)
  expect(submit.x + submit.width).toBeLessThanOrEqual(leftPane.x + leftPane.width + 1)
  await expect(page.getByRole('button', { name: 'Go to Mesh' })).toHaveCount(0)

  // Wheel zoom and Fit/reset stay inside the fixed canvas.
  const camera = () =>
    page.locator('.seal-vtk-host').getAttribute('data-camera')
  const original = await camera()
  await page.getByTestId('vtk-viewport').hover()
  await page.mouse.wheel(0, -240)
  await expect.poll(camera).not.toEqual(original)
  await page.getByRole('button', { name: 'Fit and reset view' }).click()
  await expect.poll(camera).toEqual(original)

  // A resize keeps the shell inside the new client area.
  await page.setViewportSize({ width: 1280, height: 720 })
  const resized = await documentMetrics(page)
  expect(Math.abs(resized.scrollW - resized.clientW)).toBeLessThanOrEqual(1)
  expect(Math.abs(resized.scrollH - resized.clientH)).toBeLessThanOrEqual(1)
  await expect(page.getByTestId('vtk-viewport')).toBeVisible()
})

test('an expanded assembly stays readable above analysis actions on a short desktop', async ({
  page,
  request,
}) => {
  const revision = await example(request, 'Assembly tree height')
  for (const face of revision.setup.faces) face.material = null
  const saved = await request.put('/api/projects/' + revision.project, {
    data: { base: revision.id, setup: revision.setup },
  })
  expect(saved.ok()).toBeTruthy()
  await page.setViewportSize({ width: 1280, height: 720 })
  await page.goto('/#workspace/' + (await saved.json()).id)
  await page.getByRole('navigation', { name: 'Workflow' }).getByRole('button', { name: 'Materials' }).click()
  const tree = page.locator('.left .tree')
  await tree.locator('[aria-expanded="false"]').first().click()
  const thirdChild = tree.locator('.children button').nth(2)
  await expect(thirdChild).toBeInViewport({ ratio: 1 })

  const canvas = page.getByTestId('vtk-viewport')
  const before = await canvas.boundingBox()
  const submit = page.getByTestId('action-group').getByRole('button', { name: 'Submit Abaqus analysis' })
  await submit.scrollIntoViewIfNeeded()
  await expect(submit).toBeInViewport({ ratio: 1 })
  expect(await canvas.boundingBox()).toEqual(before)
})

test('narrow and zoomed layouts keep every control reachable', async ({ page, request }) => {
  const revision = await example(request, 'Layout narrow')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/#workspace/' + revision.id)
  await expect(page.getByTestId('vtk-viewport')).toBeVisible()
  const metrics = await documentMetrics(page)
  expect(metrics.scrollW).toBeLessThanOrEqual(metrics.clientW + 1)
  const toggle = page.getByRole('button', { name: 'Workflow & properties' })
  await expect(toggle).toBeVisible()
  await toggle.click()
  await expect(page.locator('.workgrid > .left')).toBeHidden()
  await expect(page.getByTestId('vtk-viewport')).toBeVisible()
  await toggle.click()
  await expect(page.locator('.workgrid > .left')).toBeVisible()
  await expect(page.locator('.left .tree-row').first()).toBeVisible()
  // The action group remains reachable by scrolling, not clipped away.
  const prepare = page.getByRole('button', { name: 'Prepare input deck' })
  await prepare.scrollIntoViewIfNeeded()
  await expect(prepare).toBeVisible()

  // 200% desktop zoom is 720 x 450 CSS pixels: no horizontal overflow.
  await page.setViewportSize({ width: 720, height: 450 })
  await page.goto('/#workspace/' + revision.id)
  const zoomed = await documentMetrics(page)
  expect(zoomed.scrollW).toBeLessThanOrEqual(zoomed.clientW + 1)
  await expect(page.getByRole('button', { name: 'Workflow & properties' })).toBeVisible()
})

test('the empty viewport has no import button; Import owns one chooser', async ({
  page,
  request,
}) => {
  const empty = (await (
    await request.post('/api/projects', { data: { name: 'Empty import', example: false } })
  ).json()) as Revision
  const sibling = await example(request, 'Import sibling')
  const siblingBefore = await (await request.get('/api/revisions/' + sibling.id)).json()
  await page.goto('/#workspace/' + empty.id)
  const viewport = page.getByTestId('vtk-viewport')
  await expect(viewport).toBeVisible()
  await expect(
    viewport.getByRole('button', { name: /Import DXF|読み込む/ }),
  ).toHaveCount(0)
  await expect(page.getByText('No geometry to display')).toHaveCount(0)

  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Import' })
    .click()
  const chooser = page.waitForEvent('filechooser')
  await page.getByRole('button', { name: 'Import DXF / DWG' }).click()
  const picker = await chooser
  expect(picker).toBeTruthy()
  // Cancelling the picker leaves the revision unchanged.
  await expect(page.locator('.crumb')).toContainText('Revision 01')

  await page.locator('input[type=file]').setInputFiles(resolve('../../examples/hollow-section.dxf'))
  await expect(page.locator('.subtitle')).toContainText('hollow-section.dxf')
  await expect(page.locator('.crumb')).toContainText('Revision 02')
  const siblingAfter = await (await request.get('/api/revisions/' + sibling.id)).json()
  expect(siblingAfter.setup).toEqual(siblingBefore.setup)
})
