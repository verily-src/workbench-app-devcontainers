import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useCohortFilter } from '../api/hooks'
import type { CohortFilters } from '../api/types'

export default function CohortSelector() {
  const navigate = useNavigate()
  const [filters, setFilters] = useState<CohortFilters>({})
  const [activeFilters, setActiveFilters] = useState<CohortFilters>({})

  const { data, isLoading, error } = useCohortFilter(activeFilters)

  // Store selected cohort in localStorage for other pages
  useEffect(() => {
    if (data && data.participants.length > 0) {
      const cohortIds = data.participants.map(p => p.usubjid)
      localStorage.setItem('selectedCohort', JSON.stringify(cohortIds))
    }
  }, [data])

  const handleApply = () => {
    setActiveFilters({ ...filters })
  }

  const handleReset = () => {
    setFilters({})
    setActiveFilters({})
    localStorage.removeItem('selectedCohort')
  }

  const handleExportCsv = () => {
    if (!data || data.participants.length === 0) return

    const headers = ['USUBJID', 'Sex', 'Age', 'Race']
    const rows = data.participants.map(p => [
      p.usubjid,
      p.sex || '',
      p.age_at_enrollment?.toString() || '',
      p.race || '',
    ])

    const csv = [headers, ...rows].map(row => row.join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `cohort_${data.cohort_id}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="mx-auto max-w-[1600px] px-6 py-6">
      <div className="mb-4">
        <h1 className="text-xl font-semibold">Cohort Selector</h1>
        <p className="text-sm text-verily-ink/60 mt-1">
          Filter participants by clinical labels to build your cohort
        </p>
      </div>

      <div className="card p-6">
        <h2 className="text-lg font-medium mb-4">Filters</h2>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <div>
            <label className="block text-sm font-medium mb-1">Sex</label>
            <select
              className="input w-full"
              value={filters.sex || ''}
              onChange={(e) => setFilters({ ...filters, sex: e.target.value || undefined })}
            >
              <option value="">Any</option>
              <option value="Female">Female</option>
              <option value="Male">Male</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Min Age</label>
            <input
              type="number"
              className="input w-full"
              placeholder="18"
              value={filters.min_age ?? ''}
              onChange={(e) => setFilters({ ...filters, min_age: e.target.value ? Number(e.target.value) : undefined })}
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Max Age</label>
            <input
              type="number"
              className="input w-full"
              placeholder="90"
              value={filters.max_age ?? ''}
              onChange={(e) => setFilters({ ...filters, max_age: e.target.value ? Number(e.target.value) : undefined })}
            />
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Disease</label>
            <select
              className="input w-full"
              value={filters.disease || ''}
              onChange={(e) => setFilters({ ...filters, disease: e.target.value || undefined })}
            >
              <option value="">Any</option>
              <option value="htn">Hypertension</option>
              <option value="diabetes">Diabetes</option>
              <option value="cvd">Cardiovascular Disease</option>
              <option value="ckd">Chronic Kidney Disease</option>
              <option value="afib">Atrial Fibrillation</option>
              <option value="copd">COPD</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Medication</label>
            <select
              className="input w-full"
              value={filters.medication || ''}
              onChange={(e) => setFilters({ ...filters, medication: e.target.value || undefined })}
            >
              <option value="">Any</option>
              <option value="acei">ACE Inhibitors</option>
              <option value="arb">ARBs</option>
              <option value="bb">Beta Blockers</option>
              <option value="ccb">Calcium Channel Blockers</option>
              <option value="diuretics">Diuretics</option>
            </select>
          </div>
        </div>

        <div className="mt-6 flex gap-3">
          <button className="btn-primary" onClick={handleApply} disabled={isLoading}>
            {isLoading ? 'Loading...' : 'Apply Filters'}
          </button>
          <button className="btn-ghost" onClick={handleReset}>
            Reset
          </button>
        </div>
      </div>

      {error && (
        <div className="card p-4 mt-6 border-verily-warm bg-verily-warm/10">
          <p className="text-sm text-verily-warm">
            Error loading cohort: {error.message}
          </p>
        </div>
      )}

      {data && (
        <div className="card p-6 mt-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-medium">
              Cohort Results
              <span className="ml-2 text-sm font-normal text-verily-ink/60">
                ({data.total_participants} participants)
              </span>
            </h2>
            <div className="flex gap-2">
              <button
                className="btn-ghost text-xs"
                onClick={handleExportCsv}
                disabled={data.participants.length === 0}
              >
                ⬇ Export CSV
              </button>
              <button
                className="btn-primary text-xs"
                onClick={() => navigate('/device')}
                disabled={data.participants.length === 0}
              >
                View Device Data →
              </button>
            </div>
          </div>

          {data.participants.length === 0 ? (
            <p className="text-sm text-verily-ink/60">
              No participants match the selected filters
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-verily-mute">
                  <tr>
                    <th className="text-left py-2 px-3 font-medium">USUBJID</th>
                    <th className="text-left py-2 px-3 font-medium">Sex</th>
                    <th className="text-left py-2 px-3 font-medium">Age</th>
                    <th className="text-left py-2 px-3 font-medium">Race</th>
                  </tr>
                </thead>
                <tbody>
                  {data.participants.slice(0, 100).map((p) => (
                    <tr key={p.usubjid} className="border-b border-verily-mute/50">
                      <td className="py-2 px-3 font-mono text-xs">{p.usubjid}</td>
                      <td className="py-2 px-3">{p.sex || '-'}</td>
                      <td className="py-2 px-3">{p.age_at_enrollment ?? '-'}</td>
                      <td className="py-2 px-3">{p.race || '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.participants.length > 100 && (
                <p className="text-xs text-verily-ink/60 mt-2">
                  Showing first 100 of {data.total_participants} participants
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
