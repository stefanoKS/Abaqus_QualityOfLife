/**
 * Gate 5b: the real partition workflow through the browser, worker and deck.
 *
 * Fictional synthetic section only. The pre-cut revision keeps its own mesh and
 * deck, and a sibling model is checked to be untouched.
 */
import { expect, test } from './fixtures'
import { meshAndDeck } from './pipeline'
import type { Job, Revision } from '../src/api'

async function example(request: import('@playwright/test').APIRequestContext, name: string) {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name, example: true } })
  ).json()
  return revision
}

test('partition a seal in the browser, remesh, prepare a deck and replay the pre-cut revision', async ({
  page,
  request,
}) => {
  const revision = await example(request, 'Partition acceptance')
  const sibling = await example(request, 'Partition sibling')
  const siblingBefore = await (await request.get('/api/revisions/' + sibling.id)).json()

  // A prepared deck on the pre-cut revision is the replay reference.
  const before = await meshAndDeck(request, revision)
  const beforeDeck = await (
    await request.get('/api/jobs/' + before.deck.id + '/artifacts/analysis.inp')
  ).text()
  const beforeRevision = await (await request.get('/api/revisions/' + revision.id)).json()

  await page.goto('/#workspace/' + revision.id)
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  // Components owns the region list; choosing a region opens its Materials editor.
  await workflow.getByRole('button', { name: 'Components' }).click()
  await page.getByRole('button', { name: /Mounting foot/ }).click()
  const editor = page.getByTestId('partition-editor')
  await expect(editor).toBeVisible()

  // Real viewport clicks after a pan and a zoom. No XY form entry.
  const viewport = page.getByRole('application')
  const box = (await viewport.boundingBox())!
  const projectPoint = async (x: number, y: number) => {
    const camera = (await page.locator('.seal-vtk-host').getAttribute('data-camera'))!
      .split(',')
      .map(Number)
    const [fx, fy, , , , , scale] = [camera[3], camera[4], 0, 0, 0, 0, camera[6]]
    const aspect = box.width / box.height
    return {
      x: box.x + box.width / 2 + ((x - fx) / (scale * aspect)) * (box.width / 2),
      y: box.y + box.height / 2 - ((y - fy) / scale) * (box.height / 2),
    }
  }
  // Pan a little with the middle button, then zoom, then acquire both points.
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down({ button: 'middle' })
  await page.mouse.move(box.x + box.width / 2 + 26, box.y + box.height / 2 + 12, { steps: 4 })
  await page.mouse.up({ button: 'middle' })
  await page.getByRole('button', { name: 'Zoom in' }).click()

  const partitionWrites: string[] = []
  page.on('request', (req) => {
    if (req.url().includes('/partition')) partitionWrites.push(req.method() + ' ' + req.url())
  })

  await page.getByRole('button', { name: 'Cut region' }).click()
  const a = await projectPoint(0, 0)
  await page.mouse.move(a.x, a.y, { steps: 3 })
  await page.mouse.click(a.x, a.y)
  const b = await projectPoint(0, 3.2)
  await page.mouse.move(b.x, b.y, { steps: 5 })
  await page.mouse.click(b.x, b.y)
  await expect(page.getByTestId('partition-plan')).toContainText('Boundary edges intersected')
  // Snapped canonical coordinates, not raw pixels.
  const snapped = await page.getByTestId('partition-plan').innerText()
  expect(snapped).toContain('Cut preview ready')
  await page.getByRole('button', { name: 'Cancel cut' }).click()
  await expect(page.getByTestId('partition-plan')).toHaveCount(0)
  expect(partitionWrites.filter((write) => write.includes('/partition') && !write.includes('preview'))).toHaveLength(0)

  // Re-pick the start point, then preview and apply once.
  await page.getByRole('button', { name: 'Cut region' }).click()
  await page.mouse.click(a.x, a.y)
  await page.getByRole('button', { name: 'Back one point' }).click()
  await expect(page.getByTestId('cut-status')).toHaveAttribute('data-phase', 'start')
  await page.mouse.click(a.x, a.y)
  await page.mouse.move(b.x, b.y, { steps: 3 })
  await page.mouse.click(b.x, b.y)
  await expect(page.getByTestId('partition-plan')).toBeVisible()
  await page.getByRole('button', { name: 'Apply partition' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 02')

  // Two independent child regions, each with its own material card.
  await expect(page.getByLabel('Material card')).toBeVisible()
  await page.getByLabel('Material card').selectOption({ label: 'Cellular EPDM' })
  await workflow.getByRole('button', { name: 'Components' }).click()
  await page.getByRole('button', { name: /Mounting foot B/ }).click()
  await page.getByLabel('Material card').selectOption({ label: 'Dense EPDM' })
  await page.getByRole('button', { name: 'Save revision' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 03')

  // A topology change invalidates the prepared deck and requires remeshing.
  await workflow.getByRole('button', { name: 'Review / Run' }).click()
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toBeDisabled()
  await workflow.getByRole('button', { name: 'Mesh' }).click()
  await page.getByRole('button', { name: 'Generate mesh', exact: true }).click()
  await expect(page.getByTestId('mesh-status')).toContainText('Mesh ready', { timeout: 60000 })
  await workflow.getByRole('button', { name: 'Mounting' }).click()
  await page.getByRole('button', { name: /Resolve .* mounting edges to nodes/ }).click()
  await page.getByRole('button', { name: 'Save fixed nodes' }).click()
  await workflow.getByRole('button', { name: 'Review / Run' }).click()
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toBeEnabled()
  await page.getByRole('button', { name: 'Prepare input deck' }).click()
  await expect(page.getByTestId('deck-status')).toContainText('Input ready', { timeout: 60000 })

  const current = await (
    await request.get('/api/projects/' + revision.project + '/revisions')
  ).json()
  const newest = current.find((row: { number: number }) => row.number === 3)
  expect(newest).toBeTruthy()
  const currentRevision = await (await request.get('/api/revisions/' + newest.id)).json()
  expect(currentRevision.mesh_compat).not.toEqual(beforeRevision.mesh_compat)

  const decks: Job[] = await (await request.get('/api/decks')).json()
  const deck = decks.find((job) => job.revision === newest.id && job.status === 'Completed')!
  expect(deck).toBeTruthy()
  const inp = await (await request.get('/api/jobs/' + deck.id + '/artifacts/analysis.inp')).text()
  expect(inp.match(/\*Solid Section/g)?.length).toBe(3)
  expect(inp).toContain('*Elset, elset=REGION_1')
  expect(inp).toContain('*Elset, elset=REGION_2')
  expect(inp).toContain('*Elset, elset=REGION_3')
  expect(inp).toMatch(/CPS4R|CPS3/)
  const inpLines = inp.split(/\r?\n/)
  for (let i = 0; i < inpLines.length; i++)
    if (inpLines[i].startsWith('*Solid Section')) expect(inpLines[i + 1]).toBe('1,')

  // The internal interface has one shared node set on both children.
  const meshes: Job[] = await (await request.get('/api/meshes')).json()
  const meshJob = meshes.find((job) => job.revision === newest.id && job.status === 'Completed')!
  const mesh = await (
    await request.get('/api/jobs/' + meshJob.id + '/artifacts/mesh.json')
  ).json()
  const setup = currentRevision.setup
  const cutUse = new Map<string, string[]>()
  for (const face of setup.faces) {
    for (const loop of face.loops) {
      for (const token of loop) {
        const id = token.replace('-', '')
        cutUse.set(id, [...(cutUse.get(id) ?? []), face.id])
      }
    }
  }
  const shared = [...cutUse.entries()].filter(([, faces]) => new Set(faces).size === 2)
  expect(shared.length).toBeGreaterThan(0)
  let interfaceChecked = false
  for (const [edgeId, faces] of shared) {
    const nodes = mesh.edge_nodes[edgeId] as number[] | undefined
    if (!nodes?.length) continue
    const region = (faceId: string) =>
      new Set<number>(
        (mesh.elements as { nodes: number[]; entity: string }[])
          .filter((element) => element.entity === faceId)
          .flatMap((element) => element.nodes),
      )
    const a = region(faces[0])
    const b = region(faces[1])
    expect([...nodes].every((node) => a.has(node) && b.has(node))).toBe(true)
    interfaceChecked = true
  }
  expect(interfaceChecked).toBe(true)

  // The pre-cut revision still opens with its own digest and byte-identical deck.
  await page.goto('/#workspace/' + revision.id)
  await page.waitForTimeout(500)
  const replayed = await (await request.get('/api/revisions/' + revision.id)).json()
  expect(replayed.mesh_compat).toEqual(beforeRevision.mesh_compat)
  const replayedDeck = await (
    await request.get('/api/jobs/' + before.deck.id + '/artifacts/analysis.inp')
  ).text()
  expect(replayedDeck).toEqual(beforeDeck)

  // A sibling model was not touched by the partition.
  const siblingAfter = await (await request.get('/api/revisions/' + sibling.id)).json()
  expect(siblingAfter.setup).toEqual(siblingBefore.setup)
  expect(siblingAfter.mesh_compat).toEqual(siblingBefore.mesh_compat)
})
