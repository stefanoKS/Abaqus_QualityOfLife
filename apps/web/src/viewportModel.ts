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
  /** Run-wide 6-value bounds recorded or derived from the result. */
  bounds?: number[] | null
  /** Legacy largest |displacement| estimate; used only when bounds is absent. */
  extent?: number
}
/**
 * One measured door-panel contact-pressure glyph. ``anchor`` is the rendered
 * deformed position in model millimetres; ``direction`` is the measured unit
 * CNORMF direction in the assembly frame; ``pressureKpa`` is signed.
 */
export interface PressureArrow {
  anchor: [number, number]
  direction: [number, number]
  pressureKpa: number
  station: number
  node: number
  /** Index in the station array, so a selection highlights the right glyph. */
  row?: number
}
export interface PressureArrows {
  profileId: string
  name: string
  arrows: PressureArrow[]
  /**
   * Screen-space calibration: the number of CSS pixels used for the run-wide
   * reference pressure. The renderer recomputes this from its own viewport on
   * resize; this value is the fallback and the value reported to tests.
   */
  pixelsPerKPa: number
  /** Run-wide raw reference pressure (unmultiplied) shown beside the key. */
  maximumKpa: number
  /** ``auto`` = fixed screen size; ``manual`` = model millimetres per 10 kPa. */
  mode: 'auto' | 'manual'
  /** Manual calibration: model length for 10 kPa (default 5 mm). */
  manualMmPer10Kpa: number
  origin?: [number, number] | null
  /** Unit direction of increasing station, drawn beside the origin marker. */
  directionHint?: [number, number] | null
  /** Station index under the pointer or selected on the graph. */
  selected?: number | null
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
  /**
   * Rigid profiles as separate assembled instances. The moving door is
   * ``PANEL-1`` and the moving body ``BODY-1``; each keeps its own initial
   * offset so one panel's placement never moves the other.
   */
  rigidInstances?: { component: string; instance: string; offset: number }[]
  lengthUnit?: string
  /** Nodal displacement quantity used for contouring. */
  resultComponent?: 'magnitude' | 'U1' | 'U2' | 'U3'
  /**
   * Per-instance element values for a cell-coloured field (stress). Each cell is
   * flat-coloured with one value and keeps one parent element identity.
   */
  elementValues?: Record<string, Record<number, number>>
  /**
   * Per-instance nodal values for a nodal scalar field such as |CNORMF|. The
   * geometry still follows the measured displacement; a node without a value
   * keeps the surface visibly unavailable instead of inventing a zero.
   */
  nodalValues?: Record<string, Record<number, number>>
  /** Door-panel pressure glyphs on the same displayed frame as the contour. */
  pressureArrows?: PressureArrows | null
  /** Lower bound of the colour scale; defaults to 0. */
  resultMin?: number
  /** Deformation multiplier; 1 is true scale. */
  deformationScale?: number
  /** Draw independent node markers on top of a result. */
  nodeMarkers?: boolean
  /** Show element edges without changing the cell colours. */
  showMeshEdges?: boolean
  /** Results canvas: solid white, no grid or decorative background. */
  plain?: boolean
  resultUnit?: string
  /** True when a measured value exceeds the display maximum. */
  resultSaturated?: boolean
  /** True when a measured value falls below a positive display minimum. */
  resultUnderflow?: boolean
  /**
   * Recorded colour maximum for this quantity. ``null`` means the quantity is
   * unavailable for this run and must not be painted with a fabricated zero;
   * ``undefined`` asks the viewport to derive a bounded fallback.
   */
  resultRange?: number | null
  /** Localized legend heading supplied by the caller. */
  resultLabel?: string
  /**
   * Optional material perimeters and internal interfaces. A display preference
   * only: it never changes the field, ranges, probes, camera or artifacts.
   */
  materialOutlines?: boolean
  /**
   * Face-id to effective material identity, taken from the job's immutable
   * submitted revision. Legacy results without region data simply draw nothing.
   */
  faceMaterials?: Record<string, MaterialFaceAssignment>
  /** Rectangular node selection is armed (fixed-node fixture review). */
  boxSelect?: boolean
  /** How a completed rectangle combines with the current fixture. */
  boxOperation?: 'replace' | 'add' | 'subtract'
  /** Instance-qualified labels drawn as a persistent fixture highlight. */
  selectedNodes?: string[]
  /** Instances whose nodes may be box-selected; others are ignored. */
  nodeInstances?: string[]
  /** Receives the instance-qualified labels inside the drawn rectangle. */
  onBoxSelect?: (labels: string[]) => void
  /** Proposed partition line in model XY, drawn as an overlay only. */
  guide?: number[][] | null
  /**
   * Interactive section cut. The boundary is the selected face's eligible
   * exterior polyline in model XY; points are always snapped onto it before
   * they reach the server, which keeps its own 0.05 mm engineering tolerance.
   */
  cut?: ViewportCut | null
  onCutPoint?: (point: [number, number]) => void
  onCutHover?: (point: [number, number] | null) => void
  onCutCancel?: () => void
  /**
   * Display-only translation of one component, keyed by component id, in model
   * millimetres. Used by the prescribed-motion preview; it never mutates setup,
   * saved geometry, results or a queued job.
   */
  previewTranslation?: Record<string, [number, number]>
}

