import { useState, useEffect } from 'react'
import { useData } from '../context/DataContext'
import Plot from 'react-plotly.js'
import Plotly from 'plotly.js-dist-min'

export default function Passport() {
  const { passportMetrics, timeline, isLoading } = useData()
  const [enrollDateRange, setEnrollDateRange] = useState<[string, string] | null>(null)
  const [minCompleteness, setMinCompleteness] = useState(0)
  const [cumulativeTimeline, setCumulativeTimeline] = useState<any[]>([])
  const [filteredMetrics, setFilteredMetrics] = useState<any>(null)
  const [isFiltering, setIsFiltering] = useState(false)

  // Load cumulative enrollment timeline
  useEffect(() => {
    fetch('/dashboard/api/passport/cumulative-enrollment')
      .then(r => r.json())
      .then(data => setCumulativeTimeline(data.timeline))
      .catch(err => console.error('Failed to load cumulative enrollment:', err))
  }, [])

  // Apply filters
  useEffect(() => {
    if (!enrollDateRange && minCompleteness === 0) {
      setFilteredMetrics(null)
      return
    }

    setIsFiltering(true)
    const params = new URLSearchParams()
    if (enrollDateRange) {
      params.append('enroll_start', enrollDateRange[0])
      params.append('enroll_end', enrollDateRange[1])
    }
    if (minCompleteness > 0) {
      params.append('min_completeness_pct', minCompleteness.toString())
    }

    const timer = setTimeout(() => {
      fetch(`/dashboard/api/passport/filter?${params}`)
        .then(r => r.json())
        .then(data => {
          setFilteredMetrics(data)
          setIsFiltering(false)
        })
        .catch(err => {
          console.error('Filter failed:', err)
          setIsFiltering(false)
        })
    }, 500)

    return () => clearTimeout(timer)
  }, [enrollDateRange, minCompleteness])

  if (isLoading) {
    return (
      <div style={{ color: 'rgba(26, 26, 26, 0.6)' }}>
        Loading passport data...
      </div>
    )
  }

  const displayCount = filteredMetrics ? filteredMetrics.filtered_participants : (passportMetrics?.total_participants || 2502)
  const domainData = filteredMetrics ? filteredMetrics.domains : passportMetrics?.domains || []

  return (
    <div>
      <div style={{
        backgroundColor: '#fff',
        borderRadius: '12px',
        padding: '24px',
        marginBottom: '24px',
        boxShadow: '0 2px 4px rgba(0,0,0,0.08)',
        border: '1px solid #e9e4d8'
      }}>
        <h2 style={{
          fontSize: '24px',
          fontWeight: 600,
          color: '#1a1a1a',
          marginBottom: '8px'
        }}>
          Dataset Passport
        </h2>
        <p style={{ color: 'rgba(26, 26, 26, 0.6)', fontSize: '14px', marginBottom: '24px' }}>
          High-level overview of dataset provenance, structure, and coverage
        </p>

        {/* Current N Display */}
        <div style={{
          marginBottom: '32px',
          padding: '20px',
          backgroundColor: '#f5f2ea',
          border: '2px solid #e9e4d8',
          borderRadius: '8px'
        }}>
          <div style={{ fontSize: '12px', color: 'rgba(26, 26, 26, 0.6)', marginBottom: '8px', textTransform: 'uppercase', fontWeight: 600 }}>
            Current Analysis Cohort
          </div>
          <div style={{ fontSize: '48px', fontWeight: 600, color: '#087A6A', lineHeight: 1.1 }}>
            N = {isFiltering ? '...' : displayCount.toLocaleString()}
          </div>
          {filteredMetrics && (
            <div style={{ fontSize: '14px', color: 'rgba(26, 26, 26, 0.6)', marginTop: '8px' }}>
              Filtered from {passportMetrics?.total_participants.toLocaleString() || '2,502'} total patients
              {minCompleteness > 0 && ` (≥${minCompleteness}% data completeness)`}
            </div>
          )}
        </div>

        {/* Enrollment Timeline with Range Selector */}
        {timeline && timeline.length > 0 && (
          <div style={{ marginBottom: '32px' }}>
            <h3 style={{
              fontSize: '18px',
              fontWeight: 600,
              color: '#1a1a1a',
              marginBottom: '16px'
            }}>
              Enrollment Timeline
            </h3>
            <p style={{
              fontSize: '13px',
              color: 'rgba(26, 26, 26, 0.6)',
              marginBottom: '12px'
            }}>
              Drag the range selector below to restrict the analysis window
            </p>
            <Plot
              plotly={Plotly}
              data={[
                {
                  x: timeline.map(t => t.month),
                  y: timeline.map(t => t.count),
                  type: 'scatter',
                  mode: 'lines+markers',
                  marker: { color: '#087A6A' },
                  line: { color: '#087A6A' },
                },
              ]}
              layout={{
                width: 900,
                height: 350,
                margin: { t: 20, r: 20, b: 100, l: 60 },
                xaxis: {
                  title: 'Enrollment Month',
                  rangeslider: { visible: true },
                  rangeselector: {
                    buttons: [
                      { count: 6, label: '6m', step: 'month', stepmode: 'backward' },
                      { count: 1, label: '1y', step: 'year', stepmode: 'backward' },
                      { step: 'all', label: 'All' }
                    ]
                  }
                },
                yaxis: { title: 'New Enrollments' },
                plot_bgcolor: '#f5f2ea',
                paper_bgcolor: '#fff',
              }}
              config={{ displayModeBar: false }}
              onRelayout={(e: any) => {
                if (e['xaxis.range[0]'] && e['xaxis.range[1]']) {
                  const start = e['xaxis.range[0]'].split(' ')[0]
                  const end = e['xaxis.range[1]'].split(' ')[0]
                  setEnrollDateRange([start, end])
                } else if (e['xaxis.range']) {
                  // Reset to full range
                  setEnrollDateRange(null)
                }
              }}
            />
            {enrollDateRange && (
              <div style={{
                marginTop: '12px',
                padding: '12px 16px',
                backgroundColor: 'rgba(8, 122, 106, 0.05)',
                border: '1px solid rgba(8, 122, 106, 0.2)',
                borderRadius: '6px',
                fontSize: '14px',
                color: '#087A6A',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center'
              }}>
                <span>
                  Restricted to enrollments between {enrollDateRange[0]} and {enrollDateRange[1]}
                </span>
                <button
                  onClick={() => setEnrollDateRange(null)}
                  style={{
                    padding: '4px 12px',
                    backgroundColor: '#087A6A',
                    color: '#fff',
                    border: 'none',
                    borderRadius: '4px',
                    fontSize: '12px',
                    fontWeight: 600,
                    cursor: 'pointer'
                  }}
                >
                  Reset
                </button>
              </div>
            )}
          </div>
        )}

        {/* Cumulative Enrollment Graph */}
        {cumulativeTimeline && cumulativeTimeline.length > 0 && (
          <div style={{ marginBottom: '32px' }}>
            <h3 style={{
              fontSize: '18px',
              fontWeight: 600,
              color: '#1a1a1a',
              marginBottom: '16px'
            }}>
              Cumulative Enrollment Over Time
            </h3>
            <p style={{
              fontSize: '13px',
              color: 'rgba(26, 26, 26, 0.6)',
              marginBottom: '12px'
            }}>
              Total number of participants enrolled from study start to present
            </p>
            <Plot
              plotly={Plotly}
              data={[
                {
                  x: cumulativeTimeline.map(t => t.month),
                  y: cumulativeTimeline.map(t => t.cumulative_count),
                  type: 'scatter',
                  mode: 'lines',
                  fill: 'tozeroy',
                  marker: { color: '#087A6A' },
                  line: { color: '#087A6A', width: 3 },
                },
              ]}
              layout={{
                width: 900,
                height: 300,
                margin: { t: 20, r: 20, b: 60, l: 60 },
                xaxis: { title: 'Month' },
                yaxis: { title: 'Total Enrolled Participants' },
                plot_bgcolor: '#f5f2ea',
                paper_bgcolor: '#fff',
              }}
              config={{ displayModeBar: false }}
            />
          </div>
        )}

        {/* Minimum Completeness Slider */}
        <div style={{ marginBottom: '32px' }}>
          <h3 style={{
            fontSize: '18px',
            fontWeight: 600,
            color: '#1a1a1a',
            marginBottom: '8px'
          }}>
            Minimum Data Completeness Threshold
          </h3>
          <p style={{
            fontSize: '13px',
            color: 'rgba(26, 26, 26, 0.6)',
            marginBottom: '12px'
          }}>
            Remove participants with less than this percentage of data completeness. Completeness = % of 6 data domains they have.
          </p>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <input
              type="range"
              min="0"
              max="100"
              step="10"
              value={minCompleteness}
              onChange={(e) => setMinCompleteness(parseInt(e.target.value))}
              style={{
                flex: 1,
                height: '8px',
                borderRadius: '4px',
                outline: 'none',
                background: `linear-gradient(to right, #087A6A 0%, #087A6A ${minCompleteness}%, #e9e4d8 ${minCompleteness}%, #e9e4d8 100%)`
              }}
            />
            <div style={{
              minWidth: '100px',
              padding: '8px 16px',
              backgroundColor: '#f5f2ea',
              border: '1px solid #e9e4d8',
              borderRadius: '6px',
              fontSize: '16px',
              fontWeight: 600,
              color: '#087A6A',
              textAlign: 'center'
            }}>
              {minCompleteness}%
            </div>
          </div>
          {minCompleteness > 0 && (
            <button
              onClick={() => setMinCompleteness(0)}
              style={{
                marginTop: '12px',
                padding: '6px 16px',
                backgroundColor: 'transparent',
                color: '#087A6A',
                border: '1px solid #087A6A',
                borderRadius: '4px',
                fontSize: '13px',
                fontWeight: 600,
                cursor: 'pointer'
              }}
            >
              Reset to 0%
            </button>
          )}
        </div>

        {/* Domain Coverage - Always Show */}
        <div style={{
          backgroundColor: '#f5f2ea',
          border: '1px solid #e9e4d8',
          borderRadius: '6px',
          padding: '20px'
        }}>
          <h3 style={{
            fontSize: '16px',
            fontWeight: 600,
            color: '#1a1a1a',
            marginBottom: '16px'
          }}>
            Data Domain Coverage
            <span style={{ fontWeight: 400, fontSize: '14px', color: 'rgba(26, 26, 26, 0.6)', marginLeft: '8px' }}>
              ({filteredMetrics ? 'filtered cohort' : 'full cohort'})
            </span>
          </h3>
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: '12px'
          }}>
            {domainData.map((domain: any) => (
              <DomainCard key={domain.name} domain={domain} />
            ))}
          </div>
          <p style={{
            marginTop: '16px',
            fontSize: '13px',
            color: 'rgba(26, 26, 26, 0.6)',
            fontStyle: 'italic'
          }}>
            Coverage shows percentage of {displayCount.toLocaleString()} participants with at least one record in each domain
          </p>
        </div>
      </div>
    </div>
  )
}

