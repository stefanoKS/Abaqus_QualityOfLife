import type { Project } from '../../api'

export interface MeshElement {
  id: number
  type: string
  nodes: number[]
  entity: string
  component: string
}

export interface MeshFile {
  nodes: { id: number; xyz: number[] }[]
  elements: MeshElement[]
  edge_nodes: Record<string, number[]>
  face_elements: Record<string, number[]>
  counts: Record<string, number>
}

export interface MeshQuality {
  nodes: number
  elements: number
  byType: { type: string; count: number }[]
  regions: {
    id: string
    name: string
    count: number
    types: { type: string; count: number }[]
  }[]
  edgeSegments: { id: string; name: string; segments: number }[]
  /** One row per component: role, inclusion, element type and count. */
  components: {
    id: string
    name: string
    role: string
    included: boolean
    elementType: string
    count: number
    segments: number
  }[]
  shortestEdge: number
  longestEdge: number
  /** Longest polygon edge divided by the shortest one, within a single element. */
  worstEdgeRatio: number
  worstElement: number
}

const distance = (a: number[], b: number[]) => Math.hypot(a[0] - b[0], a[1] - b[1])

/**
 * Derives review metrics from the mesh that was actually written by the mesher.
 * Every value here is measured from returned node coordinates; nothing is a
 * synthetic quality score. Inverted/degenerate elements never reach this data
 * because `packages/engineering/mesh.py::_check_element` rejects them.
 */
export function meshQuality(mesh: MeshFile, project: Project): MeshQuality {
  const coord = new Map(mesh.nodes.map((node) => [node.id, node.xyz]))
  let shortest = Infinity
  let longest = 0
  let ratio = 0
  let worst = 0
  for (const element of mesh.elements) {
    const points = element.nodes.map((id) => coord.get(id)).filter(Boolean) as number[][]
    if (points.length < 2) continue
    let min = Infinity
    let max = 0
    for (let i = 0; i < points.length; i++) {
      const length = distance(points[i], points[(i + 1) % points.length])
      if (length < min) min = length
      if (length > max) max = length
    }
    if (!Number.isFinite(min) || min <= 0) continue
    shortest = Math.min(shortest, min)
    longest = Math.max(longest, max)
    const elementRatio = max / min
    if (elementRatio > ratio) {
      ratio = elementRatio
      worst = element.id
    }
  }
  const perComponent = new Map<string, { types: Set<string>; count: number }>()
  for (const element of mesh.elements) {
    const row = perComponent.get(element.component) ?? { types: new Set<string>(), count: 0 }
    row.types.add(element.type)
    row.count += 1
    perComponent.set(element.component, row)
  }
  const edgeIds = new Map(project.edges.map((edge) => [edge.id, edge.component]))
  const segmentsByComponent = new Map<string, number>()
  for (const [edgeId, list] of Object.entries(mesh.edge_nodes ?? {})) {
    const component = edgeIds.get(edgeId)
    if (!component) continue
    segmentsByComponent.set(component, (segmentsByComponent.get(component) ?? 0) + Math.max(0, list.length - 1))
  }
  const twoStep = project.analysis.mode === 'body_then_door'
  const components = project.components.map((component) => {
    const row = perComponent.get(component.id)
    // Door-only reviews the body profile but does not analyse it. In the
    // two-panel template the body is a meshed, participating rigid profile.
    const excluded = String(component.role) === 'vehicle_body' && !twoStep
    const types = row ? [...row.types] : []
    return {
      id: component.id,
      name: component.alias?.trim() || component.name,
      role: String(component.role),
      included: Boolean(row) && !excluded,
      elementType: types.join(' + '),
      count: row?.count ?? 0,
      segments: segmentsByComponent.get(component.id) ?? 0,
    }
  })
  const names = new Map(project.faces.map((face) => [face.id, face.name]))
  const edgeNames = new Map(project.edges.map((edge) => [edge.id, edge.name]))
  const regionTypes = new Map<string, Map<string, number>>()
  for (const element of mesh.elements) {
    const counts = regionTypes.get(element.entity) ?? new Map<string, number>()
    counts.set(element.type, (counts.get(element.type) ?? 0) + 1)
    regionTypes.set(element.entity, counts)
  }
  return {
    nodes: mesh.nodes.length,
    elements: mesh.elements.length,
    byType: Object.entries(mesh.counts).map(([type, count]) => ({ type, count })),
    regions: Object.entries(mesh.face_elements ?? {}).map(([id, list]) => ({
      id,
      name: names.get(id) ?? id,
      count: list.length,
      types: [...(regionTypes.get(id) ?? new Map())].map(([type, count]) => ({ type, count })),
    })),
    components,
    edgeSegments: Object.entries(mesh.edge_nodes ?? {}).map(([id, list]) => ({
      id,
      name: edgeNames.get(id) ?? id,
      segments: Math.max(0, list.length - 1),
    })),
    shortestEdge: Number.isFinite(shortest) ? shortest : 0,
    longestEdge: longest,
    worstEdgeRatio: ratio,
    worstElement: worst,
  }
}
