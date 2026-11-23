/**
 * Request 13: prescribed-motion preview.
 *
 * The preview is display-only: it animates the selected rigid profile along its
 * configured vector and back to the exact assembled pose. It never writes a
 * revision, queues work or changes the camera/selection.
 */
import { expect, test } from './fixtures'
import type { Revision } from '../src/api'

test('the body and door previews animate and return without mutating the setup', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', {
      data: { name: 'Motion preview', example: true, template: 'two-panel' },
    })
  ).json()
  await page.goto('/#workspace/' + revision.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.getByRole('button', { name: 'Motion' }).click()

  const writes: string[] = []
  page.on('request', (req) => {
    // Saving or queueing is a mutation; the display preview request is not.
    if (req.method() === 'PUT' || /\/api\/(meshes|decks|runs|projects)/.test(req.url()))
      writes.push(req.method() + ' ' + req.url())
  })
  const camera = () => page.locator('.seal-vtk-host').getAttribute('data-camera')
  const translation = () =>
    page.getByTestId('vtk-viewport').getAttribute('data-preview-translation')
  const cameraBefore = await camera()
  const actors = await page.getByTestId('vtk-viewport').getAttribute('data-scene-actors')

  // Body: +Y 2 mm. The preview reports a live non-zero translation.
  await page.getByTestId('preview-body').click()
  await expect(page.getByRole('button', { name: 'Stop preview' })).toBeVisible()
  await expect
    .poll(translation)
    .toMatch(/"body":\[\d/)
  const during = await translation()
  expect(during).toContain('"body"')
  // It returns to the exact assembled pose (empty translation) after the stroke.
  await expect.poll(translation, { timeout: 10000 }).toBe('')
  await expect(page.getByTestId('preview-body')).toContainText('Preview body panel motion')
  expect(await camera()).toBe(cameraBefore)
  expect(await page.getByTestId('vtk-viewport').getAttribute('data-scene-actors')).toBe(actors)

  // Door: stop mid-animation restores the baseline immediately.
  await page.getByTestId('preview-door').click()
  await expect(page.getByRole('button', { name: 'Stop preview' })).toBeVisible()
  await page.getByRole('button', { name: 'Stop preview' }).click()
  await expect(page.getByTestId('preview-door')).toContainText('Preview door panel motion')
  await expect.poll(translation).toBe('')

  // A zero stroke is a hold with no animation to run.
  const stroke = page.getByLabel('Door panel stroke (mm)')
  await stroke.fill('0')
  await stroke.press('Tab')
  await expect(page.getByTestId('preview-door')).toBeDisabled()

  // Nothing was saved or queued by any preview.
  expect(writes).toHaveLength(0)
  const stored: Revision = await (await request.get('/api/revisions/' + revision.id)).json()
  expect(stored.setup.motion.body.stroke).toBe(5)
  expect(stored.setup.motion.stroke).toBe(10)

  // Reduced motion shows the endpoint and restores without an animation.
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await stroke.fill('6')
  await stroke.press('Tab')
  await page.getByTestId('preview-door').click()
  await expect
    .poll(translation)
    .toMatch(/"panel":\[\d/)
  await expect.poll(translation, { timeout: 5000 }).toBe('')
})
