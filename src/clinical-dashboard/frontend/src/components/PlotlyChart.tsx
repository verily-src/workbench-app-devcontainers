import { useEffect, useRef } from 'react'
import Plotly from 'plotly.js'

interface PlotlyChartProps {
  data: Plotly.Data[]
  layout?: Partial<Plotly.Layout>
  config?: Partial<Plotly.Config>
  className?: string
}

export default function PlotlyChart({ data, layout = {}, config = {}, className = '' }: PlotlyChartProps) {
  const plotRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!plotRef.current) return

    const defaultLayout: Partial<Plotly.Layout> = {
      autosize: true,
      margin: { t: 40, r: 40, b: 60, l: 60 },
      paper_bgcolor: '#f5f2ea',
      plot_bgcolor: '#ffffff',
      font: { family: 'Inter, sans-serif', size: 12 },
      hovermode: 'x unified',
      ...layout,
    }

    const defaultConfig: Partial<Plotly.Config> = {
      responsive: true,
      displayModeBar: true,
      displaylogo: false,
      modeBarButtonsToRemove: ['lasso2d', 'select2d'],
      ...config,
    }

    Plotly.newPlot(plotRef.current, data, defaultLayout, defaultConfig)

    return () => {
      if (plotRef.current) {
        Plotly.purge(plotRef.current)
      }
    }
  }, [data, layout, config])

  return <div ref={plotRef} className={className} />
}
