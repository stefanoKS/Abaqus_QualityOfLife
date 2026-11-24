import { randomUUID } from 'node:crypto'
import { expect, test, type Page } from './fixtures'
import type { Job, Revision } from '../src/api'

/**
 * Gate 5.5: a real Edge/WebGL click on the door and the body at distinct
 * nonzero offsets, then again after a zoom and a middle-button pan. The
 * instance-qualified identity (PANEL-1 / BODY-1) must survive both.
 *
 * Points are projected from the renderer's recorded orthographic camera, not
 * from CAD bounds, so the test follows a fitted, zoomed or panned view.
 */
async function twoPanel(request: import('@playwright/test').APIRequestContext) {
  return (await (
    await request.post('/api/projects', {
      data: { name: 'Offset picking', example: true, template: 'two-panel' },
    })
  ).json()) as Revision
}

async function viewportBox(page: Page) {
  const viewport = page.getByRole('application', { name: '2D engineering viewport' })
  return (await viewport.boundingBox())!
}

async function camera(page: Page) {
  const raw = await page.locator('.seal-vtk-host').getAttribute('data-camera')
  return raw!.split(',').map(Number)
}

/** data-camera = camera position xyz, focal xyz, parallel scale. */
function project(
  box: { x: number; y: number; width: number; height: number },
  cam: number[],
  x: number,
  y: number,
) {
  const fx = cam[3]
  const fy = cam[4]
  const scale = cam[6]
  const aspect = box.width / box.height
  return {
    x: box.x + box.width / 2 + ((x - fx) / (scale * aspect)) * (box.width / 2),
    y: box.y + box.height / 2 - ((y - fy) / scale) * (box.height / 2),
  }
}

test('door and body pick at distinct nonzero offsets through zoom and pan', async ({
  page,
  request,
}) => {
  const first = await twoPanel(request)
  // Save distinct nonzero door/body offsets through the same project route the
  // editor uses, then mesh that revision so the assembled scene is active.
  const setup = structuredClone(first.setup)
  setup.motion.offset = 0.5
  setup.motion.body.offset = -1
  const saved = await request.put('/api/projects/' + first.project, {
    data: { base: first.id, setup },
  })
  expect(saved.ok()).toBeTruthy()
  const revision: Revision = await saved.json()
  expect(revision.setup.motion.offset).toBe(0.5)
  expect(revision.setup.motion.body?.offset).toBe(-1)

  const mesh = (await (
    await request.post('/api/meshes', { data: { revision: revision.id, token: randomUUID() } })
  ).json()) as Job
  await expect
    .poll(
      async () => ((await (await request.get('/api/jobs/' + mesh.id)).json()) as Job).status,
      { timeout: 60000 },
    )
    .toBe('Completed')

  await page.goto('/#workspace/' + revision.id)
  await expect(page.getByTestId('vtk-viewport')).toBeVisible()
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.getByRole('button', { name: 'Mesh' }).click()
  await expect(page.getByTestId('mesh-status')).toContainText('Mesh ready')
  await page.getByLabel('Selection mode').selectOption('element')
  await expect.poll(async () =>
    Number(await page.getByTestId('vtk-viewport').getAttribute('data-scene-actors')),
  ).toBeGreaterThan(0)
  await expect
    .poll(async () => await page.locator('.seal-vtk-host').getAttribute('data-camera'))
    .toBeTruthy()
  // Wait for the first container resize to settle before projecting model XY.
  await expect
    .poll(
      async () => {
        const first = (await camera(page)).join()
        await page.waitForTimeout(120)
        return first === (await camera(page)).join()
      },
      { timeout: 5000 },
    )
    .toBe(true)

  const box = await viewportBox(page)
  const status = page.getByRole('status')
  const body = project(box, await camera(page), 0, -1 - 1)
  const door = project(box, await camera(page), 0, 14 + 0.5)

  await page.mouse.click(body.x, body.y)
  await expect(status).toContainText('BODY-1:')
  const bodyIdentity = await status.innerText()

  await page.mouse.click(door.x, door.y)
  await expect(status).toContainText('PANEL-1:')
  const doorIdentity = await status.innerText()
  expect(doorIdentity).not.toContain('BODY-1:')
  expect(bodyIdentity).not.toContain('PANEL-1:')

  // Zoom out with the viewport's zoom control; the camera signature is recorded.
  const fitted = (await camera(page)).join()
  await page.locator('.seal-vtk-tools button').nth(1).click()
  await expect.poll(async () => (await camera(page)).join()).not.toBe(fitted)
  const zoomed = project(box, await camera(page), 0, 14 + 0.5)
  await page.mouse.click(zoomed.x, zoomed.y)
  await expect(status).toContainText('PANEL-1:')

  // Middle-button pan: the content follows the cursor, so the door moves by the
  // same screen delta. First show the shifted point is not the door, then pan
  // and pick the door there.
  const dy = 25
  await page.mouse.click(zoomed.x, zoomed.y + dy)
  await expect(status).not.toContainText('PANEL-1:')
  await page.mouse.move(zoomed.x, zoomed.y)
  await page.mouse.down({ button: 'middle' })
  await page.mouse.move(zoomed.x, zoomed.y + dy, { steps: 6 })
  await page.mouse.up({ button: 'middle' })
  await page.mouse.click(zoomed.x, zoomed.y + dy)
  await expect(status).toContainText('PANEL-1:')
})
