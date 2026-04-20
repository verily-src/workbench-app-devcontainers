import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDeviceData, useIndividualData, useParticipantsWithData } from '../api/hooks'
import PlotlyChart from '../components/PlotlyChart'
import type { Data } from 'plotly.js'

export default function DeviceData() {
  const navigate = useNavigate()
  const [cohortIds, setCohortIds] = useState<string[]>([])
  const [minDay, setMinDay] = useState<number | undefined>(undefined)
  const [maxDay, setMaxDay] = useState<number | undefined>(undefined)
  const [selectedParticipant, setSelectedParticipant] = useState<string | null>(null)

  useEffect(() => {
    const stored = localStorage.getItem('selectedCohort')
    if (stored) {
      setCohortIds(JSON.parse(stored))
    }
  }, [])

  const { data: participantsWithData } = useParticipantsWithData(cohortIds)
  const { data, isLoading, error } = useDeviceData(cohortIds, minDay, maxDay)
  const { data: individualData } = useIndividualData(
    selectedParticipant,
    'steps,sleep,sleep_rem,sleep_deep,sleep_light,hrv',
    minDay,
    maxDay
  )

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

    const traces: Data[] = [
      {
        x,
        y,
        type: 'scatter',
        mode: 'lines+markers',
        name: 'Cohort Mean',
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

    // Add individual participant overlay if selected
    if (selectedParticipant && individualData?.metrics[metricName]) {
      const individualPoints = individualData.metrics[metricName]
      traces.push({
        x: individualPoints.map(p => p.study_day),
        y: individualPoints.map(p => p.value),
        type: 'scatter',
        mode: 'lines+markers',
        name: `Participant ${selectedParticipant}`,
        line: { color: 'rgb(255, 159, 28)', width: 2, dash: 'dash' },
        marker: { size: 5 },
      })
    }

    return traces
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
            {participantsWithData && ` (${participantsWithData.participants.length} with sensor data)`}
          </p>
        </div>
        <button
          onClick={() => navigate('/cohort')}
          className="btn-ghost text-xs"
        >
          ← Change Cohort
        </button>
      </div>

      {/* Filters */}
      <div className="card p-6 mb-6">
        <h2 className="text-md font-medium mb-3">Filters</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-sm font-medium mb-1">Min Study Day</label>
            <input
              type="number"
              className="input w-full"
              placeholder="e.g., 0"
              value={minDay ?? ''}
              onChange={(e) => setMinDay(e.target.value ? parseInt(e.target.value) : undefined)}
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Max Study Day</label>
            <input
              type="number"
              className="input w-full"
              placeholder="e.g., 365"
              value={maxDay ?? ''}
              onChange={(e) => setMaxDay(e.target.value ? parseInt(e.target.value) : undefined)}
            />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Compare Individual Participant</label>
            <select
              className="input w-full"
              value={selectedParticipant ?? ''}
              onChange={(e) => setSelectedParticipant(e.target.value || null)}
            >
              <option value="">None (cohort average only)</option>
              {participantsWithData?.participants.map(p => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>
        </div>
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

          {/* Sleep Duration - Total */}
          {data.metrics.sleep && data.metrics.sleep.length > 0 && (
            <div className="card p-6">
              <h2 className="text-lg font-medium mb-4">Total Sleep Duration</h2>
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

          {/* Sleep Stages - REM */}
          {data.metrics.sleep_rem && data.metrics.sleep_rem.length > 0 && (
            <div className="card p-6">
              <h2 className="text-lg font-medium mb-4">REM Sleep</h2>
              <PlotlyChart
                data={createMetricChart('sleep_rem', 'Minutes', 'rgb(147, 51, 234)')}
                layout={{
                  xaxis: { title: 'Study Day' },
                  yaxis: { title: 'REM Sleep (minutes)' },
                  height: 400,
                }}
                className="w-full"
              />
            </div>
          )}

          {/* Sleep Stages - Deep */}
          {data.metrics.sleep_deep && data.metrics.sleep_deep.length > 0 && (
            <div className="card p-6">
              <h2 className="text-lg font-medium mb-4">Deep Sleep</h2>
              <PlotlyChart
                data={createMetricChart('sleep_deep', 'Minutes', 'rgb(79, 70, 229)')}
                layout={{
                  xaxis: { title: 'Study Day' },
                  yaxis: { title: 'Deep Sleep (minutes)' },
                  height: 400,
                }}
                className="w-full"
              />
            </div>
          )}

          {/* Sleep Stages - Light */}
          {data.metrics.sleep_light && data.metrics.sleep_light.length > 0 && (
            <div className="card p-6">
              <h2 className="text-lg font-medium mb-4">Light Sleep</h2>
              <PlotlyChart
                data={createMetricChart('sleep_light', 'Minutes', 'rgb(168, 162, 251)')}
                layout={{
                  xaxis: { title: 'Study Day' },
                  yaxis: { title: 'Light Sleep (minutes)' },
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
