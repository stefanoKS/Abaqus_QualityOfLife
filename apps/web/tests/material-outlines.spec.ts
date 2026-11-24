/**
 * Gate E: optional material outlines in Results.
 *
 * Part 1 is a renderer-free synthetic equivalent that CI can always run: a
 * two-material bonded patch, distinct CAD regions that share one material, a
 * hollow ring (cavity boundary), a rigid instance reusing local node labels and
 * a legacy result with no region mapping. Expected FE interfaces are counted by
 * hand from the connectivity, never from the renderer.
 *
 * Part 2 drives the real API and worker pipeline against a manufactured
 * (license-free) result and checks the rendered scene, actor counts and the
 * legend against the job's immutable submitted revision.
 */
import { randomUUID } from 'node:crypto'
import { mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from './fixtures'
import { makeScene, materialTopology, type ViewportProps } from '../src/viewportModel'
import { pickAt } from '../src/viewportPicking'
import type { Job, Revision } from '../src/api'
import { meshAndDeck } from './pipeline'

type Element = {
  label: number
  type: string
  connectivity: number[]
  region?: string | null
}

function patch(): { nodes: number[][]; elements: Element[] } {
  // 2x2 quad patch, node labels shown in the comment:
  //   7---8---9
  //   | e3 | e4 |
  //   4---5---6
  //   | e1 | e2 |
  //   1---2---3
  const nodes = [
    [1, 0, 0, 0],
    [2, 1, 0, 0],
    [3, 2, 0, 0],
    [4, 0, 1, 0],
    [5, 1, 1, 0],
    [6, 2, 1, 0],
    [7, 0, 2, 0],
    [8, 1, 2, 0],
    [9, 2, 2, 0],
  ]
  const elements: Element[] = [
    { label: 1, type: 'CPS4R', connectivity: [1, 2, 5, 4], region: 'a' },
    { label: 2, type: 'CPS4R', connectivity: [2, 3, 6, 5], region: 'b' },
    { label: 3, type: 'CPS4R', connectivity: [4, 5, 8, 7], region: 'a' },
    { label: 4, type: 'CPS4R', connectivity: [5, 6, 9, 8], region: 'b' },
  ]
  return { nodes, elements }
}

function materials() {
  return {
    a: { key: 'lib:a@1', name: 'A', color: '#46ad94', version: 1 },
    b: { key: 'lib:b@1', name: 'B', color: '#dc9b50', version: 1 },
  }
}

function props(overrides: Partial<ViewportProps> = {}): ViewportProps {
  const { nodes, elements } = patch()
  return {
    dimension: '2D',
    display: null,
    mode: 'element',
    selection: null,
    onSelect: () => undefined,
    results: {
      instances: [
        { name: 'WS-1', nodes, elements },
        {
          name: 'PANEL-1',
          nodes: [
            [1, 0, 2, 0],
            [2, 2, 2, 0],
          ],
          elements: [{ label: 9, type: 'R2D2', connectivity: [1, 2], region: 'panel' }],
        },
      ],
      frame: {
        time: 1,
        displacements: {
          'WS-1': nodes.map((node) => [node[0], 0, 1, 0]),
          'PANEL-1': [
            [1, 0, -1, 0],
            [2, 0, -1, 0],
          ],
        },
      },
      bounds: [0, 2, 0, 2, 0, 0],
    },
    deformed: true,
    deformationScale: 1,
    resultComponent: 'magnitude',
    resultRange: 0.5,
    resultMin: 0,
    elementValues: { 'WS-1': { 1: 0.1, 2: 0.2, 3: 0.3, 4: 0.4 } },
    faceMaterials: materials(),
    materialOutlines: true,
    ...overrides,
  }
}

function overlays(scene: ReturnType<typeof makeScene>, kind: string) {
  return scene.surfaces.filter((surface) => surface.overlay === kind)
}

test('two materials in one bonded patch produce exactly the hand-counted interfaces', () => {
  const topology = materialTopology(
    props().results!.instances,
    materials(),
  )
  // Shared edges between e1/e2 and between e3/e4 cross A|B; e1/e3 and e2/e4 are
  // same-material regional seams and must not count.
  expect(topology.interfaces).toHaveLength(2)
  expect(topology.perimeters).toHaveLength(8)
  expect(topology.total).toBe(4)
  expect(topology.mapped).toBe(4)
  expect(topology.materials).toEqual(['lib:a@1', 'lib:b@1'])
  // The rigid panel reuses labels 1 and 2 but is not a continuum element.
  expect(topology.perimeters.some((row) => row.instance === 'PANEL-1')).toBe(false)

  const scene = makeScene(props())
  const interfaces = overlays(scene, 'material-interface')
  expect(interfaces).toHaveLength(1)
  expect(interfaces[0].cells).toHaveLength(2)
  expect(interfaces[0].materials).toEqual(['lib:a@1', 'lib:b@1'])
  expect(overlays(scene, 'material-perimeter').flatMap((row) => row.cells)).toHaveLength(8)
})

test('the overlay follows the displayed frame, deformation toggle and scale', () => {
  const still = makeScene(props({ deformed: false }))
  const moved = makeScene(props({ deformed: true, deformationScale: 1 }))
  const scaled = makeScene(props({ deformed: true, deformationScale: 2 }))
  const point = (scene: ReturnType<typeof makeScene>) =>
    overlays(scene, 'material-interface')[0].points[0]
  expect(point(still)[1]).toBe(0)
  expect(point(moved)[1]).toBe(1)
  expect(point(scaled)[1]).toBe(2)
})

test('material outlines are independent of mesh edges, markers and the field', () => {
  const base = makeScene(props({ showMeshEdges: false }))
  const withEdges = makeScene(props({ showMeshEdges: true }))
  const withMarkers = makeScene(props({ nodeMarkers: true }))
  const displacement = makeScene(props({ resultComponent: 'U1' }))
  const count = (scene: ReturnType<typeof makeScene>) =>
    overlays(scene, 'material-interface')[0].cells.length
  expect(count(base)).toBe(count(withEdges))
  expect(count(base)).toBe(count(withMarkers))
  expect(count(base)).toBe(count(displacement))
})

test('overlays are never probe or pick targets', () => {
  // Undeformed so the rigid panel line does not sit under the probe point.
  const scene = makeScene(props({ deformed: false }))
  const projected = scene.surfaces.map((surface) => ({ surface, points: surface.points }))
  const interfaceLine = overlays(scene, 'material-interface')[0]
  const point = interfaceLine.points[0]
  for (const mode of ['element', 'node'] as const) {
    const picked = pickAt(
      projected.filter((row) => row.surface.overlay),
      mode,
      point[0],
      point[1],
    )
    expect(picked).toBeNull()
  }
  // Element probing still resolves the continuum element underneath.
  const element = pickAt(projected, 'element', 0.5, 0.5)
  expect(element?.instance).toBe('WS-1')
  expect(element?.label).toBe(1)
})

test('two distinct regions that share one material create no false interface', () => {
  const { nodes, elements } = patch()
  // Different CAD face ids, same effective pinned card identity.
  for (const element of elements) element.region = element.label <= 2 ? 'a' : 'b'
  const shared = {
    a: { key: 'lib:a@1', name: 'A', color: '#46ad94', version: 1 },
    b: { key: 'lib:a@1', name: 'A', color: '#46ad94', version: 1 },
  }
  const topology = materialTopology(
    [{ name: 'WS-1', nodes, elements }],
    shared,
  )
  expect(topology.materials).toEqual(['lib:a@1'])
  expect(topology.interfaces).toHaveLength(0)
  const scene = makeScene(
    props({
      results: {
        instances: [{ name: 'WS-1', nodes, elements }],
        frame: { time: 0, displacements: { 'WS-1': nodes.map((n) => [n[0], 0, 0, 0]) } },
        bounds: [0, 2, 0, 2, 0, 0],
      },
      faceMaterials: shared,
    }),
  )
  expect(overlays(scene, 'material-interface')).toHaveLength(0)
  expect(overlays(scene, 'material-perimeter').flatMap((row) => row.cells)).toHaveLength(8)
})

test('a pinned library version change splits the material identity', () => {
  const { nodes, elements } = patch()
  const versions = {
    a: { key: 'lib:a@1', name: 'A', color: '#46ad94', version: 1 },
    b: { key: 'lib:a@2', name: 'A', color: '#46ad94', version: 2 },
  }
  const topology = materialTopology([{ name: 'WS-1', nodes, elements }], versions)
  expect(topology.interfaces).toHaveLength(2)
})

test('a hollow ring draws exterior and cavity boundaries but no interface', () => {
  // Ring of 8 triangles between an inner square (1-4) and an outer square (5-8).
  const nodes = [
    [1, 1, 1, 0],
    [2, 2, 1, 0],
    [3, 2, 2, 0],
    [4, 1, 2, 0],
    [5, 0, 0, 0],
    [6, 3, 0, 0],
    [7, 3, 3, 0],
    [8, 0, 3, 0],
  ]
  const ring: Element[] = [
    [1, 2, 6],
    [2, 7, 6],
    [2, 3, 7],
    [3, 8, 7],
    [3, 4, 8],
    [4, 5, 8],
    [4, 1, 5],
    [1, 6, 5],
  ].map((connectivity, index) => ({
    label: index + 1,
    type: 'CPS3',
    connectivity,
    region: 'ring',
  }))
  const one = { ring: { key: 'lib:r@1', name: 'Rubber', color: '#dc9b50', version: 1 } }
  const topology = materialTopology([{ name: 'WS-1', nodes, elements: ring }], one)
  expect(topology.interfaces).toHaveLength(0)
  // 8 boundary edges: four on the inner square (the cavity) and four outside.
  expect(topology.perimeters).toHaveLength(8)
  expect(topology.perimeters.filter((row) => row.a <= 4 && row.b <= 4)).toHaveLength(4)
})

test('a legacy result with no region mapping draws nothing and says so', () => {
  const { nodes, elements } = patch()
  for (const element of elements) element.region = null
  const topology = materialTopology([{ name: 'WS-1', nodes, elements }], materials())
  expect(topology.mapped).toBe(0)
  expect(topology.total).toBe(4)
  expect(topology.interfaces).toHaveLength(0)
  const scene = makeScene(
    props({
      results: {
        instances: [{ name: 'WS-1', nodes, elements }],
        frame: { time: 0, displacements: {} },
        bounds: [0, 2, 0, 2, 0, 0],
      },
    }),
  )
  expect(overlays(scene, 'material-interface')).toHaveLength(0)
  expect(overlays(scene, 'material-perimeter')).toHaveLength(0)
})

/* ---------------------------------------------------------------- real pipeline */

interface ResultIndex {
  instances: {
    name: string
    nodes: number[][]
    elements: { label: number; type: string; connectivity: number[]; region?: string | null }[]
  }[]
}

/** Independent count from the artifact and the pinned revision, not the app. */
function expectedInterfaces(index: ResultIndex, revision: Revision) {
  const cards = new Map(revision.setup.materials.map((card) => [card.id, card]))
  const keyOf: Record<string, string> = {}
  for (const face of revision.setup.faces) {
    const card = face.material ? cards.get(face.material) : undefined
    if (!card) continue
    keyOf[face.id] = card.library_id
      ? card.library_id + '@' + (card.library_version ?? 0)
      : 'card:' + card.id
  }
  let interfaces = 0
  for (const instance of index.instances) {
    const edges = new Map<string, Set<string>>()
    const counts = new Map<string, number>()
    for (const element of instance.elements) {
      if (!['CPS3', 'CPS4', 'CPS4R'].includes(element.type)) continue
      const key = element.region ? keyOf[element.region] : undefined
      if (!key) continue
      for (let i = 0; i < element.connectivity.length; i++) {
        const one = element.connectivity[i]
        const two = element.connectivity[(i + 1) % element.connectivity.length]
        const id = Math.min(one, two) + ':' + Math.max(one, two)
        counts.set(id, (counts.get(id) ?? 0) + 1)
        const set = edges.get(id) ?? new Set<string>()
        set.add(key)
        edges.set(id, set)
      }
    }
    for (const [id, set] of edges)
      if (counts.get(id) === 2 && set.size === 2) interfaces++
  }
  return interfaces
}

async function completeRun(
  request: import('@playwright/test').APIRequestContext,
  revision: Revision,
) {
  const { deck } = await meshAndDeck(request, revision)
  const run: Job = await (
    await request.post('/api/runs', {
      data: {
        revision: revision.id,
        deck: deck.id,
        token: randomUUID(),
        name: 'Material outline run',
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
  return run
}

test('real manufactured result: outlines match the pinned materials and survive playback toggles', async ({
  page,
  request,
}) => {
  const revision: Revision = await (
    await request.post('/api/projects', { data: { name: 'Material outlines', example: true } })
  ).json()
  const run = await completeRun(request, revision)
  const index: ResultIndex = await (
    await request.get(`/api/jobs/${run.id}/artifacts/results.json`)
  ).json()
  const pinned = (await (await request.get('/api/revisions/' + run.revision)).json()) as Revision
  const expected = expectedInterfaces(index, pinned)
  expect(expected).toBeGreaterThan(0)

  await page.goto('/#results/' + run.id)
  const toggle = page.getByTestId('material-outlines')
  await expect(toggle).not.toBeChecked()
  mkdirSync(resolve('../../.local/evidence'), { recursive: true })
  const viewport = page.getByTestId('vtk-viewport')
  await expect(viewport).toHaveAttribute('data-material-outlines', 'off')
  await expect(viewport).toHaveAttribute('data-material-interfaces', '0')

  await toggle.check()
  await expect(viewport).toHaveAttribute('data-material-outlines', 'on')
  await expect(viewport).toHaveAttribute('data-material-interfaces', String(expected))
  await page.screenshot({
    path: resolve('../../.local/evidence/material-outlines-undeformed.png'),
  })
  const legend = page.getByTestId('material-legend')
  await expect(legend).toBeVisible()
  await expect(legend).toContainText('Cellular EPDM')
  await expect(legend).toContainText('Dense EPDM')
  await expect(page.getByTestId('material-interface-count')).toContainText(String(expected))

  // Mesh edges and node markers are independent layers: toggling them must not
  // change the interface count or the material legend.
  await page.getByLabel('Mesh edges').uncheck()
  await expect(viewport).toHaveAttribute('data-material-interfaces', String(expected))
  await page.getByLabel('Node markers').check()
  await expect(viewport).toHaveAttribute('data-material-interfaces', String(expected))
  await page.getByLabel('Mesh edges').check()
  await expect(viewport).toHaveAttribute('data-material-interfaces', String(expected))

  // Deformed playback keeps the same topology and moves the interface with the
  // displayed frame rather than the undeformed coordinates.
  const firstTime = await viewport.getAttribute('data-frame-time')
  await page.getByLabel('Deformed geometry').check()
  await page.locator('.playback-slider').fill('20')
  await expect.poll(() => viewport.getAttribute('data-frame-time')).not.toBe(firstTime)
  await expect(viewport).toHaveAttribute('data-material-interfaces', String(expected))
  await page.screenshot({
    path: resolve('../../.local/evidence/material-outlines-deformed.png'),
  })
  await page.getByLabel('Deformed geometry').uncheck()
  await expect(viewport).toHaveAttribute('data-material-interfaces', String(expected))

  // The colorbar range, field and probe text are untouched by the overlay.
  await expect(page.getByTestId('legend-limits')).toBeVisible()
  await expect(page.getByLabel('Field')).not.toHaveValue('')
})

test('a single-material result keeps a readable perimeter and reports no interface', async ({
  page,
  request,
}) => {
  const created: Revision = await (
    await request.post('/api/projects', { data: { name: 'One material outline', example: true } })
  ).json()
  // Give both seal regions the same card: distinct CAD faces, one material.
  const setup = structuredClone(created.setup)
  for (const face of setup.faces) face.material = 'base_rubber'
  const revision: Revision = await (
    await request.put('/api/projects/' + created.project, {
      data: { base: created.id, setup },
    })
  ).json()
  const run = await completeRun(request, revision)
  await page.goto('/#results/' + run.id)
  await page.getByTestId('material-outlines').check()
  const viewport = page.getByTestId('vtk-viewport')
  await expect(viewport).toHaveAttribute('data-material-interfaces', '0')
  expect(Number(await viewport.getAttribute('data-material-perimeters'))).toBeGreaterThan(0)
  await expect(page.getByTestId('material-single')).toBeVisible()
})
