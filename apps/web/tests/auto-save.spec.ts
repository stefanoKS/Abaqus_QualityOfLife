/**
 * Gate B: valid edits replace the current model automatically.
 *
 * The ordinary workspace has no manual Save step. A committed edit becomes the
 * model's new head without remounting the form, and work is never queued from
 * the previous settings. These tests cover immediate action after typing, rapid
 * edits, two tabs, reload, navigation away, a failed/lost write, idempotent
 * recovery and the immutability of a submitted run's setup, mesh, deck and
 * results.
 */
import { createHash, randomUUID } from 'node:crypto'
import { expect, test, type Page } from './fixtures'
import type { Job, Revision } from '../src/api'
import { meshAndDeck } from './pipeline'

async function head(request: import('@playwright/test').APIRequestContext, project: string) {
  const projects = (await (await request.get('/api/projects')).json()) as {
    id: string
    revision: string
  }[]
  return projects.find((entry) => entry.id === project)!.revision
}

async function headRevision(
  request: import('@playwright/test').APIRequestContext,
  project: string,
) {
  return (await request.get('/api/revisions/' + (await head(request, project)))).json() as Promise<Revision>
}

async function openMotion(page: Page, revisionId: string) {
  await page.goto('/#workspace/' + revisionId)
  await page.getByRole('navigation', { name: 'Workflow' }).locator('[data-stage="motion"]').click()
}

async function saved(page: Page) {
  await expect(
    page.locator('[data-testid="save-state"][data-state="saved"][data-dirty="false"]'),
  ).toHaveCount(1, { timeout: 20000 })
}

test('an edit is committed before Mesh acts, even when the button is pressed immediately', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Immediate mesh', example: true } })
  ).json()
  await page.goto('/#workspace/' + revision.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.locator('[data-stage="mesh"]').click()
  const size = page.getByLabel('Global size (mm)')
  // Type, then press Generate mesh at once: the click's blur commits the value
  // and the action flushes it before the job is queued.
  await size.fill('1.4')
  await page.getByRole('button', { name: 'Generate mesh', exact: true }).click()
  await expect(page.getByTestId('mesh-status')).toContainText('Mesh ready', { timeout: 60000 })
  const current = await headRevision(request, revision.project)
  expect(current.setup.mesh.size).toBe(1.4)
  const meshes = (await (await request.get('/api/meshes')).json()) as Job[]
  const queue = meshes.filter((job) => job.revision === current.id)
  expect(queue).toHaveLength(1)
  expect(queue[0].status).toBe('Completed')
})

test('rapid edits coalesce instead of creating one revision per keystroke', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Rapid edits', example: true } })
  ).json()
  await openMotion(page, revision.id)
  const width = page.getByLabel('Reporting width W (mm)')
  const before = Number(revision.number)
  for (const value of ['101', '102', '103']) {
    await width.fill(value)
    await width.press('Tab')
  }
  await saved(page)
  const current = await headRevision(request, revision.project)
  expect(current.setup.analysis.reporting_width).toBe(103)
  // Three committed edits inside the coalescing window never become three
  // historical revisions.
  expect(current.number - before).toBeLessThanOrEqual(2)
})

