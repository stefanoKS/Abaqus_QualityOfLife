import { test, expect } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import type { Job, Revision } from '../src/api'

test('dashboard filters, cancellation, disconnected browser and extraction-only retry', async ({
  page,
  context,
  request,
}) => {
  const r: Revision = await (
    await request.post('/api/projects', { data: { name: 'Queue checks' } })
  ).json()
  const build: Job = await (
    await request.post('/api/builds', { data: { revision: r.id, token: randomUUID() } })
  ).json()
  async function job(id: string): Promise<Job> {
    return (await request.get('/api/jobs/' + id)).json()
  }
  async function run(name: string, scenario: string): Promise<Job> {
    const resp = await request.post('/api/runs', {
      data: { revision: r.id, token: randomUUID(), build: build.id, name, scenario, mode: 'DEMO' },
    })
    expect(resp.ok()).toBeTruthy()
    return resp.json()
  }
  await expect.poll(async () => (await job(build.id)).status).toBe('Completed')
  const slow = await run('Cancel this slow closing', 'slow')
  await expect.poll(async () => (await job(slow.id)).status).toBe('Running')
  await page.goto('/#dashboard')
  await page.getByLabel('Filter by project').selectOption(r.project)
  const slowRow = page.getByRole('row').filter({ hasText: slow.name })
  await slowRow.getByRole('button', { name: 'Cancel job' }).click()
  await expect(slowRow.getByText('Cancelled', { exact: true })).toBeVisible()
  const failed = await run('Requested failure', 'failure')
  await expect.poll(async () => (await job(failed.id)).status).toBe('Failed')
  await page.getByLabel('Filter by status').selectOption('Failed')
  await expect(page.getByRole('row').filter({ hasText: failed.name })).toBeVisible()
  await expect(slowRow).toHaveCount(0)
  const recover = await run('Re-extract results', 'extraction_failure')
  await page.close()
  await expect
    .poll(async () => (await job(recover.id)).extraction, { timeout: 15000 })
    .toBe('Failed')
  const before = await job(recover.id)
  const reopened = await context.newPage()
  await reopened.goto('/#diagnostics/' + recover.id)
  await reopened.getByRole('button', { name: 'Retry extraction' }).click()
  await reopened.getByRole('button', { name: 'Results', exact: true }).click()
  await expect(reopened.getByRole('heading', { name: 'Force–displacement' })).toBeVisible()
  const after = await job(recover.id)
  expect(after.started).toBe(before.started)
  expect(after.input_hash).toBe(before.input_hash)
  expect(after.solver).toBe('Succeeded')
})
