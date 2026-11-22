import { expect, test, type Page } from './fixtures'
import { meshAndDeck } from './pipeline'
import type { Job, Revision } from '../src/api'

function wsfix(inp: string) {
  const lines = inp.split(/\r?\n/)
  const labels: number[] = []
  let collecting = false
  for (const line of lines) {
    if (line.startsWith('*Nset, nset=WSFIX')) {
      collecting = true
      continue
    }
    if (collecting) {
      if (line.startsWith('*')) break
      labels.push(...line.split(',').filter(Boolean).map(Number))
    }
  }
  return labels
}

async function openReview(page: Page, revision: Revision) {
  await page.goto('/#workspace/' + revision.id)
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Review / Run' })
    .click()
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toBeVisible()
}

async function prepare(page: Page) {
  await page.getByRole('button', { name: 'Prepare input deck' }).click()
  await expect(page.getByTestId('deck-status')).toContainText('Input ready', { timeout: 60000 })
  const href = await page.getByRole('link', { name: 'Inspect input deck' }).getAttribute('href')
  return (await (await page.request.get(href!)).text())
}

test('Review prepares decks without ever enqueueing a mesh', async ({ page, request }) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Review ownership', example: true } })
  ).json()
  const { labels } = await meshAndDeck(request, revision)

  // Count actual mesh submissions from the moment Review opens.
  let meshPosts = 0
  page.on('request', (r) => {
    if (r.method() === 'POST' && new URL(r.url()).pathname === '/api/meshes') meshPosts += 1
  })
  await openReview(page, revision)
  const deckText = await prepare(page)
  // The prepared WSFIX is exactly the saved instance-qualified node set.
  expect(wsfix(deckText).sort((a, b) => a - b)).toEqual(
    labels.map((label) => Number(label.split(':')[1])).sort((a, b) => a - b),
  )

  // Travel changes require a new deck but never a new mesh.
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Motion' })
    .click()
  await page.getByLabel('Prescribed Y travel (mm)').fill('-6.5')
  await page.getByLabel('Prescribed Y travel (mm)').press('Tab')
  await page.getByRole('button', { name: 'Save revision' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 02')
  const saved: Revision = await (
    await request.get('/api/revisions/' + page.url().split('/').pop())
  ).json()
  await openReview(page, saved)
  const second = await prepare(page)
  expect(wsfix(second).sort((a, b) => a - b)).toEqual(wsfix(deckText).sort((a, b) => a - b))
  expect(second).toContain('PANEL_RP, 2, 2, -6.5')

  // Submission also performs no mesh work.
  await page.getByLabel('Run name').fill('Review ownership run')
  await page.getByRole('button', { name: 'Submit Abaqus analysis' }).click()
  await page.waitForURL('**/#diagnostics/*')
  expect(meshPosts).toBe(0)

  const runId = page.url().split('/').pop()!
  await expect
    .poll(
      async () => ((await (await request.get('/api/jobs/' + runId)).json()) as Job).status,
      { timeout: 90000 },
    )
    .toBe('Completed')

  // An intentional remesh starts from zero reviewed nodes, while the submitted
  // setup still replays its own archived labels and mesh.
  await page.goto('/#workspace/' + saved.id)
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Mesh' })
    .click()
  await page.getByRole('button', { name: 'Generate mesh', exact: true }).click()
  await page.getByRole('button', { name: 'Regenerate' }).click()
  await expect
    .poll(
      async () =>
        ((await (await request.get('/api/meshes')).json()) as Job[]).find(
          (job) => job.revision === saved.id,
        )?.status,
      { timeout: 60000 },
    )
    .toBe('Completed')
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Mounting' })
    .click()
  await expect(page.getByTestId('fixture-count')).toHaveText('0')

  await page.goto('/#setup/' + runId)
  await page
    .getByRole('navigation', { name: 'Workflow' })
    .getByRole('button', { name: 'Mounting' })
    .click()
  await expect.poll(async () => Number(await page.getByTestId('fixture-count').textContent())).toBe(
    labels.length,
  )
  const archived: Job = await (await request.get('/api/jobs/' + runId)).json()
  expect(archived.fixture_labels).toEqual([...labels].sort(
    (a, b) => Number(a.split(':')[1]) - Number(b.split(':')[1]),
  ))
})

test('a generated mesh token is never reused as a Review action', async ({ page, request }) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Token discipline', example: true } })
  ).json()
  const { deck } = await meshAndDeck(request, revision)
  const before = ((await (await request.get('/api/meshes')).json()) as Job[]).filter(
    (job) => job.revision === revision.id,
  ).length
  // Preparing and submitting this reviewed deck must not create another MESH row.
  await openReview(page, revision)
  expect(wsfix(await prepare(page)).length).toBeGreaterThan(0)
  await page.getByLabel('Run name').fill('Token discipline run')
  await page.getByRole('button', { name: 'Submit Abaqus analysis' }).click()
  await page.waitForURL('**/#diagnostics/*')
  const after = ((await (await request.get('/api/meshes')).json()) as Job[]).filter(
    (job) => job.revision === revision.id,
  ).length
  expect(after).toBe(before)
  expect(deck.mesh).toBeTruthy()
})
