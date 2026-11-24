/**
 * Gate A: the dashboard run list at every width the operator uses.
 *
 * The measured defects were (1) filter selects whose intrinsic width was set by
 * long project/model names and which protruded past the card's clipping edge,
 * and (2) a table whose own scroll area revealed the last action while the
 * filter header could not scroll with it. Both are measured here with real
 * bounding boxes, not stylesheet expectations.
 *
 * Statuses that need a durable job state (Running/Queued/Failed) are supplied
 * through a read-only response fixture so the layout can be measured without
 * waiting for a solver. A separate test exercises a real active run through the
 * manufactured launcher and proves Diagnostics/Cancel are reachable without
 * cancelling anything by accident.
 */
import { randomUUID } from 'node:crypto'
import { mkdirSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test, type Page } from './fixtures'
import type { Job, Revision } from '../src/api'
import { meshAndDeck } from './pipeline'

const LONG_GROUP = '車両シール開発プロジェクト・ドア開口部の接触解析・2026年度後期検証'
const LONG_MODEL = 'フロントドアシール断面・中空リップ付き・材料二層・固定条件検証モデル'
const LONG_RUN = '閉じ方向の準静的接触解析・摩擦係数0.70・節点数37・製造試験用の長い実行名'

const WIDTHS = [
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
  { width: 720, height: 450 },
  { width: 390, height: 844 },
]

type Box = { x: number; y: number; width: number; height: number; right: number; bottom: number }

/** Fabricated list: four states, long names, several groups and many rows. */
function rows(group: string) {
  const states = ['Running', 'Queued', 'Completed', 'Failed']
  return states.flatMap((status, index) =>
    Array.from({ length: 3 }, (_, copy) => ({
      id: randomUUID(),
      project: 'model-' + index + copy,
      project_name: LONG_MODEL,
      group,
      group_name: index % 2 ? '第二グループ・長い名前の検証' : LONG_GROUP,
      name: LONG_RUN + ' #' + (index + 1) + '.' + (copy + 1),
      mode: 'ABAQUS',
      status,
      phase:
        status === 'Running'
          ? 'Step 1, increment 4'
          : status === 'Failed'
            ? 'Analysis aborted'
            : 'Queued',
      solver: status === 'Completed' ? 'Succeeded' : status === 'Failed' ? 'Failed' : 'Running',
      extraction: status === 'Completed' ? 'Succeeded' : 'Pending',
      created: 1763900000 - (index * 3 + copy) * 60,
      started: 1763900001,
      ended: status === 'Completed' ? 1763900100 : null,
      step: status === 'Running' ? 'Closing' : null,
      increment: status === 'Running' ? 4 : null,
      dimension: '2D',
      number: 1,
      manifest: [],
      cpus: 1,
      activity: status === 'Running' || status === 'Queued' ? 'active' : 'terminal',
    })),
  )
}

async function measure(page: Page) {
  return page.evaluate(() => {
    const box = (element: Element | null): Box | null => {
      if (!element) return null
      const rect = element.getBoundingClientRect()
      return {
        x: rect.x,
        y: rect.y,
        width: rect.width,
        height: rect.height,
        right: rect.right,
        bottom: rect.bottom,
      }
    }
    const card = document.querySelector('.run-card') as HTMLElement
    const header = card.querySelector('.card-heading')
    const filters = card.querySelector('.filters') as HTMLElement
    const scroller = card.querySelector('.table-scroll') as HTMLElement
    const rows = [...card.querySelectorAll('tbody tr')] as HTMLElement[]
    const activeRow = rows.find((row) => row.getAttribute('data-run-status') === 'Running')
    const lastRow = rows[rows.length - 1]
    const lastButton = card.querySelector(
      'tbody tr:last-child .run-actions button:last-child',
    )
    return {
      card: box(card),
      header: box(header),
      filters: box(filters),
      activeRow: box(activeRow ?? null),
      lastRow: box(lastRow ?? null),
      lastButton: box(lastButton),
      scroller: box(scroller),
      scrollerScrollWidth: scroller ? scroller.scrollWidth : 0,
      scrollerClientWidth: scroller ? scroller.clientWidth : 0,
      lastButtonReachable: (() => {
        if (!lastButton) return false
        lastButton.scrollIntoView({ block: 'nearest' })
        const rect = lastButton.getBoundingClientRect()
        return rect.top >= 0 && rect.bottom <= window.innerHeight + 1 && rect.width > 0
      })(),
      documentOverflow:
        document.documentElement.scrollWidth - document.documentElement.clientWidth,
      selectBoxes: [...card.querySelectorAll('.filters select')].map((select) => {
        const rect = select.getBoundingClientRect()
        return { left: rect.left, right: rect.right, width: rect.width }
      }),
      tableLabels: [...card.querySelectorAll('.filters select')].map(
        (select) =>
          select.getAttribute('aria-label') ||
          select.closest('label')?.textContent?.trim() ||
          '',
      ),
    }
  })
}

