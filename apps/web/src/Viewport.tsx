import { useEffect, useMemo, useRef, useState } from 'react'
import { Maximize, Minus, Plus } from 'lucide-react'
import {
  makeScene,
  ramp,
  type Picked,
  type ViewportProps,
} from './viewportModel'
import { ViewportRenderer } from './viewportRenderer'
import './viewport.css'

export type {
  Display,
  Picked,
  SelectionMode,
  ViewMesh,
  ViewResults,
  ViewportProps,
} from './viewportModel'

export function Viewport(props: ViewportProps) {
  const host = useRef<HTMLDivElement>(null)
  const overlay = useRef<HTMLCanvasElement>(null)
  const controller = useRef<ViewportRenderer | null>(null)
  const latest = useRef(props)
  latest.current = props
  const hover = useRef<Picked | null>(null)
  const [error, setError] = useState('')
  const [hoverLabel, setHoverLabel] = useState('')
  const [grabbing, setGrabbing] = useState(false)
  const colorsKey = JSON.stringify(props.colors),
    hiddenKey = JSON.stringify(props.hidden)
  const scene = useMemo(
    () => makeScene(props),
    [
      props.display,
      props.dimension,
      props.mesh,
      props.results?.instances,
      props.results?.frame,
      props.deformed,
      props.panelOffset,
      colorsKey,
      hiddenKey,
    ]
  )
  // Keep the view stable through frame changes while fitting newly loaded topology.
  const resultExtent = useMemo(() => {
    if (!props.results?.instances.length) return ''
    const ext = [Infinity, -Infinity, Infinity, -Infinity, Infinity, -Infinity]
    for (const instance of props.results.instances)
      for (const row of instance.nodes) {
        for (let i = 0; i < 3; i++) {
          ext[2 * i] = Math.min(ext[2 * i], row[i + 1])
          ext[2 * i + 1] = Math.max(ext[2 * i + 1], row[i + 1])
        }
      }
    return ext.join(',')
  }, [props.results?.instances])
  const fitKey = [
    props.dimension,
    resultExtent || props.display?.bounds.join(','),
    props.resetKey ?? 0,
  ].join('|')
  const lastFit = useRef<string | null>(null)

  useEffect(() => {
    const el = host.current!
    let view: ViewportRenderer | undefined
    let resize: ResizeObserver | undefined
    const listeners = new AbortController()
    const signal = listeners.signal
    let animation = 0
    try {
      view = new ViewportRenderer(el, overlay.current!)
      controller.current = view
      view.resize()
      resize = new ResizeObserver(() => view?.resize())
      resize.observe(el)
      let drag: {
        pointer: number
        startX: number
        startY: number
        x: number
        y: number
        moved: boolean
        pan: boolean
        button: number
      } | null = null
      const local = (e: PointerEvent) => {
        const rect = el.getBoundingClientRect()
        return [e.clientX - rect.left, e.clientY - rect.top] as const
      }
      const setHover = (hit: Picked | null) => {
        if (hit?.kind === hover.current?.kind && hit?.id === hover.current?.id)
          return
        hover.current = hit
        setHoverLabel(
          hit
            ? hit.instance
              ? hit.instance + ' · ' + hit.kind + ' ' + hit.label
              : hit.kind + ' · ' + hit.id
            : ''
        )
        view!.highlight(latest.current.selection, hit)
      }
      el.addEventListener(
        'pointerdown',
        (e) => {
          if (drag || e.button > 2) return
          el.focus({ preventScroll: true })
          el.setPointerCapture(e.pointerId)
          drag = {
            pointer: e.pointerId,
            startX: e.clientX,
            startY: e.clientY,
            x: e.clientX,
            y: e.clientY,
            moved: false,
            pan: e.shiftKey || e.button > 0,
            button: e.button,
          }
        },
        { signal }
      )
      el.addEventListener(
        'pointermove',
        (e) => {
          cancelAnimationFrame(animation)
          if (drag) {
            if (drag.pointer !== e.pointerId) return
            if (
              Math.hypot(e.clientX - drag.startX, e.clientY - drag.startY) > 3
            ) {
              drag.moved = true
              setGrabbing(true)
            }
            if (drag.moved) {
              setHover(null)
              view!.drag(e.clientX - drag.x, e.clientY - drag.y, drag.pan)
            }
            drag.x = e.clientX
            drag.y = e.clientY
          } else {
            const [x, y] = local(e)
            animation = requestAnimationFrame(() =>
              setHover(view!.pick(latest.current.mode, x, y))
            )
          }
        },
        { signal }
      )
      el.addEventListener(
        'pointerleave',
        () => {
          cancelAnimationFrame(animation)
          setHover(null)
        },
        { signal }
      )
      el.addEventListener(
        'pointerup',
        (e) => {
          if (drag?.pointer !== e.pointerId) return
          if (!drag.moved && drag.button === 0)
            latest.current.onSelect(
              view!.pick(latest.current.mode, ...local(e))
            )
          drag = null
          setGrabbing(false)
          if (el.hasPointerCapture(e.pointerId))
            el.releasePointerCapture(e.pointerId)
        },
        { signal }
      )
      el.addEventListener(
        'lostpointercapture',
        () => {
          drag = null
          setGrabbing(false)
        },
        { signal }
      )
      el.addEventListener('contextmenu', (e) => e.preventDefault(), { signal })
      el.addEventListener(
        'wheel',
        (e) => {
          e.preventDefault()
          const delta = e.deltaMode === 1 ? 16 * e.deltaY : e.deltaY
          view!.zoom(Math.exp(Math.max(-1, Math.min(1, delta * 0.0015))))
          setHover(null)
        },
        { signal, passive: false }
      )
      el.addEventListener(
        'keydown',
        (e) => {
          if (e.key.toLowerCase() === 'f') view!.fit()
          else if (e.key === '+' || e.key === '=') view!.zoom(0.8)
          else if (e.key === '-') view!.zoom(1.25)
          else if (e.key === 'Escape') latest.current.onSelect(null)
        },
        { signal }
      )
    } catch (e) {
      setError(
        'The engineering viewport could not start. Enable WebGL in this browser. ' +
          String(e)
      )
    }
    return () => {
      cancelAnimationFrame(animation)
      listeners.abort()
      resize?.disconnect()
      view?.dispose()
      controller.current = null
      lastFit.current = null
    }
  }, [])

  useEffect(() => {
    if (!controller.current) return
    controller.current.lengthUnit = props.lengthUnit ?? 'mm'
    try {
      controller.current.setScene(
        scene,
        props.dimension,
        lastFit.current !== fitKey
      )
      lastFit.current = fitKey
      hover.current = null
      setHoverLabel('')
      setError('')
      controller.current.highlight(latest.current.selection, null)
    } catch (e) {
      setError('Unable to display this geometry. ' + String(e))
    }
  }, [scene, props.dimension, fitKey, props.lengthUnit])

  useEffect(() => {
    hover.current = null
    setHoverLabel('')
    controller.current?.highlight(props.selection, null)
  }, [props.selection, props.mode])

  return (
    <div
      className="seal-viewport"
      data-testid="vtk-viewport"
      data-dimension={props.dimension}
    >
      <div
        className="seal-vtk-host"
        ref={host}
        tabIndex={0}
        role="application"
        aria-label={props.dimension + ' engineering viewport'}
        style={{
          cursor: grabbing ? 'grabbing' : hoverLabel ? 'pointer' : 'crosshair',
        }}
      />
      <canvas ref={overlay} aria-hidden="true" className="seal-vtk-overlay" />
      <div className="seal-vtk-tools" aria-label="View controls">
        <button
          type="button"
          title="Zoom in (+)"
          aria-label="Zoom in"
          onClick={() => controller.current?.zoom(0.8)}
        >
          <Plus size={15} />
        </button>
        <button
          type="button"
          title="Zoom out (−)"
          aria-label="Zoom out"
          onClick={() => controller.current?.zoom(1.25)}
        >
          <Minus size={15} />
        </button>
        <button
          type="button"
          title="Fit and reset view (F)"
          aria-label="Fit and reset view"
          onClick={() => controller.current?.fit()}
        >
          <Maximize size={15} />
        </button>
      </div>
      <div className="seal-vtk-orientation">
        {props.dimension === '2D' ? 'XY section' : '3D segment'}
      </div>
      {error ? (
        <div role="alert" className="seal-vtk-empty">
          {error}
        </div>
      ) : (
        scene.surfaces.length === 0 && (
          <div className="seal-vtk-empty">No visible geometry</div>
        )
      )}
      {props.results && (
        <div className="seal-vtk-legend">
          <strong>Displacement magnitude</strong>
          {scene.range === null ? (
            <span>Unavailable</span>
          ) : (
            <>
              <i
                style={{
                  background:
                    'linear-gradient(90deg,' +
                    ramp.map((rgb) => 'rgb(' + rgb.join(',') + ')').join(',') +
                    ')',
                }}
              />
              <span>
                0{' '}
                <b>
                  {Number(scene.range.toPrecision(4))}{' '}
                  {props.lengthUnit ?? 'mm'}
                </b>
              </span>
              {scene.surfaces.some((s) => !s.contour) && (
                <span>Gray · U unavailable</span>
              )}
            </>
          )}
        </div>
      )}
      {hoverLabel && <div className="seal-vtk-tip">{hoverLabel}</div>}
    </div>
  )
}
export default Viewport