export type ViewportCut = {
  active: boolean
  /** Historical boundary guide; empty for the projected draw-anywhere tool. */
  boundary: number[][]
  start?: [number, number] | null
  end?: [number, number] | null
  phase?: 'start' | 'end' | 'previewed'
  invalid?: boolean
  /** Raw model-space candidate under the pointer. */
  hover?: [number, number] | null
  /** Completed pending guides, drawn as a live ghost. */
  strokes?: { a: [number, number]; b: [number, number] }[]
  /**
   * Material intervals the server selected for the pending guides. These are
   * drawn solid; the untouched part of a stroke stays dashed.
   */
  segments?: { a: [number, number]; b: [number, number] }[]
  /** Authoritative preview status, shown by the overlay. */
  status?: string | null
}

export interface Surface {
  /** Stable identity of this surface across frames, used to reuse the actor. */
  key?: string
  kind: 'face' | 'edge' | 'points'
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
  /** Line width in pixels for edge overlays (material interfaces read thicker). */
  width?: number
  /** Both effective material identities of a drawn interface, when known. */
  materials?: string[]
  /** Which display overlay produced this surface; never a pick target. */
  overlay?: 'material-perimeter' | 'material-interface'
}
export interface Scene {
  surfaces: Surface[]
  range: number | null
  /** Lower bound of the colour scale. */
  min?: number
  /** Bounds covering the whole run, so the camera is fitted once. */
  extent?: number[] | null
}

/**
 * Effective material identity for one CAD region of the job's pinned revision.
 *
 * ``key`` is the pinned card identity. Two distinct CAD face IDs that point at
 * the same card (or the same pinned library version) therefore share a key and
 * never create a false material interface.
 */
export interface MaterialFaceAssignment {
  key: string
  name: string
  color: string
  /** Library version when the card is pinned to the global library. */
  version?: number | null
}

export interface MaterialInterface {
  instance: string
  a: number
  b: number
  /** The two distinct effective material keys sharing this FE edge. */
  materials: string[]
}

export interface MaterialPerimeter {
  instance: string
  a: number
  b: number
  material: string
}

/**
 * Independent FE-edge classification for one result.
 *
 * Built once from each deformable instance's original element connectivity and
 * local node labels (never from renderer vertices), so an element-based stress
 * display with duplicated corner vertices cannot change the topology.
 */
