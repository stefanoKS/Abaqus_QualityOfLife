import { expect, test } from './fixtures'

test('a project holds several named models that can be duplicated and browsed', async ({
  page,
}) => {
  const unique = '5q45 · ' + test.info().title
  await page.goto('/#dashboard')
  await page.getByRole('button', { name: 'New project' }).click()
  await expect(
    page.getByText('A project groups several models. Its first model is created now'),
  ).toBeVisible()
  await page.getByLabel('Project name').fill(unique)
  await page.getByRole('button', { name: 'Create project' }).click()
  // The group and its first model share the project name when no model name is given.
  await expect(page.locator('.crumb')).toContainText(unique)
  await expect(page.getByRole('heading', { name: unique })).toBeVisible()

  await page.goto('/#dashboard')
  const group = page.locator('.group-card').filter({ hasText: unique })
  await expect(group).toContainText('1 model(s)')
  await group.getByRole('button', { name: 'New model' }).click()
  await group.getByLabel('Model name').fill('Door 3D variant')
  await group.getByLabel('Starting geometry').selectOption('3D')
  await group.getByRole('button', { name: 'Create model' }).click()
  await expect(page.getByRole('heading', { name: 'Door 3D variant' })).toBeVisible()
  await expect(page.locator('.subtitle')).toContainText('3D')

  await page.goto('/#dashboard')
  await expect(group).toContainText('2 model(s)')
  await expect(group.getByText('Door 3D variant')).toBeVisible()
  await expect(group.getByText(unique, { exact: true }).first()).toBeVisible()

  // Revisions of a model are reachable from the group.
  const model = group.locator('.model-entry').filter({ hasText: 'Door 3D variant' }).first()
  await model.getByRole('button', { name: 'Revisions', exact: true }).click()
  await expect(group.locator('.revision-list')).toBeVisible()
  await expect(group.locator('.revision-list button').first()).toContainText('Revision 1')

  // Duplicating a model keeps it inside the same group as an independent history.
  await model.getByRole('button', { name: /Duplicate model/ }).click()
  await expect(group).toContainText('3 model(s)')
  await expect(group.getByText('Door 3D variant · copy')).toBeVisible()
})

test('an in-progress region selection survives a language switch', async ({ page, request }) => {
  const revision = await (
    await request.post('/api/projects', { data: { name: 'Selection locale', example: true } })
  ).json()
  await page.goto('/#workspace/' + revision.id)
  await page.getByRole('button', { name: 'Expand Weatherstrip' }).click()
  await page
    .locator('.tree')
    .getByRole('button', { name: 'Hollow bulb', exact: true })
    .click()
  await expect(page.getByRole('heading', { name: 'Hollow bulb' })).toBeVisible()
  await page.getByTestId('assign-material').click()
  await page.getByLabel('Material card').selectOption('base_rubber')
  await page.locator('.lang-button').click()

  // Same selected region and the same edit, now in Japanese. The automatic
  // writer may still be committing, but it never remounts this form: the chosen
  // card and the region selection survive the language switch.
  await expect(page.getByRole('heading', { name: 'Hollow bulb' })).toBeVisible()
  await expect(page.getByLabel('材料カード')).toHaveValue('base_rubber')
  await expect(page.getByTestId('save-state')).toHaveAttribute('data-state', 'saved', {
    timeout: 15000,
  })
  await expect(page.locator('.statusbar')).toContainText('自動保存済み')
})
