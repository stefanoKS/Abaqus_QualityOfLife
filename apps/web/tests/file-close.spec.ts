/**
 * Gate B: Dashboard is the file entry point, Close is reliable, and a file save
 * packages the revision the workspace autosave actually committed.
 */
import { mkdirSync, mkdtempSync, readFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createHash } from 'node:crypto'
import { expect, test, type Page } from './fixtures'
import type { Revision } from '../src/api'

function hashFile(path: string) {
  return createHash('sha256').update(readFileSync(path)).digest('hex')
}

async function head(request: Page['request'], project: string): Promise<Revision> {
  const rows = await (await request.get('/api/projects/' + project + '/revisions')).json()
  return (await request.get('/api/revisions/' + rows[0].id)).json()
}

async function openModel(page: Page, request: Page['request'], name: string) {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name, example: true } })
  ).json()
  await page.goto('/#workspace/' + revision.id)
  return revision
}

async function saveAs(page: Page, folder: string, name: string) {
  await page.getByTestId('model-save').click()
  await expect(page.getByTestId('save-as-dialog')).toBeVisible()
  await page.getByTestId('save-as-dialog').getByLabel(/Folder|フォルダ/).fill(folder)
  await page.getByTestId('save-as-dialog').getByLabel(/File name|ファイル名/).fill(name)
  await page.getByTestId('save-as-confirm').click()
  const path = join(folder, name)
  await expect.poll(() => existsSync(path), { timeout: 20000 }).toBe(true)
  // Clear the first confirmation so the next save is unambiguous.
  const dismiss = page.locator('.toast button[aria-label="Dismiss message"]')
  if (await dismiss.count()) await dismiss.click()
  return path
}

async function openWidth(request: Page['request'], path: string): Promise<number> {
  const reopened = await (
    await request.post('/api/files/model/open', { data: { path } })
  ).json()
  return reopened.setup.analysis.reporting_width
}

async function editWidth(page: Page, value: string, japanese = false) {
  await page
    .getByRole('navigation', { name: japanese ? 'ワークフロー' : 'Workflow' })
    .locator('[data-stage="motion"]')
    .click()
  const width = page.getByLabel(japanese ? /表示幅 W/ : /Reporting width W/)
  await width.fill(value)
  await width.press('Tab')
}

/** Hold the first working-head PUT until ``release`` is called. */
async function holdFirstWrite(page: Page) {
  let release!: () => void
  const gate = new Promise<void>((resolve) => (release = resolve))
  let held = false
  await page.route('**/api/projects/*', async (route) => {
    if (route.request().method() === 'PUT' && !held) {
      held = true
      await gate
    }
    await route.continue()
  })
  return release
}

test('primary navigation is Dashboard → Workspace → Materials in both languages', async ({
  page,
}) => {
  await page.goto('/')
  // Cold start opens the Dashboard, the file entry point.
  await expect(page.getByRole('heading', { name: 'Simulation dashboard' })).toBeVisible()
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  const buttons = nav.getByRole('button')
  await expect(buttons).toHaveCount(3)
  const order = await buttons.allTextContents()
  expect(order.map((text) => text.trim())).toEqual(['Dashboard', 'Workspace', 'Materials'])

  // Visual left-to-right order at desktop width.
  const xs = []
  for (let index = 0; index < 3; index += 1) {
    const box = await buttons.nth(index).boundingBox()
    xs.push(box?.x ?? 0)
  }
  expect(xs[0]).toBeLessThan(xs[1])
  expect(xs[1]).toBeLessThan(xs[2])

  // Keyboard order follows the visual order after the brand.
  await page.locator('.brand').focus()
  const focused: string[] = []
  for (let index = 0; index < 3; index += 1) {
    await page.keyboard.press('Tab')
    focused.push(
      (await page.evaluate(() => document.activeElement?.textContent?.trim() ?? '')),
    )
  }
  expect(focused).toEqual(['Dashboard', 'Workspace', 'Materials'])

  // The same three controls stay reachable and ordered at narrow width.
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(buttons.nth(0)).toBeVisible()
  await expect(buttons.nth(1)).toBeVisible()
  await expect(buttons.nth(2)).toBeVisible()
  expect((await buttons.allTextContents()).map((text) => text.trim())).toEqual([
    'Dashboard',
    'Workspace',
    'Materials',
  ])

  // Japanese: the same order with the localized names.
  await page.setViewportSize({ width: 1440, height: 960 })
  await page.locator('.lang-button').click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'ja')
  const japanese = page.getByRole('navigation', { name: 'メインナビゲーション' })
  expect((await japanese.getByRole('button').allTextContents()).map((t) => t.trim())).toEqual([
    'ダッシュボード',
    '作業画面',
    '材料ライブラリ',
  ])
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(japanese.getByRole('button').nth(2)).toBeVisible()
})

