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
  regions: { id: string; name: string; count: number }[]
  edgeSegments: { id: string; name: string; segments: number }[]
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
  const names = new Map(project.faces.map((face) => [face.id, face.name]))
  const edgeNames = new Map(project.edges.map((edge) => [edge.id, edge.name]))
  return {
    nodes: mesh.nodes.length,
    elements: mesh.elements.length,
    byType: Object.entries(mesh.counts).map(([type, count]) => ({ type, count })),
    regions: Object.entries(mesh.face_elements ?? {}).map(([id, list]) => ({
      id,
      name: names.get(id) ?? id,
      count: list.length,
    })),
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
