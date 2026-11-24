import '@kitware/vtk.js/Rendering/OpenGL/Profiles/Geometry'
import vtkRenderer from '@kitware/vtk.js/Rendering/Core/Renderer'
import vtkRenderWindow from '@kitware/vtk.js/Rendering/Core/RenderWindow'
import vtkOpenGLRenderWindow from '@kitware/vtk.js/Rendering/OpenGL/RenderWindow'
import vtkActor from '@kitware/vtk.js/Rendering/Core/Actor'
import vtkMapper from '@kitware/vtk.js/Rendering/Core/Mapper'
import vtkPolyData from '@kitware/vtk.js/Common/DataModel/PolyData'
import vtkDataArray from '@kitware/vtk.js/Common/Core/DataArray'
import { colorAt, type Picked, type Scene, type Surface, type ViewportCut } from './viewportModel'
import {
  outline,
  pickAt,
  type Projected,
  type ScreenPoint,
} from './viewportPicking'
import type { SelectionMode } from './viewportModel'

type Bounds = [number, number, number, number, number, number]
const identityBounds: Bounds = [-1, 1, -1, 1, -1, 1]
function extent(scene: Scene): Bounds {
  const box: Bounds = [
    Infinity,
    -Infinity,
    Infinity,
    -Infinity,
    Infinity,
    -Infinity,
  ]
  for (const surface of scene.surfaces)
    for (const point of surface.points) {
      for (let j = 0; j < 3; j++) {
        box[j * 2] = Math.min(box[j * 2], point[j])
        box[j * 2 + 1] = Math.max(box[j * 2 + 1], point[j])
      }
    }
  return Number.isFinite(box[0]) ? box : identityBounds
}

/** Reuse is only safe when the primitive, its cells and its rendering class match. */
function sameTopology(a: Surface, b: Surface) {
  return (
    a.kind === b.kind &&
    a.contour === b.contour &&
    a.meshEdges === b.meshEdges &&
    a.points.length === b.points.length &&
    a.cells.length === b.cells.length &&
    a.cells.every((cell, index) => {
      const other = b.cells[index]
      return cell.length === other.length && cell.every((value, i) => value === other[i])
    })
  )
}

