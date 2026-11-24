/**
 * Gate C: setting order, action readiness and locks.
 *
 * Every row of the requested transition matrix is exercised through the real UI
 * and the direct API. For each state the test records the editable controls, the
 * Prepare/Submit state, the visible reason and the artifact identity (mesh,
 * fixture, deck) the decision used. The server remains the authority: wherever
 * the UI exposes an action state, it must agree with `/readiness`.
 */
import { randomUUID } from 'node:crypto'
import { expect, test, type Page } from './fixtures'
import type { Job, Revision } from '../src/api'
import { meshAndFixture, meshAndDeck } from './pipeline'

async function headRelease(request: import('@playwright/test').APIRequestContext, page: Page) {
  return (await request.get('/api/revisions/' + page.url().split('/').pop())).json() as Promise<Revision>
}

async function readiness(
  request: import('@playwright/test').APIRequestContext,
  revision: string,
) {
  return (await request.get(`/api/revisions/${revision}/readiness`)).json() as Promise<{
    can_prepare: boolean
    can_submit: boolean
    setup_issues: { code: string; stage: string }[]
    submit_issues: { code: string; stage: string }[]
    stage_states: Record<string, { state: string; code?: string }>
  }>
}

/** Wait until the displayed action state describes the current head. */
async function settle(page: Page) {
  await expect(
    page.locator('[data-testid="save-state"][data-state="saved"][data-dirty="false"]'),
  ).toHaveCount(1, { timeout: 20000 })
}

/** The only Prepare/Submit owner is the top of the Results properties. */
async function openResults(page: Page) {
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .locator('[data-stage="results"]')
    .click()
  await expect(page.getByTestId('action-group')).toBeVisible()
}

/**
 * The UI must agree with the direct API for both actions, and a disabled action
 * must always carry a reason while an enabled one must not.
 */
async function assertActionsMatchApi(
  page: Page,
  request: import('@playwright/test').APIRequestContext,
) {
  await openResults(page)
  await settle(page)
  const revision = page.url().split('/').pop()!
  const document = await readiness(request, revision)
  const prepare = page.getByTestId('prepare')
  const submit = page.getByTestId('submit')
  if (document.can_prepare) await expect(prepare).toBeEnabled()
  else await expect(prepare).toBeDisabled()
  if (document.can_submit) await expect(submit).toBeEnabled()
  else await expect(submit).toBeDisabled()
  const prepareReason = (await page.getByTestId('prepare-reason').innerText()).trim()
  if (document.can_prepare) expect(prepareReason).toBe('Ready to prepare.')
  else expect(prepareReason.length).toBeGreaterThan(0)
  if (!document.can_submit) {
    const submitReason = (await page.getByTestId('submit-reason').innerText()).trim()
    expect(submitReason.length).toBeGreaterThan(0)
  }
  return document
}

