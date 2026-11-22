import { expect, test, type Page } from './fixtures'
import { randomUUID } from 'node:crypto'
import { meshAndDeck } from './pipeline'
import type { Job, Revision } from '../src/api'

async function completedRun(page: Page, revision: Revision) {
  const { deck } = await meshAndDeck(page.request, revision)
  const run: Job = await (
    await page.request.post('/api/runs', {
      data: {
        revision: revision.id,
        deck: deck.id,
        token: randomUUID(),
        name: 'Playback evidence',
        mode: 'ABAQUS',
      },
    })
  ).json()
  await expect
    .poll(
      async () => ((await (await page.request.get('/api/jobs/' + run.id)).json()) as Job).status,
      { timeout: 90000 },
    )
    .toBe('Completed')
  return run
}

async function cameraSignature(page: Page) {
  // Results use a plain white canvas (no section grid), so the camera identity
  // is read from the renderer's recorded signature rather than grid spacing.
  return page.locator('.seal-vtk-host').getAttribute('data-camera')
}

test('a delayed frame never blanks the view and the camera and scale stay fixed', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Playback evidence', example: true } })
  ).json()
  const run = await completedRun(page, revision)
  const index = await (
    await request.get('/api/jobs/' + run.id + '/artifacts/results.json')
  ).json()
  const metadata = await (
    await request.get('/api/jobs/' + run.id + '/display-metadata')
  ).json()
  const frames = index.frames as { time: number; step: string; file: string }[]

  await page.goto('/#results/' + run.id)
  await expect(page.getByRole('heading', { name: 'Force–displacement' })).toBeVisible()
  const viewport = page.locator('.result-viewport')
  const slider = page.getByRole('slider')

  await slider.fill('9')
  await expect(page.locator('.playback')).toContainText(frames[9].time.toFixed(3))
  const cameraBefore = await cameraSignature(page)
  const legend = page.locator('.seal-vtk-legend')
  const magnitudeLegend = await legend.innerText()
  expect(magnitudeLegend).toContain(Number(metadata.ranges.magnitude.toPrecision(4)).toString())

  const frameTime = async () =>
    Number(await page.getByTestId('vtk-viewport').getAttribute('data-frame-time'))
  const sceneActors = async () =>
    await page.getByTestId('vtk-viewport').getAttribute('data-scene-actors')
  await expect.poll(frameTime).toBeCloseTo(frames[9].time)
  const actorsBefore = await sceneActors()

  // A frame slower than the 220 ms cadence must not abandon its request.
  await page.route('**/frame-00010.json', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500))
    await route.continue()
  })
  await page.getByRole('button', { name: 'Play frames' }).click()
  await expect(slider).toHaveValue('10', { timeout: 10000 })
  await expect(page.locator('.loading-note')).toBeVisible()
  // The last complete frame stays displayed, with its geometry unchanged.
  await expect.poll(frameTime).toBeCloseTo(frames[9].time)
  expect(await sceneActors()).toBe(actorsBefore)
  await expect(page.locator('.playback')).toContainText(frames[9].time.toFixed(3))
  // Stop playback while the slow request is still in flight, then let it land.
  await page.getByRole('button', { name: 'Pause playback' }).click()
  await expect(page.locator('.loading-note')).toBeHidden({ timeout: 10000 })
  await expect.poll(frameTime).toBeCloseTo(frames[10].time)
  await expect(page.locator('.playback')).toContainText(frames[10].time.toFixed(3))
  expect(await sceneActors()).toBe(actorsBefore)
  expect(await cameraSignature(page)).toEqual(cameraBefore)

  // Pan and zoom deliberately, then step frames: the camera must not move.
  await viewport.hover()
  const box = (await viewport.boundingBox())!
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down()
  await page.mouse.move(box.x + box.width / 2 + 60, box.y + box.height / 2 + 30, { steps: 4 })
  await page.mouse.up()
  await page.getByRole('button', { name: 'Zoom in' }).click()
  const moved = await cameraSignature(page)
  expect(moved).not.toEqual(cameraBefore)
  await slider.fill('11')
  await expect(page.locator('.playback')).toContainText(frames[11].time.toFixed(3))
  expect(await cameraSignature(page)).toEqual(moved)
  await page.getByRole('button', { name: 'Fit and reset view' }).click()
  expect(await cameraSignature(page)).toEqual(cameraBefore)

  // The colour scale is a run-wide constant, not a per-frame maximum.
  await page.getByLabel('Field').selectOption('U2')
  const u2Legend = await legend.innerText()
  expect(u2Legend).toContain(Number(metadata.ranges.U2.toPrecision(4)).toString())
  await slider.fill('0')
  await expect(page.locator('.playback')).toContainText(frames[0].time.toFixed(3))
  expect(await legend.innerText()).toBe(u2Legend)
  await slider.fill(String(frames.length - 1))
  await expect(page.locator('.playback')).toContainText(frames.at(-1)!.time.toFixed(3))
  expect(await legend.innerText()).toBe(u2Legend)

  // Out-of-order scrub responses: the newer request wins.
  await page.route('**/frame-00020.json', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 900))
    await route.continue()
  })
  await slider.fill('20')
  await slider.fill('5')
  await expect(page.locator('.playback')).toContainText(frames[5].time.toFixed(3), {
    timeout: 10000,
  })
  await page.waitForTimeout(1200)
  await expect(page.locator('.playback')).toContainText(frames[5].time.toFixed(3))
  await expect(slider).toHaveValue('5')

  // A failed frame identifies itself and leaves the last complete frame visible.
  await page.route('**/frame-00007.json', (route) => route.abort())
  await slider.fill('7')
  await expect(page.locator('.playback [role=alert]')).toContainText('Frame 8', {
    timeout: 10000,
  })
  await expect(page.locator('.playback')).toContainText(frames[5].time.toFixed(3))
})
