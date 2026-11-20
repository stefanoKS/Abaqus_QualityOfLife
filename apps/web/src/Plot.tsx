import { useEffect, useRef } from 'react'
import Plotly from 'plotly.js-basic-dist-min'
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
  useEffect(() => {
    const el = ref.current!
    const plot = [
      {
        x,
        y,
        mode: 'lines+markers',
        line: { color: '#197968', width: 2 },
        marker: { size: 4 },
        type: 'scatter',
        hovertemplate: '%{x:.3g}, %{y:.3g}<extra></extra>',
      },
    ]
    if (active !== undefined && x[active] !== undefined)
      plot.push({
        x: [x[active]],
        y: [y[active]],
        mode: 'markers',
        type: 'scatter',
        marker: { size: 10 },
        line: { color: '#bf722b', width: 0 },
        hovertemplate: '%{x:.3g}, %{y:.3g}<extra></extra>',
      })
    let alive = true
    Plotly.react(
      el,
      plot,
      {
        autosize: true,
        margin: { l: 56, r: 15, b: 45, t: 14 },
        showlegend: false,
        font: { family: 'Segoe UI, sans-serif', size: 11 },
        xaxis: { title: { text: xlabel }, gridcolor: '#e5ebed', zerolinecolor: '#bac7c9' },
        yaxis: { title: { text: ylabel }, gridcolor: '#e5ebed', zerolinecolor: '#bac7c9' },
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
      },
      { displayModeBar: false, responsive: true },
    ).then(() => {
      if (alive && onPick)
        (
          el as unknown as {
            on: (
              key: string,
              fn: (e: { points: { pointIndex: number; curveNumber: number }[] }) => void,
            ) => void
          }
        ).on('plotly_click', (e) => {
          if (e.points[0]?.curveNumber === 0) onPick(e.points[0].pointIndex)
        })
    })
    const resize = new ResizeObserver(() => {
      if (alive) Plotly.Plots.resize(el)
    })
    resize.observe(el)
    return () => {
      alive = false
      resize.disconnect()
      Plotly.purge(el)
    }
  }, [x, y, xlabel, ylabel, active, onPick])
  return <div ref={ref} className="plot" aria-label={ylabel + ' versus ' + xlabel} />
}
