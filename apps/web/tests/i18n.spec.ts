import { randomUUID } from 'node:crypto'
import { expect, test } from '@playwright/test'
import type { Job, Revision } from '../src/api'

/**
 * These tests use the default (unmodified) context on purpose: Japanese must be
 * the initial interface language regardless of the browser's own preference.
 */
test('Japanese is the default interface language', async ({ page }) => {
  await page.goto('/#dashboard')
  await expect(page.locator('html')).toHaveAttribute('lang', 'ja')
  await expect(page).toHaveTitle('Abaqus QOL')
  await expect(page.locator('.brand-name')).toHaveText('Abaqus QOL')
  const nav = page.getByRole('navigation', { name: 'メインナビゲーション' })
  await expect(nav.getByRole('button', { name: '作業画面' })).toBeVisible()
  await expect(nav.getByRole('button', { name: 'ダッシュボード' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '解析ダッシュボード' })).toBeVisible()
  await expect(page.getByRole('button', { name: '新規プロジェクト' })).toBeVisible()
})

test('switching to English and back updates the interface without a reload', async ({ page }) => {
  await page.goto('/#dashboard')
  const picker = page.locator('.lang-picker select')
  await picker.selectOption('en')
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await expect(page.getByRole('heading', { name: 'Simulation dashboard' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'New project' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Switch language' })).toBeVisible()
  await picker.selectOption('ja')
  await expect(page.locator('html')).toHaveAttribute('lang', 'ja')
  await expect(page.getByRole('heading', { name: '解析ダッシュボード' })).toBeVisible()
})

test('the language choice survives a reload', async ({ page }) => {
  await page.goto('/#dashboard')
  await page.locator('.lang-picker select').selectOption('en')
  await expect(page.getByRole('heading', { name: 'Simulation dashboard' })).toBeVisible()
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await expect(page.getByRole('heading', { name: 'Simulation dashboard' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save revision' })).toHaveCount(0)
})

test('engineer-entered values and the active step survive a language switch', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Locale edit' } })
  ).json()
  await page.goto('/#workspace/' + revision.id)
  const workflow = page.getByRole('navigation', { name: 'ワークフロー' })
  await workflow.getByRole('button', { name: '移動条件' }).click()
  const travel = page.getByLabel('Y 方向の強制移動量 (mm)')
  await travel.fill('-6.5')
  await travel.press('Tab')
  await expect(page.getByText('未保存の変更があります')).toBeVisible()

  await page.locator('.lang-picker select').selectOption('en')

  // Same step, same committed numeric value, English labels.
  await expect(page.getByRole('navigation', { name: 'Workflow' })).toBeVisible()
  const englishTravel = page.getByLabel('Prescribed Y travel (mm)')
  await expect(englishTravel).toHaveValue('-6.5')
  await expect(page.getByText('Unsaved changes')).toBeVisible()
  // The draft is still unsaved, so saving must remain available.
  await expect(page.getByRole('button', { name: 'Save revision' })).toBeEnabled()
  await page.getByRole('button', { name: 'Save revision' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 02')
  // The engineering value is stored once, untranslated, in the saved revision.
  const projects = (await (await request.get('/api/projects')).json()) as {
    id: string
    revision: string
  }[]
  const head = projects.find((project) => project.id === revision.project)!
  const saved = (await (await request.get('/api/revisions/' + head.revision)).json()) as Revision
  expect(saved.setup.motion.travel).toBe(-6.5)
})

test('job states are translated while the stored value stays machine-readable', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Localized states' } })
  ).json()
  const build: Job = await (
    await request.post('/api/builds', { data: { revision: revision.id, token: randomUUID() } })
  ).json()
  await expect
    .poll(
      async () => ((await (await request.get('/api/jobs/' + build.id)).json()) as Job).status,
      { timeout: 60000 },
    )
    .toBe('Completed')
  const run: Job = await (
    await request.post('/api/runs', {
      data: {
        revision: revision.id,
        build: build.id,
        token: randomUUID(),
        name: 'Localized run',
        scenario: 'success',
        mode: 'DEMO',
      },
    })
  ).json()
  await expect
    .poll(
      async () => ((await (await request.get('/api/jobs/' + run.id)).json()) as Job).status,
      { timeout: 60000 },
    )
    .toBe('Completed')

  await page.goto('/#dashboard')
  const row = page.getByRole('row').filter({ hasText: 'Localized run' })
  await expect(row.locator('.badge')).toHaveText('完了')
  // The raw contract value is retained for diagnostics.
  await expect(row.locator('.badge')).toHaveAttribute('data-status', 'Completed')
  await page.locator('.lang-picker select').selectOption('en')
  await expect(row.locator('.badge')).toHaveText('Completed')
  await expect(page.getByLabel('Filter by status')).toBeVisible()
})

test('accessibility labels are localized in both languages', async ({ page, request }) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'A11y labels' } })
  ).json()
  await page.goto('/#workspace/' + revision.id)
  await expect(page.getByRole('application', { name: '2D 形状ビューポート' })).toBeVisible()
  await expect(page.getByRole('button', { name: '拡大' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: '選択モード' })).toBeVisible()

  await page.locator('.lang-picker select').selectOption('en')

  await expect(page.getByRole('application', { name: '2D engineering viewport' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Zoom in' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Selection mode' })).toBeVisible()
})
