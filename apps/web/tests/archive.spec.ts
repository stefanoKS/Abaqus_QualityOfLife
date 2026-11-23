import { randomUUID } from 'node:crypto'
import { expect, test, type Page } from './fixtures'

async function createProject(
  request: import('@playwright/test').APIRequestContext,
  group: string,
  model: string,
): Promise<{
  group: { id: string; name: string }
  model: { id: string; project: string; setup: { name: string } }
}> {
  const response = await request.post('/api/project-groups', {
    data: {
      name: group,
      model_name: model,
      example: true,
      token: randomUUID(),
    },
  })
  return response.json()
}

async function dashboard(page: Page) {
  await page.goto('/#dashboard')
}

test('a model can be archived, shown on demand and restored', async ({ page, request }) => {
  const created = await createProject(request, 'Archive project', 'Door A')
  await dashboard(page)
  const card = page.locator('.model-entry').filter({ hasText: 'Door A' })
  await expect(card).toBeVisible()

  await page.getByRole('button', { name: 'Archive · Door A' }).click()
  await expect(card).toHaveCount(0)
  await page.getByLabel('Show archived').check()
  await expect(page.locator('.model-entry').filter({ hasText: 'Door A' })).toBeVisible()
  await expect(page.locator('.model-entry.archived').filter({ hasText: 'Door A' })).toBeVisible()

  await page.getByRole('button', { name: 'Restore · Door A' }).click()
  await page.getByLabel('Show archived').uncheck()
  await expect(page.locator('.model-entry').filter({ hasText: 'Door A' })).toBeVisible()
})

test('a whole project group can be archived and restored', async ({ page, request }) => {
  await createProject(request, 'Whole project', 'Group model')
  await dashboard(page)
  const group = page.locator('.group-card').filter({ hasText: 'Whole project' })
  await expect(group).toBeVisible()
  await page.getByRole('button', { name: 'Archive · Whole project' }).click()
  await expect(page.locator('.group-card').filter({ hasText: 'Whole project' })).toHaveCount(0)

  await page.getByLabel('Show archived').check()
  const archivedGroup = page.locator('.group-card').filter({ hasText: 'Whole project' })
  await expect(archivedGroup).toBeVisible()
  await expect(archivedGroup).toContainText('Archived')
  await expect(archivedGroup.getByRole('button', { name: 'New model' })).toBeDisabled()

  await page.getByRole('button', { name: 'Restore · Whole project' }).click()
  await expect(
    page.locator('.group-card').filter({ hasText: 'Whole project' }).getByText('Archived'),
  ).toHaveCount(0)
})

test('permanent deletion is available without archiving and needs the typed dialog', async ({
  page,
  request,
}) => {
  const created = await createProject(request, 'Delete project', 'Disposable')
  await request.post('/api/materials/import', { data: { revision: created.model.id } })
  await dashboard(page)
  const card = () => page.locator('.model-entry').filter({ hasText: 'Disposable' })
  await expect(card()).toBeVisible()

  // Cancel and Escape make no change and return focus to the destructive action.
  const trigger = page.getByRole('button', { name: 'Delete model permanently · Disposable' })
  await trigger.click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('Disposable')
  await expect(dialog.getByRole('button', { name: 'Delete permanently' })).toBeDisabled()
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
  await expect(card()).toBeVisible()

  await trigger.click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(card()).toBeVisible()

  // A wrong name cannot enable deletion; the exact name does.
  await trigger.click()
  const input = page.getByRole('dialog').locator('input')
  await input.fill('disposable')
  await expect(page.getByRole('button', { name: 'Delete permanently' })).toBeDisabled()
  await input.fill('Disposable')
  await page.getByRole('button', { name: 'Delete permanently' }).click()
  await expect(page.locator('.toast')).toContainText('permanently deleted')
  await expect(card()).toHaveCount(0)

  const all = (await (await request.get('/api/projects?include_archived=true')).json()) as {
    id: string
  }[]
  expect(all.some((row) => row.id === created.model.project)).toBe(false)
  // Library cards survive a model deletion.
  const library = (await (await request.get('/api/materials')).json()) as { name: string }[]
  expect(library.length).toBeGreaterThan(0)
})

test('an unarchived mixed project group is deleted directly from its listing', async ({
  page,
  request,
}) => {
  const created = await createProject(request, 'Direct group', 'First model')
  const second = await request.post('/api/projects', {
    data: { name: 'Second model', example: true, group: created.group.id },
  })
  expect(second.ok()).toBeTruthy()
  const sibling = await createProject(request, 'Keep group', 'Keep model')
  await request.post(`/api/projects/${created.model.project}/archive`)
  await dashboard(page)
  const group = page.locator('.group-card').filter({ hasText: 'Direct group' })
  await expect(group).toBeVisible()
  // The archived child is hidden from the ordinary listing; the deletion impact still counts it.\n  await expect(group).toContainText('1 model(s)')
  await group.getByRole('button', { name: 'Delete project permanently · Direct group' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('Revisions')
  await dialog.locator('input').fill('Direct group')
  await dialog.getByRole('button', { name: 'Delete permanently' }).click()
  await expect(page.locator('.toast')).toContainText('permanently deleted')
  await expect(group).toHaveCount(0)
  await expect(page.locator('.group-card').filter({ hasText: 'Keep group' })).toBeVisible()

  const models = (await (
    await request.get('/api/projects?include_archived=true')
  ).json()) as { id: string; group: string }[]
  expect(models.some((row) => row.group === created.group.id)).toBe(false)
  expect(models.some((row) => row.group === sibling.group.id)).toBe(true)
})

test('an archived model opens read-only with a restore explanation', async ({ page, request }) => {
  const created = await createProject(request, 'Readonly project', 'Readonly model')
  await request.post(`/api/projects/${created.model.project}/archive`)
  await page.goto('/#workspace/' + created.model.id)
  await expect(page.getByTestId('archived-banner')).toBeVisible()
  await expect(page.getByTestId('archived-banner')).toContainText('restore it from the dashboard')
  await expect(page.getByRole('button', { name: 'Save revision' })).toBeDisabled()
})
