import { expect, type APIRequestContext } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import type { Job, Revision } from '../src/api'

/** Run the mesh → reviewed fixture pipeline without preparing a deck. */
export async function meshAndFixture(
  request: APIRequestContext,
  revision: Revision,
  labels?: string[],
) {
  const mesh: Job = await (
    await request.post('/api/meshes', { data: { revision: revision.id, token: randomUUID() } })
  ).json()
  await expect
    .poll(async () => ((await (await request.get('/api/jobs/' + mesh.id)).json()) as Job).status, {
      timeout: 60000,
    })
    .toBe('Completed')
  const fixture =
    labels ??
    (
      (await (
        await request.post('/api/meshes/' + mesh.id + '/fixture/edges', { data: {} })
      ).json()) as { labels: string[] }
    ).labels
  const saved = await request.put('/api/meshes/' + mesh.id + '/fixture', {
    data: { labels: fixture },
  })
  expect(saved.ok()).toBeTruthy()
  const settled: Job = await (await request.get('/api/jobs/' + mesh.id)).json()
  return { mesh: settled, labels: fixture }
}

/** Run the mesh → fixture → deck pipeline through the real API and worker. */
export async function meshAndDeck(
  request: APIRequestContext,
  revision: Revision,
  labels?: string[],
) {
  const mesh: Job = await (
    await request.post('/api/meshes', { data: { revision: revision.id, token: randomUUID() } })
  ).json()
  await expect
    .poll(async () => ((await (await request.get('/api/jobs/' + mesh.id)).json()) as Job).status, {
      timeout: 60000,
    })
    .toBe('Completed')
  const fixture =
    labels ??
    (
      (await (
        await request.post('/api/meshes/' + mesh.id + '/fixture/edges', { data: {} })
      ).json()) as { labels: string[] }
    ).labels
  const saved = await request.put('/api/meshes/' + mesh.id + '/fixture', {
    data: { labels: fixture },
  })
  expect(saved.ok()).toBeTruthy()
  const deck: Job = await (
    await request.post('/api/decks', {
      data: { revision: revision.id, token: randomUUID(), mesh: mesh.id },
    })
  ).json()
  await expect
    .poll(async () => ((await (await request.get('/api/jobs/' + deck.id)).json()) as Job).status, {
      timeout: 60000,
    })
    .toBe('Completed')
  const settled: Job = await (await request.get('/api/jobs/' + mesh.id)).json()
  return { mesh: settled, deck, labels: fixture }
}
