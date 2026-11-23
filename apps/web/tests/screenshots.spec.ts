/**
 * Before/after visual evidence capture. Opt-in only: set SEAL_CAPTURE to a
 * directory name (for example `before`) and run this file alone. It seeds
 * fictional projects through the normal API, the isolated `--test-data` worker
 * and the manufactured launcher double; no operator data or solver is used.
 */
import { test, expect, type APIRequestContext, type Page } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import { randomUUID } from 'node:crypto'
import { resolve } from 'node:path'
import type { Job, Revision } from '../src/api'
import { meshAndDeck } from './pipeline'

const phase = process.env.SEAL_CAPTURE
const out = resolve('../../.local/screenshots', phase || 'scratch')
const viewport = { width: 1440, height: 900 }

test.skip(!phase, 'set SEAL_CAPTURE=before|after to capture visual evidence')
test.describe.configure({ mode: 'serial' })
test.use({ viewport })

async function shot(page: Page, name: string) {
  mkdirSync(out, { recursive: true })
  await page.screenshot({ path: resolve(out, name + '.png'), fullPage: false })
}

async function captureBothLocales(page: Page, name: string) {
  // Japanese is the product default; capture it first, then the English UI.
  await page.evaluate(() => window.localStorage.removeItem('abaqus-qol.language'))
  await page.reload()
  await page.waitForTimeout(400)
  await shot(page, name + '-ja')
  await page.locator('.lang-button').click()
  await page.waitForTimeout(400)
  await shot(page, name + '-en')
}

async function exampleProject(request: APIRequestContext, name: string): Promise<Revision> {
  const response = await request.post('/api/projects', { data: { name, example: true } })
  expect(response.ok()).toBeTruthy()
  return response.json()
}

async function emptyProject(request: APIRequestContext, name: string): Promise<Revision> {
  const response = await request.post('/api/projects', { data: { name, example: false } })
  expect(response.ok()).toBeTruthy()
  return response.json()
}

test('capture dashboard, materials, workspace, review and results', async ({ page, request }) => {
  const seeded = await exampleProject(request, 'Seal programme A')
  const empty = await emptyProject(request, 'New door seal')
  await request.post('/api/materials/import', { data: { revision: seeded.id } })

  // Dashboard: ordinary listing with fictional models.
  await page.goto('/#dashboard')
  await expect(page.getByRole('heading', { name: /Projects|プロジェクト/ })).toBeVisible()
  await page.evaluate(() => window.localStorage.removeItem('abaqus-qol.language'))
  await page.reload()
  await shot(page, 'dashboard-ja')
  await page.locator('.lang-button').click()
  await shot(page, 'dashboard-en')

  // Materials library populated from the example cards.
  await page.goto('/#materials')
  await expect(page.locator('.material-row').first()).toBeVisible()
  await page.evaluate(() => window.localStorage.removeItem('abaqus-qol.language'))
  await page.reload()
  await page.waitForTimeout(300)
  await shot(page, 'materials-ja')
  await page.locator('.lang-button').click()
  await shot(page, 'materials-en')

  // Empty Import stage: no centered viewport call to action.
  await page.goto('/#workspace/' + empty.id)
  await page.getByRole('navigation', { name: /Workflow|ワークフロー/ }).getByRole('button').first().click()
  await page.waitForTimeout(500)
  await captureBothLocales(page, 'empty-import')

  // Populated workspace at Components, with the assembly tree and drawing.
  await page.goto('/#workspace/' + seeded.id)
  await page.waitForTimeout(800)
  await captureBothLocales(page, 'workspace')

  // Review / Run with a real reviewed mesh and prepared deck.
  const { deck } = await meshAndDeck(request, seeded)
  await page.goto('/#workspace/' + seeded.id)
  const workflow = page.getByRole('navigation', { name: /Workflow|ワークフロー/ })
  await workflow.getByRole('button', { name: /Review|レビュー/ }).click()
  await expect(page.getByTestId('deck-status')).toContainText(/Input ready|入力/, {
    timeout: 60000,
  })
  await captureBothLocales(page, 'review')

  // A completed manufactured run through API -> worker -> extractor double.
  const run = (await (
    await request.post('/api/runs', {
      data: {
        revision: seeded.id,
        name: 'Closing run',
        deck: deck.id,
        mode: 'ABAQUS',
        scenario: 'success',
        cpus: 1,
        token: randomUUID(),
      },
    })
  ).json()) as Job
  await expect
    .poll(
      async () => ((await (await request.get('/api/jobs/' + run.id)).json()) as Job).status,
      { timeout: 120000 },
    )
    .toBe('Completed')
  await page.goto('/#results/' + run.id)
  await expect(page.locator('.js-plotly-plot')).toBeVisible({ timeout: 60000 })
  await page.waitForTimeout(500)
  await captureBothLocales(page, 'results')
})
