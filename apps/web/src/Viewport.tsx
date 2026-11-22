import { useEffect, useMemo, useRef, useState } from 'react'
import { Maximize, Minus, Plus } from 'lucide-react'
import { makeScene, ramp, type Picked, type ViewportProps } from './viewportModel'
import { ViewportRenderer } from './viewportRenderer'
import { useI18n } from './i18n'
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
  const { t } = useI18n()
  // The renderer effect must not depend on the language: recreating it would
  // discard the camera state the user is working with.
  const translate = useRef(t)
  translate.current = t
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
      props.results?.bounds,
      props.results?.frame,
      props.deformed,
      props.panelOffset,
      props.resultComponent,
      props.resultRange,
      colorsKey,
      hiddenKey,
    ],
  )
  // Keep the view stable through frame changes while fitting newly loaded topology.
  const resultExtent = useMemo(() => {
    if (!props.results) return ''
    const recorded = props.results.bounds
    if (Array.isArray(recorded) && recorded.length === 6) return recorded.join(',')
    if (!props.results.instances.length) return ''
    const ext = [Infinity, -Infinity, Infinity, -Infinity, Infinity, -Infinity]
    for (const instance of props.results.instances)
      for (const row of instance.nodes) {
        for (let i = 0; i < 3; i++) {
          ext[2 * i] = Math.min(ext[2 * i], row[i + 1])
          ext[2 * i + 1] = Math.max(ext[2 * i + 1], row[i + 1])
        }
      }
    return ext.join(',')
  }, [props.results?.instances, props.results?.bounds])
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
        startLocalX: number
        startLocalY: number
        x: number
        y: number
        moved: boolean
        pan: boolean
        box: boolean
        button: number
      } | null = null
      const local = (e: PointerEvent) => {
        const rect = el.getBoundingClientRect()
        return [e.clientX - rect.left, e.clientY - rect.top] as const
      }
      const setHover = (hit: Picked | null) => {
        if (hit?.kind === hover.current?.kind && hit?.id === hover.current?.id) return
        hover.current = hit
        setHoverLabel(
          hit
            ? hit.instance
              ? hit.instance + ' · ' + hit.kind + ' ' + hit.label
              : hit.kind + ' · ' + hit.id
            : '',
        )
        view!.highlight(latest.current.selection, hit)
      }
      el.addEventListener(
        'pointerdown',
        (e) => {
          if (drag || e.button > 2) return
          el.focus({ preventScroll: true })
          el.setPointerCapture(e.pointerId)
          const [lx, ly] = local(e)
          // In fixed-node mode a plain left drag is a selection rectangle; Shift
          // and the secondary buttons keep panning, so camera gestures stay
          // distinct from selection gestures.
          const box =
            !!latest.current.boxSelect &&
            latest.current.mode === 'node' &&
            e.button === 0 &&
            !e.shiftKey
          drag = {
            pointer: e.pointerId,
            startX: e.clientX,
            startY: e.clientY,
            startLocalX: lx,
            startLocalY: ly,
            x: e.clientX,
            y: e.clientY,
            moved: false,
            pan: e.shiftKey || e.button > 0,
            box,
            button: e.button,
          }
        },
        { signal },
      )
      el.addEventListener(
        'pointermove',
        (e) => {
          cancelAnimationFrame(animation)
          if (drag) {
            if (drag.pointer !== e.pointerId) return
            if (Math.hypot(e.clientX - drag.startX, e.clientY - drag.startY) > 3) {
              drag.moved = true
              setGrabbing(true)
            }
            if (drag.moved) {
              setHover(null)
              if (drag.box) {
                const [bx, by] = local(e)
                view!.setBox({
                  x0: drag.startLocalX,
                  y0: drag.startLocalY,
                  x1: bx,
                  y1: by,
                })
              } else view!.drag(e.clientX - drag.x, e.clientY - drag.y, drag.pan)
            }
            drag.x = e.clientX
            drag.y = e.clientY
          } else {
            const [x, y] = local(e)
            animation = requestAnimationFrame(() => setHover(view!.pick(latest.current.mode, x, y)))
          }
        },
        { signal },
      )
      el.addEventListener(
        'pointerleave',
        () => {
          cancelAnimationFrame(animation)
          setHover(null)
        },
        { signal },
      )
      el.addEventListener(
        'pointerup',
        (e) => {
          if (drag?.pointer !== e.pointerId) return
          const [lx, ly] = local(e)
          if (drag.box) {
            view!.setBox(null)
            if (drag.moved) {
              latest.current.onBoxSelect?.(
                view!.nodesInBox(
                  drag.startLocalX,
                  drag.startLocalY,
                  lx,
                  ly,
                  latest.current.nodeInstances,
                ),
              )
            } else {
              latest.current.onSelect(view!.pick(latest.current.mode, lx, ly))
            }
          } else if (!drag.moved && drag.button === 0) {
            latest.current.onSelect(view!.pick(latest.current.mode, lx, ly))
          }
          drag = null
          setGrabbing(false)
          if (el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId)
        },
        { signal },
      )
      el.addEventListener(
        'lostpointercapture',
        () => {
          drag = null
          setGrabbing(false)
        },
        { signal },
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
        { signal, passive: false },
      )
      el.addEventListener(
        'keydown',
        (e) => {
          if (e.key.toLowerCase() === 'f') view!.fit()
          else if (e.key === '+' || e.key === '=') view!.zoom(0.8)
          else if (e.key === '-') view!.zoom(1.25)
          else if (e.key === 'Escape') latest.current.onSelect(null)
        },
        { signal },
      )
    } catch (e) {
      setError(translate.current('viewport.startError') + ' ' + String(e))
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
      controller.current.setScene(scene, props.dimension, lastFit.current !== fitKey)
      lastFit.current = fitKey
      hover.current = null
      setHoverLabel('')
      setError('')
      controller.current.highlight(latest.current.selection, null)
    } catch (e) {
      setError(translate.current('viewport.displayError') + ' ' + String(e))
    }
  }, [scene, props.dimension, fitKey, props.lengthUnit])

  useEffect(() => {
    hover.current = null
    setHoverLabel('')
    controller.current?.highlight(props.selection, null)
  }, [props.selection, props.mode])

  const fixtureKey = (props.selectedNodes ?? []).join(',')
  useEffect(() => {
    controller.current?.setSelection(props.selectedNodes ?? [])
  }, [fixtureKey, props.selectedNodes])

  return (
    <div className="seal-viewport" data-testid="vtk-viewport" data-dimension={props.dimension}
      data-frame-time={props.results?.frame ? String(props.results.frame.time) : ''}
      data-scene-actors={scene.surfaces.length}>
      <div
        className="seal-vtk-host"
        ref={host}
        tabIndex={0}
        role="application"
        aria-label={
          props.dimension === '2D' ? t('viewport.label2d') : t('viewport.label3d')
        }
        style={{
          cursor: grabbing ? 'grabbing' : hoverLabel ? 'pointer' : 'crosshair',
        }}
      />
      <canvas ref={overlay} aria-hidden="true" className="seal-vtk-overlay" />
      <div className="seal-vtk-tools" aria-label={t('viewport.controls')}>
        <button
          type="button"
          title={t('viewport.zoomIn') + ' (+)'}
          aria-label={t('viewport.zoomIn')}
          onClick={() => controller.current?.zoom(0.8)}
        >
          <Plus size={15} />
        </button>
        <button
          type="button"
          title={t('viewport.zoomOut') + ' (−)'}
          aria-label={t('viewport.zoomOut')}
          onClick={() => controller.current?.zoom(1.25)}
        >
          <Minus size={15} />
        </button>
        <button
          type="button"
          title={t('viewport.fit') + ' (F)'}
          aria-label={t('viewport.fit')}
          onClick={() => controller.current?.fit()}
        >
          <Maximize size={15} />
        </button>
      </div>
      <div className="seal-vtk-orientation">
        {props.dimension === '2D' ? t('viewport.xySection') : t('viewport.segment3d')}
      </div>
      {error ? (
        <div role="alert" className="seal-vtk-empty">
          {error}
        </div>
      ) : (
        scene.surfaces.length === 0 && (
          <div className="seal-vtk-empty">
            <span>{t('viewport.noGeometry')}</span>
            {props.onEmptyAction && (
              <button type="button" onClick={props.onEmptyAction}>
                {props.emptyActionLabel ?? t('import.action')}
              </button>
            )}
          </div>
        )
      )}
      {props.results && (
        <div className="seal-vtk-legend">
          <strong>{props.resultLabel ?? t('run.displacementField')}</strong>
          {scene.range === null ? (
            <span>{t('viewport.unavailable')}</span>
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
                  {Number(scene.range.toPrecision(4))} {props.lengthUnit ?? 'mm'}
                </b>
              </span>
              {scene.surfaces.some((s) => !s.contour) && (
                <span>{t('viewport.grayUnavailable')}</span>
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
