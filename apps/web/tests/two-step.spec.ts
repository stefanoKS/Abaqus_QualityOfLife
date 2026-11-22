import { expect, test } from './fixtures'
import type { Revision } from '../src/api'

test('the two-step mode exposes body motion and requires a moving body', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Two step UI', example: true } })
  ).json()
  await page.goto('/#workspace/' + revision.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.getByRole('button', { name: 'Motion' }).click()
  await expect(page.getByLabel('Analysis mode')).toHaveValue('door_only')
  await expect(page.getByLabel('Body travel (mm, signed)')).toHaveCount(0)

  await page
    .getByLabel('Analysis mode')
    .selectOption('body_then_door')
  await expect(page.getByLabel('Body travel (mm, signed)')).toBeVisible()
  await expect(page.getByLabel('Body seating duration (s)')).toBeVisible()
  await expect(page.getByLabel('Body initial Y offset (mm)')).toBeVisible()
  await expect(page.getByTestId('motion-needs-body')).toBeVisible()

  // Saving without a moving-body component is rejected by the model validator.
  await page.getByRole('button', { name: 'Save revision' }).click()
  await expect(page.locator('.toast')).toContainText('moving body')
  await expect(page.locator('.crumb')).not.toContainText('Revision 02')

  // Switching back restores the legacy single-step fields and hides body motion.
  await page.getByLabel('Analysis mode').selectOption('door_only')
  await expect(page.getByLabel('Body travel (mm, signed)')).toHaveCount(0)
  await expect(page.getByLabel('Prescribed Y travel (mm)')).toBeVisible()
})
