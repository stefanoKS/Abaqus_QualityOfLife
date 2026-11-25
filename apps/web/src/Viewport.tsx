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
  const { t, formatNumber } = useI18n()
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
  const [cutHover, setCutHover] = useState<[number, number] | null>(null)
  const cutRef = useRef(props.cut)
  cutRef.current = props.cut
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
      props.rigidInstances,
      props.elementValues,
      props.nodalValues,
      props.resultMin,
      props.deformationScale,
      props.nodeMarkers,
      props.showMeshEdges,
      props.resultComponent,
      props.resultRange,
      props.materialOutlines,
      props.faceMaterials,
      colorsKey,
      hiddenKey,
      props.previewTranslation,
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
  // Until the user moves the camera, a container resize (including the first
  // layout settle after CSS loads) re-fits the scene. Otherwise the initial
  // projection would keep the size it was mounted at and screen picking would
  // no longer agree with the drawn geometry.
  const userMoved = useRef(false)

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
      resize = new ResizeObserver(() => {
        view?.resize()
        if (!userMoved.current) view?.fit()
        if (host.current && view) host.current.dataset.camera = view.cameraSignature()
      })
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
          // Middle-button drag pans. Cancelling pointerdown suppresses the
          // compatibility mousedown that starts browser auto-scroll, so the page
          // must not scroll while the camera moves.
          if (e.button === 1) e.preventDefault()
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
            if (drag.moved && !drag.box) userMoved.current = true
            drag.x = e.clientX
            drag.y = e.clientY
          } else {
            const [x, y] = local(e)
            const cut = latest.current.cut
            if (cut?.active) {
              // The projected workflow accepts any model point. The server owns
              // the engineering projection onto material; pixels are ergonomics.
              const [mx, my] = view!.modelAt(x, y)
              animation = requestAnimationFrame(() => {
                setCutHover((previous) => {
                  if (previous && previous[0] === mx && previous[1] === my) return previous
                  return [mx, my]
                })
                latest.current.onCutHover?.([mx, my])
              })
            } else {
              animation = requestAnimationFrame(() =>
                setHover(view!.pick(latest.current.mode, x, y))
              )
            }
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
            const cut = latest.current.cut
            if (cut?.active) {
              const [mx, my] = view!.modelAt(lx, ly)
              latest.current.onCutPoint?.([mx, my])
            } else {
              latest.current.onSelect(view!.pick(latest.current.mode, lx, ly))
            }
          }
          el.dataset.camera = view!.cameraSignature()
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
      // Middle-click often produces auxclick after pointerup; suppressing it
      // keeps browser auto-scroll and new-tab gestures out of the viewport.
      el.addEventListener(
        'auxclick',
        (e) => {
          if (e.button === 1) e.preventDefault()
        },
        { signal },
      )
      el.addEventListener(
        'wheel',
        (e) => {
          e.preventDefault()
          const delta = e.deltaMode === 1 ? 16 * e.deltaY : e.deltaY
          view!.zoom(Math.exp(Math.max(-1, Math.min(1, delta * 0.0015))))
          userMoved.current = true
          el.dataset.camera = view!.cameraSignature()
          setHover(null)
        },
        { signal, passive: false },
      )
      el.addEventListener(
        'keydown',
        (e) => {
          if (e.key.toLowerCase() === 'f') {
            userMoved.current = false
            view!.fit()
          }
          else if (e.key === '+' || e.key === '=') {
            userMoved.current = true
            view!.zoom(0.8)
          }
          else if (e.key === '-') {
            userMoved.current = true
            view!.zoom(1.25)
          }
          else if (e.key === 'Escape') {
            if (latest.current.cut?.active) {
              setCutHover(null)
              latest.current.onCutCancel?.()
            } else latest.current.onSelect(null)
          }
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
    controller.current.plain = !!props.plain
    if (lastFit.current !== fitKey) userMoved.current = false
    try {
      controller.current.setScene(scene, props.dimension, lastFit.current !== fitKey)
      lastFit.current = fitKey
      if (host.current) host.current.dataset.camera = controller.current.cameraSignature()
      hover.current = null
      setHoverLabel('')
      setError('')
      controller.current.highlight(latest.current.selection, null)
    } catch (e) {
      setError(translate.current('viewport.displayError') + ' ' + String(e))
    }
  }, [scene, props.dimension, fitKey, props.lengthUnit, props.plain])
  // The partition guide is an overlay in model space; it never becomes a
  // pickable CAD primitive and never enters the saved model.
  useEffect(() => {
    controller.current?.setGuide(props.guide ?? [])
  }, [props.guide])
  useEffect(() => {
    if (!props.cut?.active) setCutHover(null)
    const cut = props.cut
    controller.current?.setCut(
      cut?.active ? { ...cut, hover: cutHover ?? cut.hover ?? null } : null
    )
  }, [props.cut, cutHover])
  // Pressure glyphs are an overlay on the exact displayed geometry: the same
  // frame, deformation toggle and scale as the contour. They are never picked.
  useEffect(() => {
    controller.current?.setPressureArrows(props.pressureArrows ?? null)
  }, [props.pressureArrows, scene])

  useEffect(() => {
    hover.current = null
    setHoverLabel('')
    controller.current?.highlight(props.selection, null)
  }, [props.selection, props.mode])

  const fixtureKey = (props.selectedNodes ?? []).join(',')
  useEffect(() => {
    controller.current?.setSelection(props.selectedNodes ?? [])
  }, [fixtureKey, props.selectedNodes])
  // Toolbar camera changes update the same signature pointer gestures record,
  // so the viewport has one authoritative camera identity.
  const recordCamera = () => {
    if (host.current && controller.current)
      host.current.dataset.camera = controller.current.cameraSignature()
  }

  return (
    <div className="seal-viewport" data-testid="vtk-viewport" data-dimension={props.dimension}
      data-frame-time={props.results?.frame ? String(props.results.frame.time) : ''}
      data-scene-actors={scene.surfaces.length}
      data-display-bounds={props.display ? props.display.bounds.join(',') : ''}
      data-material-outlines={props.materialOutlines ? 'on' : 'off'}
      data-material-interfaces={String(
        scene.surfaces
          .filter((surface) => surface.overlay === 'material-interface')
          .reduce((total, surface) => total + surface.cells.length, 0),
      )}
      data-material-perimeters={String(
        scene.surfaces
          .filter((surface) => surface.overlay === 'material-perimeter')
          .reduce((total, surface) => total + surface.cells.length, 0),
      )}
      data-material-keys={[
        ...new Set(
          scene.surfaces
            .filter((surface) => surface.overlay)
            .flatMap((surface) => surface.materials ?? []),
        ),
      ]
        .sort()
        .join(',')}
      data-plain={props.plain ? 'true' : 'false'}
      data-cut-phase={props.cut?.active ? props.cut.phase ?? 'start' : ''}
      data-preview-translation={
        props.previewTranslation ? JSON.stringify(props.previewTranslation) : ''
      }
      data-scene-instances={[
        ...new Set(
          scene.surfaces
            .map((surface) => surface.instance)
            .filter((name): name is string => Boolean(name))
        ),
      ].join(',')}
    >
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
          onClick={() => {
            userMoved.current = true
            controller.current?.zoom(0.8)
            recordCamera()
          }}
        >
          <Plus size={15} />
        </button>
        <button
          type="button"
          title={t('viewport.zoomOut') + ' (−)'}
          aria-label={t('viewport.zoomOut')}
          onClick={() => {
            userMoved.current = true
            controller.current?.zoom(1.25)
            recordCamera()
          }}
        >
          <Minus size={15} />
        </button>
        <button
          type="button"
          title={t('viewport.fit') + ' (F)'}
          aria-label={t('viewport.fit')}
          onClick={() => {
            userMoved.current = false
            controller.current?.fit()
            recordCamera()
          }}
        >
          <Maximize size={15} />
        </button>
      </div>
      <div className="seal-vtk-orientation">
        {props.dimension === '2D' ? t('viewport.xySection') : t('viewport.segment3d')}
      </div>
      {error && (
        <div role="alert" className="seal-vtk-empty">
          {error}
        </div>
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
              <span data-testid="legend-limits">
                <b>
                  {formatNumber(props.resultMin ?? 0)} {props.resultUnit ?? props.lengthUnit ?? 'mm'}
                </b>
                <b>
                  {Number(scene.range.toPrecision(4))} {props.resultUnit ?? props.lengthUnit ?? 'mm'}
                </b>
              </span>
              {props.resultSaturated && (
                <span className="legend-saturated" data-testid="legend-saturated">
                  {t('viewport.saturated')}
                </span>
              )}
              {props.resultUnderflow && (
                <span className="legend-saturated" data-testid="legend-underflow">
                  {t('viewport.underflow')}
                </span>
              )}
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
