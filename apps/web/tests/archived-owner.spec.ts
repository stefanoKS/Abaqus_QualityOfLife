/**
 * Gate A: a standalone file document is editable even while the historical
 * migration group is archived.
 *
 * The real File → New and Open Model buttons are used. The archived group is
 * created through the ordinary API, which is the operator's configuration.
 */
import { randomUUID } from 'node:crypto'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { expect, test, type Page } from './fixtures'
import type { Group, Revision } from '../src/api'

const DRAWING = resolve('tests/fixtures/units/millimetres.dxf')

async function archiveAGroup(request: Page['request'], name: string) {
  const created = await (
    await request.post('/api/project-groups', {
      data: { name, model_name: 'Existing model', token: randomUUID() },
    })
  ).json()
  const archived = await request.post('/api/groups/' + created.group.id + '/archive')
  expect(archived.ok()).toBeTruthy()
  return created.group as Group
}

async function head(request: Page['request'], project: string): Promise<Revision> {
  const rows = await (
    await request.get('/api/projects/' + project + '/revisions')
  ).json()
  expect(Array.isArray(rows) && rows.length > 0).toBe(true)
  const response = await request.get('/api/revisions/' + rows[0].id)
  expect(response.ok()).toBeTruthy()
  return response.json()
}

async function editWidth(
  page: Page,
  request: Page['request'],
  project: string,
  value: number,
) {
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .locator('[data-stage="motion"]')
    .click()
  const width = page.getByLabel('Reporting width W (mm)')
  await width.fill(String(value))
  await width.press('Tab')
  // The autosave is asynchronous; the committed head is the assertion, not the
  // transient save indicator.
  await expect
    .poll(async () => (await head(request, project)).setup.analysis.reporting_width, {
      timeout: 30000,
    })
    .toBe(value)
}

test('File → New is editable while the migration group is archived', async ({
  page,
  request,
}) => {
  // Two same-name groups: ownership must never be decided by a display name.
  const legacy = await archiveAGroup(request, 'Imported projects')
  await archiveAGroup(request, 'Imported projects')
  await page.goto('/#dashboard')

  await page.getByTestId('file-new').click()
  await expect(page).toHaveURL(/#workspace\/[0-9a-f-]{36}/)
  const model = new URL(page.url()).hash.split('/')[1]
  await expect(page.getByTestId('archived-banner')).toHaveCount(0)
  await expect(page.getByTestId('model-save')).toBeEnabled()
  await expect(page.getByTestId('save-state')).toHaveAttribute('data-state', 'saved', {
    timeout: 20000,
  })

  const created = await head(
    request,
    (await (await request.get('/api/revisions/' + model)).json()).project,
  )
  expect(created.archived).toBe(false)
  expect(created.group_archived).toBe(false)

  await editWidth(page, request, created.project, 111)

  // The drawing import of the new document queues normally.
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Import' })
    .click()
  await page.locator('input[type=file]').setInputFiles(DRAWING)
  await expect(page.locator('.subtitle')).toContainText('millimetres.dxf', { timeout: 60000 })

  // The archived group and its original model are untouched and still read-only.
  const groups = await (await request.get('/api/groups?include_archived=true')).json()
  const found = groups.find((row: Group) => row.id === legacy.id)
  expect(found?.archived).toBe(true)
  const refused = await request.post('/api/projects', {
    data: { name: 'Refused', group: legacy.id },
  })
  expect(refused.status()).toBe(409)
})

test('Open Model produces an editable document and recovery is deliberate', async ({
  page,
  request,
}) => {
  // A file saved from a normal model, opened while the migration group is archived.
  const source: Revision = await (
    await request.post('/api/projects', { data: { name: 'Portable source', example: true } })
  ).json()
  const folder = mkdtempSync(join(tmpdir(), 'gate-a-'))
  const path = join(folder, 'seal.aqmodel')
  const saved = await request.post('/api/files/model/save', {
    data: { revision: source.id, path },
  })
  expect(saved.ok()).toBeTruthy()
  const legacy = await archiveAGroup(request, 'Imported projects')

  await page.goto('/#dashboard')
  await page.getByTestId('file-open-model').click()
  await page.getByTestId('file-bar').getByLabel(/Model file|モデルファイル/).fill(path)
  await page.getByTestId('file-bar').getByRole('button', { name: /^Open$|^開く$/ }).click()
  await expect(page.getByTestId('model-file')).toContainText('seal.aqmodel')
  await expect(page.getByTestId('archived-banner')).toHaveCount(0)
  await expect(page.getByTestId('model-save')).toBeEnabled()

  const opened = await (await request.get('/api/revisions/' + page.url().split('/').pop())).json()
  expect(opened.project).not.toBe(source.project)
  expect(opened.archived).toBe(false)
  expect(opened.group_archived).toBe(false)
  await editWidth(page, request, opened.project, 112)

  // The direct endpoint behaves the same.
  const direct = await request.post('/api/files/model/open', { data: { path } })
  expect(direct.ok()).toBeTruthy()
  expect((await direct.json()).group_archived).toBe(false)

  // A stranded model is recovered only through a deliberate action, into a new
  // editable identity, while the original group stays archived.
  const stranded = await (
    await request.post('/api/project-groups', {
      data: { name: 'Stranded household', model_name: 'Stranded', token: randomUUID() },
    })
  ).json()
  await request.post('/api/groups/' + stranded.group.id + '/archive')
  await page.goto('/#dashboard')
  await page.getByLabel('Show archived').check()
  const card = page.locator('.model-entry').filter({ hasText: 'Stranded' }).first()
  await card.getByRole('button', { name: /Recover as an editable copy/ }).click()
  await expect(page.getByTestId('archived-banner')).toHaveCount(0)
  await expect(page.getByTestId('model-save')).toBeEnabled()
  const recovered = await (await request.get('/api/revisions/' + page.url().split('/').pop())).json()
  expect(recovered.project).not.toBe(stranded.model.project)
  expect(recovered.group_archived).toBe(false)
  // The migration group referenced above is still the archived one.
  expect((await (await request.get('/api/groups?include_archived=true')).json())
    .find((row: Group) => row.id === legacy.id)?.archived).toBe(true)
})