test('Materials is a detour: Workspace returns to the active document', async ({
  page,
  request,
}) => {
  const revision = await openModel(page, request, 'Return from materials')
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('button', { name: 'Materials' }).click()
  await expect(page).toHaveURL(/#materials/)
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('button', { name: 'Workspace' }).click()
  await expect(page).toHaveURL(new RegExp('#workspace/' + revision.id))
  await expect(page.getByTestId('model-save')).toBeEnabled()
})

test('Close ends the tab document and blocks a silent reopen', async ({ page, request }) => {
  const revision = await openModel(page, request, 'Close me')
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('button', { name: 'Dashboard' }).click()
  await expect(page.getByTestId('file-active')).toContainText('Close me')
  await expect(page.getByTestId('file-active')).toContainText(/Not saved to a file/)
  await page.getByTestId('file-close').click()
  await expect(page.getByTestId('file-active')).toHaveCount(0)
  await expect(page.locator('.toast')).toContainText('Closed Close me')

  // Workspace does not silently reopen the closed document.
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('button', { name: 'Workspace' }).click()
  await expect(page).toHaveURL(/#dashboard/)
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Simulation dashboard' })).toBeVisible()
  await expect(page).toHaveURL(/#dashboard/)
  // The model itself is untouched and still listed.
  const listed = await (await request.get('/api/projects')).json()
  expect(listed.some((row: { id: string }) => row.id === revision.project)).toBe(true)
})

test('a closed file is reopened deliberately from Recent files', async ({ page, request }) => {
  const revision = await openModel(page, request, 'Recent document')
  const folder = mkdtempSync(join(tmpdir(), 'gate-b-recent-'))
  const path = await saveAs(page, folder, 'recent.aqmodel')
  await expect.poll(() => existsSync(path)).toBe(true)
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('button', { name: 'Dashboard' }).click()
  await expect(page.getByTestId('file-active')).toContainText('recent.aqmodel')
  await page.getByTestId('file-close').click()
  await expect(page.getByTestId('file-active')).toHaveCount(0)
  // The path is not silently reopened, but a Recent click is deliberate.
  await page.getByTestId('file-bar').getByText('Recent files').scrollIntoViewIfNeeded()
  await page.locator('.file-recent button').filter({ hasText: 'recent.aqmodel' }).first().click()
  await page.getByTestId('file-bar').getByRole('button', { name: /^Open$|^開く$/ }).click()
  await expect(page.getByTestId('model-file')).toContainText('recent.aqmodel')
  expect(revision.project).not.toBe(undefined)
})

test('a second tab keeps its own active document', async ({ context, request }) => {
  const first: Revision = await (
    await request.post('/api/projects', { data: { name: 'Tab one', example: true } })
  ).json()
  const second: Revision = await (
    await request.post('/api/projects', { data: { name: 'Tab two', example: true } })
  ).json()
  const one = await context.newPage()
  const two = await context.newPage()
  await one.goto('/#workspace/' + first.id)
  await two.goto('/#workspace/' + second.id)
  await expect(one.getByTestId('model-save')).toBeEnabled()
  await expect(two.getByTestId('model-save')).toBeEnabled()
  await one.getByRole('navigation', { name: 'Main navigation' }).getByRole('button', { name: 'Dashboard' }).click()
  await one.getByTestId('file-close').click()
  // Closing in the first tab leaves the second tab's document open.
  await two.bringToFront()
  await expect(two.getByTestId('model-save')).toBeEnabled()
  await two.getByRole('navigation', { name: 'Main navigation' }).getByRole('button', { name: 'Workspace' }).click()
  await expect(two).toHaveURL(new RegExp('#workspace/' + second.id))
  expect(first.project).not.toBe(second.project)
})

test('Ctrl+S packages the flushed edit while the working-head write is held', async ({
  page,
  request,
}) => {
  const revision = await openModel(page, request, 'Held save')
  const folder = mkdtempSync(join(tmpdir(), 'gate-b-save-'))
  const path = await saveAs(page, folder, 'held.aqmodel')
  await expect.poll(() => existsSync(path)).toBe(true)
  expect((await head(request, revision.project)).setup.analysis.reporting_width).toBe(100)

  const release = await holdFirstWrite(page)
  await editWidth(page, '111')
  // Immediately save: the flush must wait for the held write and package 111.
  await page.getByTestId('model-save').click()
  await page.waitForTimeout(800)
  release()
  await expect(page.locator('.toast')).toContainText('Saved to', { timeout: 30000 })
  await expect(page.getByTestId('model-save')).toBeEnabled({ timeout: 30000 })

  // The on-disk file itself contains 111, not the previous head.
  await expect.poll(() => openWidth(request, path), { timeout: 30000 }).toBe(111)
  await expect
    .poll(async () => (await head(request, revision.project)).setup.analysis.reporting_width, {
      timeout: 30000,
    })
    .toBe(111)
})

test('Save & Close packages the flushed edit while the working-head write is held', async ({
  page,
  request,
}) => {
  const revision = await openModel(page, request, 'Held save and close')
  const folder = mkdtempSync(join(tmpdir(), 'gate-b-close-'))
  const path = await saveAs(page, folder, 'held-close.aqmodel')
  await expect.poll(() => existsSync(path)).toBe(true)
  const before = hashFile(path)

  const release = await holdFirstWrite(page)
  await editWidth(page, '111')
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('button', { name: 'Dashboard' }).click()
  await expect(page.getByTestId('file-active')).toContainText('held-close.aqmodel')
  await page.getByTestId('file-close').click()
  await expect(page.getByTestId('close-dialog')).toBeVisible()
  await page.getByTestId('close-save').click()
  await page.waitForTimeout(600)
  release()
  await expect(page.getByTestId('file-active')).toHaveCount(0, { timeout: 40000 })
  expect(hashFile(path)).not.toBe(before)

  await expect.poll(() => openWidth(request, path), { timeout: 30000 }).toBe(111)
  await expect
    .poll(async () => (await head(request, revision.project)).setup.analysis.reporting_width, {
      timeout: 30000,
    })
    .toBe(111)
})

test('Cancel and a failed disk write keep the document and its draft', async ({
  page,
  request,
}) => {
  await openModel(page, request, 'Failed save')
  const folder = mkdtempSync(join(tmpdir(), 'gate-b-fail-'))
  const path = await saveAs(page, folder, 'failed.aqmodel')
  await expect.poll(() => existsSync(path)).toBe(true)

  await editWidth(page, '113')
  await expect(page.getByTestId('save-state')).toHaveAttribute('data-state', 'saved', {
    timeout: 20000,
  })
  // A failed disk write reports the cause, keeps the document and the draft.
  await page.route('**/api/files/model/save', (route) => route.abort('failed'))
  await page.getByTestId('model-save').click()
  await expect(page.locator('.toast')).toBeVisible({ timeout: 20000 })
  await expect(page.getByTestId('model-file')).toContainText('failed.aqmodel')
  await expect(page.getByLabel(/Reporting width W/)).toHaveValue('113')
  await page.unroute('**/api/files/model/save')

  // Closing is cancelled explicitly: nothing is discarded.
  await page.getByRole('navigation', { name: 'Main navigation' }).getByRole('button', { name: 'Dashboard' }).click()
  await page.getByTestId('file-close').click()
  await page.getByTestId('close-cancel').click()
  await expect(page.getByTestId('file-active')).toContainText('failed.aqmodel')
})

test('Save As accepts a Japanese folder and file name', async ({ page, request }) => {
  await openModel(page, request, '日本語モデル')
  const root = mkdtempSync(join(tmpdir(), 'gate-b-ja-'))
  const folder = join(root, '設計データ')
  mkdirSync(folder)
  await page.locator('.lang-button').click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'ja')
  await page.getByTestId('model-save').click()
  await page.getByTestId('save-as-dialog').getByLabel(/フォルダ/).fill(folder)
  await page.getByTestId('save-as-dialog').getByLabel(/ファイル名/).fill('シール.aqmodel')
  await page.getByTestId('save-as-confirm').click()
  const written = join(folder, 'シール.aqmodel')
  await expect.poll(() => existsSync(written), { timeout: 20000 }).toBe(true)
  await expect(page.getByTestId('model-file')).toContainText('シール.aqmodel')
})
