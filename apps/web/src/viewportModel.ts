// CAD IDs live on primitives. FE IDs are always paired with an instance name.
export type SelectionMode = 'component' | 'edge' | 'face' | 'element' | 'node'
export type Picked = {
  kind: SelectionMode
  id: string
  component?: string
  entity?: string
  instance?: string
  source?: string
  label?: number
  value?: number
}
export interface DisplayPrimitive {
  id: string
  entity: string
  component: string
  source?: string
  material?: string | null
  kind: 'edge' | 'face'
  points: number[][]
  cells: number[][]
}
export interface Display {
  primitives: DisplayPrimitive[]
  bounds: number[]
}
export interface ViewMesh {
  nodes: { id: number; xyz: number[] }[]
  elements: {
    id: number
    type: string
    nodes: number[]
    entity: string
    component: string
  }[]
}
export interface ResultInstance {
  name: string
  nodes: number[][]
  elements: {
    label: number
    type: string
    connectivity: number[]
    region?: string | null
  }[]
}
export interface ResultFrame {
  time: number
  displacements: Record<string, number[][]>
}
export interface ViewResults {
  instances: ResultInstance[]
  frame: ResultFrame | null
}
export interface ViewportProps {
  dimension: '2D' | '3D'
  display: Display | null
  mode: SelectionMode
  selection: Picked | null
  onSelect: (selection: Picked | null) => void
  colors?: Record<string, string>
  hidden?: string[]
  mesh?: ViewMesh | null
  results?: ViewResults | null
  deformed?: boolean
  resetKey?: number
  panelOffset?: number
  lengthUnit?: string
  /** Nodal displacement quantity used for contouring. */
  resultComponent?: 'magnitude' | 'U1' | 'U2' | 'U3'
  /** Localized legend heading supplied by the caller. */
  resultLabel?: string
}

export interface Surface {
  kind: 'face' | 'edge'
  points: number[][]
  cells: number[][]
  color: string
  meshEdges: boolean
  cad?: { entity: string; component: string; source?: string }
  instance?: string
  elements?: { id: number; entity?: string; component?: string }[]
  nodeIds?: number[]
  magnitudes?: (number | undefined)[]
  contour?: boolean
}
export interface Scene {
  surfaces: Surface[]
  range: number | null
}

function cadColor(
  entity: string,
  component: string,
  colors: Record<string, string>
): string {
  return (
    colors[entity] ??
    colors[entity.replace(/^(top-|side-)/, '')] ??
    colors[component] ??
    '#57aaa0'
  )
}

type SurfaceSource = {
  instance: string
  nodes: number[][]
  elements: {
    id: number
    type: string
    connectivity: number[]
    entity?: string
    component?: string
  }[]
  displacements?: number[][]
}