function within(box: Box | null, outer: Box | null) {
  if (!box || !outer) return false
  return box.x >= outer.x - 1 && box.right <= outer.right + 1
}

test('long names and filters never clip at 1440, 1280, 720 or 390 px in either locale', async ({
  page,
  request,
}) => {
  // Real long-named groups and models. Fictional names, isolated data.
  for (const suffix of ['A', 'B']) {
    await request.post('/api/project-groups', {
      data: {
        name: LONG_GROUP + ' ' + suffix,
        model_name: LONG_MODEL + ' ' + suffix,
        token: randomUUID(),
      },
    })
  }
  const groups = (await (await request.get('/api/groups')).json()) as {
    id: string
    name: string
  }[]
  const group = groups.find((entry) => entry.name.startsWith(LONG_GROUP))!

  await mkdirSync(resolve('../../.local/evidence'), { recursive: true })
  const fabricated = rows(group.id)
  await page.route('**/api/runs', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(fabricated),
    })
  })
  await page.route('**/api/groups*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: group.id,
          name: LONG_GROUP,
          created: 1763900000,
          archived: false,
          models: [
            {
              id: 'model-1',
              revision: 'revision-1',
              number: 3,
              name: LONG_MODEL,
              dimension: '2D',
              created: 1763900000,
              group: group.id,
              group_name: LONG_GROUP,
              archived: false,
              group_archived: false,
              revisions: 3,
            },
          ],
        },
      ]),
    })
  })

  const measurements: Record<string, unknown>[] = []
  for (const size of WIDTHS) {
    await page.setViewportSize(size)
    await page.goto('/#dashboard')
    await expect(page.locator('.run-card tbody tr')).toHaveCount(12)
    for (const locale of ['en', 'ja'] as const) {
      const htmlLang = await page.locator('html').getAttribute('lang')
      if (htmlLang !== locale) await page.locator('.lang-button').click()
      await expect(page.locator('.run-card tbody tr')).toHaveCount(12)
      const metrics = await measure(page)
      measurements.push({ ...size, locale, ...metrics })
      const label = `${size.width}x${size.height} ${locale}`
      // The filter header and every filter stay inside the card that clips its
      // overflow: this is the exact reported protrusion.
      expect(within(metrics.header, metrics.card), `header ${label}`).toBe(true)
      expect(within(metrics.filters, metrics.card), `filters ${label}`).toBe(true)
      for (const select of metrics.selectBoxes) {
        expect(select.left, `select left ${label}`).toBeGreaterThanOrEqual(metrics.card!.x - 1)
        expect(select.right, `select right ${label}`).toBeLessThanOrEqual(metrics.card!.right + 1)
        expect(select.width, `select width ${label}`).toBeGreaterThan(80)
      }
      // The active row, the progress/step line and the actions are inside the card.
      expect(within(metrics.activeRow, metrics.card), `active row ${label}`).toBe(true)
      expect(within(metrics.lastRow, metrics.card), `last row ${label}`).toBe(true)
      // No horizontal page overflow at any width.
      expect(metrics.documentOverflow, `page overflow ${label}`).toBeLessThanOrEqual(1)
      // Above the compact breakpoint the table fits its own scroller.
      if (size.width > 760) {
        expect(
          metrics.scrollerScrollWidth,
          `table scroll ${label}`,
        ).toBeLessThanOrEqual(metrics.scrollerClientWidth + 1)
      }
      // The bottom of a long list and its last action are reachable.
      expect(metrics.lastButtonReachable, `last action ${label}`).toBe(true)
      await page.screenshot({
        path: resolve(`../../.local/evidence/dashboard-${size.width}-${locale}.png`),
      })
    }
  }
  test.info().attach('dashboard-measurements.json', {
    body: JSON.stringify(measurements, null, 2),
    contentType: 'application/json',
  })
  writeFileSync(
    resolve('../../.local/evidence/dashboard-measurements.json'),
    JSON.stringify(measurements, null, 2),
  )
})

