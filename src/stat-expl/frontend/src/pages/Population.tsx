import { useState, useEffect } from 'react'
import { useCohort } from '../context/CohortContext'
import Plot from 'react-plotly.js'
import Plotly from 'plotly.js-dist-min'

interface Demographics {
  total_participants: number
  mean_age: number
  min_age: number
  max_age: number
  male_count: number
  female_count: number
  age_distribution: { age_group: string; count: number }[]
  enrollment_start: string
  enrollment_end: string
}

export default function Population() {
  const { filters, setFilters } = useCohort()
  const [demographics, setDemographics] = useState<Demographics | null>(null)

  useEffect(() => {
    fetch('/dashboard/api/demographics')
      .then(r => r.json())
      .then(d => setDemographics(d))
      .catch(e => console.error('Demographics fetch failed:', e))
  }, [])

  // Calculate filtered count (simple client-side estimation)
  const getFilteredCount = () => {
    if (!demographics) return 0
    if (!filters.ageMin && !filters.ageMax && filters.sex === 'all') {
      return demographics.total_participants
    }
    // Rough estimation based on filters
    let estimate = demographics.total_participants
    if (filters.sex === 'M') estimate = demographics.male_count
    if (filters.sex === 'F') estimate = demographics.female_count
    if (filters.ageMin || filters.ageMax) estimate = Math.round(estimate * 0.7) // rough filter
    return estimate
  }

  return (
    <div>
      <div style={{
        backgroundColor: '#fff',
        borderRadius: '8px',
        padding: '24px',
        marginBottom: '24px',
        boxShadow: '0 1px 3px rgba(0,0,0,0.1)'
      }}>
        <h2 style={{
          fontSize: '24px',
          fontWeight: 600,
          color: '#1e293b',
          marginBottom: '8px'
        }}>
          Population
        </h2>
        <p style={{ color: '#64748b', fontSize: '14px', marginBottom: '24px' }}>
          Demographic breakdown, enrollment patterns, and cohort definitions
        </p>

        {/* Cohort Filters */}
        <div style={{
          backgroundColor: '#eff6ff',
          border: '1px solid #bfdbfe',
          borderRadius: '6px',
          padding: '16px',
          marginBottom: '24px'
        }}>
          <h3 style={{ fontSize: '14px', fontWeight: 600, color: '#1e40af', marginBottom: '12px' }}>
            Cohort Filters
          </h3>
          <div style={{ display: 'flex', gap: '16px', alignItems: 'end', flexWrap: 'wrap' }}>
            <div>
              <label style={{ display: 'block', fontSize: '12px', color: '#64748b', marginBottom: '4px' }}>
                Age Range
              </label>
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                <input
                  type="number"
                  placeholder="Min"
                  value={filters.ageMin || ''}
                  onChange={e => setFilters({ ...filters, ageMin: parseInt(e.target.value) || undefined })}
                  style={{
                    width: '80px',
                    padding: '6px 12px',
                    border: '1px solid #cbd5e1',
                    borderRadius: '4px',
                    fontSize: '14px'
                  }}
                />
                <span style={{ color: '#64748b' }}>–</span>
                <input
                  type="number"
                  placeholder="Max"
                  value={filters.ageMax || ''}
                  onChange={e => setFilters({ ...filters, ageMax: parseInt(e.target.value) || undefined })}
                  style={{
                    width: '80px',
                    padding: '6px 12px',
                    border: '1px solid #cbd5e1',
                    borderRadius: '4px',
                    fontSize: '14px'
                  }}
                />
              </div>
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '12px', color: '#64748b', marginBottom: '4px' }}>
                Sex
              </label>
              <select
                value={filters.sex || 'all'}
                onChange={e => setFilters({ ...filters, sex: e.target.value as any })}
                style={{
                  padding: '6px 12px',
                  border: '1px solid #cbd5e1',
                  borderRadius: '4px',
                  fontSize: '14px',
                  backgroundColor: '#fff'
                }}
              >
                <option value="all">All</option>
                <option value="M">Male</option>
                <option value="F">Female</option>
              </select>
            </div>
          </div>
        </div>

        {demographics ? (
          <>
            {/* Demographics Overview */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '16px', marginBottom: '24px' }}>
              <MetricCard label="Total Participants" value={demographics.total_participants.toLocaleString()} />
              <MetricCard label="Mean Age" value={`${demographics.mean_age} years`} />
              <MetricCard label="Enrollment Period" value={`${demographics.enrollment_start?.slice(0, 4)}-${demographics.enrollment_end?.slice(0, 4)}`} />
              <MetricCard label="Filtered Cohort" value={getFilteredCount().toLocaleString()} />
            </div>

            {/* Age Distribution Chart */}
            <div style={{
              backgroundColor: '#fff',
              border: '1px solid #e2e8f0',
              borderRadius: '6px',
              padding: '16px',
              marginBottom: '24px'
            }}>
              <h3 style={{ fontSize: '16px', fontWeight: 600, color: '#1e293b', marginBottom: '12px' }}>
                Age Distribution
              </h3>
              <Plot
                plotly={Plotly}
                data={[
                  {
                    x: demographics.age_distribution.map(d => d.age_group),
                    y: demographics.age_distribution.map(d => d.count),
                    type: 'bar',
                    marker: { color: '#3b82f6' },
                    name: 'Participants'
                  },
                ]}
                layout={{
                  width: 800,
                  height: 300,
                  margin: { t: 20, r: 20, b: 40, l: 60 },
                  xaxis: { title: 'Age Group' },
                  yaxis: { title: 'Count' },
                  plot_bgcolor: '#f8fafc',
                  paper_bgcolor: '#fff',
                }}
                config={{ displayModeBar: false }}
              />
            </div>

            {/* Sex Distribution */}
            <div style={{
              backgroundColor: '#fff',
              border: '1px solid #e2e8f0',
              borderRadius: '6px',
              padding: '16px'
            }}>
              <h3 style={{ fontSize: '16px', fontWeight: 600, color: '#1e293b', marginBottom: '12px' }}>
                Sex Distribution
              </h3>
              <Plot
                plotly={Plotly}
                data={[
                  {
                    labels: ['Female', 'Male'],
                    values: [demographics.female_count, demographics.male_count],
                    type: 'pie',
                    marker: { colors: ['#ec4899', '#3b82f6'] },
                  },
                ]}
                layout={{
                  width: 500,
                  height: 300,
                  margin: { t: 20, r: 20, b: 20, l: 20 },
                  showlegend: true,
                  paper_bgcolor: '#fff',
                }}
                config={{ displayModeBar: false }}
              />
            </div>
          </>
        ) : (
          <p style={{ color: '#64748b' }}>Loading demographics...</p>
        )}
      </div>
    </div>
  )
}

function MetricCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div style={{
      backgroundColor: '#f8fafc',
      border: '1px solid #e2e8f0',
      borderRadius: '6px',
      padding: '16px'
    }}>
      <div style={{ fontSize: '12px', color: '#64748b', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
        {label}
      </div>
      <div style={{ fontSize: '20px', fontWeight: 600, color: '#1e293b' }}>
        {value}
      </div>
    </div>
  )
}
