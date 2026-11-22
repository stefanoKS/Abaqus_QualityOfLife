import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test, type Page } from './fixtures'
import type { Display, Revision } from '../src/api'

/**
 * Two redistributable drawings share the basename `section.dxf` but differ in
 * bytes and geometry (one has a circular cavity). Identity is bound to the model
 * and the stored source digest, never to the display name.
 */
const CAVITY = resolve('tests/fixtures/with-cavity/section.dxf')
const SOLID = resolve('tests/fixtures/without-cavity/section.dxf')

function digest(buffer: Buffer) {
  return createHash('sha256').update(buffer).digest('hex')
}

async function create( page: Page, name: string, group?: string): Promise<Revision> {
  const response = await page.request.post('/api/projects', {
    data: { name, example: false, ...(group ? { group } : {}) },
  })
  expect(response.ok()).toBeTruthy()
  return response.json()
}

async function upload(page: Page, revision: Revision, file: string, fresh = true) {
  await page.goto('/#workspace/' + revision.id)
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Import' })
    .click()
  if (fresh) await expect(page.getByTestId('no-drawing')).toBeVisible()
  await page.locator('input[type=file]').setInputFiles(file)
  await expect(page.locator('.subtitle')).toContainText('section.dxf', { timeout: 60000 })
  await expect(page.locator('.crumb')).toContainText(
    'Revision ' + String(revision.number + 1).padStart(2, '0'),
  )
  const id = page.url().split('/').pop()!
  const imported: Revision = await (await page.request.get('/api/revisions/' + id)).json()
  expect(imported.project).toBe(revision.project)
  return imported
}

async function clickModel(page: Page, revision: Revision, x: number, y: number) {
  const display: Display = await (
    await page.request.post('/api/display', { data: revision.setup })
  ).json()
  const viewport = page.getByRole('application', { name: '2D engineering viewport' })
  const box = (await viewport.boundingBox())!
  const [xmin, xmax, ymin, ymax] = display.bounds
  const scale = Math.min(box.width / (xmax - xmin), box.height / (ymax - ymin)) / 1.2
  await page.mouse.click(
    box.x + box.width / 2 + (x - (xmin + xmax) / 2) * scale,
    box.y + box.height / 2 - (y - (ymin + ymax) / 2) * scale,
  )
}

test('two models keep same-named drawings apart across navigation and restart', async ({
  page,
  request,
  browser,
}) => {
  const group = await (await request.post('/api/groups', { data: { name: '5q45 · drawings' } })).json()
  const a = await create(page, 'Door A', group.id)
  const b = await create(page, 'Door B', group.id)
  const c = await create(page, 'Other group model')

  for (const revision of [a, b, c]) {
    expect(revision.setup.source.kind).toBe('empty')
    await page.goto('/#workspace/' + revision.id)
    await page
      .getByRole('navigation', { name: 'Workflow' })
      .getByRole('button', { name: 'Import' })
      .click()
    await expect(page.getByTestId('no-drawing')).toBeVisible()
  }

  const importedA = await upload(page, a, CAVITY)
  const importedB = await upload(page, b, SOLID)
  expect(importedA.setup.source.filename).toBe('section.dxf')
  expect(importedB.setup.source.filename).toBe('section.dxf')
  expect(importedA.setup.source.digest).not.toBe(importedB.setup.source.digest)
  expect(importedA.project).toBe(a.project)
  expect(importedB.project).toBe(b.project)

  // The original bytes are bound to each revision.
  const bytesA = await (await request.get('/api/revisions/' + importedA.id + '/drawing')).body()
  const bytesB = await (await request.get('/api/revisions/' + importedB.id + '/drawing')).body()
  expect(digest(bytesA)).toBe(digest(readFileSync(CAVITY)))
  expect(digest(bytesB)).toBe(digest(readFileSync(SOLID)))

  // Observable geometry: the cavity centre selects nothing in A and a face in B.
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  const properties = page.locator('.property-body')
  await page.goto('/#workspace/' + importedA.id)
  await workflow.getByRole('button', { name: 'Materials' }).click()
  await clickModel(page, importedA, 10, 5)
  await expect(properties.getByRole('heading', { name: 'Select a region' })).toBeVisible()
  await page.goto('/#workspace/' + importedB.id)
  await workflow.getByRole('button', { name: 'Materials' }).click()
  await clickModel(page, importedB, 10, 5)
  await expect(properties.getByRole('heading', { name: 'Select a region' })).toHaveCount(0)
  await expect(page.getByLabel('Material card')).toBeVisible()

  // A → B → dashboard → A, reload B by URL, Back and Forward.
  await page.goto('/#workspace/' + importedA.id)
  await page.goto('/#workspace/' + importedB.id)
  await expect(page.locator('.crumb-model')).toContainText('Door B')
  await page.getByRole('button', { name: 'Dashboard' }).click()
  await page
    .locator('.model-entry')
    .filter({ hasText: 'Door A' })
    .getByRole('button')
    .first()
    .click()
  await expect(page.locator('.crumb-model')).toContainText('Door A')
  await page.goto('/#workspace/' + importedB.id)
  await page.reload()
  await expect(page.locator('.crumb-model')).toContainText('Door B')
  await page.goBack()
  await expect(page.locator('.crumb-model')).toContainText('Door A')
  await page.goForward()
  await expect(page.locator('.crumb-model')).toContainText('Door B')

  // Brand/Workspace restores the last explicitly opened model, not the first.
  await page.getByRole('button', { name: 'Dashboard' }).click()
  await page.getByRole('button', { name: 'Open the Abaqus QOL workspace' }).click()
  await expect(page.locator('.crumb-model')).toContainText('Door B')

  // C stayed empty throughout.
  const headC: Revision = await (await request.get('/api/revisions/' + c.id)).json()
  expect(headC.setup.source.kind).toBe('empty')

  // A fresh browser session opens the same model and drawing.
  const origin = new URL(page.url()).origin
  const fresh = await browser.newContext()
  const freshPage = await fresh.newPage()
  await freshPage.goto(origin + '/#workspace/' + importedB.id)
  await expect(freshPage.locator('.crumb-model')).toContainText('Door B')
  await expect(freshPage.locator('.subtitle')).toContainText('section.dxf')
  await fresh.close()

  // An invalid link names the missing item and offers a way back.
  await page.goto('/#workspace/00000000-0000-0000-0000-000000000000')
  await expect(page.getByRole('alert')).toContainText('Revision not found')
  await page.getByRole('button', { name: 'Back to Projects' }).click()
  await expect(page.getByRole('heading', { name: 'Simulation dashboard' })).toBeVisible()
})

