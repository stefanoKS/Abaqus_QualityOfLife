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

test('permanent deletion needs a typed confirmation and removes the model', async ({
  page,
  request,
}) => {
  const created = await createProject(request, 'Delete project', 'Disposable')
  await dashboard(page)
  await page.getByRole('button', { name: 'Archive · Disposable' }).click()
  await page.getByLabel('Show archived').check()
  await expect(page.locator('.model-entry.archived').filter({ hasText: 'Disposable' })).toBeVisible()

  const dialogs: string[] = []
  page.on('dialog', async (dialog) => {
    dialogs.push(dialog.type())
    if (dialog.type() === 'confirm') await dialog.accept()
    else await dialog.accept('Disposable')
  })
  await page.getByRole('button', { name: 'Delete model permanently · Disposable' }).click()
  await expect(page.locator('.toast')).toContainText('permanently deleted')
  await expect(page.locator('.model-entry').filter({ hasText: 'Disposable' })).toHaveCount(0)
  expect(dialogs).toEqual(['confirm', 'prompt'])

  const all = (await (await request.get('/api/projects?include_archived=true')).json()) as {
    id: string
  }[]
  expect(all.some((row) => row.id === created.model.project)).toBe(false)
})

test('an archived model opens read-only with a restore explanation', async ({ page, request }) => {
  const created = await createProject(request, 'Readonly project', 'Readonly model')
  await request.post(`/api/projects/${created.model.project}/archive`)
  await page.goto('/#workspace/' + created.model.id)
  await expect(page.getByTestId('archived-banner')).toBeVisible()
  await expect(page.getByTestId('archived-banner')).toContainText('restore it from the dashboard')
  await expect(page.getByRole('button', { name: 'Save revision' })).toBeDisabled()
})