test('filtering to an active run reaches Diagnostics and Cancel without cancelling it', async ({
  page,
}) => {
  let cancels = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().includes('/cancel')) cancels += 1
  })
  const fabricated = rows('group-1')
  await page.route('**/api/runs', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(fabricated),
    })
  })
  await page.route('**/cancel', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  })
  await page.goto('/#dashboard')
  await expect(page.locator('.run-card tbody tr')).toHaveCount(12)

  // Filter by status: only the active rows remain.
  await page.getByLabel('Filter by status').selectOption('Running')
  await expect(page.locator('.run-card tbody tr')).toHaveCount(3)
  const first = page.locator('.run-card tbody tr').first()
  await expect(first).toHaveAttribute('data-run-status', 'Running')

  // Diagnostics navigation must not cancel the run.
  const diagnostics = first.getByRole('button', { name: 'Open diagnostics' })
  await diagnostics.focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/#diagnostics\//)
  expect(cancels).toBe(0)

  // Back on the dashboard the Cancel control is focusable, but focusing and
  // tabbing away never activates it.
  await page.goto('/#dashboard')
  await page.getByLabel('Filter by status').selectOption('Running')
  const cancel = page
    .locator('.run-card tbody tr')
    .first()
    .getByRole('button', { name: 'Cancel job' })
  await cancel.focus()
  await page.keyboard.press('Tab')
  expect(cancels).toBe(0)
  await cancel.click()
  await expect.poll(() => cancels).toBe(1)
})

test('a real manufactured run appears as active and is not cancelled by inspection', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Dashboard active run', example: true } })
  ).json()
  const { deck } = await meshAndDeck(request, revision)
  const submit = async (name: string): Promise<Job> => {
    const response = await request.post('/api/runs', {
      data: {
        revision: revision.id,
        deck: deck.id,
        token: randomUUID(),
        name,
        mode: 'ABAQUS',
        cpus: 1,
      },
    })
    expect(response.ok()).toBeTruthy()
    return response.json()
  }
  // The test double sleeps for a few seconds, so the first job reads Running
  // while the second is still Queued.
  const first = await submit('Dashboard running row')
  await submit('Dashboard queued row')
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/#dashboard')
  let cancels = 0
  page.on('request', (r) => {
    if (r.method() === 'POST' && r.url().includes('/cancel')) cancels += 1
  })
  const running = page.locator('.run-card tbody tr').filter({ hasText: 'Dashboard running row' })
  await expect(running).toBeVisible()
  await expect(
    page.locator('.run-card tbody tr').filter({ hasText: 'Dashboard queued row' }),
  ).toBeVisible()
  await expect(running.locator('[data-status]')).not.toHaveAttribute('data-status', 'Completed')
  await running.getByRole('button', { name: 'Open diagnostics' }).click()
  await expect(page).toHaveURL(new RegExp('/#diagnostics/' + first.id))
  expect(cancels).toBe(0)
})