test('a background save keeps focus, stage, selection and the viewport camera', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'No remount', example: true } })
  ).json()
  await openMotion(page, revision.id)
  const width = page.getByLabel('Reporting width W (mm)')
  // Let the initial fit settle before using the camera as evidence that the save
  // did not disturb the viewport.
  const camera = () => page.locator('.seal-vtk-host').getAttribute('data-camera')
  await expect
    .poll(
      async () => {
        const first = await camera()
        await page.waitForTimeout(180)
        return first !== null && first === (await camera())
      },
      { timeout: 15000 },
    )
    .toBe(true)
  const before = await camera()
  const beforeBox = await page.locator('.seal-vtk-host').boundingBox()
  const beforeBounds = await page.getByTestId('vtk-viewport').getAttribute('data-display-bounds')
  await width.fill('104')
  await width.press('Enter')
  await saved(page)
  // Still the same stage, the same focused field, the same selected entity and
  // the same camera: the save advanced the head without rebuilding the form.
  await expect(page.locator('.property-body .eyebrow')).toContainText('Motion')
  const active = await page.evaluate(() => {
    const element = document.activeElement as HTMLInputElement | null
    return {
      tag: element?.tagName ?? '',
      value: element?.value ?? '',
      label: element?.getAttribute('aria-label') ?? element?.id ?? '',
    }
  })
  expect(active).toMatchObject({ tag: 'INPUT', value: '104' })
  const afterBox = await page.locator('.seal-vtk-host').boundingBox()
  expect({
    camera: await camera(),
    box: afterBox,
    bounds: await page.getByTestId('vtk-viewport').getAttribute('data-display-bounds'),
  }).toMatchObject({
    camera: before,
    box: beforeBox,
    bounds: beforeBounds,
  })
  await expect(page.getByTestId('analysis-settings')).toBeVisible()
  // Reloading the head URL restores the same stage and the saved value.
  await page.reload()
  await expect(page.locator('.property-body .eyebrow')).toContainText('Motion')
  await expect(page.getByLabel('Reporting width W (mm)')).toHaveValue('104')
})

test('navigating away flushes the latest valid edit', async ({ page, request }) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Navigate away', example: true } })
  ).json()
  await openMotion(page, revision.id)
  const width = page.getByLabel('Reporting width W (mm)')
  await width.fill('107')
  await width.press('Tab')
  // Leave immediately, before the coalescing window elapses.
  await page.getByRole('button', { name: 'Dashboard' }).click()
  await expect(page.locator('.dashboard.page')).toBeVisible()
  await expect
    .poll(async () => (await headRevision(request, revision.project)).setup.analysis.reporting_width, {
      timeout: 20000,
    })
    .toBe(107)
})

test('a failed write keeps the draft, explains the cause and retries successfully', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Failed write', example: true } })
  ).json()
  await openMotion(page, revision.id)
  let fail = true
  await page.route('**/api/projects/*', async (route) => {
    if (route.request().method() === 'PUT' && fail) {
      fail = false
      await route.abort('failed')
      return
    }
    await route.continue()
  })
  const width = page.getByLabel('Reporting width W (mm)')
  await width.fill('108')
  await width.press('Tab')
  await expect(page.getByTestId('save-state')).toHaveAttribute('data-state', 'error', {
    timeout: 20000,
  })
  await expect(page.getByTestId('save-error')).toBeVisible()
  // The typed value is never erased by a failed write.
  await expect(width).toHaveValue('108')
  // Prepare explains the temporary state instead of queueing stale settings.
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .locator('[data-stage="results"]')
    .click()
  await expect(page.getByTestId('prepare-reason')).toContainText('not saved')
  await page.getByTestId('save-retry').click()
  await saved(page)
  expect((await headRevision(request, revision.project)).setup.analysis.reporting_width).toBe(108)
})

test('a lost response is recovered idempotently without a duplicate revision', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Lost response', example: true } })
  ).json()
  await openMotion(page, revision.id)
  const before = Number(revision.number)
  let lost = true
  await page.route('**/api/projects/*', async (route) => {
    if (route.request().method() === 'PUT' && lost) {
      lost = false
      // Deliver the request, then drop the response: the server committed it.
      await route.fetch()
      await route.abort('failed')
      return
    }
    await route.continue()
  })
  const width = page.getByLabel('Reporting width W (mm)')
  await width.fill('109')
  await width.press('Tab')
  await expect(page.getByTestId('save-state')).toHaveAttribute('data-state', 'error', {
    timeout: 20000,
  })
  await page.getByTestId('save-retry').click()
  await saved(page)
  const current = await headRevision(request, revision.project)
  expect(current.setup.analysis.reporting_width).toBe(109)
  // The retry recognised the already-committed setup instead of appending a
  // second identical revision.
  expect(current.number - before).toBe(1)
})