function instanceSurfaces(
  source: SurfaceSource,
  isResult: boolean,
  props: ViewportProps
): Surface[] {
  const displacement = new Map(
    source.displacements?.map((row) => [row[0], row.slice(1)])
  )
  const coords = new Map(source.nodes.map((row) => [row[0], row.slice(1)]))
  // Signed components are contoured by magnitude; the probe still reports the
  // signed value, so a reader never mistakes the ramp for a signed field.
  const component = props.resultComponent ?? 'magnitude'
  const axis = component === 'U1' ? 0 : component === 'U2' ? 1 : component === 'U3' ? 2 : -1
  const groups = new Map<
    string,
    { surface: Surface; indices: Map<number, number> }
  >()
  for (const element of source.elements) {
    if (
      props.hidden?.some(
        (id) => id === element.component || id === element.entity
      )
    )
      continue
    const line = element.type === 'R2D2'
    // The documented first results schema currently exposes 2D faces and rigid lines.
    // Volume connectivity must go through an exterior-face extractor before rendering.
    if (!line && !['CPS3', 'CPS4', 'CPS4R'].includes(element.type)) continue
    if (!element.connectivity.every((id) => coords.has(id))) continue
    const complete =
      isResult && element.connectivity.every((id) => displacement.has(id))
    const color =
      isResult && !complete
        ? '#a3a9ae'
        : line
          ? '#4c5963'
          : cadColor(
              element.entity ?? '',
              element.component ?? '',
              props.colors ?? {}
            )
    const key = [element.entity, element.component, line, complete, color].join(
      '|'
    )
    let group = groups.get(key)
    if (!group) {
      group = {
        indices: new Map(),
        surface: {
          kind: line ? 'edge' : 'face',
          points: [],
          cells: [],
          elements: [],
          nodeIds: [],
          magnitudes: [],
          contour: complete,
          instance: source.instance,
          color,
          meshEdges: !line && !isResult,
        },
      }
      groups.set(key, group)
    }
    const surface = group.surface
    const cell = element.connectivity.map((label) => {
      let index = group.indices.get(label)
      if (index === undefined) {
        index = surface.points.length
        group!.indices.set(label, index)
        const xyz = coords.get(label)!
        const u = displacement.get(label)
        surface.points.push(
          complete && props.deformed && u
            ? xyz.map((x, i) => x + (u[i] ?? 0))
            : xyz
        )
        surface.nodeIds!.push(label)
        surface.magnitudes!.push(
          u ? (axis < 0 ? Math.hypot(...u) : Math.abs(u[axis] ?? 0)) : undefined
        )
      }
      return index
    })
    // Keep polygons (including quads) and their FE labels together. The picker
    // tests triangle fans internally and maps each triangle back to its parent.
    surface.cells.push(cell)
    surface.elements!.push(element)
  }
  return [...groups.values()].map((group) => group.surface)
}

export function makeScene(props: ViewportProps): Scene {
  if (props.results) {
    const surfaces = props.results.instances.flatMap((instance) =>
      instanceSurfaces(
        {
          instance: instance.name,
          nodes: instance.nodes,
          elements: instance.elements.map((e) => ({
            id: e.label,
            type: e.type,
            connectivity: e.connectivity,
            entity: e.region ?? undefined,
          })),
          displacements: props.results!.frame?.displacements[instance.name],
        },
        true,
        props
      )
    )
    let range: number | null = null
    for (const surface of surfaces)
      if (surface.contour) {
        for (const value of surface.magnitudes ?? [])
          if (value !== undefined) range = Math.max(range ?? 0, value)
      }
    return { surfaces, range }
  }
  const surfaces: Surface[] = []
  if (props.mesh && props.dimension === '2D') {
    for (const rigid of [false, true]) {
      surfaces.push(
        ...instanceSurfaces(
          {
            instance: rigid ? 'PANEL-1' : 'WS-1',
            nodes: props.mesh.nodes.map((node) => [
              node.id,
              node.xyz[0],
              node.xyz[1] + (rigid ? (props.panelOffset ?? 0) : 0),
              node.xyz[2],
            ]),
            elements: props.mesh.elements
              .filter((e) => (e.type === 'R2D2') === rigid)
              .map((e) => ({ ...e, connectivity: e.nodes })),
          },
          false,
          props
        )
      )
    }
  }
  for (const p of props.display?.primitives ?? []) {
    if (props.hidden?.some((id) => id === p.component || id === p.entity))
      continue
    if (props.mesh && props.dimension === '2D' && p.kind === 'face') continue
    surfaces.push({
      ...p,
      cad: { entity: p.entity, component: p.component, source: p.source },
      color:
        p.kind === 'edge'
          ? '#354f55'
          : cadColor(p.source ?? p.entity, p.component, props.colors ?? {}),
      meshEdges: false,
    })
  }
  return { surfaces, range: null }
}

export const ramp = [
  [36, 72, 140],
  [41, 155, 176],
  [119, 207, 150],
  [249, 212, 99],
  [212, 76, 54],
]
export function colorAt(ratio: number): number[] {
  const x = Math.min(1, Math.max(0, ratio)) * (ramp.length - 1)
  const i = Math.min(ramp.length - 2, Math.floor(x))
  return ramp[i].map((v, k) => Math.round(v + (ramp[i + 1][k] - v) * (x - i)))
}