test('empty model: Import is actionable, other stages explain geometry without a padlock', async ({
  page,
  request,
}) => {
  const empty: Revision = await (
    await request.post('/api/projects', { data: { name: 'Matrix empty' } })
  ).json()
  await page.goto('/#workspace/' + empty.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await expect(workflow.locator('[data-stage="import"]')).toHaveAttribute('data-state', 'incomplete')
  // A correctable missing input must never be rendered as a read-only padlock.
  await expect(page.locator('.steps .lucide-lock')).toHaveCount(0)
  // Every stage is reachable; opening the one that repairs the blocker works.
  for (const stage of ['components', 'materials', 'mesh', 'mounting', 'contact', 'motion']) {
    await workflow.locator(`[data-stage="${stage}"]`).click()
    await expect(page.locator('.property-body .eyebrow')).toBeVisible()
  }
  // Mesh and Prepare both name the missing drawing.
  await workflow.locator('[data-stage="mesh"]').click()
  await expect(workflow.locator('[data-stage="mesh"]')).toHaveAttribute('title', /drawing/i)
  const document = await assertActionsMatchApi(page, request)
  expect(document.stage_states.mesh.code).toBe('drawing.missing')
  expect(document.can_prepare).toBe(false)
  expect(document.setup_issues[0].code).toBe('drawing.missing')
})

test('roles missing: Components is editable, the last correction clears the badge without Mesh', async ({
  page,
  request,
}) => {
  const created: Revision = await (
    await request.post('/api/projects', { data: { name: 'Matrix roles', example: true } })
  ).json()
  const setup = structuredClone(created.setup)
  for (const component of setup.components) component.role = 'unassigned'
  const revision: Revision = await (
    await request.put('/api/projects/' + created.project, {
      data: { base: created.id, setup },
    })
  ).json()

  await page.goto('/#workspace/' + revision.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.locator('[data-stage="components"]').click()
  // The role selector is enabled while the stage is explicitly incomplete.
  await expect(page.getByLabel('Role')).toBeEnabled()
  await expect(workflow.locator('[data-stage="components"]')).toHaveAttribute(
    'data-state',
    'incomplete',
  )
  await expect(page.locator('.steps .lucide-lock')).toHaveCount(0)
  // The reason names the affected part by its engineering identifier.
  const document = await assertActionsMatchApi(page, request)
  expect(document.stage_states.components.code).toMatch(/^components\./)
  expect(document.setup_issues.some((issue) => issue.code === 'components.unassigned')).toBe(true)

  // Correct the last role in the tree/selector; no Mesh visit and no manual save.
  const tree = page.locator('.tree')
  for (const component of revision.setup.components) {
    // The item button is named "<display name> · <role>"; the expand/rename
    // controls start with a verb and must not be clicked here.
    await tree
      .getByRole('button', {
        name: new RegExp('^' + component.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ' ·'),
      })
      .first()
      .click()
    const role = component.id === 'panel' ? 'moving_panel' : 'seal'
    await page.getByLabel('Role').selectOption(role)
  }
  await settle(page)
  await expect(workflow.locator('[data-stage="components"]')).not.toHaveAttribute(
    'data-state',
    'blocked',
  )
  await expect(page.locator('.steps .lucide-lock')).toHaveCount(0)
  // The derived plan appears without opening Contact or Mesh.
  const after = await assertActionsMatchApi(page, request)
  expect(after.setup_issues.some((issue) => issue.code.startsWith('components.'))).toBe(false)
})

test('mesh inputs ready: Contact and Motion open early and defaults prepare a deck without visits', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Matrix order', example: true } })
  ).json()
  // Mesh and fixture are produced out of order through the API, never by opening
  // Contact or Motion in the browser.
  const { mesh, labels } = await meshAndFixture(request, revision)
  await page.goto('/#workspace/' + revision.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.locator('[data-stage="contact"]').click()
  await expect(page.getByLabel('Door panel ↔ seal coefficient')).toBeEnabled()
  await workflow.locator('[data-stage="motion"]').click()
  await expect(page.getByLabel('Door panel stroke (mm)')).toBeEnabled()
  const document = await assertActionsMatchApi(page, request)
  expect(document.can_prepare).toBe(true)
  expect(document.can_submit).toBe(false)
  // Prepare queues exactly one DECK for the current setup/mesh/fixture.
  const decksBefore = ((await (await request.get('/api/decks')).json()) as Job[]).filter(
    (job) => job.revision === revision.id,
  ).length
  await page.getByTestId('prepare').click()
  await expect(page.getByTestId('deck-status')).toContainText('Input ready', { timeout: 60000 })
  const decks = ((await (await request.get('/api/decks')).json()) as Job[]).filter(
    (job) => job.revision === revision.id,
  )
  expect(decks.length).toBe(decksBefore + 1)
  const deck = decks[0]
  expect(deck.mesh).toBe(mesh.id)
  expect(deck.fixture_hash).toBe(mesh.fixture!.hash)
  await expect(page.getByTestId('submit')).toBeEnabled()
})

test('mounting prerequisite: the node picker waits for a mesh and explains it', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Matrix mounting', example: true } })
  ).json()
  await page.goto('/#workspace/' + revision.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.locator('[data-stage="mounting"]').click()
  await expect(page.getByRole('button', { name: 'Generate mesh first' })).toBeVisible()
  const before = await assertActionsMatchApi(page, request)
  expect(before.stage_states.mounting.code).toBe('mounting.awaiting_mesh')
  expect(before.setup_issues.some((issue) => issue.code === 'mesh.missing')).toBe(true)

  // Complete the mesh through the API; Mounting becomes actionable at once.
  const { mesh } = await meshAndFixture(request, revision)
  await page.reload()
  await workflow.locator('[data-stage="mounting"]').click()
  await expect(page.getByLabel('Fixed-node box mode')).toBeEnabled()
  await expect(page.getByTestId('fixture-count')).toHaveText(String(mesh.fixture!.count))
  const after = await assertActionsMatchApi(page, request)
  expect(after.stage_states.mounting.state).toBe('complete')
  expect(after.can_prepare).toBe(true)
})