function makeActor(
  surface: Surface,
  range: number | null,
  shade: boolean,
  minimum = 0
) {
  const data = vtkPolyData.newInstance()
  data.getPoints().setData(new Float32Array(surface.points.flat()), 3)
  const connectivity = Uint32Array.from(
    surface.cells.flatMap((cell) => [cell.length, ...cell])
  )
  if (surface.kind === 'edge') data.getLines().setData(connectivity)
  else if (surface.kind === 'points') data.getVerts().setData(connectivity)
  else data.getPolys().setData(connectivity)
  const mapper = vtkMapper.newInstance()
  const ratio = (value: number) =>
    range === null || range <= minimum
      ? 0
      : (value - minimum) / (range - minimum)
  if (surface.contour) {
    const values = Uint8Array.from(
      surface.magnitudes!.flatMap((v) => colorAt(ratio(v ?? 0)))
    )
    data
      .getPointData()
      .setScalars(
        vtkDataArray.newInstance({
          name: 'Field value',
          numberOfComponents: 3,
          values,
        })
      )
    mapper.setColorModeToDirectScalars()
  } else mapper.setScalarVisibility(false)
  mapper.setInputData(data)
  const actor = vtkActor.newInstance()
  actor.setMapper(mapper)
  const hex = /^#[a-f0-9]{6}$/i.test(surface.color) ? surface.color : '#62a7a1'
  const color = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
  const property = actor.getProperty()
  property.setColor(color[0], color[1], color[2])
  property.setLighting(shade && surface.kind === 'face')
  property.setAmbient(0.4)
  property.setDiffuse(0.6)
  property.setEdgeVisibility(surface.meshEdges)
  property.setEdgeColor(0.19, 0.28, 0.3)
  property.setLineWidth(surface.kind === 'edge' ? 2 : 1)
  if (surface.kind === 'points') {
    property.setRepresentationToPoints()
    property.setPointSize(5)
  }
  const item = {
    key: surface.key ?? '',
    surface,
    actor,
    data,
    mapper,
    update: (next: Surface, range: number | null, minimum = 0) => {
      item.surface = next
      // Same topology: swap coordinates in place and refresh the colours.
      const points = data.getPoints()
      const existing = points.getData() as (Float32Array & { delete?: () => void }) | undefined
      const flat = new Float32Array(next.points.flat())
      if (existing && typeof existing.set === 'function' && existing.length === flat.length) {
        existing.set(flat)
        points.setData(existing, 3)
      } else {
        existing?.delete?.()
        points.setData(flat, 3)
      }
      const nextHex = /^#[a-f0-9]{6}$/i.test(next.color) ? next.color : '#62a7a1'
      property.setColor(
        parseInt(nextHex.slice(1, 3), 16) / 255,
        parseInt(nextHex.slice(3, 5), 16) / 255,
        parseInt(nextHex.slice(5, 7), 16) / 255
      )
      const ratio = (value: number) =>
        range === null || range <= minimum
          ? 0
          : (value - minimum) / (range - minimum)
      if (next.contour && next.magnitudes) {
        const values = Uint8Array.from(
          next.magnitudes.flatMap((v) => colorAt(ratio(v ?? 0)))
        )
        const scalars = data.getPointData().getScalars()
        if (scalars && scalars.getNumberOfTuples() === next.magnitudes.length) {
          scalars.setData(values, 3)
        } else {
          scalars?.delete()
          data
            .getPointData()
            .setScalars(
              vtkDataArray.newInstance({
                name: 'Field value',
                numberOfComponents: 3,
                values,
              })
            )
        }
        mapper.setColorModeToDirectScalars()
      } else {
        mapper.setScalarVisibility(false)
      }
      data.modified()
      points.modified()
      actor.modified()
    },
    delete: () => {
      data.getPointData().getScalars()?.delete()
      data.getPoints().delete()
      data.getPolys().delete()
      data.getLines().delete()
      data.getVerts().delete()
      actor.getProperty().delete()
      actor.delete()
      mapper.delete()
      data.delete()
    },
  }
  return item
}

