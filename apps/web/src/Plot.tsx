import { useEffect, useRef } from 'react'
import Plotly from 'plotly.js-basic-dist-min'
import { nextAxisRange, type AxisLike } from './plotAxis'

/**
 * The curve is drawn once; the frame cursor is updated in place. Rebuilding the
 * plot on every frame used to purge Plotly and reset the reader's axis zoom.
 */
export function Plot({
  x,
  y,
  xlabel,
  ylabel,
  active,
  onPick,
}: {
  x: number[]
  y: number[]
  xlabel: string
  ylabel: string
  active?: number
  onPick?: (index: number) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const pick = useRef(onPick)
  pick.current = onPick
  const ready = useRef(false)
  const bound = useRef(false)
  // Previous series, used to tell a sign mirror from an ordinary frame change.
  const previous = useRef<{ x: number[]; y: number[] } | null>(null)
  const cursor = active !== undefined && x[active] !== undefined ? active : -1

  // Mount: one resize observer. Click binding waits until Plotly has created the
  // plot, because the div has no `on` method before that.
  useEffect(() => {
    const el = ref.current!
    let alive = true
    const resize = new ResizeObserver(() => {
      if (!alive || !ready.current || !el.isConnected) return
      try {
        Plotly.Plots.resize(el)
      } catch {
        // A hidden tab can briefly report a zero-sized plot; the next frame resizes it.
      }
    })
    resize.observe(el)
    return () => {
      alive = false
      ready.current = false
      bound.current = false
      resize.disconnect()
      Plotly.purge(el)
    }
  }, [])

  // Data or axis-title change: keep the reader's zoom if they have one. A sign
  // mirror refits an automatic axis and mirrors a deliberately zoomed one, so a
  // reversed positive-travel curve can never stay clipped to positive limits.
  useEffect(() => {
    const el = ref.current!
    const layout = (
      el as unknown as { layout?: { xaxis?: AxisLike; yaxis?: AxisLike } }
    ).layout
    const xRange = nextAxisRange(previous.current?.x, x, layout?.xaxis)
    const yRange = nextAxisRange(previous.current?.y, y, layout?.yaxis)
    previous.current = { x, y }
    void Plotly.react(
      el,
      [
        {
          x,
          y,
          mode: 'lines+markers',
          line: { color: '#197968', width: 2 },
          marker: { size: 4 },
          type: 'scatter',
          hovertemplate: '%{x:.3g}, %{y:.3g}<extra></extra>',
        },
        {
          x: [],
          y: [],
          mode: 'markers',
          type: 'scatter',
          marker: { size: 10 },
          line: { color: '#bf722b', width: 0 },
          hovertemplate: '%{x:.3g}, %{y:.3g}<extra></extra>',
        },
      ],
      {
        autosize: true,
        margin: { l: 56, r: 15, b: 45, t: 14 },
        showlegend: false,
        font: { family: 'Segoe UI, sans-serif', size: 11 },
        xaxis: {
          title: { text: xlabel },
          gridcolor: '#e5ebed',
          zerolinecolor: '#bac7c9',
          range: xRange,
        },
        yaxis: {
          title: { text: ylabel },
          gridcolor: '#e5ebed',
          zerolinecolor: '#bac7c9',
          range: yRange,
        },
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
      },
      { displayModeBar: false, responsive: true },
    ).then(() => {
      ready.current = true
      if (!bound.current) {
        bound.current = true
        ;(
          el as unknown as {
            on: (
              key: string,
              fn: (e: { points: { pointIndex: number; curveNumber: number }[] }) => void,
            ) => void
          }
        ).on('plotly_click', (e) => {
          if (e.points[0]?.curveNumber === 0) pick.current?.(e.points[0].pointIndex)
        })
      }
      restyleCursor(el, x, y, cursor)
    })
  }, [x, y, xlabel, ylabel])

  // Frame cursor only: Plotly.restyle never purges the plot or its axes.
  useEffect(() => {
    if (ready.current && ref.current) restyleCursor(ref.current, x, y, cursor)
  }, [cursor, x, y])

  return <div ref={ref} className="plot" aria-label={ylabel + ' versus ' + xlabel} />
}

function restyleCursor(el: HTMLDivElement, x: number[], y: number[], index: number) {
  const point = index >= 0 && x[index] !== undefined ? [x[index]] : []
  const value = index >= 0 && y[index] !== undefined ? [y[index]] : []
  void Plotly.restyle(el, { x: [point], y: [value] }, [1])
}
