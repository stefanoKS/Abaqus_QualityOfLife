import { randomUUID } from 'node:crypto'
import { expect, test } from '@playwright/test'
import { meshAndDeck } from './pipeline'
import type { Job, Revision } from '../src/api'
import { en, ja } from '../src/i18n'

/** Build the expected accessible name from the dictionaries, not a literal. */
function switchLabel(destination: string, japanese: boolean): string {
  const template = (japanese ? ja : en)['lang.switchTo']
  return template.replace('{language}', destination)
}

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

test('the language button names the destination language and switches in one activation', async ({
  page,
}) => {
  await page.goto('/#dashboard')
  const button = page.locator('.lang-button')
  // Japanese interface: the button offers English, and names the action.
  await expect(button).toHaveText(en['lang.en'])
  await expect(button).toHaveAttribute('aria-label', switchLabel(en['lang.en'], true))
  await button.focus()
  await expect(button).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  // English interface: the button offers Japanese.
  await expect(button).toHaveText(ja['lang.ja'])
  await expect(button).toHaveAttribute('aria-label', switchLabel(ja['lang.ja'], false))
  await button.focus()
  await page.keyboard.press(' ')
  await expect(page.locator('html')).toHaveAttribute('lang', 'ja')
})

test('switching to English and back updates the interface without a reload', async ({ page }) => {
  await page.goto('/#dashboard')
  const picker = page.locator('.lang-button')
  await page.locator('.lang-button').click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await expect(page.getByRole('heading', { name: 'Simulation dashboard' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'New project' })).toBeVisible()
  await expect(picker).toBeVisible()
  await page.locator('.lang-button').click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'ja')
  await expect(page.getByRole('heading', { name: '解析ダッシュボード' })).toBeVisible()
})

test('the language choice survives a reload', async ({ page }) => {
  await page.goto('/#dashboard')
  await page.locator('.lang-button').click()
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
    await request.post('/api/projects', { data: { name: 'Locale edit', example: true } })
  ).json()
  await page.goto('/#workspace/' + revision.id)
  const workflow = page.getByRole('navigation', { name: 'ワークフロー' })
  await workflow.getByRole('button', { name: '移動条件' }).click()
  const travel = page.getByLabel('Y 方向の強制移動量 (mm)')
  await travel.fill('-6.5')
  await travel.press('Tab')
  await expect(page.getByText('未保存の変更があります')).toBeVisible()

  await page.locator('.lang-button').click()

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
    await request.post('/api/projects', { data: { name: 'Localized states', example: true } })
  ).json()
  const { deck } = await meshAndDeck(request, revision)
  const run: Job = await (
    await request.post('/api/runs', {
      data: {
        revision: revision.id,
        deck: deck.id,
        token: randomUUID(),
        name: 'Localized run',
        mode: 'ABAQUS',
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
  await page.locator('.lang-button').click()
  await expect(row.locator('.badge')).toHaveText('Completed')
  await expect(page.getByLabel('Filter by status')).toBeVisible()
})

test('accessibility labels are localized in both languages', async ({ page, request }) => {  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'A11y labels', example: true } })
  ).json()
  await page.goto('/#workspace/' + revision.id)
  await expect(page.getByRole('application', { name: '2D 形状ビューポート' })).toBeVisible()
  await expect(page.getByRole('button', { name: '拡大' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: '選択モード' })).toBeVisible()

  await page.locator('.lang-button').click()

  await expect(page.getByRole('application', { name: '2D engineering viewport' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Zoom in' })).toBeVisible()
  await expect(page.getByRole('combobox', { name: 'Selection mode' })).toBeVisible()
})

test('Japanese Create, Import, Mesh, Mounting, Review and Results labels are readable', async ({
  page,
  request,
}) => {
  await page.goto('/#dashboard')
  await page.getByRole('button', { name: '新規プロジェクト' }).click()
  await expect(page.getByLabel('プロジェクト名')).toBeVisible()
  await expect(page.getByLabel('モデル名')).toBeVisible()
  await expect(page.getByLabel('公開サンプル断面から開始する')).toBeVisible()
  await expect(page.getByRole('button', { name: 'プロジェクトを作成' })).toBeVisible()
  await page.getByRole('button', { name: 'キャンセル' }).click()

  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: '日本語確認', example: true } })
  ).json()
  await page.goto('/#workspace/' + revision.id)
  const workflow = page.getByRole('navigation', { name: 'ワークフロー' })

  await workflow.getByRole('button', { name: '図面読込' }).click()
  await expect(page.getByRole('heading', { name: '図面ソース' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'DXF / DWG を読み込む' })).toBeVisible()

  await workflow.getByRole('button', { name: 'メッシュ' }).click()
  await expect(page.getByRole('heading', { name: '断面メッシュ' })).toBeVisible()
  await expect(page.getByLabel('全体サイズ (mm)')).toBeVisible()
  await page.getByRole('button', { name: 'メッシュを生成' }).click()
  await expect(page.getByTestId('mesh-status')).toContainText('メッシュ準備完了', {
    timeout: 60000,
  })

  await workflow.getByRole('button', { name: '固定条件' }).click()
  await expect(page.getByRole('heading', { name: '固定条件' })).toBeVisible()
  await expect(page.getByText('固定節点（WSFIX）').first()).toBeVisible()
  await expect(page.getByLabel('矩形選択モード')).toBeVisible()
  await expect(page.getByLabel('矩形選択の動作')).toBeVisible()

  await workflow.getByRole('button', { name: '解析条件確認・実行' }).click()
  await expect(page.getByRole('heading', { name: 'メッシュ識別情報' })).toBeVisible()
  await expect(page.getByRole('button', { name: '入力デッキを作成' })).toBeVisible()
  await expect(page.getByText('「入力デッキを作成」はメッシュ生成ジョブを一切投入しません。')).toBeVisible()
  // The language button names the destination language in readable Japanese UI.
  await expect(page.locator('.lang-button')).toHaveText('English')

  const { deck } = await meshAndDeck(request, revision)
  const run: Job = await (
    await request.post('/api/runs', {
      data: {
        revision: revision.id,
        deck: deck.id,
        token: randomUUID(),
        name: '日本語結果',
        mode: 'ABAQUS',
      },
    })
  ).json()
  await expect
    .poll(
      async () => ((await (await request.get('/api/jobs/' + run.id)).json()) as Job).status,
      { timeout: 90000 },
    )
    .toBe('Completed')
  await page.goto('/#results/' + run.id)
  await expect(page.getByRole('heading', { name: '荷重－変位' })).toBeVisible()
  await expect(page.getByText('ドアパネル応答').first()).toBeVisible()
  await expect(page.locator('.lang-button')).toHaveText('English')
})
