/**
 * Gate 6: folder-based model and result files.
 *
 * The browser writes real files into a temporary folder supplied by the test.
 * A result file is produced by the isolated worker after the page is closed,
 * which is the "tab closed" case the acceptance requires.
 */
import { mkdtempSync, readFileSync, readdirSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { randomUUID, createHash } from 'node:crypto'
import { expect, test } from './fixtures'
import { meshAndDeck } from './pipeline'
import type { Job, Revision } from '../src/api'

function hashFile(path: string) {
  return createHash('sha256').update(readFileSync(path)).digest('hex')
}

test('New → Save As → edit → Save keeps the pathname and Save As keeps the original bytes', async ({
  page,
  request,
}) => {
  const folder = mkdtempSync(join(tmpdir(), 'aqmodel-'))
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'File model', example: true } })
  ).json()
  await page.goto('/#workspace/' + revision.id)

  // First Save prompts for a folder and a name.
  await page.getByTestId('model-save').click()
  await expect(page.getByTestId('save-as-dialog')).toBeVisible()
  await page.getByTestId('save-as-dialog').getByLabel(/Folder|フォルダ/).fill(folder)
  await page
    .getByTestId('save-as-dialog')
    .getByLabel(/File name|ファイル名/)
    .fill('seal.aqmodel')
  await page.getByTestId('save-as-confirm').click()
  const first = join(folder, 'seal.aqmodel')
  await expect.poll(() => existsSync(first), { timeout: 20000 }).toBe(true)
  await expect(page.getByTestId('model-file')).toContainText('seal.aqmodel')
  const original = readFileSync(first)
  const originalHash = hashFile(first)

  // Edit and press Ctrl+S: the same file is replaced, not a new one.
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .locator('[data-stage="motion"]')
    .click()
  const width = page.getByLabel('Reporting width W (mm)')
  await width.fill('111')
  await width.press('Tab')
  await expect(
    page.locator('[data-testid="save-state"][data-state="saved"][data-dirty="false"]'),
  ).toHaveCount(1, { timeout: 20000 })
  await page.keyboard.press('Control+s')
  await expect.poll(() => hashFile(first), { timeout: 20000 }).not.toBe(originalHash)
  expect(readdirSync(folder).filter((name) => name.endsWith('.aqmodel'))).toHaveLength(1)

  // Save As to a second name: the original bytes are untouched.
  const editedHash = hashFile(first)
  await page.getByTestId('model-save-as').click()
  await page.getByTestId('save-as-dialog').getByLabel(/Folder|フォルダ/).fill(folder)
  await page
    .getByTestId('save-as-dialog')
    .getByLabel(/File name|ファイル名/)
    .fill('seal-copy.aqmodel')
  await page.getByTestId('save-as-confirm').click()
  const copy = join(folder, 'seal-copy.aqmodel')
  await expect.poll(() => existsSync(copy), { timeout: 20000 }).toBe(true)
  expect(hashFile(first)).toBe(editedHash)
  expect(hashFile(copy)).not.toBe(editedHash)

  // Open the copy through the File entry point: it is a new independent head.
  await page.getByRole('button', { name: /Dashboard|ダッシュボード/ }).first().click()
  await expect(page.getByTestId('file-bar')).toBeVisible()
  await page.getByTestId('file-open-model').click()
  await page.getByTestId('file-bar').getByLabel(/Model file|モデルファイル/).fill(copy)
  await page.getByTestId('file-bar').getByRole('button', { name: /^Open$|^開く$/ }).click()
  await expect(page.getByTestId('model-file')).toContainText('seal-copy.aqmodel')
  // The copy is a new independent model; its own history starts at revision 1.
  await expect(page.locator('.run-banner, .page-heading')).toBeVisible()
})

test('the worker publishes a result file after extraction while the tab is closed', async ({
  page,
  request,
}) => {
  const folder = mkdtempSync(join(tmpdir(), 'aqresult-'))
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'File result', example: true } })
  ).json()
  const { deck } = await meshAndDeck(request, revision)
  const run: Job = await (
    await request.post('/api/runs', {
      data: {
        revision: revision.id,
        deck: deck.id,
        token: randomUUID(),
        name: 'File result run',
        mode: 'ABAQUS',
        cpus: 1,
        output_dir: folder,
      },
    })
  ).json()
  // Close the only browser page: publication must not depend on it.
  await page.close()
  await expect
    .poll(
      () =>
        readdirSync(folder).filter((name) => name.endsWith('.aqresult')).length,
      { timeout: 90000 },
    )
    .toBe(1)
  const packaged = readdirSync(folder).find((name) => name.endsWith('.aqresult'))!
  expect(packaged).toMatch(/\.aqresult$/)
  expect(readFileSync(join(folder, packaged)).length).toBeGreaterThan(100)

  // Open the result in a fresh tab; it is read-only evidence with its frames.
  const reopened = await request.post('/api/files/result/open', {
    data: { path: join(folder, packaged) },
  })
  expect(reopened.ok()).toBeTruthy()
  const job = (await reopened.json()) as Job
  await expect
    .poll(async () => (await request.get('/api/jobs/' + job.id)).json())
    .toMatchObject({ status: 'Completed', publication: 'Imported' })
})
