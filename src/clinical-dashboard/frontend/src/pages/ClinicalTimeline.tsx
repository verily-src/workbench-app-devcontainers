import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useClinicalTimeline } from '../api/hooks'
import PlotlyChart from '../components/PlotlyChart'
import type { Data } from 'plotly.js'

export default function ClinicalTimeline() {
  const navigate = useNavigate()
  const [cohortIds, setCohortIds] = useState<string[]>([])

  useEffect(() => {
    const stored = localStorage.getItem('selectedCohort')
    if (stored) {
      setCohortIds(JSON.parse(stored))
    }
  }, [])

  const { data, isLoading, error } = useClinicalTimeline(cohortIds)

  if (cohortIds.length === 0) {
    return (
      <div className="mx-auto max-w-[1600px] px-6 py-6">
        <div className="mb-4">
          <h1 className="text-xl font-semibold">Clinical Timeline</h1>
          <p className="text-sm text-verily-ink/60 mt-1">
            Physician visit timeline with BP, HR, and other clinical measurements
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

  const createBPChart = (): Data[] => {
    if (!data?.visits || data.visits.length === 0) return []

    const x = data.visits.map(v => v.visit_num)
    const sbp_y = data.visits.map(v => v.sbp_mean)
    const sbp_upper = data.visits.map(v => v.sbp_mean + v.sbp_std)
    const sbp_lower = data.visits.map(v => v.sbp_mean - v.sbp_std)

    const dbp_y = data.visits.map(v => v.dbp_mean)
    const dbp_upper = data.visits.map(v => v.dbp_mean + v.dbp_std)
    const dbp_lower = data.visits.map(v => v.dbp_mean - v.dbp_std)

    return [
      // Systolic BP
      {
        x,
        y: sbp_y,
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Systolic BP',
        line: { color: 'rgb(211, 92, 101)', width: 2 },
        marker: { size: 8 },
      },
      {
        x: [...x, ...x.slice().reverse()],
        y: [...sbp_upper, ...sbp_lower.slice().reverse()],
        type: 'scatter',
        fill: 'toself',
        fillcolor: 'rgba(211, 92, 101, 0.2)',
        line: { width: 0 },
        showlegend: false,
        hoverinfo: 'skip',
      },
      // Diastolic BP
      {
        x,
        y: dbp_y,
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Diastolic BP',
        line: { color: 'rgb(8, 122, 106)', width: 2 },
        marker: { size: 8 },
      },
      {
        x: [...x, ...x.slice().reverse()],
        y: [...dbp_upper, ...dbp_lower.slice().reverse()],
        type: 'scatter',
        fill: 'toself',
        fillcolor: 'rgba(8, 122, 106, 0.2)',
        line: { width: 0 },
        showlegend: false,
        hoverinfo: 'skip',
      },
    ]
  }

  const createHRChart = (): Data[] => {
    if (!data?.visits || data.visits.length === 0) return []

    const x = data.visits.map(v => v.visit_num)
    const y = data.visits.map(v => v.hr_mean)
    const upper = data.visits.map(v => v.hr_mean + v.hr_std)
    const lower = data.visits.map(v => v.hr_mean - v.hr_std)

    return [
      {
        x,
        y,
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Heart Rate',
        line: { color: 'rgb(162, 91, 197)', width: 2 },
        marker: { size: 8 },
      },
      {
        x: [...x, ...x.slice().reverse()],
        y: [...upper, ...lower.slice().reverse()],
        type: 'scatter',
        fill: 'toself',
        fillcolor: 'rgba(162, 91, 197, 0.2)',
        line: { width: 0 },
        showlegend: false,
        hoverinfo: 'skip',
      },
    ]
  }

  return (
    <div className="mx-auto max-w-[1600px] px-6 py-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Clinical Timeline</h1>
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
          <p className="text-sm text-verily-ink/60">Loading clinical timeline...</p>
        </div>
      )}

      {error && (
        <div className="card p-4 border-verily-warm bg-verily-warm/10">
          <p className="text-sm text-verily-warm">
            Error loading clinical data: {error.message}
          </p>
        </div>
      )}

      {data && data.visits.length > 0 && (
        <div className="space-y-6">
          {/* Blood Pressure Timeline */}
          <div className="card p-6">
            <h2 className="text-lg font-medium mb-4">Blood Pressure by Visit</h2>
            <PlotlyChart
              data={createBPChart()}
              layout={{
                xaxis: {
                  title: 'Visit Number',
                  tickmode: 'linear',
                  tick0: 0,
                  dtick: 1,
                },
                yaxis: { title: 'Blood Pressure (mmHg)' },
                height: 500,
                shapes: [
                  {
                    type: 'line',
                    x0: data.visits[0].visit_num,
                    x1: data.visits[data.visits.length - 1].visit_num,
                    y0: 120,
                    y1: 120,
                    line: {
                      color: 'rgb(34, 197, 94)',
                      width: 1,
                      dash: 'dash',
                    },
                  },
                  {
                    type: 'line',
                    x0: data.visits[0].visit_num,
                    x1: data.visits[data.visits.length - 1].visit_num,
                    y0: 140,
                    y1: 140,
                    line: {
                      color: 'rgb(249, 115, 22)',
                      width: 1,
                      dash: 'dash',
                    },
                  },
                ],
                annotations: [
                  {
                    x: data.visits[data.visits.length - 1].visit_num,
                    y: 120,
                    xanchor: 'left',
                    yanchor: 'bottom',
                    text: 'Normal (<120 SBP)',
                    showarrow: false,
                    font: { size: 10, color: 'rgb(34, 197, 94)' },
                  },
                  {
                    x: data.visits[data.visits.length - 1].visit_num,
                    y: 140,
                    xanchor: 'left',
                    yanchor: 'bottom',
                    text: 'Stage 1 HTN (≥140 SBP)',
                    showarrow: false,
                    font: { size: 10, color: 'rgb(249, 115, 22)' },
                  },
                ],
              }}
              className="w-full"
            />
          </div>

          {/* Heart Rate Timeline */}
          <div className="card p-6">
            <h2 className="text-lg font-medium mb-4">Heart Rate by Visit</h2>
            <PlotlyChart
              data={createHRChart()}
              layout={{
                xaxis: {
                  title: 'Visit Number',
                  tickmode: 'linear',
                  tick0: 0,
                  dtick: 1,
                },
                yaxis: { title: 'Heart Rate (bpm)' },
                height: 400,
              }}
              className="w-full"
            />
          </div>

          {/* Visit Summary Table */}
          <div className="card p-6">
            <h2 className="text-lg font-medium mb-4">Visit Summary</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-verily-mute">
                  <tr>
                    <th className="text-left py-2 px-3 font-medium">Visit</th>
                    <th className="text-left py-2 px-3 font-medium">Study Day</th>
                    <th className="text-left py-2 px-3 font-medium">SBP (mmHg)</th>
                    <th className="text-left py-2 px-3 font-medium">DBP (mmHg)</th>
                    <th className="text-left py-2 px-3 font-medium">HR (bpm)</th>
                    <th className="text-left py-2 px-3 font-medium">N</th>
                  </tr>
                </thead>
                <tbody>
                  {data.visits.map((v) => (
                    <tr key={v.visit_num} className="border-b border-verily-mute/50">
                      <td className="py-2 px-3">{v.visit_name}</td>
                      <td className="py-2 px-3">{v.study_day_mean.toFixed(1)}</td>
                      <td className="py-2 px-3">
                        {v.sbp_mean.toFixed(1)} ± {v.sbp_std.toFixed(1)}
                      </td>
                      <td className="py-2 px-3">
                        {v.dbp_mean.toFixed(1)} ± {v.dbp_std.toFixed(1)}
                      </td>
                      <td className="py-2 px-3">
                        {v.hr_mean.toFixed(1)} ± {v.hr_std.toFixed(1)}
                      </td>
                      <td className="py-2 px-3">{v.count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {data && data.visits.length === 0 && (
        <div className="card p-6">
          <p className="text-sm text-verily-ink/60">
            No clinical visit data available for this cohort
          </p>
        </div>
      )}
    </div>
  )
}