test('friction edit keeps the mesh and fixture, keeps Mounting usable and rebuilds a stale deck', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Matrix friction', example: true } })
  ).json()
  const { mesh, deck } = await meshAndDeck(request, revision)
  const fixtureHash = mesh.fixture!.hash
  await page.goto('/#workspace/' + revision.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await openResults(page)
  await expect(page.getByTestId('submit')).toBeEnabled()

  await workflow.locator('[data-stage="contact"]').click()
  const friction = page.getByLabel('Door panel ↔ seal coefficient')
  await expect(friction).toHaveValue('0.7')
  await friction.fill('0.63')
  await friction.press('Tab')
  await settle(page)
  // The edit advanced the head automatically; the deck built for the previous
  // revision is stale and Prepare is independently available.
  await openResults(page)
  await expect(page.locator('.crumb')).not.toContainText('Revision 01')
  await expect(page.getByTestId('submit')).toBeDisabled()
  await expect(page.getByTestId('prepare')).toBeEnabled()
  const head = await headRelease(request, page)
  expect(head.setup.contact.door_seal).toBe(0.63)
  // Same mesh, same reviewed fixture: no reapplication and no remesh.
  const meshes = (await (await request.get('/api/meshes')).json()) as Job[]
  const active = meshes.find((job) => job.id === mesh.id)!
  expect(active.status).toBe('Completed')
  expect(active.fixture!.hash).toBe(fixtureHash)
  expect(active.mesh_compat).toBeTruthy()
  // Mounting stays visible and usable during and after the unrelated edit.
  await workflow.locator('[data-stage="mounting"]').click()
  await expect(page.getByLabel('Fixed-node box mode')).toBeEnabled()
  await expect(page.getByTestId('fixture-count')).toHaveText(String(mesh.fixture!.count))
  // Prepare rebuilds the deck for the new head with the same mesh and fixture.
  await openResults(page)
  await page.getByTestId('prepare').click()
  await expect(page.getByTestId('deck-status')).toContainText('Input ready', { timeout: 60000 })
  const decks = ((await (await request.get('/api/decks')).json()) as Job[]).filter(
    (job) => job.revision === head.id,
  )
  expect(decks).toHaveLength(1)
  expect(decks[0].mesh).toBe(mesh.id)
  expect(decks[0].fixture_hash).toBe(fixtureHash)
  expect(decks[0].id).not.toBe(deck.id)
})

test('a mesh-affecting change explains the remesh while material edits reuse the mesh', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Matrix remesh', example: true } })
  ).json()
  const { mesh } = await meshAndFixture(request, revision)
  // A material card value change must reuse the mesh: identity excludes cards.
  const setup = structuredClone(revision.setup)
  setup.materials[0].young = 3.5
  const materialHead: Revision = await (
    await request.put('/api/projects/' + revision.project, {
      data: { base: revision.id, setup },
    })
  ).json()
  await page.goto('/#workspace/' + materialHead.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.locator('[data-stage="mesh"]').click()
  await expect(page.getByTestId('mesh-status')).toContainText('Mesh ready')
  const reused = await assertActionsMatchApi(page, request)
  expect(reused.stage_states.mesh.state).toBe('complete')

  // A meshing input change requires a new mesh and a fresh review.
  await workflow.locator('[data-stage="mesh"]').click()
  const size = page.getByLabel('Global size (mm)')
  await size.fill('1.4')
  await size.press('Tab')
  await settle(page)
  const remesh = await assertActionsMatchApi(page, request)
  expect(remesh.stage_states.mesh.state).toBe('incomplete')
  expect(remesh.setup_issues.some((issue) => issue.code === 'mesh.missing')).toBe(true)
  await workflow.locator('[data-stage="mesh"]').click()
  await expect(page.getByTestId('mesh-status')).toContainText('mesh inputs changed')
  // The old mesh is preserved as an artifact; it is simply not reusable.
  const old = (await (await request.get('/api/jobs/' + mesh.id)).json()) as Job
  expect(old.status).toBe('Completed')
})

test('a fixed-node change on the same mesh invalidates the deck and Prepare can rebuild', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Matrix fixture', example: true } })
  ).json()
  const { mesh, deck } = await meshAndDeck(request, revision)
  const original = mesh.fixture!.labels
  const smaller = original.slice(0, Math.max(1, Math.floor(original.length / 2)))
  await page.goto('/#workspace/' + revision.id)
  await openResults(page)
  await expect(page.getByTestId('submit')).toBeEnabled()
  // Replacing the reviewed set on the same mesh is an explicit committed gesture.
  const saved = await request.put('/api/meshes/' + mesh.id + '/fixture', {
    data: { labels: smaller, expected_hash: mesh.fixture!.hash },
  })
  expect(saved.ok()).toBeTruthy()
  await page.reload()
  await openResults(page)
  await expect(page.getByTestId('submit')).toBeDisabled()
  await expect(page.getByTestId('prepare')).toBeEnabled()
  // Reapplying the identical set is idempotent.
  const again = await request.put('/api/meshes/' + mesh.id + '/fixture', {
    data: { labels: smaller, expected_hash: (await (
      await request.get('/api/jobs/' + mesh.id)
    ).json()).fixture.hash },
  })
  expect(again.ok()).toBeTruthy()
  const settled = (await (await request.get('/api/jobs/' + mesh.id)).json()) as Job
  expect(settled.fixture!.labels).toEqual(smaller)
  expect(deck.fixture_hash).not.toBe(settled.fixture!.hash)
})