export interface MaterialTopology {
  perimeters: MaterialPerimeter[]
  interfaces: MaterialInterface[]
  /** Deformable continuum elements considered. */
  total: number
  /** Elements whose CAD region maps to a known pinned material. */
  mapped: number
  /** Effective material keys present, in first-seen order. */
  materials: string[]
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
  const scale = props.deformationScale ?? 1
  const cellValues = isResult ? props.elementValues : undefined
  const nodalValues = isResult ? props.nodalValues : undefined
  const nodal = nodalValues ? nodalValues[source.instance] : undefined
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
    const cellValue = cellValues
      ? cellValues[source.instance]?.[element.id]
      : undefined
    const complete = nodalValues
      ? element.connectivity.every((id) => nodal?.[id] !== undefined)
      : cellValues
        ? cellValue !== undefined
        : isResult && element.connectivity.every((id) => displacement.has(id))
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
    const key = [
      element.entity,
      element.component,
      line,
      complete,
      color,
      cellValues ? 'cell' : 'node',
    ].join('|')
    let group = groups.get(key)
    if (!group) {
      group = {
        indices: new Map(),
        surface: {
          // Stable while the element set and its rendering class are unchanged.
          key: [source.instance, key].join('#'),
          kind: line ? 'edge' : 'face',
          points: [],
          cells: [],
          elements: [],
          nodeIds: [],
          magnitudes: [],
          contour: complete,
          instance: source.instance,
          color,
          meshEdges: !line && (isResult ? !!props.showMeshEdges : true),
        },
      }
      groups.set(key, group)
    }
    const surface = group.surface
    const cell = element.connectivity.map((label) => {
      if (cellValues) {
        // A stress cell is flat: every corner carries the same value and the
        // points are private to this element, so a shared mesh node cannot
        // blend two different element values.
        const index = surface.points.length
        const xyz = coords.get(label)!
        const u = displacement.get(label)
        // Geometry is decided only by this frame's measured nodal displacement.
        // Scalar (stress) availability decides colour alone: a rigid line has no
        // integration-point stress yet still moves with its reference motion.
        surface.points.push(
          props.deformed && u
            ? xyz.map((x, i) => x + (u[i] ?? 0) * scale)
            : xyz
        )
        surface.nodeIds!.push(label)
        surface.magnitudes!.push(complete ? cellValue : undefined)
        return index
      }
      let index = group.indices.get(label)
      if (index === undefined) {
        index = surface.points.length
        group!.indices.set(label, index)
        const xyz = coords.get(label)!
        const u = displacement.get(label)
        // A node without a measured U stays at its base position; the missing
        // measurement is identified by the un-contoured surface and the probe.
        surface.points.push(
          props.deformed && u
            ? xyz.map((x, i) => x + (u[i] ?? 0) * scale)
            : xyz
        )
        surface.nodeIds!.push(label)
        const value = u ? (axis < 0 ? Math.hypot(...u) : u[axis]) : undefined
        // A contact-force contour follows the nodal CNORMF magnitude while the
        // geometry continues to use this frame's measured U.
        const nodalValue = nodal?.[label]
        surface.magnitudes!.push(
          nodalValues
            ? nodalValue === undefined
              ? undefined
              : Math.abs(nodalValue)
            : value === undefined
              ? undefined
              : Math.abs(value)
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


/**
 * Continuum element types that participate in material assignment. Rigid panel
 * lines (R2D2) reuse local node labels in their own assembly instance and are
 * excluded, so a rigid instance can never fabricate an interface.
 */
const DEFORMABLE = new Set(['CPS3', 'CPS4', 'CPS4R'])

const topologyCache = new WeakMap<object, WeakMap<object, MaterialTopology>>()

function buildMaterialTopology(
  instances: ResultInstance[],
  faceMaterials: Record<string, MaterialFaceAssignment>,
): MaterialTopology {
  type Edge = { instance: string; a: number; b: number; materials: Set<string>; count: number }
  const edges = new Map<string, Edge>()
  const order: string[] = []
  const seen = new Set<string>()
  let total = 0
  let mapped = 0
  for (const instance of instances) {
    for (const element of instance.elements) {
      if (!DEFORMABLE.has(element.type)) continue
      total += 1
      const assignment = element.region ? faceMaterials[element.region] : undefined
      if (!assignment) continue
      mapped += 1
      if (!seen.has(assignment.key)) {
        seen.add(assignment.key)
        order.push(assignment.key)
      }
      const ring = element.connectivity
      for (let i = 0; i < ring.length; i++) {
        const one = ring[i]
        const two = ring[(i + 1) % ring.length]
        if (one === two) continue
        const a = Math.min(one, two)
        const b = Math.max(one, two)
        const id = instance.name + '|' + a + '|' + b
        let edge = edges.get(id)
        if (!edge) {
          edge = { instance: instance.name, a, b, materials: new Set(), count: 0 }
          edges.set(id, edge)
        }
        edge.count += 1
        edge.materials.add(assignment.key)
      }
    }
  }
  const perimeters: MaterialPerimeter[] = []
  const interfaces: MaterialInterface[] = []
  for (const edge of edges.values()) {
    if (edge.count === 1 && edge.materials.size === 1) {
      perimeters.push({
        instance: edge.instance,
        a: edge.a,
        b: edge.b,
        material: [...edge.materials][0],
      })
    } else if (edge.count === 2 && edge.materials.size === 2) {
      // Exactly one interior FE edge shared by two differently assigned
      // materials. Same-material regional seams keep size 1 and are skipped;
      // an edge with an unknown neighbour is not guessed.
      interfaces.push({
        instance: edge.instance,
        a: edge.a,
        b: edge.b,
        materials: [...edge.materials].sort(),
      })
    }
  }
  return { perimeters, interfaces, total, mapped, materials: order }
}

/** Cached per result instance list and pinned material map. */
export function materialTopology(
  instances: ResultInstance[] | undefined,
  faceMaterials: Record<string, MaterialFaceAssignment> | undefined,
): MaterialTopology {
  const empty: MaterialTopology = {
    perimeters: [],
    interfaces: [],
    total: 0,
    mapped: 0,
    materials: [],
  }
  if (!instances?.length || !faceMaterials) return empty
  let byMaterials = topologyCache.get(instances)
  if (!byMaterials) {
    byMaterials = new WeakMap()
    topologyCache.set(instances, byMaterials)
  }
  const cached = byMaterials.get(faceMaterials)
  if (cached) return cached
  const built = buildMaterialTopology(instances, faceMaterials)
  byMaterials.set(faceMaterials, built)
  return built
}

function outlineSurface(
  instance: ResultInstance,
  pairs: { a: number; b: number }[],
  color: string,
  key: string,
  props: ViewportProps,
  extra: Pick<Surface, 'overlay' | 'materials' | 'width'>,
): Surface | null {
  if (!pairs.length) return null
  const displacement = new Map(
    (props.results?.frame?.displacements[instance.name] ?? []).map((row) => [
      row[0],
      row.slice(1),
    ]),
  )
  const coords = new Map(instance.nodes.map((row) => [row[0], row.slice(1)]))
  const deformed = !!props.deformed
  const scale = props.deformationScale ?? 1
  const index = new Map<number, number>()
  const points: number[][] = []
  const cells: number[][] = []
  const add = (label: number) => {
    const existing = index.get(label)
    if (existing !== undefined) return existing
    const xyz = coords.get(label)
    if (!xyz) return -1
    const u = displacement.get(label)
    const position = deformed && u ? xyz.map((x, i) => x + (u[i] ?? 0) * scale) : xyz
    const next = points.length
    points.push(position)
    index.set(label, next)
    return next
  }
  for (const pair of pairs) {
    const a = add(pair.a)
    const b = add(pair.b)
    if (a >= 0 && b >= 0) cells.push([a, b])
  }
  if (!cells.length) return null
  return {
    key,
    kind: 'edge',
    points,
    cells,
    color,
    meshEdges: false,
    instance: instance.name,
    contour: false,
    ...extra,
  }
}

/**
 * Material perimeters (material-specific colour) and internal interfaces (one
 * thicker neutral line, associated with both materials).
 *
 * Coordinates use the exact displayed frame: the same nodal displacements, the
 * Deformed toggle and the deformation scale as the drawn surface. The overlays
 * are separate line surfaces, so they are not pick or probe targets and their
 * actors are reused while the topology is unchanged.
 */
export function materialOutlineSurfaces(props: ViewportProps): Surface[] {
  if (!props.materialOutlines || !props.results) return []
  const topology = materialTopology(props.results.instances, props.faceMaterials)
  if (!topology.mapped) return []
  const instances = new Map(props.results.instances.map((row) => [row.name, row]))
  const surfaces: Surface[] = []
  const byMaterial = new Map<string, { instance: string; pairs: { a: number; b: number }[] }[]>()
  for (const perimeter of topology.perimeters) {
    const key = perimeter.instance + '|' + perimeter.material
    let group = byMaterial.get(key)
    if (!group) {
      group = []
      byMaterial.set(key, group)
    }
    let bucket = group.find((entry) => entry.instance === perimeter.instance)
    if (!bucket) {
      bucket = { instance: perimeter.instance, pairs: [] }
      group.push(bucket)
    }
    bucket.pairs.push({ a: perimeter.a, b: perimeter.b })
  }
  for (const [key, buckets] of byMaterial) {
    const color = props.faceMaterials ? colorOf(key, props.faceMaterials) : '#12262c'
    for (const bucket of buckets) {
      const instance = instances.get(bucket.instance)
      if (!instance) continue
      const surface = outlineSurface(
        instance,
        bucket.pairs,
        color,
        [bucket.instance, 'material-perimeter', key].join('#'),
        props,
        { overlay: 'material-perimeter', materials: [key], width: 2.5 },
      )
      if (surface) surfaces.push(surface)
    }
  }
  const byInstance = new Map<string, MaterialInterface[]>()
  for (const item of topology.interfaces) {
    const list = byInstance.get(item.instance) ?? []
    list.push(item)
    byInstance.set(item.instance, list)
  }
  for (const [name, list] of byInstance) {
    const instance = instances.get(name)
    if (!instance) continue
    const surface = outlineSurface(
      instance,
      list.map((item) => ({ a: item.a, b: item.b })),
      '#102b33',
      name + '#material-interface',
      props,
      {
        overlay: 'material-interface',
        materials: [...new Set(list.flatMap((item) => item.materials))],
        width: 3.2,
      },
    )
    if (surface) surfaces.push(surface)
  }
  return surfaces
}

function colorOf(
  key: string,
  faceMaterials: Record<string, MaterialFaceAssignment>,
): string {
  const entry = Object.values(faceMaterials).find((row) => row.key === key)
  return entry?.color ?? '#12262c'
}

/**
 * Bounds that cover the whole run, so fitting once cannot clip later frames.
 * The recorded display metadata is authoritative; the legacy estimate only
 * applies to a retained result that predates it.
 */
function runExtent(props: ViewportProps): number[] | null {
  const recorded = props.results?.bounds
  if (
    Array.isArray(recorded) &&
    recorded.length === 6 &&
    recorded.every((value) => Number.isFinite(value))
  )
    return recorded
  const instances = props.results?.instances
  if (!instances?.length) return null
  const motion = Math.max(0, Number(props.results?.extent ?? 0))
  const ext = [Infinity, -Infinity, Infinity, -Infinity, Infinity, -Infinity]
  for (const instance of instances)
    for (const row of instance.nodes) {
      for (let i = 0; i < 3; i++) {
        ext[2 * i] = Math.min(ext[2 * i], row[i + 1] - motion)
        ext[2 * i + 1] = Math.max(ext[2 * i + 1], row[i + 1] + motion)
      }
    }
  return ext
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
    // Stable per-instance topology identity is assigned while the surface is
    // grouped; an actor is reused only when that identity and its cells match.
    const unavailable = props.resultRange === null
    if (unavailable)
      for (const surface of surfaces) {
        surface.contour = false
        surface.color = '#a3a9ae'
        surface.magnitudes = surface.magnitudes?.map(() => undefined)
      }
    let range: number | null = null
    if (typeof props.resultRange === 'number') range = props.resultRange
    else
      for (const surface of surfaces)
        if (surface.contour) {
          for (const value of surface.magnitudes ?? [])
            if (value !== undefined) range = Math.max(range ?? 0, value)
        }
    if (props.nodeMarkers) {
      // Node markers are an independent overlay: element mode ignores them and
      // node probing still resolves the original instance-qualified label.
      const scale = props.deformationScale ?? 1
      for (const instance of props.results.instances) {
        const displacement = new Map(
          (props.results.frame?.displacements[instance.name] ?? []).map((row) => [
            row[0],
            row.slice(1),
          ])
        )
        const points = instance.nodes.map((node) => {
          const u = displacement.get(node[0])
          return props.deformed && u
            ? [node[1] + (u[0] ?? 0) * scale, node[2] + (u[1] ?? 0) * scale, node[3] + (u[2] ?? 0) * scale]
            : [node[1], node[2], node[3]]
        })
        surfaces.push({
          key: instance.name + '#nodes',
          kind: 'points',
          points,
          cells: points.map((_, index) => [index]),
          color: '#24343b',
          meshEdges: false,
          instance: instance.name,
          nodeIds: instance.nodes.map((node) => node[0]),
          magnitudes: [],
          contour: false,
        })
      }
    }
    // Material overlays are appended after the field surfaces: they are a
    // separate display layer, independent of mesh edges, node markers and the
    // selected field, and they never become probe or pick targets.
    surfaces.push(...materialOutlineSurfaces(props))
    return {
      surfaces,
      range,
      min: props.resultMin ?? 0,
      extent: runExtent(props),
    }
  }
  const surfaces: Surface[] = []
  if (props.mesh && props.dimension === '2D') {
    // Mesh surfaces are grouped by assembled instance. Continuum elements stay
    // on WS-1; every rigid profile is drawn on its own instance with its own
    // initial offset, so a bottom-mounted body is not shifted with the door.
    const groups = new Map<
      string,
      { instance: string; offset: number; elements: ViewMesh['elements'] }
    >()
    const rigidByComponent = new Map(
      (props.rigidInstances ?? []).map((row) => [row.component, row])
    )
    for (const element of props.mesh.elements) {
      let instance = 'WS-1'
      let offset = 0
      if (element.type === 'R2D2') {
        const rigid = rigidByComponent.get(element.component)
        instance = rigid?.instance ?? 'PANEL-1'
        offset = rigid?.offset ?? (props.panelOffset ?? 0)
      }
      let group = groups.get(instance)
      if (!group) {
        group = { instance, offset, elements: [] }
        groups.set(instance, group)
      }
      group.elements.push(element)
    }
    const order = ['WS-1', 'PANEL-1', 'BODY-1']
    const rank = (name: string) => {
      const index = order.indexOf(name)
      return index < 0 ? order.length : index
    }
    for (const name of [...groups.keys()].sort(
      (a, b) => rank(a) - rank(b) || a.localeCompare(b)
    )) {
      const group = groups.get(name)!
      const preview = props.previewTranslation?.[group.elements[0]?.component ?? ''] ?? [0, 0]
      surfaces.push(
        ...instanceSurfaces(
          {
            instance: group.instance,
            nodes: props.mesh.nodes.map((node) => [
              node.id,
              node.xyz[0] + preview[0],
              node.xyz[1] + group.offset + preview[1],
              node.xyz[2],
            ]),
            elements: group.elements.map((e) => ({ ...e, connectivity: e.nodes })),
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
    const preview = props.previewTranslation?.[p.component] ?? [0, 0]
    surfaces.push({
      ...p,
      points:
        preview[0] || preview[1]
          ? p.points.map((point) => [point[0] + preview[0], point[1] + preview[1], point[2]])
          : p.points,
      // CAD identity is the drawing entity, not its array position.
      key: ['cad', p.kind, p.id, p.source ?? '', p.component].join('|'),
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

/**
 * One saturated blue–cyan–green–yellow–red display ramp shared by the VTK
 * scalar colours, actor updates and the legend. Chart axes, engineering values
 * and material colours are deliberately independent of this palette.
 */
export const ramp = [
  [23, 69, 230], // #1745E6
  [0, 185, 242], // #00B9F2
  [8, 184, 79], // #08B84F
  [255, 212, 0], // #FFD400
  [227, 38, 33], // #E32621
]
export function colorAt(ratio: number): number[] {
  const x = Math.min(1, Math.max(0, ratio)) * (ramp.length - 1)
  const i = Math.min(ramp.length - 2, Math.floor(x))
  return ramp[i].map((v, k) => Math.round(v + (ramp[i + 1][k] - v) * (x - i)))
}