/** Owns the GL context, render objects, screen projection and camera. */
export class ViewportRenderer {
  private renderer = vtkRenderer.newInstance()
  private window = vtkRenderWindow.newInstance()
  private view = vtkOpenGLRenderWindow.newInstance()
  private actors: ReturnType<typeof makeActor>[] = []
  private scene: Scene = { surfaces: [], range: null }
  private bounds: Bounds = identityBounds
  private projected: Projected[] = []
  private selected: Picked | null = null
  private hovered: Picked | null = null
  private fixture: Set<string> = new Set()
  private box: { x0: number; y0: number; x1: number; y1: number } | null = null
  private guide: number[][] = []
  private cut: ViewportCut | null = null
  private originPoint: ScreenPoint = [0, 0, 0]
  private dimension: '2D' | '3D' = '2D'
  private ctx: CanvasRenderingContext2D
  private width = 1
  private height = 1
  private ratio = 1
  private axes: ScreenPoint[] = []
  lengthUnit = 'mm'
  /** Results viewport: solid white background, no section grid. */
  plain = false
  private started = false
  constructor(
    private host: HTMLElement,
    private overlay: HTMLCanvasElement
  ) {
    this.renderer.setBackground(0, 0, 0, 0)
    this.window.addRenderer(this.renderer)
    this.window.addView(this.view)
    this.view.setContainer(host)
    this.renderer.getActiveCamera().setParallelProjection(true)
    this.ctx = overlay.getContext('2d')!
  }
  setScene(scene: Scene, dimension: '2D' | '3D', fit: boolean) {
    // A frame change keeps the same topology: reuse each actor and only push new
    // coordinates and colours into it. An actor with no key, or with different
    // cells, is replaced instead of having new coordinates written against old
    // connectivity.
    const reusable = new Map<string, ReturnType<typeof makeActor>>()
    for (const item of this.actors) if (item.key) reusable.set(item.key, item)
    const next: ReturnType<typeof makeActor>[] = []
    for (const surface of scene.surfaces) {
      const existing = surface.key ? reusable.get(surface.key) : undefined
      if (existing && sameTopology(existing.surface, surface)) {
        reusable.delete(surface.key!)
        existing.update(surface, scene.range, scene.min ?? 0)
        next.push(existing)
        continue
      }
      if (existing) {
        // The key is the same but the primitive changed: the old actor cannot
        // carry the new connectivity, so it is disposed exactly once here.
        reusable.delete(surface.key!)
        this.renderer.removeActor(existing.actor)
        existing.delete()
      }
      const created = makeActor(surface, scene.range, dimension === '3D', scene.min ?? 0)
      this.renderer.addActor(created.actor)
      next.push(created)
    }
    for (const stale of reusable.values()) {
      this.renderer.removeActor(stale.actor)
      stale.delete()
    }
    this.actors = next
    this.scene = scene
    this.dimension = dimension
    // Observable actor count for regression tests: a leaked or collided actor
    // shows up here before it can be seen as a wrong pick.
    this.host.dataset.actors = String(next.length)
    const recorded = scene.extent
    this.bounds =
      Array.isArray(recorded) &&
      recorded.length === 6 &&
      recorded.every((value) => Number.isFinite(value))
        ? (recorded as Bounds)
        : extent(scene)
    this.hovered = null
    if (fit || !this.started) this.fit()
    else {
      this.renderer.resetCameraClippingRange(this.bounds)
      this.draw()
    }
    if (scene.surfaces.length) this.started = true
  }
  private clear() {
    for (const item of this.actors) {
      this.renderer.removeActor(item.actor)
      item.delete()
    }
    this.actors = []
  }
  fit() {
    const b = this.bounds,
      cam = this.renderer.getActiveCamera()
    const x = (b[0] + b[1]) / 2,
      y = (b[2] + b[3]) / 2,
      z = (b[4] + b[5]) / 2
    const span = Math.max(b[1] - b[0], b[3] - b[2], b[5] - b[4], 0.001)
    cam.setFocalPoint(x, y, z)
    if (this.dimension === '3D')
      cam.setPosition(x + span * 1.3, y + span * 0.9, z + span * 1.7)
    else cam.setPosition(x, y, z + span * 2)
    cam.setViewUp(0, 1, 0)
    cam.orthogonalizeViewUp()
    this.renderer.resetCamera(b)
    if (this.dimension === '2D')
      cam.setParallelScale(
        0.6 *
          Math.max(
            b[3] - b[2],
            ((b[1] - b[0]) * this.height) / this.width,
            0.001
          )
      )
    this.renderer.resetCameraClippingRange(b)
    this.draw()
  }
  resize() {
    const rect = this.host.getBoundingClientRect()
    if (!rect.width || !rect.height) return
    const px = window.devicePixelRatio || 1
    const first = this.width === 1
    this.width = rect.width
    this.height = rect.height
    this.ratio = px
    this.overlay.width = Math.round(rect.width * px)
    this.overlay.height = Math.round(rect.height * px)
    this.view.setSize(this.overlay.width, this.overlay.height)
    if (first && this.started) this.fit()
    else this.draw()
  }
  drag(dx: number, dy: number, pan: boolean) {
    const cam = this.renderer.getActiveCamera()
    if (this.dimension === '3D' && !pan) {
      cam.azimuth(-dx * 0.45)
      cam.elevation(dy * 0.45)
      cam.orthogonalizeViewUp()
      this.renderer.resetCameraClippingRange(this.bounds)
    } else {
      const p = cam.getPosition(),
        f = cam.getFocalPoint()
      const depth = this.view.worldToDisplay(f[0], f[1], f[2], this.renderer)[2]
      const a = this.view.displayToWorld(0, 0, depth, this.renderer)
      const b = this.view.displayToWorld(
        dx * this.ratio,
        -dy * this.ratio,
        depth,
        this.renderer
      )
      const tx = a[0] - b[0],
        ty = a[1] - b[1],
        tz = a[2] - b[2]
      cam.setPosition(p[0] + tx, p[1] + ty, p[2] + tz)
      cam.setFocalPoint(f[0] + tx, f[1] + ty, f[2] + tz)
    }
    this.draw()
  }
  /** Stable camera fingerprint for interaction tests and diagnostics. */
  cameraSignature() {
    const cam = this.renderer.getActiveCamera()
    const position = cam.getPosition()
    const focal = cam.getFocalPoint()
    return [...position, ...focal, cam.getParallelScale()]
      .map((value) => Number(value).toFixed(5))
      .join(',')
  }
  zoom(factor: number) {
    const cam = this.renderer.getActiveCamera()
    const b = this.bounds,
      span = Math.max(b[1] - b[0], b[3] - b[2], b[5] - b[4], 0.001)
    cam.setParallelScale(
      Math.min(
        span * 1000,
        Math.max(span * 1e-4, cam.getParallelScale() * factor)
      )
    )
    this.draw()
  }
  private draw() {
    this.window.render()
    // Both engineering views use an orthographic camera, so the world-to-screen
    // transform is affine. Project four basis points per camera update.
    const project = (x: number, y: number, z: number): ScreenPoint => {
      const p = this.view.worldToDisplay(x, y, z, this.renderer)
      return [p[0] / this.ratio, this.height - p[1] / this.ratio, p[2]]
    }
    const origin = project(0, 0, 0)
    this.originPoint = origin
    this.axes = [project(1, 0, 0), project(0, 1, 0), project(0, 0, 1)].map(
      (p) => [p[0] - origin[0], p[1] - origin[1], p[2] - origin[2]]
    )
    // One white drawing field for the workspace, mesh preview and results. The
    // former section grid is gone: a white base must read consistently under the
    // transparent GL canvas and in screenshots.
    this.host.style.backgroundImage = 'none'
    this.host.style.backgroundColor = '#FFFFFF'
    this.projected = this.scene.surfaces.map((surface) => ({
      surface,
      points: surface.points.map((p) => {
        const q: ScreenPoint = [...origin]
        for (let axis = 0; axis < 3; axis++)
          for (let k = 0; k < 3; k++) q[k] += this.axes[axis][k] * p[axis]
        return q
      }),
    }))
    this.drawOverlay()
  }
  pick(mode: SelectionMode, x: number, y: number) {
    return pickAt(this.projected, mode, x, y)
  }
  /** Instance-qualified labels whose projected node lies inside the rectangle. */
  nodesInBox(x0: number, y0: number, x1: number, y1: number, instances?: string[]) {
    const left = Math.min(x0, x1),
      right = Math.max(x0, x1),
      top = Math.min(y0, y1),
      bottom = Math.max(y0, y1)
    const found = new Set<string>()
    for (const { surface, points } of this.projected) {
      if (!surface.nodeIds || !surface.instance) continue
      if (instances && !instances.includes(surface.instance)) continue
      for (let i = 0; i < points.length; i++) {
        const p = points[i]
        if (p[0] >= left && p[0] <= right && p[1] >= top && p[1] <= bottom)
          found.add(surface.instance + ':' + surface.nodeIds[i])
      }
    }
    return [...found]
  }
  setSelection(labels: string[]) {
    this.fixture = new Set(labels)
    this.drawOverlay()
  }
  setBox(rect: { x0: number; y0: number; x1: number; y1: number } | null) {
    this.box = rect
    this.drawOverlay()
  }
  setGuide(points: number[][]) {
    this.guide = points
    this.drawOverlay()
  }
  /** Interactive section-cut state drawn on the 2D overlay, never in the model. */
  setCut(cut: ViewportCut | null) {
    this.cut = cut
    this.drawOverlay()
  }
  /** Model XY under a CSS-pixel point using the affine orthographic projection. */
  modelAt(xCss: number, yCss: number): [number, number] {
    if (this.axes.length < 2) return [0, 0]
    const [ax, ay] = [this.axes[0][0], this.axes[0][1]]
    const [bx, by] = [this.axes[1][0], this.axes[1][1]]
    const det = ax * by - ay * bx
    if (!Number.isFinite(det) || Math.abs(det) < 1e-12) return [0, 0]
    const px = xCss - this.originPoint[0]
    const py = yCss - this.originPoint[1]
    return [(px * by - py * bx) / det, (ax * py - ay * px) / det]
  }
  /** Project model XY to CSS pixels with the same affine basis used for picking. */
  modelToScreen(x: number, y: number): ScreenPoint {
    const [px, py] = this.originPoint
    const ax = this.axes[0] ?? [0, 0, 0]
    const ay = this.axes[1] ?? [0, 0, 0]
    return [px + ax[0] * x + ay[0] * y, py + ax[1] * x + ay[1] * y, 0]
  }
  /** Model-space length represented by one CSS pixel at the current zoom. */
  modelPerPixel(): number {
    if (!this.axes.length) return 1
    const x = Math.hypot(this.axes[0][0], this.axes[0][1])
    const y = Math.hypot(this.axes[1][0], this.axes[1][1])
    const scale = Math.sqrt(Math.max(x * y, 1e-12))
    return scale > 0 ? 1 / scale : 1
  }
  highlight(selection: Picked | null, hover: Picked | null) {
    this.selected = selection
    this.hovered = hover
    this.drawOverlay()
  }
  private drawOverlay() {
    const ctx = this.ctx
    ctx.setTransform(this.ratio, 0, 0, this.ratio, 0, 0)
    ctx.clearRect(0, 0, this.width, this.height)
    if (this.selected) outline(ctx, this.projected, this.selected, false)
    if (
      this.hovered &&
      (this.hovered.id !== this.selected?.id ||
        this.hovered.kind !== this.selected?.kind)
    )
      outline(ctx, this.projected, this.hovered, true)
    this.drawFixture(ctx)
    this.drawBox(ctx)
    this.drawGuide(ctx)
    this.drawCut(ctx)
    if (!this.axes.length || !this.scene.surfaces.length) return
    const scale =
      this.height / (2 * this.renderer.getActiveCamera().getParallelScale())
    const origin = [38, this.height - 39],
      colors = ['#a15d4b', '#488476', '#5678a3']
    ctx.font = '11px monospace'
    for (let i = 0; i < (this.dimension === '2D' ? 2 : 3); i++) {
      const axis = this.axes[i],
        x = origin[0] + (23 * axis[0]) / scale,
        y = origin[1] + (23 * axis[1]) / scale
      ctx.strokeStyle = colors[i]
      ctx.fillStyle = colors[i]
      ctx.lineWidth = 1.7
      ctx.beginPath()
      ctx.moveTo(origin[0], origin[1])
      ctx.lineTo(x, y)
      ctx.stroke()
      ctx.fillText('XYZ'[i], x + 2, y - 2)
    }
    const target = 80 / scale,
      power = 10 ** Math.floor(Math.log10(target))
    const units = [5, 2, 1].find((val) => val * power <= target) ?? 1
    const length = units * power,
      right = this.width - 20,
      bottom = this.height - 25
    ctx.strokeStyle = '#546974'
    ctx.fillStyle = '#405660'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(right - length * scale, bottom - 4)
    ctx.lineTo(right - length * scale, bottom)
    ctx.lineTo(right, bottom)
    ctx.lineTo(right, bottom - 4)
    ctx.stroke()
    ctx.textAlign = 'right'
    ctx.fillText(
      Number(length.toPrecision(4)) + ' ' + this.lengthUnit,
      right,
      bottom - 7
    )
    ctx.textAlign = 'left'
  }
  private drawGuide(ctx: CanvasRenderingContext2D) {
    if (this.guide.length < 2 || !this.axes.length) return
    const origin = this.originPoint
    const points = this.guide.map((point) => {
      const projected: ScreenPoint = [...origin]
      for (let axis = 0; axis < 2; axis++)
        for (let k = 0; k < 3; k++) projected[k] += this.axes[axis][k] * (point[axis] ?? 0)
      return projected
    })
    ctx.save()
    ctx.lineCap = 'round'
    ctx.strokeStyle = '#ffffff'
    ctx.lineWidth = 4
    ctx.beginPath()
    ctx.moveTo(points[0][0], points[0][1])
    for (const point of points.slice(1)) ctx.lineTo(point[0], point[1])
    ctx.stroke()
    ctx.strokeStyle = '#0f6b57'
    ctx.lineWidth = 2
    ctx.setLineDash([7, 4])
    ctx.stroke()
    ctx.setLineDash([])
    for (const point of points) {
      ctx.beginPath()
      ctx.arc(point[0], point[1], 4.2, 0, 2 * Math.PI)
      ctx.fillStyle = '#0f6b57'
      ctx.fill()
      ctx.lineWidth = 1.5
      ctx.strokeStyle = '#ffffff'
      ctx.stroke()
    }
    ctx.restore()
  }
  private drawCut(ctx: CanvasRenderingContext2D) {
    if (!this.cut) return
    ctx.save()
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    // Historical boundary guide: a quiet dashed line when a caller supplies one.
    if (this.cut.boundary && this.cut.boundary.length > 1) {
      ctx.strokeStyle = 'rgba(255,150,44,0.55)'
      ctx.lineWidth = 1.4
      ctx.setLineDash([6, 5])
      ctx.beginPath()
      this.cut.boundary.forEach((point, index) => {
        const p = this.modelToScreen(point[0], point[1])
        if (index === 0) ctx.moveTo(p[0], p[1])
        else ctx.lineTo(p[0], p[1])
      })
      ctx.stroke()
      ctx.setLineDash([])
    }
    const line = (
      a: [number, number],
      b: [number, number],
      colour: string,
      dashed: boolean,
      width: number
    ) => {
      const p = this.modelToScreen(a[0], a[1])
      const q = this.modelToScreen(b[0], b[1])
      ctx.strokeStyle = '#ffffff'
      ctx.lineWidth = width + 2.4
      ctx.setLineDash([])
      ctx.beginPath()
      ctx.moveTo(p[0], p[1])
      ctx.lineTo(q[0], q[1])
      ctx.stroke()
      ctx.strokeStyle = colour
      ctx.lineWidth = width
      ctx.setLineDash(dashed ? [7, 5] : [])
      ctx.beginPath()
      ctx.moveTo(p[0], p[1])
      ctx.lineTo(q[0], q[1])
      ctx.stroke()
      ctx.setLineDash([])
    }
    const handle = (point: [number, number], filled: boolean) => {
      const p = this.modelToScreen(point[0], point[1])
      ctx.beginPath()
      ctx.arc(p[0], p[1], 5.5, 0, 2 * Math.PI)
      ctx.fillStyle = filled ? '#ff962c' : '#ffffff'
      ctx.fill()
      ctx.lineWidth = 2
      ctx.strokeStyle = this.cut?.invalid ? '#b42318' : '#10233f'
      ctx.stroke()
    }
    // Completed pending guides stay visible as dashed ghosts.
    for (const stroke of this.cut.strokes ?? []) {
      line(stroke.a, stroke.b, '#e07a12', true, 1.8)
      handle(stroke.a, true)
      handle(stroke.b, true)
    }
    // Server-selected material intervals are solid: they are the prospective
    // seam, while the dashed remainder is outside the target material.
    for (const segment of this.cut.segments ?? []) {
      line(segment.a, segment.b, '#0f6b57', false, 3)
    }
    const start = this.cut.start
      ? this.modelToScreen(this.cut.start[0], this.cut.start[1])
      : null
    const end = this.cut.end
      ? this.modelToScreen(this.cut.end[0], this.cut.end[1])
      : null
    const hover = this.cut.hover
      ? this.modelToScreen(this.cut.hover[0], this.cut.hover[1])
      : null
    if (start) {
      const target = end ?? hover
      if (target) {
        ctx.strokeStyle = '#ffffff'
        ctx.lineWidth = 4
        ctx.beginPath()
        ctx.moveTo(start[0], start[1])
        ctx.lineTo(target[0], target[1])
        ctx.stroke()
        ctx.strokeStyle = this.cut.invalid ? '#b42318' : '#e07a12'
        ctx.lineWidth = 2.2
        ctx.setLineDash([8, 5])
        ctx.beginPath()
        ctx.moveTo(start[0], start[1])
        ctx.lineTo(target[0], target[1])
        ctx.stroke()
        ctx.setLineDash([])
      }
    }
    if (start) {
      ctx.beginPath()
      ctx.arc(start[0], start[1], 7, 0, 2 * Math.PI)
      ctx.fillStyle = '#ff962c'
      ctx.fill()
      ctx.lineWidth = 2.4
      ctx.strokeStyle = '#10233f'
      ctx.stroke()
      ctx.fillStyle = '#10233f'
      ctx.font = '600 12px system-ui, sans-serif'
      ctx.fillText('A', start[0] + 10, start[1] - 9)
    }
    if (end) {
      ctx.beginPath()
      ctx.arc(end[0], end[1], 7, 0, 2 * Math.PI)
      ctx.fillStyle = '#ff962c'
      ctx.fill()
      ctx.lineWidth = 2.4
      ctx.strokeStyle = '#10233f'
      ctx.stroke()
      ctx.fillStyle = '#10233f'
      ctx.font = '600 12px system-ui, sans-serif'
      ctx.fillText('B', end[0] + 10, end[1] - 9)
    }
    if (hover && !end) {
      ctx.beginPath()
      ctx.arc(hover[0], hover[1], 6, 0, 2 * Math.PI)
      ctx.fillStyle = '#ffffff'
      ctx.fill()
      ctx.lineWidth = 2.2
      ctx.strokeStyle = '#10233f'
      ctx.stroke()
    }
    ctx.restore()
  }
  private drawFixture(ctx: CanvasRenderingContext2D) {
    if (!this.fixture.size) return
    ctx.save()
    ctx.fillStyle = '#d77514'
    ctx.strokeStyle = '#fff'
    ctx.lineWidth = 1.2
    for (const { surface, points } of this.projected) {
      if (!surface.nodeIds || !surface.instance) continue
      for (let i = 0; i < points.length; i++) {
        if (!this.fixture.has(surface.instance + ':' + surface.nodeIds[i])) continue
        ctx.beginPath()
        ctx.arc(points[i][0], points[i][1], 3.4, 0, 2 * Math.PI)
        ctx.fill()
        ctx.stroke()
      }
    }
    ctx.restore()
  }
  private drawBox(ctx: CanvasRenderingContext2D) {
    if (!this.box) return
    const { x0, y0, x1, y1 } = this.box
    ctx.save()
    ctx.strokeStyle = '#147d9a'
    ctx.fillStyle = 'rgba(20,125,154,0.12)'
    ctx.lineWidth = 1.2
    ctx.setLineDash([4, 3])
    const left = Math.min(x0, x1),
      top = Math.min(y0, y1)
    ctx.fillRect(left, top, Math.abs(x1 - x0), Math.abs(y1 - y0))
    ctx.strokeRect(left, top, Math.abs(x1 - x0), Math.abs(y1 - y0))
    ctx.restore()
  }
  dispose() {
    this.clear()
    // Public OpenGL implementation supplies this resource-release method in vtk.js 34.
    const gl = this.view as typeof this.view & {
      releaseGraphicsResources: () => void
    }
    gl.releaseGraphicsResources()
    const canvas = this.view.getCanvas()
    const context = canvas?.getContext('webgl2') ?? canvas?.getContext('webgl')
    const loss = context?.getExtension('WEBGL_lose_context')
    this.view.setContainer(null)
    this.window.removeView(this.view)
    this.window.removeRenderer(this.renderer)
    this.renderer.getActiveCamera().delete()
    this.renderer.delete()
    this.view.delete()
    this.window.delete()
    loss?.loseContext()
  }
}
