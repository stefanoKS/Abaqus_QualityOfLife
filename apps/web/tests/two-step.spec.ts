import { expect, test } from './fixtures'
import type { Revision } from '../src/api'

test('the step sequence is derived from the assigned roles, not a mode switch', async ({
  page,
  request,
}) => {
  const single: Revision = await (
    await request.post('/api/projects', { data: { name: 'Single step UI', example: true } })
  ).json()
  await page.goto('/#workspace/' + single.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.getByRole('button', { name: 'Motion' }).click()

  // One door + one seal => one Closing step. No manual analysis-mode selector.
  await expect(page.getByTestId('step-plan')).toContainText('One step')
  await expect(page.getByLabel('Analysis mode')).toHaveCount(0)
  await expect(page.getByLabel('Body panel stroke (mm)')).toHaveCount(0)
  await expect(page.getByLabel('Door panel stroke (mm)')).toHaveValue('10')
  await expect(page.getByLabel('Door panel direction angle (°)')).toHaveValue('-90')
  await expect(page.getByTestId('motion-vector')).toContainText('(0.000, -10.000)')

  // The vector summary is the single direction convention used by deck, plot
  // and CSV: 5 mm at atan2(-4, 3) is (3, -4) mm.
  await page.getByLabel('Door panel stroke (mm)').fill('5')
  await page.getByLabel('Door panel stroke (mm)').press('Tab')
  const angle = String((Math.atan2(-4, 3) * 180) / Math.PI)
  await page.getByLabel('Door panel direction angle (°)').fill(angle)
  await page.getByLabel('Door panel direction angle (°)').press('Tab')
  await expect(page.getByTestId('motion-vector')).toContainText('(3.000, -4.000)')

  // Exactly one body panel participates => the derived sequence is two steps.
  const two: Revision = await (
    await request.post('/api/projects', {
      data: { name: 'Two step UI', example: true, template: 'two-panel' },
    })
  ).json()
  await page.goto('/#workspace/' + two.id)
  await workflow.getByRole('button', { name: 'Motion' }).click()
  await expect(page.getByTestId('step-plan')).toContainText('Two steps')
  await expect(page.getByTestId('step-plan')).toContainText('Body seating')
  await expect(page.getByLabel('Body panel stroke (mm)')).toBeVisible()
  await expect(page.getByLabel('Body panel direction angle (°)')).toHaveValue('90')
  await expect(page.getByLabel('Body panel seating duration (s)')).toBeVisible()
  await expect(page.getByLabel('Door panel stroke (mm)')).toBeVisible()
})

test('a duplicated door role is reported instead of silently choosing one panel', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', {
      data: { name: 'Duplicate roles', example: true, template: 'two-panel' },
    })
  ).json()
  // Turn the body component into a second door: the assignment is ambiguous.
  const edited = structuredClone(revision.setup)
  for (const component of edited.components) {
    if (component.role === 'vehicle_body') component.role = 'moving_panel'
  }
  const saved = await request.put('/api/projects/' + revision.project, {
    data: { base: revision.id, setup: edited },
  })
  expect(saved.ok()).toBeTruthy()
  const stored = await saved.json()

  await page.goto('/#workspace/' + stored.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.getByRole('button', { name: 'Motion' }).click()
  await expect(page.getByTestId('step-plan')).toContainText('One step')
  await expect(page.getByTestId('step-plan-components.duplicate_moving_panel')).toBeVisible()
  // The server also derives door-only: a stale manual mode is not persisted.
  const again = await (await request.get('/api/revisions/' + stored.id)).json()
  expect(again.setup.analysis.mode).toBe('door_only')
})
