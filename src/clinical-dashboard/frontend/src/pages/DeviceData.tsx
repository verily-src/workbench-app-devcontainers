import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDeviceData } from '../api/hooks'
import PlotlyChart from '../components/PlotlyChart'
import type { Data } from 'plotly.js'

export default function DeviceData() {
  const navigate = useNavigate()
  const [cohortIds, setCohortIds] = useState<string[]>([])

  useEffect(() => {
    const stored = localStorage.getItem('selectedCohort')
    if (stored) {
      setCohortIds(JSON.parse(stored))
    }
  }, [])

  const { data, isLoading, error } = useDeviceData(cohortIds)

  const createMetricChart = (
    metricName: string,
    yAxisTitle: string,
    color: string
  ): Data[] => {
    if (!data?.metrics[metricName]) return []

    const points = data.metrics[metricName]
    const x = points.map(p => p.study_day)
    const y = points.map(p => p.mean)
    const upper = points.map(p => p.mean + p.std)
    const lower = points.map(p => p.mean - p.std)

    return [
      {
        x,
        y,
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Mean',
        line: { color, width: 2 },
        marker: { size: 6 },
      },
      {
        x: [...x, ...x.slice().reverse()],
        y: [...upper, ...lower.slice().reverse()],
        type: 'scatter',
        fill: 'toself',
        fillcolor: color.replace(')', ', 0.2)').replace('rgb', 'rgba'),
        line: { width: 0 },
        showlegend: false,
        hoverinfo: 'skip',
        name: '±1 SD',
      },
    ]
  }

  if (cohortIds.length === 0) {
    return (
      <div className="mx-auto max-w-[1600px] px-6 py-6">
        <div className="mb-4">
          <h1 className="text-xl font-semibold">Device Data</h1>
          <p className="text-sm text-verily-ink/60 mt-1">
            Cohort-aggregated sensor metrics: steps, sleep, HRV, walking bouts
          </p>
        </div>

        <div className="card p-6">
          <p className="text-sm text-verily-ink/60">
            No cohort selected.{' '}
            <button
              onClick={() => navigate('/cohort')}
              className="text-verily-primary hover:underline"
            >
              Go to Cohort Selector
            </button>
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-[1600px] px-6 py-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Device Data</h1>
          <p className="text-sm text-verily-ink/60 mt-1">
            Cohort size: {cohortIds.length} participants
          </p>
        </div>
        <button
          onClick={() => navigate('/cohort')}
          className="btn-ghost text-xs"
        >
          ← Change Cohort
        </button>
      </div>

      {isLoading && (
        <div className="card p-6">
          <p className="text-sm text-verily-ink/60">Loading device data...</p>
        </div>
      )}

      {error && (
        <div className="card p-4 border-verily-warm bg-verily-warm/10">
          <p className="text-sm text-verily-warm">
            Error loading device data: {error.message}
          </p>
        </div>
      )}

      {data && (
        <div className="space-y-6">
          {/* Step Count */}
          {data.metrics.steps && data.metrics.steps.length > 0 && (
            <div className="card p-6">
              <h2 className="text-lg font-medium mb-4">Daily Step Count</h2>
              <PlotlyChart
                data={createMetricChart('steps', 'Steps', 'rgb(8, 122, 106)')}
                layout={{
                  xaxis: { title: 'Study Day' },
                  yaxis: { title: 'Average Step Count' },
                  height: 400,
                }}
                className="w-full"
              />
            </div>
          )}

          {/* Sleep Duration */}
          {data.metrics.sleep && data.metrics.sleep.length > 0 && (
            <div className="card p-6">
              <h2 className="text-lg font-medium mb-4">Sleep Duration</h2>
              <PlotlyChart
                data={createMetricChart('sleep', 'Minutes', 'rgb(162, 91, 197)')}
                layout={{
                  xaxis: { title: 'Study Day' },
                  yaxis: { title: 'Sleep Duration (minutes)' },
                  height: 400,
                }}
                className="w-full"
              />
            </div>
          )}

          {/* Heart Rate Variability */}
          {data.metrics.hrv && data.metrics.hrv.length > 0 && (
            <div className="card p-6">
              <h2 className="text-lg font-medium mb-4">Heart Rate Variability (RMSSD)</h2>
              <PlotlyChart
                data={createMetricChart('hrv', 'HRV (ms)', 'rgb(211, 92, 101)')}
                layout={{
                  xaxis: { title: 'Study Day' },
                  yaxis: { title: 'HRV - RMSSD (ms)' },
                  height: 400,
                }}
                className="w-full"
              />
            </div>
          )}

          {/* Walking Bouts */}
          {data.metrics.walking_bouts && data.metrics.walking_bouts.length > 0 && (
            <div className="card p-6">
              <h2 className="text-lg font-medium mb-4">Walking Bouts</h2>
              <PlotlyChart
                data={createMetricChart('walking_bouts', 'Count', 'rgb(59, 130, 246)')}
                layout={{
                  xaxis: { title: 'Study Day' },
                  yaxis: { title: 'Walking Bout Count' },
                  height: 400,
                }}
                className="w-full"
              />
            </div>
          )}

          {/* Non-Walking Bouts */}
          {data.metrics.nonwalking_bouts && data.metrics.nonwalking_bouts.length > 0 && (
            <div className="card p-6">
              <h2 className="text-lg font-medium mb-4">Non-Walking Activity Bouts</h2>
              <PlotlyChart
                data={createMetricChart('nonwalking_bouts', 'Count', 'rgb(249, 115, 22)')}
                layout={{
                  xaxis: { title: 'Study Day' },
                  yaxis: { title: 'Non-Walking Bout Count' },
                  height: 400,
                }}
                className="w-full"
              />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
