/**
 * Gate D: projected partition workflow through the real viewport, worker and
 * deck. Guides are drawn with arbitrary model points (away from any former
 * snap band) and stay in Components throughout.
 *
 * Fictional synthetic sections only. The pre-cut revision keeps its own mesh
 * and deck, and a sibling model is checked to be untouched.
 */
import { expect, test, type Page } from './fixtures'
import { saveRevision } from './save'
import { meshAndDeck } from './pipeline'
import type { Job, Revision } from '../src/api'

async function example(request: import('@playwright/test').APIRequestContext, name: string) {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name, example: true } })
  ).json()
  return revision
}

async function projectPoint(page: Page, x: number, y: number) {
  const viewport = page.getByRole('application')
  const box = (await viewport.boundingBox())!
  const camera = (await page.locator('.seal-vtk-host').getAttribute('data-camera'))!
    .split(',')
    .map(Number)
  const fx = camera[3],
    fy = camera[4],
    scale = camera[6]
  const aspect = box.width / box.height
  return {
    x: box.x + box.width / 2 + ((x - fx) / (scale * aspect)) * (box.width / 2),
    y: box.y + box.height / 2 - ((y - fy) / scale) * (box.height / 2),
  }
}

async function drawGuide(page: Page, a: [number, number], b: [number, number]) {
  const first = await projectPoint(page, a[0], a[1])
  await page.mouse.move(first.x, first.y, { steps: 3 })
  await page.mouse.click(first.x, first.y)
  const second = await projectPoint(page, b[0], b[1])
  await page.mouse.move(second.x, second.y, { steps: 4 })
  await page.mouse.click(second.x, second.y)
}

async function selectRegion(page: Page, name: RegExp | string) {
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.getByRole('button', { name: 'Components' }).click()
  await page.locator('.region-list button', { hasText: name }).first().click()
}

function manufacturedDxf(kind: 'lip' | 'box') {
  const tags: (string | number)[] = [
    0, 'SECTION', 2, 'HEADER', 9, '$ACADVER', 1, 'AC1024', 9, '$INSUNITS', 70, 4,
    0, 'ENDSEC', 0, 'SECTION', 2, 'ENTITIES',
  ]
  let handle = 100
  const line = (a: number[], b: number[], layer = '0') => {
    tags.push(0, 'LINE', 5, (handle++).toString(16).toUpperCase(), 100, 'AcDbEntity', 8, layer,
      100, 'AcDbLine', 10, a[0], 20, a[1], 30, 0, 11, b[0], 21, b[1], 31, 0)
  }
  const fit = (points: number[][], closed: boolean) => {
    tags.push(0, 'SPLINE', 5, (handle++).toString(16).toUpperCase(), 100, 'AcDbEntity', 8, '0',
      100, 'AcDbSpline', 70, closed ? 1 : 0, 71, 3, 72, 0, 73, 0, 74, points.length)
    for (const point of points) tags.push(11, point[0], 21, point[1], 31, 0)
  }
  if (kind === 'lip') {
    line([-5, -5], [5, -5])
    fit([[5, -5], [7, -4], [7, -2], [5, -2], [5, 5], [-5, 5], [-5, -5]], false)
    fit([[-2, -2], [2, -2], [2, 2], [-2, 2], [-2, -2]], true)
  } else {
    line([-5, -5], [5, -5])
    line([5, -5], [5, 5])
    line([5, 5], [-5, 5])
    tags.push(0, 'SPLINE', 5, (handle++).toString(16).toUpperCase(), 100, 'AcDbEntity', 8, '0',
      100, 'AcDbSpline', 70, 0, 71, 1, 72, 4, 73, 2, 74, 0,
      40, 0, 40, 0, 40, 1, 40, 1, 10, -5, 20, 5, 30, 0, 10, -5, 20, -5, 30, 0)
    line([-2, -2], [2, -2])
    line([2, -2], [2, 2])
    line([2, 2], [-2, 2])
    line([-2, 2], [-2, -2])
  }
  line([-10, 14], [10, 14], 'PANEL')
  tags.push(0, 'ENDSEC', 0, 'EOF')
  return Buffer.from(tags.join('\n') + '\n')
}