test('two tabs surface a same-field conflict and Reload adopts the other edit', async ({
  context,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Two tabs', example: true } })
  ).json()
  const first = await context.newPage()
  const second = await context.newPage()
  await openMotion(first, revision.id)
  await openMotion(second, revision.id)

  const firstWidth = first.getByLabel('Reporting width W (mm)')
  await firstWidth.fill('110')
  await firstWidth.press('Tab')
  await saved(first)

  const secondWidth = second.getByLabel('Reporting width W (mm)')
  await secondWidth.fill('111')
  await secondWidth.press('Tab')
  // The second tab's base is now behind the head: it must say so, not overwrite
  // silently and not lose the typed value.
  await expect(second.getByTestId('save-state')).toHaveAttribute('data-state', 'error', {
    timeout: 20000,
  })
  await expect(second.getByTestId('save-error')).toContainText('Another revision was saved')
  await expect(secondWidth).toHaveValue('111')
  // The explicit retry cannot merge two different values for the same field.
  // It names the field, keeps this tab's value and never overwrites the other
  // engineer's committed 110 mm.
  await second.getByTestId('save-retry').click()
  await expect(second.getByTestId('save-reload')).toBeVisible({ timeout: 20000 })
  await expect(second.getByTestId('save-error')).toContainText('analysis.reporting_width')
  await expect(secondWidth).toHaveValue('111')
  const before = await headRevision(request, revision.project)
  expect(before.setup.analysis.reporting_width).toBe(110)
  // Reload is the explicit choice to take the other tab's revision.
  await second.getByTestId('save-reload').click()
  await expect(secondWidth).toHaveValue('110', { timeout: 20000 })
  await expect(second.getByTestId('save-state')).toHaveAttribute('data-dirty', 'false')
  await second.close()
})

test('a retry rebases only the local field and keeps the other tab\'s change', async ({
  context,
  request,
}) => {
  // The reported regression: editor A saves width 111 mm, editor B changed only
  // the mesh size, and Retry resubmitted B's whole stale snapshot, reverting the
  // width to 100 mm.
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Rebase fields', example: true } })
  ).json()
  const first = await context.newPage()
  const second = await context.newPage()
  await openMotion(first, revision.id)
  const firstWidth = first.getByLabel('Reporting width W (mm)')
  await firstWidth.fill('111')
  await firstWidth.press('Tab')
  await saved(first)
  const withWidth = await headRevision(request, revision.project)
  expect(withWidth.setup.analysis.reporting_width).toBe(111)

  // The second editor changes an unrelated field from the same old base.
  await second.goto('/#workspace/' + revision.id)
  await second.getByRole('navigation', { name: 'Workflow' }).locator('[data-stage="mesh"]').click()
  const size = second.getByLabel('Global size (mm)')
  await size.fill('1.25')
  await size.press('Tab')
  await expect(second.getByTestId('save-state')).toHaveAttribute('data-state', 'error', {
    timeout: 20000,
  })
  await expect(size).toHaveValue('1.25')
  await second.getByTestId('save-retry').click()
  await saved(second)

  const merged = await headRevision(request, revision.project)
  // Both independent edits survive: the width is not reverted and the mesh size
  // is committed.
  expect(merged.setup.analysis.reporting_width).toBe(111)
  expect(merged.setup.mesh.size).toBe(1.25)
  // The second window shows the merged document, not its stale copy.
  await expect(size).toHaveValue('1.25')
  await second.close()
})

test('a same-field conflict is reported by path and Reload adopts the other edit', async ({
  context,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Same field conflict', example: true } })
  ).json()
  const first = await context.newPage()
  const second = await context.newPage()
  await openMotion(first, revision.id)
  await openMotion(second, revision.id)

  const firstWidth = first.getByLabel('Reporting width W (mm)')
  await firstWidth.fill('111')
  await firstWidth.press('Tab')
  await saved(first)

  const secondWidth = second.getByLabel('Reporting width W (mm)')
  await secondWidth.fill('112')
  await secondWidth.press('Tab')
  await expect(second.getByTestId('save-state')).toHaveAttribute('data-state', 'error', {
    timeout: 20000,
  })
  await second.getByTestId('save-retry').click()
  // Both windows changed the same field: nothing is written, the cause names the
  // field, and the local value is retained until the engineer chooses.
  await expect(second.getByTestId('save-reload')).toBeVisible({ timeout: 20000 })
  await expect(second.getByTestId('save-error')).toContainText('reporting_width')
  await expect(secondWidth).toHaveValue('112')
  expect((await headRevision(request, revision.project)).setup.analysis.reporting_width).toBe(111)

  await second.getByTestId('save-reload').click()
  await expect(secondWidth).toHaveValue('111', { timeout: 20000 })
  await expect(second.getByTestId('save-state')).toHaveAttribute('data-dirty', 'false')
  await second.close()
})

