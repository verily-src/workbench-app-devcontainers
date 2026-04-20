import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useCohortFilter } from '../api/hooks'
import type { CohortFilters } from '../api/types'

// Top priority conditions to show by default
const PRIORITY_CONDITIONS = [
  { key: 'cad', label: 'Coronary Artery Disease', category: 'cardiovascular' },
  { key: 'chf', label: 'Congestive Heart Failure', category: 'cardiovascular' },
  { key: 'mi', label: 'Myocardial Infarction (Heart Attack)', category: 'cardiovascular' },
  { key: 'stroke', label: 'Stroke', category: 'cardiovascular' },
  { key: 'tia', label: 'TIA (Mini-Stroke)', category: 'cardiovascular' },
  { key: 'diab1', label: 'Type 1 Diabetes', category: 'metabolic' },
  { key: 'diab2', label: 'Type 2 Diabetes', category: 'metabolic' },
  { key: 'depression', label: 'Major Depression', category: 'mental_health' },
  { key: 'dementia', label: 'Dementia', category: 'mental_health' },
  { key: 'statin', label: 'Taking Statins', category: 'medications' },
]

// Additional filters available in dropdown
const ADDITIONAL_FILTERS = [
  { key: 'smoking_status', label: 'Smoking Status', category: 'demographics' },
  { key: 'pad', label: 'Peripheral Artery Disease', category: 'cardiovascular' },
  { key: 'vhd', label: 'Valvular Heart Disease', category: 'cardiovascular' },
  { key: 'prediabetes', label: 'Prediabetes', category: 'metabolic' },
  { key: 'sleepapnea', label: 'Sleep Apnea', category: 'metabolic' },
  { key: 'bipolar', label: 'Bipolar Disorder', category: 'mental_health' },
  { key: 'diabetes_med', label: 'Diabetes Medications', category: 'medications' },
]

export default function CohortSelector() {
  const navigate = useNavigate()
  const [filters, setFilters] = useState<CohortFilters>({})
  const [activeFilters, setActiveFilters] = useState<CohortFilters>({})
  const [additionalFilters, setAdditionalFilters] = useState<Record<string, string>>({})

  const { data, isLoading, error } = useCohortFilter(activeFilters, additionalFilters)

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
    setAdditionalFilters({})
    localStorage.removeItem('selectedCohort')
  }

  const handleToggleCondition = (key: string) => {
    setAdditionalFilters(prev => {
      const newFilters = { ...prev }
      if (newFilters[key]) {
        delete newFilters[key]
      } else {
        newFilters[key] = '1'
      }
      return newFilters
    })
  }

  const handleAddFilter = (key: string) => {
    if (!additionalFilters[key]) {
      setAdditionalFilters(prev => ({ ...prev, [key]: '1' }))
    }
  }

  const handleRemoveFilter = (key: string) => {
    setAdditionalFilters(prev => {
      const newFilters = { ...prev }
      delete newFilters[key]
      return newFilters
    })
  }

  const handleExportCsv = () => {
    if (!data || data.participants.length === 0) return

    const headers = ['USUBJID', 'Sex']
    const rows = data.participants.map(p => [
      p.usubjid,
      p.sex || '',
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

  const activeAdditionalFilters = ADDITIONAL_FILTERS.filter(f => !additionalFilters[f.key])

  return (
    <div className="mx-auto max-w-[1600px] px-6 py-6">
      <div className="mb-4">
        <h1 className="text-xl font-semibold">Cohort Selector</h1>
        <p className="text-sm text-verily-ink/60 mt-1">
          Filter participants by clinical labels to build your cohort
        </p>
      </div>

      <div className="card p-6">
        <h2 className="text-lg font-medium mb-4">Basic Filters</h2>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
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
            <label className="block text-sm font-medium mb-1">Disease (Legacy)</label>
            <select
              className="input w-full"
              value={filters.disease || ''}
              onChange={(e) => setFilters({ ...filters, disease: e.target.value || undefined })}
            >
              <option value="">Any</option>
              <option value="htn">Hypertension</option>
              <option value="diabetes">Diabetes (Any)</option>
              <option value="cvd">Cardiovascular Disease</option>
              <option value="ckd">Chronic Kidney Disease</option>
              <option value="afib">Atrial Fibrillation</option>
              <option value="copd">COPD</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium mb-1">Medication (Legacy)</label>
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

        <h3 className="text-md font-medium mb-3 mt-6">Important Conditions</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2 mb-6">
          {PRIORITY_CONDITIONS.map(condition => (
            <label key={condition.key} className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={!!additionalFilters[condition.key]}
                onChange={() => handleToggleCondition(condition.key)}
                className="rounded border-verily-mute"
              />
              <span className="text-sm">{condition.label}</span>
            </label>
          ))}
        </div>

        {Object.keys(additionalFilters).length > 0 && (
          <div className="mb-6">
            <h3 className="text-md font-medium mb-2">Active Additional Filters</h3>
            <div className="flex flex-wrap gap-2">
              {Object.entries(additionalFilters).map(([key, value]) => {
                const filter = [...PRIORITY_CONDITIONS, ...ADDITIONAL_FILTERS].find(f => f.key === key)
                if (!filter) return null
                return (
                  <div key={key} className="inline-flex items-center gap-1 px-3 py-1 bg-verily-primary/10 text-verily-primary rounded-full text-sm">
                    <span>{filter.label}</span>
                    <button
                      onClick={() => handleRemoveFilter(key)}
                      className="ml-1 hover:text-verily-primary/70"
                    >
                      ×
                    </button>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        <div className="mb-6">
          <label className="block text-sm font-medium mb-1">+ Add Filter</label>
          <select
            className="input w-full max-w-md"
            value=""
            onChange={(e) => {
              if (e.target.value) {
                handleAddFilter(e.target.value)
              }
            }}
          >
            <option value="">Choose a filter to add...</option>
            {activeAdditionalFilters.map(filter => (
              <option key={filter.key} value={filter.key}>
                {filter.label} ({filter.category})
              </option>
            ))}
          </select>
        </div>

        <div className="flex gap-3">
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
                  </tr>
                </thead>
                <tbody>
                  {data.participants.slice(0, 100).map((p) => (
                    <tr key={p.usubjid} className="border-b border-verily-mute/50">
                      <td className="py-2 px-3 font-mono text-xs">{p.usubjid}</td>
                      <td className="py-2 px-3">{p.sex || '-'}</td>
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
