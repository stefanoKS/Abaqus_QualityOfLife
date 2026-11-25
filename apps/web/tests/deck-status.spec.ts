/**
 * Gate B: the deck card names the actual state and never calls every non-ready
 * deck a changed fixture. The worker diagnostic is preserved, recovery is
 * offered, and "fixed nodes changed" appears only on a proven hash mismatch.
 *
 * The deck list is fabricated in the browser route so each status can be
 * exercised without waiting for a real worker failure. Mesh, fixture and
 * readiness are the real test-data artifacts for this revision.
 */
import { randomUUID } from 'node:crypto'
import { expect, test } from './fixtures'
import type { Job, Revision } from '../src/api'

async function preparedModel(request: import('@playwright/test').APIRequestContext) {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Deck status', example: true } })
  ).json()
  const mesh: Job = await (
    await request.post('/api/meshes', { data: { revision: revision.id, token: randomUUID() } })
  ).json()
  await expect
    .poll(async () => ((await (await request.get('/api/jobs/' + mesh.id)).json()) as Job).status, {
      timeout: 90000,
    })
    .toBe('Completed')
  const job = (await (await request.get('/api/jobs/' + mesh.id)).json()) as Job & {
    fixture?: { count: number; hash: string; labels: string[] }
  }
  const fixture = await (
    await request.post('/api/meshes/' + mesh.id + '/fixture/edges', { data: {} })
  ).json()
  await request.put('/api/meshes/' + mesh.id + '/fixture', { data: { labels: fixture.labels } })
  const refreshed = (await (await request.get('/api/jobs/' + mesh.id)).json()) as Job & {
    fixture?: { count: number; hash: string; labels: string[] }
  }
  return { revision, mesh: refreshed }
}

function deckJob(
  revision: Revision,
  mesh: Job & { fixture?: { count: number; hash: string; labels: string[] } },
  overrides: Record<string, unknown>,
): Record<string, unknown> {
  return {
    id: 'deck-status-job',
    revision: revision.id,
    project: revision.project,
    number: 1,
    project_name: revision.name,
    name: 'Prepare input deck',
    dimension: '2D',
    mode: 'DECK',
    status: 'Failed',
    solver: 'Failed',
    extraction: 'Failed',
    scenario: '',
    phase: 'Preparation or execution failed',
    created: Date.now() / 1000,
    started: Date.now() / 1000,
    ended: Date.now() / 1000,
    heartbeat: null,
    pid: null,
    process_started: null,
    step: null,
    increment: null,
    step_time: null,
    exit_code: null,
    extraction_exit: null,
    cpus: 1,
    build: null,
    mesh: mesh.id,
    mesh_digest: mesh.mesh_digest,
    mesh_compat: mesh.mesh_compat,
    fixture_hash: mesh.fixture?.hash ?? null,
    fixture: mesh.fixture ?? null,
    fixture_labels: mesh.fixture?.labels ?? null,
    diagnostic: 'The door profile branches at node 42. Repair the profile and remesh.',
    manifest: [],
    input_hash: null,
    ...overrides,
  }
}

async function openWorkspace(page: import('@playwright/test').Page, revision: Revision) {
  await page.goto('/#workspace/' + revision.id)
  await page.locator('[data-stage="results"]').click()
  await expect(page.getByTestId('deck-status')).toBeVisible({ timeout: 30000 })
}

test('a failed deck shows its worker diagnostic, not a changed fixture', async ({
  page,
  request,
}) => {
  const { revision, mesh } = await preparedModel(request)
  await page.route('**/api/decks', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([deckJob(revision, mesh, {})]),
    }),
  )
  await openWorkspace(page, revision)
  const status = page.getByTestId('deck-status')
  await expect(status).toContainText('Input deck preparation failed.')
  await expect(page.getByTestId('deck-diagnostic')).toContainText(
    'The door profile branches at node 42.',
  )
  await expect(page.getByTestId('deck-failed-stage')).toContainText(
    'Preparation or execution failed',
  )
  await expect(page.getByTestId('deck-hint')).toContainText('reviewed fixture is unchanged')
  await expect(page.getByText('The fixed nodes changed.')).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Open diagnostics' })).toBeVisible()

  // The same state is explained in Japanese; the diagnostic stays verbatim.
  await page.locator('.lang-button').click()
  await expect(status).toContainText('入力デッキを作成できませんでした。')
  await expect(page.getByTestId('deck-diagnostic')).toContainText('node 42')
  await page.locator('.lang-button').click()
})

test('a proven fixture mismatch is the only changed-fixture message', async ({
  page,
  request,
}) => {
  const { revision, mesh } = await preparedModel(request)
  await page.route('**/api/decks', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        deckJob(revision, mesh, {
          status: 'Completed',
          solver: 'Succeeded',
          extraction: 'Succeeded',
          phase: 'Input ready',
          fixture_hash: 'different-fixture-hash',
          diagnostic: '',
        }),
      ]),
    }),
  )
  await openWorkspace(page, revision)
  await expect(page.getByTestId('deck-status')).toContainText(
    'The fixed nodes changed. Prepare the input deck again.',
  )
  await expect(page.getByTestId('deck-hint')).toContainText('Save the reviewed nodes')
  await expect(page.getByTestId('deck-diagnostic')).toHaveCount(0)

  // A completed deck for a superseded mesh names the mesh, not the fixture.
  await page.unroute('**/api/decks')
  await page.route('**/api/decks', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        deckJob(revision, mesh, {
          status: 'Completed',
          solver: 'Succeeded',
          extraction: 'Succeeded',
          phase: 'Input ready',
          mesh: 'an-older-mesh',
          diagnostic: '',
        }),
      ]),
    }),
  )
  await page.reload()
  await expect(page.getByTestId('deck-status')).toContainText(
    'The mesh changed. Prepare the input deck again.',
  )
  await expect(page.getByText('The fixed nodes changed.')).toHaveCount(0)
})

test('a typed preparation blocker is shown before Prepare is attempted', async ({
  page,
  request,
}) => {
  const { revision } = await preparedModel(request)
  const readiness = await (
    await request.get('/api/revisions/' + revision.id + '/readiness')
  ).json()
  const blocked = structuredClone(readiness)
  blocked.can_prepare = false
  blocked.can_submit = false
  blocked.state = 'blocked'
  blocked.findings = [
    {
      code: 'panel.branched_profile',
      stage: 'components',
      action: 'assign_roles',
      severity: 'blocker',
      artifact: 'mesh:test',
      params: { label: 'door', node: 42, count: 1 },
      actions: ['prepare', 'submit'],
    },
  ]
  blocked.first_blocker = blocked.findings[0]
  blocked.setup_issues = blocked.findings
  blocked.submit_issues = blocked.findings
  await page.route('**/api/revisions/*/readiness', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(blocked),
    }),
  )
  await openWorkspace(page, revision)
  await expect(page.getByTestId('prepare-reason')).toContainText('profile branches at a node')
  await expect(page.getByTestId('prepare')).toBeDisabled()
  await page.locator('.lang-button').click()
  await expect(page.getByTestId('prepare-reason')).toContainText('プロファイルが節点で分岐')
})