async function importedManufactured(page: Page, request: import('@playwright/test').APIRequestContext, kind: 'lip' | 'box') {
  const empty: Revision = await (await request.post('/api/projects', { data: { name: `Manufactured ${kind}` } })).json()
  await page.goto('/#workspace/' + empty.id)
  await page.locator('input[type=file]').setInputFiles({
    name: `${kind}.dxf`, mimeType: 'application/dxf', buffer: manufacturedDxf(kind),
  })
  await expect(page.locator('.crumb')).toContainText('Revision 02', { timeout: 60000 })
  const imported: Revision = await (await request.get('/api/revisions/' + page.url().split('/').pop())).json()
  const target = imported.setup.faces.find((face) => !face.cavity)!
  for (const component of imported.setup.components)
    component.role = component.id === target.component ? 'seal' : 'moving_panel'
  target.material = 'bulb_foam'
  const response = await request.put('/api/projects/' + imported.project, {
    data: { base: imported.id, setup: imported.setup },
  })
  expect(response.ok(), await response.text()).toBeTruthy()
  return (await response.json()) as Revision
}

test('draw arbitrary guides in Components, apply once, then assign two materials and inspect the deck', async ({
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
  await selectRegion(page, 'Mounting foot')
  const editor = page.getByTestId('partition-editor')
  await expect(editor).toBeVisible()
  await expect(page.getByTestId('partition-target')).toContainText('Mounting foot')

  // Real viewport clicks after a pan and a zoom. Both endpoints are away from
  // any former 12-px boundary acquisition band.
  const viewport = page.getByRole('application')
  const box = (await viewport.boundingBox())!
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down({ button: 'middle' })
  await page.mouse.move(box.x + box.width / 2 + 26, box.y + box.height / 2 + 12, { steps: 4 })
  await page.mouse.up({ button: 'middle' })
  await page.getByRole('button', { name: 'Zoom in' }).click()

  const partitionWrites: string[] = []
  page.on('request', (req) => {
    if (req.url().includes('/partition')) partitionWrites.push(req.method() + ' ' + req.url())
  })

  await page.getByRole('button', { name: 'Partition region' }).click()
  await expect(page.getByTestId('cut-status')).toHaveAttribute('data-phase', 'start')
  await drawGuide(page, [0, 0.5], [0, 2.5])
  await expect(page.getByTestId('partition-plan')).toContainText('Cut preview ready')
  await expect(page.getByTestId('partition-plan')).toContainText('2 regions')
  // No commit yet; the guide is a draft.
  expect(partitionWrites.filter((write) => !write.includes('preview'))).toHaveLength(0)

  // Undo the draft guide and draw it again: the draft work is retained, and
  // only the second stroke is previewed.
  await page.getByRole('button', { name: 'Undo last guide' }).click()
  await expect(page.getByTestId('partition-plan')).toHaveCount(0)
  await drawGuide(page, [0, 0.5], [0, 2.5])
  await expect(page.getByTestId('partition-plan')).toContainText('Cut preview ready')
  await page.getByRole('button', { name: 'Apply partition' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 02')

  // Two independent child regions, each with its own material card. The tool
  // stays in Components; assigning material is an explicit link.
  await expect(page.getByTestId('assign-material')).toBeVisible()
  await page.getByTestId('assign-material').click()
  await expect(page.getByLabel('Material card')).toBeVisible()
  await page.getByLabel('Material card').selectOption({ label: 'Cellular EPDM' })
  await selectRegion(page, 'Mounting foot B')
  await page.getByTestId('assign-material').click()
  await page.getByLabel('Material card').selectOption({ label: 'Dense EPDM' })
  await saveRevision(page)
  await expect(page.locator('.crumb')).toContainText('Revision 03')

  // A topology change invalidates the prepared deck and requires remeshing.
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.locator('[data-stage="results"]').click()
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toBeDisabled()
  await workflow.getByRole('button', { name: 'Mesh' }).click()
  await page.getByRole('button', { name: 'Generate mesh', exact: true }).click()
  await expect(page.getByTestId('mesh-status')).toContainText('Mesh ready', { timeout: 60000 })
  await workflow.getByRole('button', { name: 'Mounting' }).click()
  await page.getByRole('button', { name: /Resolve .* mounting edges to nodes/ }).click()
  await page.getByRole('button', { name: 'Save fixed nodes' }).click()
  await workflow.locator('[data-stage="results"]').click()
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
  // Each child inherited its assigned material; they are independent.
  const regions = currentRevision.setup.faces.filter((face: { component: string }) => face.component === 'seal')
  expect(regions.length).toBe(3)
  expect(new Set(regions.map((face: { material: string }) => face.material)).size).toBe(2)

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
  // The two child materials are distinct in the section definitions. The deck
  // writes its own index-based material names (MAT_n), so compare the references
  // rather than the card display names.
  const materialNames = currentRevision.setup.faces
    .slice(0, 2)
    .map(
      (face: { material: string }) =>
        currentRevision.setup.materials.find(
          (material: { id: string }) => material.id === face.material,
        )?.name,
    )
  expect(new Set(materialNames).size).toBe(2)
  const sectionMaterials = inpLines
    .filter((line) => line.startsWith('*Solid Section'))
    .map((line) => line.match(/material=([^,\s]+)/)?.[1])
  expect(sectionMaterials.length).toBe(3)
  expect(sectionMaterials[0]).not.toBe(sectionMaterials[1])
  expect(new Set(sectionMaterials).size).toBe(2)

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

test('a hollow seal keeps the draft after one radial cut and splits after the second', async ({
  page,
  request,
}) => {
  const revision = await example(request, 'Hollow projected partition')
  await page.goto('/#workspace/' + revision.id)
  await selectRegion(page, 'Hollow bulb')
  await expect(page.getByTestId('partition-editor')).toBeVisible()

  await page.getByRole('button', { name: 'Partition region' }).click()
  // First radial guide crosses only the top wall (cavity to outer boundary):
  // the annulus opens but one material region remains.
  await drawGuide(page, [0, 10], [0, 13])
  await expect(page.getByTestId('partition-plan')).toHaveAttribute('data-status', 'one_region')
  await expect(page.getByTestId('partition-plan')).toContainText('One material region remains')
  const apply = page.getByRole('button', { name: 'Apply partition' })
  await expect(apply).toBeDisabled()

  // A second guide at x = 2 separates the top wall into two children.
  await drawGuide(page, [2, 10], [2, 13])
  await expect(page.getByTestId('partition-plan')).toHaveAttribute('data-status', 'valid')
  await expect(apply).toBeEnabled()
  await apply.click()
  await expect(page.locator('.crumb')).toContainText('Revision 02')

  const stored: Revision = await (
    await request.get('/api/revisions/' + page.url().split('/').pop())
  ).json()
  const children = stored.setup.faces.filter((face) =>
    face.name.startsWith('Hollow bulb'),
  )
  expect(children).toHaveLength(2)
  // The cavity still belongs to exactly one child as a hole, never a new region.
  const holed = stored.setup.faces.filter(
    (face) => face.name.startsWith('Hollow bulb') && face.loops.length === 2,
  )
  expect(holed.length).toBeLessThanOrEqual(1)
})

test('manufactured fit-point lip survives viewport apply and reopen', async ({ page, request }) => {
  const saved = await importedManufactured(page, request, 'lip')
  const splines = saved.setup.edges.filter((edge) => edge.kind === 'spline' && edge.component !== 'panel')
  expect(splines.some((edge) => edge.spline?.fit_points.length && !edge.spline.closed)).toBeTruthy()
  expect(splines.some((edge) => edge.spline?.fit_points.length && edge.spline.closed && !edge.spline.periodic)).toBeTruthy()
  await page.goto('/#workspace/' + saved.id)
  await selectRegion(page, 'Region 1')
  await page.getByRole('button', { name: 'Partition region' }).click()
  await drawGuide(page, [6, -5], [6, 0])
  await expect(page.getByTestId('partition-plan')).toHaveAttribute('data-status', 'valid')
  await page.getByRole('button', { name: 'Apply partition' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 04')
  await page.reload()
  await selectRegion(page, 'Region 1 A')
  await expect(page.getByTestId('partition-target')).toContainText('Region 1 A')
  await selectRegion(page, 'Region 1 B')
  await expect(page.getByTestId('partition-target')).toContainText('Region 1 B')
})

test('a centered through-guide crosses both walls including a straight spline', async ({ page, request }) => {
  const saved = await importedManufactured(page, request, 'box')
  await page.goto('/#workspace/' + saved.id)
  await selectRegion(page, 'Region 1')
  await page.getByRole('button', { name: 'Partition region' }).click()
  const previewResponse = page.waitForResponse((response) =>
    response.url().includes('/api/partition/preview') && response.request().method() === 'POST',
  )
  await drawGuide(page, [-6, 0], [6, 0])
  const plan = (await (await previewResponse).json()).plan
  expect(plan.status).toBe('valid')
  expect(plan.guides[0].intervals).toHaveLength(2)
  expect(plan.areas[0]).toBeCloseTo(42, 0)
  expect(plan.areas[1]).toBeCloseTo(42, 0)
  await page.getByRole('button', { name: 'Apply partition' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 04')
})

test('mixed draft can remove or complete its unfinished wall guide', async ({ page, request }) => {
  const revision = await example(request, 'Mixed hollow draft')
  await page.goto('/#workspace/' + revision.id)
  await selectRegion(page, 'Hollow bulb')
  await page.getByRole('button', { name: 'Partition region' }).click()
  await drawGuide(page, [-4, 11.6], [4, 11.6])
  await expect(page.getByTestId('partition-plan')).toHaveAttribute('data-status', 'valid')
  await drawGuide(page, [-9, 7], [-6, 7])
  await expect(page.getByTestId('partition-plan')).toHaveAttribute('data-status', 'mixed')
  await expect(page.getByTestId('partition-plan')).toContainText('unfinished guide(s): 2')
  await expect(page.getByRole('button', { name: 'Apply partition' })).toBeDisabled()
  await page.locator('.lang-button').click()
  await expect(page.getByTestId('partition-plan')).toContainText('未完成')
  await expect(page.getByRole('button', { name: 'ガイド 2 を削除' })).toBeVisible()
  await page.locator('.lang-button').click()
  await page.getByRole('button', { name: 'Remove guide 2' }).click()
  await expect(page.getByTestId('partition-plan')).toHaveAttribute('data-status', 'valid')
  await drawGuide(page, [-9, 7], [-6, 7])
  await expect(page.getByTestId('partition-plan')).toHaveAttribute('data-status', 'mixed')
  await drawGuide(page, [6, 7], [9, 7])
  await expect(page.getByTestId('partition-plan')).toHaveAttribute('data-status', 'valid')
  await page.getByRole('button', { name: 'Apply partition' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 02')
})

test('reviewed native lip is selectable after viewport partition and reopen', async ({
  page,
  request,
}) => {
  test.skip(!process.env.SEAL_NATIVE_DWG, 'Requires the local reviewed drawing')
  const empty: Revision = await (
    await request.post('/api/projects', { data: { name: 'Isolated native lip' } })
  ).json()
  await page.goto('/#workspace/' + empty.id)
  await page.locator('input[type=file]').setInputFiles(process.env.SEAL_NATIVE_DWG!)
  await expect(page.locator('.crumb')).toContainText('Revision 02', { timeout: 60000 })
  const imported: Revision = await (
    await request.get('/api/revisions/' + page.url().split('/').pop())
  ).json()
  const seal = imported.setup.faces.find((face) => !face.cavity)!
  const vertices = new Map(imported.setup.vertices.map((vertex) => [vertex.id, vertex.xyz]))
  const other = imported.setup.components.filter((component) => component.id !== seal.component)
  const meanY = (id: string) => {
    const edges = imported.setup.edges.filter((edge) => edge.component === id)
    return edges.reduce((sum, edge) => sum + vertices.get(edge.start)![1], 0) / edges.length
  }
  const door = other.reduce((a, b) => (meanY(a.id) > meanY(b.id) ? a : b))
  for (const component of imported.setup.components) {
    component.role = component.id === seal.component ? 'seal' : component.id === door.id ? 'moving_panel' : 'vehicle_body'
  }
  seal.material = 'bulb_foam'
  const mountEdge = imported.setup.edges.find((edge) => edge.component === seal.component && edge.kind === 'line')!
  imported.setup.selections.find((selection) => selection.id === 'mount')!.entities = [mountEdge.id]
  const savedResponse = await request.put('/api/projects/' + imported.project, {
    data: { base: imported.id, setup: imported.setup },
  })
  expect(savedResponse.ok()).toBeTruthy()
  const revision: Revision = await savedResponse.json()
  const health = await (await request.get('/api/health')).json()
  console.log('native test build', JSON.stringify({ build: health.build, release: health.release, git: health.git }))
  await page.goto('/#workspace/' + revision.id)
  await selectRegion(page, 'Region 1')
  await expect(page.getByTestId('partition-target')).toContainText('Region 1')
  const viewport = page.getByRole('application')
  const box = (await viewport.boundingBox())!
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  await page.mouse.down({ button: 'middle' })
  await page.mouse.move(box.x + box.width / 2 + 20, box.y + box.height / 2 + 10, { steps: 4 })
  await page.mouse.up({ button: 'middle' })
  await page.getByRole('button', { name: 'Zoom in' }).click()
  await page.getByRole('button', { name: 'Partition region' }).click()
  const previewResponse = page.waitForResponse((response) =>
    response.url().includes('/api/partition/preview') && response.request().method() === 'POST',
  )
  await drawGuide(page, [27, 6], [27, 9])
  const preview = await previewResponse
  expect(preview.status()).toBe(200)
  const plan = (await preview.json()).plan
  console.log('native preview', JSON.stringify({ status: plan.status, areas: plan.areas, guides: plan.guides }))
  expect(plan.status).toBe('valid')
  expect(plan.guides[0].intervals).toHaveLength(1)
  await expect(page.getByRole('button', { name: 'Apply partition' })).toBeEnabled()
  if (process.env.SEAL_EVIDENCE_DIR)
    await page.screenshot({ path: process.env.SEAL_EVIDENCE_DIR + '\\native-lip-preview.png' })
  await page.getByRole('button', { name: 'Apply partition' }).click()
  await expect(page.locator('.crumb')).toContainText('Revision 04')
  const partitionedId = page.url().split('/').pop()
  const partitioned: Revision = await (await request.get('/api/revisions/' + partitionedId)).json()
  expect(partitioned.setup.faces.filter((face) => face.name.startsWith('Region 1 ')).map((face) => face.id))
    .toEqual(plan.children.map((child: { id: string }) => child.id))
  await page.goto('/#workspace/' + partitionedId)
  await selectRegion(page, 'Region 1 A')
  await expect(page.getByTestId('partition-target')).toContainText('Region 1 A')
  const lipPoint = await projectPoint(page, 27.5, 7.5)
  await page.mouse.click(lipPoint.x, lipPoint.y)
  await expect(page.getByTestId('partition-target')).toContainText('Region 1 B')
  const remainderPoint = await projectPoint(page, 20, 8)
  await page.mouse.click(remainderPoint.x, remainderPoint.y)
  await expect(page.getByTestId('partition-target')).toContainText('Region 1 A')
  await page.mouse.click(lipPoint.x, lipPoint.y)
  await expect(page.getByTestId('partition-target')).toContainText('Region 1 B')
  await page.getByTestId('assign-material').click()
  await page.getByLabel('Material card').selectOption({ label: 'Dense EPDM' })
  await saveRevision(page)
  await expect(page.locator('.crumb')).toContainText('Revision 05')
  const finalRevision: Revision = await (
    await request.get('/api/revisions/' + page.url().split('/').pop())
  ).json()
  expect(new Set(finalRevision.setup.faces.filter((face) => face.name.startsWith('Region 1 ')).map((face) => face.material)).size).toBe(2)
  if (process.env.SEAL_EVIDENCE_DIR)
    await page.screenshot({ path: process.env.SEAL_EVIDENCE_DIR + '\\native-lip-reopen.png' })
  const workflow = page.getByRole('navigation', { name: 'Workflow' })
  await workflow.getByRole('button', { name: 'Mesh' }).click()
  await page.getByRole('button', { name: 'Generate mesh', exact: true }).click()
  await expect(page.getByTestId('mesh-status')).toContainText('Mesh ready', { timeout: 60000 })
  await workflow.getByRole('button', { name: 'Mounting' }).click()
  await page.getByRole('button', { name: /Resolve .* mounting edges to nodes/ }).click()
  await page.getByRole('button', { name: 'Save fixed nodes' }).click()
  await workflow.locator('[data-stage="results"]').click()
  await expect(page.getByRole('button', { name: 'Prepare input deck' })).toBeEnabled()
  await page.getByRole('button', { name: 'Prepare input deck' }).click()
  await expect(page.getByTestId('deck-status')).toContainText('Input ready', { timeout: 60000 })
  const meshes: Job[] = await (await request.get('/api/meshes')).json()
  const meshJob = meshes.find((job) => job.revision === finalRevision.id && job.status === 'Completed')!
  const mesh = await (await request.get('/api/jobs/' + meshJob.id + '/artifacts/mesh.json')).json()
  const childIds = plan.children.map((child: { id: string }) => child.id)
  const seamNodes = new Set<number>(mesh.edge_nodes[plan.seams[0]])
  const nodesFor = (id: string) => new Set<number>(
    (mesh.elements as { entity: string; nodes: number[] }[]).filter((element) => element.entity === id).flatMap((element) => element.nodes),
  )
  const firstNodes = nodesFor(childIds[0])
  const secondNodes = nodesFor(childIds[1])
  const common = [...firstNodes].filter((node) => secondNodes.has(node))
  expect(new Set(common)).toEqual(seamNodes)
  const decks: Job[] = await (await request.get('/api/decks')).json()
  const deck = decks.find((job) => job.revision === finalRevision.id && job.status === 'Completed')!
  const inp = await (await request.get('/api/jobs/' + deck.id + '/artifacts/analysis.inp')).text()
  const sections = inp.split(/\r?\n/).filter((line) => line.startsWith('*Solid Section'))
  expect(sections).toHaveLength(2)
  expect(new Set(sections.map((line) => line.match(/material=([^,\s]+)/)?.[1])).size).toBe(2)
  const surface = inp.split('*Surface, type=ELEMENT, name=SEAL_EXTERIOR')[1].split('*')[0]
  const interfaceSides: string[] = []
  for (const element of mesh.elements as { id: number; entity: string; nodes: number[] }[]) {
    if (!childIds.includes(element.entity)) continue
    for (let index = 0; index < element.nodes.length; index++) {
      if (seamNodes.has(element.nodes[index]) && seamNodes.has(element.nodes[(index + 1) % element.nodes.length]))
        interfaceSides.push(`${element.id}, S${index + 1}`)
    }
  }
  expect(interfaceSides.length).toBeGreaterThan(0)
  for (const side of interfaceSides) expect(surface.split(/\r?\n/)).not.toContain(side)
  console.log('native mesh/deck', JSON.stringify({
    nodes: mesh.nodes.length,
    elements: mesh.elements.length,
    byChild: childIds.map((id: string) => mesh.elements.filter((element: { entity: string }) => element.entity === id).length),
    sharedNodes: common.length,
    interfaceSides: interfaceSides.length,
    boundaryDeviation: mesh.boundary.worst,
    sections,
  }))
})