test('switching models during a pending write keeps each model independent', async ({
  page,
  request,
}) => {
  const first: Revision = await (
    await request.post('/api/projects', { data: { name: 'Switch first', example: true } })
  ).json()
  const second: Revision = await (
    await request.post('/api/projects', { data: { name: 'Switch second', example: true } })
  ).json()
  await openMotion(page, first.id)
  const width = page.getByLabel('Reporting width W (mm)')
  await width.fill('117')
  await width.press('Tab')
  // Leave for another model immediately, while the write may still be pending.
  await page.goto('/#workspace/' + second.id)
  await page.getByRole('navigation', { name: 'Workflow' }).locator('[data-stage="motion"]').click()
  // The first model still commits its edit; the second model is untouched.
  await expect
    .poll(async () => (await headRevision(request, first.project)).setup.analysis.reporting_width, {
      timeout: 20000,
    })
    .toBe(117)
  const other = await headRevision(request, second.project)
  expect(other.id).toBe(second.id)
  expect(other.setup.analysis.reporting_width).toBe(100)
  // The second model's form never showed the first model's draft.
  await expect(page.getByLabel('Reporting width W (mm)')).toHaveValue('100')
})

test('editing a submitted model never rewrites its setup, mesh, deck or results', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Immutable artifacts', example: true } })
  ).json()
  const { mesh, deck } = await meshAndDeck(request, revision)
  const run: Job = await (
    await request.post('/api/runs', {
      data: {
        revision: revision.id,
        deck: deck.id,
        token: randomUUID(),
        name: 'Immutable run',
        mode: 'ABAQUS',
        cpus: 1,
      },
    })
  ).json()
  await expect
    .poll(async () => ((await (await request.get('/api/jobs/' + run.id)).json()) as Job).status, {
      timeout: 90000,
    })
    .toBe('Completed')

  const hash = async (path: string) => {
    const response = await request.get(path)
    expect(response.ok()).toBeTruthy()
    return createHash('sha256').update(await response.body()).digest('hex')
  }
  const originalRevision = (await (
    await request.get('/api/revisions/' + revision.id)
  ).json()) as Revision
  const inp = await hash(`/api/jobs/${deck.id}/artifacts/analysis.inp`)
  const results = await hash(`/api/jobs/${run.id}/artifacts/results.json`)
  const meshFile = await hash(`/api/jobs/${mesh.id}/artifacts/mesh.json`)

  // Edit the model's head through the ordinary UI.
  await openMotion(page, revision.id)
  const width = page.getByLabel('Reporting width W (mm)')
  await width.fill('115')
  await width.press('Tab')
  await saved(page)
  const current = await headRevision(request, revision.project)
  expect(current.id).not.toBe(revision.id)
  expect(current.setup.analysis.reporting_width).toBe(115)

  // Every artifact and the exact submitted setup are byte-identical.
  expect(await hash(`/api/jobs/${deck.id}/artifacts/analysis.inp`)).toBe(inp)
  expect(await hash(`/api/jobs/${run.id}/artifacts/results.json`)).toBe(results)
  expect(await hash(`/api/jobs/${mesh.id}/artifacts/mesh.json`)).toBe(meshFile)
  const replay = (await (await request.get('/api/revisions/' + revision.id)).json()) as Revision
  expect(replay.setup).toEqual(originalRevision.setup)
  // The historical setup link still opens exactly what ran, read-only.
  await page.goto('/#setup/' + run.id)
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .locator('[data-stage="results"]')
    .click()
  await expect(page.getByTestId('action-locked')).toBeVisible()
  await expect(page.getByTestId('save-state')).toHaveCount(0)
  // Results stay available independently of the edited head.
  await page.goto('/#results/' + run.id)
  await expect(page.getByTestId('vtk-viewport')).toBeVisible()
})