test('a cancelled or failed import never replaces the last good drawing', async ({
  page,
  request,
}) => {
  const group = await (await request.post('/api/groups', { data: { name: 'recovery' } })).json()
  const a = await create(page, 'Recovery A', group.id)
  const imported = await upload(page, a, CAVITY)

  // Cancelling the file chooser does nothing at all.
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Import' })
    .click()
  await page.locator('input[type=file]').setInputFiles([])
  await expect(page.locator('.crumb')).toContainText('Revision 02')

  // A failed replacement keeps the model, its bytes and its head unchanged.
  await page.locator('input[type=file]').setInputFiles({
    name: 'section.dxf',
    mimeType: 'application/dxf',
    buffer: Buffer.from('this is not a drawing'),
  })
  await expect(page.locator('.statusbar.has-error')).toBeVisible({ timeout: 60000 })
  const projects = await (await request.get('/api/projects')).json()
  const head = projects.find((project: { id: string }) => project.id === a.project)
  expect(head.revision).toBe(imported.id)
  const bytes = await (await request.get('/api/revisions/' + imported.id + '/drawing')).body()
  expect(digest(bytes)).toBe(
    digest(readFileSync(CAVITY)),
  )
})

test('replacing a drawing adds a revision and the earlier one stays downloadable', async ({
  page,
  request,
}) => {
  const group = await (await request.post('/api/groups', { data: { name: 'replace' } })).json()
  const a = await create(page, 'Replace A', group.id)
  const first = await upload(page, a, CAVITY)
  const second = await upload(page, first, SOLID, false)
  expect(second.project).toBe(first.project)
  expect(second.id).not.toBe(first.id)
  expect(second.setup.source.digest).not.toBe(first.setup.source.digest)

  await page.goto('/#workspace/' + first.id)
  await expect(page.locator('.crumb')).toContainText('Revision 02')
  await expect(page.locator('.subtitle')).toContainText('section.dxf')
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Import' })
    .click()
  const download = await page
    .getByRole('link', { name: 'Download source drawing' })
    .getAttribute('href')
  const bytes = await (await request.get(download!)).body()
  expect(digest(bytes)).toBe(
    digest(readFileSync(CAVITY)),
  )
  expect(second.setup.source.digest).not.toBe(first.setup.source.digest)
})

test('an import that finishes in A stays in A while B is open', async ({ page, request }) => {
  const group = await (await request.post('/api/groups', { data: { name: 'delayed import' } })).json()
  const a = await create(page, 'Delayed A', group.id)
  const b = await create(page, 'Delayed B', group.id)
  const importedB = await upload(page, b, SOLID)

  // Queue A's import, then leave for B without waiting for completion.
  await page.goto('/#workspace/' + a.id)
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Import' })
    .click()
  const posted = page.waitForResponse(
    (response) =>
      response.url().includes('/drawing') && response.request().method() === 'POST',
  )
  await page.locator('input[type=file]').setInputFiles(CAVITY)
  await posted
  await page.goto('/#workspace/' + importedB.id)
  await expect(page.locator('.crumb-model')).toContainText('Delayed B')
  await expect(page.locator('.subtitle')).toContainText('section.dxf')

  // A's job completes in its own model while B stays untouched.
  const headOf = async () =>
    (await (await request.get('/api/projects')).json()).find(
      (project: { id: string }) => project.id === a.project,
    )
  await expect.poll(async () => (await headOf()).revisions, { timeout: 60000 }).toBe(2)
  const headA = await headOf()
  const revisionA: Revision = await (await request.get('/api/revisions/' + headA.revision)).json()
  expect(revisionA.setup.source.digest).not.toBe(importedB.setup.source.digest)
  await expect(page.locator('.crumb-model')).toContainText('Delayed B')

  await page.goto('/#workspace/' + headA.revision)
  await expect(page.locator('.crumb-model')).toContainText('Delayed A')
  await expect(page.locator('.subtitle')).toContainText('section.dxf')
})

test('a 3D preview keeps its dimension when a section is imported', async ({ page }) => {
  const model = await create(page, 'Preview only')
  const preview = await (
    await page.request.put('/api/projects/' + model.project, {
      data: {
        base: model.id,
        setup: { ...model.setup, dimension: '3D', formulation: 'extrusion_preview' },
      },
    })
  ).json()
  const imported = await upload(page, preview, SOLID)
  expect(imported.setup.dimension).toBe('3D')
  expect(imported.setup.formulation).toBe('extrusion_preview')
  await expect(page.locator('.subtitle')).toContainText('3D')
})
