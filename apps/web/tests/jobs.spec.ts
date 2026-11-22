import { test, expect } from './fixtures'
import { randomUUID } from 'node:crypto'
import { meshAndDeck } from './pipeline'
import type { Job, Revision } from '../src/api'

test('dashboard filters, cancellation and results of an Abaqus run', async ({ page, request }) => {
  const r: Revision = await (
    await request.post('/api/projects', { data: { name: 'Queue checks', example: true } })
  ).json()
  const { deck } = await meshAndDeck(request, r)
  async function job(id: string): Promise<Job> {
    return (await request.get('/api/jobs/' + id)).json()
  }
  async function run(name: string): Promise<Job> {
    const resp = await request.post('/api/runs', {
      data: { revision: r.id, token: randomUUID(), deck: deck.id, name, mode: 'ABAQUS' },
    })
    expect(resp.ok()).toBeTruthy()
    return resp.json()
  }

  // Cancel a manufactured solve while the worker is actually running it.
  const cancelled = await run('Cancel this closing')
  await expect
    .poll(async () => (await job(cancelled.id)).status, { timeout: 30000 })
    .toBe('Running')
  await page.goto('/#dashboard')
  await page.getByLabel('Filter by project').selectOption(r.project)
  const row = page.getByRole('row').filter({ hasText: cancelled.name })
  await row.getByRole('button', { name: 'Cancel job' }).click()
  await expect(row.locator('.badge')).toHaveAttribute('data-status', 'Cancelled')

  // A completed run survives the filter and opens its result view.
  const completed = await run('Completed closing')
  await expect
    .poll(async () => (await job(completed.id)).status, { timeout: 90000 })
    .toBe('Completed')
  await page.getByLabel('Filter by status').selectOption('Completed')
  const finished = page.getByRole('row').filter({ hasText: completed.name })
  await expect(finished).toBeVisible()
  await expect(row).toHaveCount(0)
  await finished.getByRole('button', { name: 'Results' }).click()
  await expect(page.getByRole('heading', { name: 'Force–displacement' })).toBeVisible()
  await expect(page.locator('.run-banner')).toContainText('ABAQUS')
  const index = await (
    await request.get('/api/jobs/' + completed.id + '/artifacts/results.json')
  ).json()
  expect(index.mode).toBe('ABAQUS')
  expect(index.frames.length).toBeGreaterThan(1)
})