function DomainCard({ domain }: { domain: { name: string; participants: number; coverage_pct: number } }) {
  const isGoodCoverage = domain.coverage_pct >= 80
  const isModerateCoverage = domain.coverage_pct >= 50 && domain.coverage_pct < 80

  return (
    <div style={{
      backgroundColor: '#fff',
      border: '1px solid #e9e4d8',
      borderRadius: '6px',
      padding: '12px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between'
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <div style={{
          width: '20px',
          height: '20px',
          borderRadius: '4px',
          backgroundColor: isGoodCoverage ? '#087A6A' : isModerateCoverage ? '#A25BC5' : '#e9e4d8',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0
        }}>
          {isGoodCoverage && (
            <span style={{ color: '#fff', fontSize: '14px', fontWeight: 'bold' }}>✓</span>
          )}
        </div>
        <div>
          <div style={{
            fontSize: '14px',
            fontWeight: 600,
            color: '#1a1a1a'
          }}>
            {domain.name}
          </div>
          <div style={{
            fontSize: '12px',
            color: 'rgba(26, 26, 26, 0.6)'
          }}>
            {domain.participants.toLocaleString()} patients
          </div>
        </div>
      </div>
      <div style={{
        fontSize: '18px',
        fontWeight: 600,
        color: isGoodCoverage ? '#087A6A' : isModerateCoverage ? '#A25BC5' : 'rgba(26, 26, 26, 0.4)'
      }}>
        {domain.coverage_pct}%
      </div>
    </div>
  )
}