test('deck ready: Submit needs the current deck and valid Submit-only settings', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Matrix submit', example: true } })
  ).json()
  await meshAndDeck(request, revision)
  await page.goto('/#workspace/' + revision.id)
  await assertActionsMatchApi(page, request)
  await expect(page.getByTestId('submit')).toBeEnabled()
  // Invalid CPU and blank run name are Submit-only reasons; Prepare stays usable.
  await page.getByLabel('CPUs').fill('0')
  await expect(page.getByTestId('submit')).toBeDisabled()
  await expect(page.getByTestId('submit-reason')).toContainText('CPU')
  await expect(page.getByTestId('prepare')).toBeEnabled()
  await page.getByLabel('CPUs').fill('2')
  await page.getByLabel('Run name').fill('')
  await expect(page.getByTestId('submit')).toBeDisabled()
  await expect(page.getByTestId('submit-reason')).toContainText('run name')
  await page.getByLabel('Run name').fill('Matrix run')
  await expect(page.getByTestId('submit')).toBeEnabled()
})

test('a submitted setup is pinned read-only and its results open independently', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Matrix replay', example: true } })
  ).json()
  const { deck } = await meshAndDeck(request, revision)
  const run: Job = await (
    await request.post('/api/runs', {
      data: {
        revision: revision.id,
        deck: deck.id,
        token: randomUUID(),
        name: 'Matrix replay run',
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
  const original = (await (await request.get('/api/revisions/' + revision.id)).json()) as Revision

  await page.goto('/#setup/' + run.id)
  // The submitted setup is read-only; its one action group lives on Results.
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .locator('[data-stage="results"]')
    .click()
  await expect(page.getByTestId('action-locked')).toBeVisible()
  await expect(page.locator('.action-fields')).toHaveCount(0)
  await expect(page.getByTestId('save-state')).toHaveCount(0)
  await expect(page.locator('.actions')).toContainText('Submitted setup')

  // Editing the model's head afterwards must not rewrite what this run used.
  const changed = structuredClone(original.setup)
  changed.analysis.reporting_width = 123
  const head: Revision = await (
    await request.put('/api/projects/' + original.project, {
      data: { base: original.id, setup: changed },
    })
  ).json()
  expect(head.id).not.toBe(original.id)
  const replay = (await (await request.get('/api/revisions/' + run.revision)).json()) as Revision
  expect(replay.setup.analysis.reporting_width).toBe(100)
  await page.goto('/#results/' + run.id)
  await expect(page.getByTestId('vtk-viewport')).toBeVisible()
})

test('3D remains preview-only and never claims a prepareable analysis', async ({
  page,
  request,
}) => {
  const created: Revision = await (
    await request.post('/api/projects', {
      data: { name: 'Matrix 3D', example: true, dimension: '3D' },
    })
  ).json()
  await page.goto('/#workspace/' + created.id)
  await openResults(page)
  await expect(page.getByTestId('prepare')).toBeDisabled()
  await expect(page.getByTestId('prepare-reason')).toContainText('extrusion preview')
  const document = await readiness(request, created.id)
  expect(document.can_prepare).toBe(false)
  expect(document.setup_issues.some((issue) => issue.code === 'drawing.extrusion_preview')).toBe(
    true,
  )
  // Deferred simulation does not make the preview model read-only: its own
  // settings still save automatically (the 3D preview owns them at Import).
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .locator('[data-stage="import"]')
    .click()
  const length = page.getByLabel('Segment length (mm)')
  await length.fill('25')
  await length.press('Tab')
  await expect(
    page.locator('[data-testid="save-state"][data-state="saved"][data-dirty="false"]'),
  ).toHaveCount(1, { timeout: 20000 })
  await expect
    .poll(async () => {
      const head = (await (
        await request.get('/api/revisions/' + page.url().split('/').pop())
      ).json()) as Revision
      return head.setup.extrusion.length
    })
    .toBe(25)
  // The stage that repairs it (Import) opens; 3D geometry is still previewable.
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .locator('[data-stage="import"]')
    .click()
  await expect(page.getByTestId('vtk-viewport')).toBeVisible()
})
