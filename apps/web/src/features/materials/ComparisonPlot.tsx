import { useEffect, useRef } from 'react'
import Plotly from 'plotly.js-basic-dist-min'

export interface CompareSeries {
  label: string
  x: number[]
  y: number[]
  color: string
}

/**
 * Multi-series comparison chart. It plots only the supplied measured points;
 * no fit, interpolation or extrapolation is drawn.
 */
export function ComparisonPlot({
  series,
  xlabel,
  ylabel,
  testId,
}: {
  series: CompareSeries[]
  xlabel: string
  ylabel: string
  testId: string
}) {
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    void Plotly.react(
      el,
      series.map((line) => ({
        x: line.x,
        y: line.y,
        name: line.label,
        type: 'scatter',
        mode: 'lines+markers',
        line: { color: line.color, width: 2 },
        marker: { size: 4, color: line.color },
        hovertemplate: '%{x:.4g}, %{y:.4g}<extra>' + line.label + '</extra>',
      })),
      {
        autosize: true,
        margin: { l: 58, r: 12, b: 46, t: 10 },
        showlegend: true,
        legend: { orientation: 'h', y: -0.22, font: { size: 11 } },
        font: { family: 'Segoe UI, sans-serif', size: 11 },
        xaxis: { title: { text: xlabel }, gridcolor: '#e5ebed', zerolinecolor: '#bac7c9' },
        yaxis: { title: { text: ylabel }, gridcolor: '#e5ebed', zerolinecolor: '#bac7c9' },
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
      },
      { displayModeBar: false, responsive: true },
    )
    return () => {
      Plotly.purge(el)
    }
  }, [series, xlabel, ylabel])

  return <div ref={ref} className="compare-plot" data-testid={testId} aria-label={ylabel} />
}
