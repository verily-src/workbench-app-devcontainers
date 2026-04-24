import { useState, useEffect } from 'react'

interface Variable {
  name: string
  column: string
  domain: string
  type: string
  unit: string
  patient_coverage_pct: number
  patients_with_data: number
  median_measurements_per_patient: number
  total_measurements: number
  median_value: number | null
  value_range: string | null
  distribution: {
    min: number
    q25: number
    median: number
    q75: number
    max: number
  } | null
  sensor_metrics?: {
    median_wear_days: number
    pct_7_consecutive_days: number
    pct_30_consecutive_days: number
  }
}

export default function Variables() {
  const [variables, setVariables] = useState<Variable[]>([])
  const [filteredVariables, setFilteredVariables] = useState<Variable[]>([])
  const [completenessThreshold, setCompletenessThreshold] = useState(0)
  const [minMeasurements, setMinMeasurements] = useState(0)
  const [searchQuery, setSearchQuery] = useState('')
  const [expandedVar, setExpandedVar] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // Load variables
  useEffect(() => {
    fetch('/dashboard/api/variables/comprehensive')
      .then(r => r.json())
      .then(data => {
        setVariables(data.variables)
        setFilteredVariables(data.variables)
        setIsLoading(false)
      })
      .catch(err => {
        console.error('Failed to load variables:', err)
        setIsLoading(false)
      })
  }, [])

  // Apply filters
  useEffect(() => {
    let filtered = variables.filter(v =>
      v.patient_coverage_pct >= completenessThreshold &&
      v.median_measurements_per_patient >= minMeasurements
    )

    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase()
      filtered = filtered.filter(v =>
        v.name.toLowerCase().includes(query) ||
        v.domain.toLowerCase().includes(query)
      )
    }

    setFilteredVariables(filtered)
  }, [variables, completenessThreshold, minMeasurements, searchQuery])

  if (isLoading) {
    return <div style={{ color: 'rgba(26, 26, 26, 0.6)' }}>Loading variables...</div>
  }

  const domains = Array.from(new Set(filteredVariables.map(v => v.domain)))
  const usableCount = filteredVariables.length
  const totalCount = variables.length

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
          Variable Catalog
        </h2>
        <p style={{ color: 'rgba(26, 26, 26, 0.6)', fontSize: '14px', marginBottom: '24px' }}>
          Comprehensive data dictionary with coverage, measurement frequency, and distributions
        </p>

        {/* Search Bar */}
        <div style={{ marginBottom: '24px' }}>
          <label style={{
            display: 'block',
            fontSize: '14px',
            fontWeight: 600,
            color: '#1a1a1a',
            marginBottom: '8px'
          }}>
            Search by Clinical Concept or Variable Name
          </label>
          <input
            type="text"
            placeholder="e.g., kidney function, blood pressure, diabetes..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              width: '100%',
              padding: '12px 16px',
              fontSize: '16px',
              border: '2px solid #e9e4d8',
              borderRadius: '8px',
              outline: 'none'
            }}
            onFocus={(e) => e.currentTarget.style.borderColor = '#087A6A'}
            onBlur={(e) => e.currentTarget.style.borderColor = '#e9e4d8'}
          />
        </div>

        {/* Filter Controls */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(2, 1fr)',
          gap: '24px',
          marginBottom: '24px',
          padding: '20px',
          backgroundColor: '#f5f2ea',
          borderRadius: '8px'
        }}>
          {/* Completeness Threshold */}
          <div>
            <label style={{
              fontSize: '14px',
              fontWeight: 600,
              color: '#1a1a1a',
              marginBottom: '8px',
              display: 'block'
            }}>
              Completeness Threshold: {completenessThreshold}%
            </label>
            <input
              type="range"
              min="0"
              max="100"
              step="5"
              value={completenessThreshold}
              onChange={(e) => setCompletenessThreshold(parseInt(e.target.value))}
              style={{
                width: '100%',
                height: '8px',
                borderRadius: '4px',
                outline: 'none',
                background: `linear-gradient(to right, #087A6A 0%, #087A6A ${completenessThreshold}%, #e9e4d8 ${completenessThreshold}%, #e9e4d8 100%)`
              }}
            />
            <p style={{
              fontSize: '12px',
              color: 'rgba(26, 26, 26, 0.6)',
              marginTop: '8px'
            }}>
              Show only variables with ≥{completenessThreshold}% patient coverage
            </p>
          </div>

          {/* Minimum Measurements */}
          <div>
            <label style={{
              fontSize: '14px',
              fontWeight: 600,
              color: '#1a1a1a',
              marginBottom: '8px',
              display: 'block'
            }}>
              Minimum Measurements: {minMeasurements}
            </label>
            <input
              type="range"
              min="0"
              max="20"
              step="1"
              value={minMeasurements}
              onChange={(e) => setMinMeasurements(parseInt(e.target.value))}
              style={{
                width: '100%',
                height: '8px',
                borderRadius: '4px',
                outline: 'none',
                background: `linear-gradient(to right, #087A6A 0%, #087A6A ${(minMeasurements / 20) * 100}%, #e9e4d8 ${(minMeasurements / 20) * 100}%, #e9e4d8 100%)`
              }}
            />
            <p style={{
              fontSize: '12px',
              color: 'rgba(26, 26, 26, 0.6)',
              marginTop: '8px'
            }}>
              Show only variables with ≥{minMeasurements} median measurements per patient
            </p>
          </div>
        </div>

        {/* Results Summary */}
        <div style={{
          padding: '16px',
          backgroundColor: 'rgba(8, 122, 106, 0.05)',
          border: '1px solid rgba(8, 122, 106, 0.2)',
          borderRadius: '6px',
          marginBottom: '32px',
          fontSize: '14px',
          color: '#087A6A',
          fontWeight: 600
        }}>
          Showing {usableCount} usable variables of {totalCount} total
          {(completenessThreshold > 0 || minMeasurements > 0) && (
            <button
              onClick={() => {
                setCompletenessThreshold(0)
                setMinMeasurements(0)
              }}
              style={{
                marginLeft: '16px',
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
              Reset Filters
            </button>
          )}
        </div>

        {/* Variables Grid by Domain */}
        {domains.map(domain => {
          const domainVars = filteredVariables.filter(v => v.domain === domain)
          if (domainVars.length === 0) return null

          return (
            <div key={domain} style={{ marginBottom: '32px' }}>
              <h3 style={{
                fontSize: '18px',
                fontWeight: 600,
                color: '#1a1a1a',
                marginBottom: '16px',
                paddingBottom: '8px',
                borderBottom: '2px solid #087A6A'
              }}>
                {domain}
                <span style={{
                  fontSize: '14px',
                  fontWeight: 400,
                  color: 'rgba(26, 26, 26, 0.6)',
                  marginLeft: '12px'
                }}>
                  ({domainVars.length} variables)
                </span>
              </h3>

              {domainVars.map(v => (
                <div key={v.column} style={{ marginBottom: '8px' }}>
                  {/* Variable Row */}
                  <div
                    onClick={() => setExpandedVar(expandedVar === v.column ? null : v.column)}
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '2fr 1fr 1fr 80px',
                      alignItems: 'center',
                      padding: '12px 16px',
                      backgroundColor: expandedVar === v.column ? 'rgba(8, 122, 106, 0.05)' : '#f5f2ea',
                      borderRadius: '6px',
                      cursor: 'pointer',
                      border: expandedVar === v.column ? '1px solid rgba(8, 122, 106, 0.3)' : '1px solid transparent',
                      transition: 'all 0.2s'
                    }}
                    onMouseEnter={(e) => {
                      if (expandedVar !== v.column) e.currentTarget.style.backgroundColor = '#e9e4d8'
                    }}
                    onMouseLeave={(e) => {
                      if (expandedVar !== v.column) e.currentTarget.style.backgroundColor = '#f5f2ea'
                    }}
                  >
                    <div>
                      <div style={{ fontSize: '14px', fontWeight: 600, color: '#1a1a1a' }}>
                        {v.name}
                      </div>
                      <div style={{ fontSize: '12px', color: 'rgba(26, 26, 26, 0.6)', marginTop: '2px' }}>
                        {v.type} • {v.unit}
                      </div>
                    </div>
                    <div style={{ fontSize: '14px', color: '#087A6A', fontWeight: 600 }}>
                      {v.patient_coverage_pct}% coverage
                      <div style={{ fontSize: '11px', color: 'rgba(26, 26, 26, 0.6)', fontWeight: 400 }}>
                        {v.patients_with_data.toLocaleString()} patients
                      </div>
                    </div>
                    <div style={{ fontSize: '14px', color: '#1a1a1a' }}>
                      {v.median_measurements_per_patient} median/patient
                      <div style={{ fontSize: '11px', color: 'rgba(26, 26, 26, 0.6)' }}>
                        {v.total_measurements.toLocaleString()} total
                      </div>
                    </div>
                    <div style={{ textAlign: 'center', fontSize: '18px', color: '#087A6A' }}>
                      {expandedVar === v.column ? '▼' : '▶'}
                    </div>
                  </div>

                  {/* Expanded Detail View */}
                  {expandedVar === v.column && (
                    <div style={{
                      marginTop: '8px',
                      padding: '20px',
                      backgroundColor: '#fff',
                      border: '1px solid #e9e4d8',
                      borderRadius: '6px'
                    }}>
                      <h4 style={{ fontSize: '16px', fontWeight: 600, color: '#1a1a1a', marginBottom: '16px' }}>
                        {v.name} - Detailed View
                      </h4>

                      <div style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(3, 1fr)',
                        gap: '16px',
                        marginBottom: '16px'
                      }}>
                        <DetailMetric label="Coverage" value={`${v.patient_coverage_pct}%`} />
                        <DetailMetric label="Patients" value={v.patients_with_data.toLocaleString()} />
                        <DetailMetric label="Total Measurements" value={v.total_measurements.toLocaleString()} />
                        <DetailMetric label="Median/Patient" value={v.median_measurements_per_patient.toString()} />
                        {v.value_range && <DetailMetric label="Value Range" value={v.value_range} />}
                        {v.median_value !== null && <DetailMetric label="Median Value" value={v.median_value.toFixed(1)} />}
                      </div>

                      {v.distribution && (
                        <div style={{
                          padding: '16px',
                          backgroundColor: '#f5f2ea',
                          borderRadius: '6px',
                          marginBottom: '16px'
                        }}>
                          <div style={{ fontSize: '14px', fontWeight: 600, color: '#1a1a1a', marginBottom: '12px' }}>
                            Distribution (5-Number Summary)
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px' }}>
                            <span>Min: {v.distribution.min?.toFixed(1)}</span>
                            <span>Q25: {v.distribution.q25?.toFixed(1)}</span>
                            <span>Median: {v.distribution.median?.toFixed(1)}</span>
                            <span>Q75: {v.distribution.q75?.toFixed(1)}</span>
                            <span>Max: {v.distribution.max?.toFixed(1)}</span>
                          </div>
                        </div>
                      )}

                      {v.sensor_metrics && (
                        <div style={{
                          padding: '16px',
                          backgroundColor: 'rgba(8, 122, 106, 0.05)',
                          border: '1px solid rgba(8, 122, 106, 0.2)',
                          borderRadius: '6px'
                        }}>
                          <div style={{ fontSize: '14px', fontWeight: 600, color: '#087A6A', marginBottom: '12px' }}>
                            Sensor-Specific Metrics
                          </div>
                          <div style={{
                            display: 'grid',
                            gridTemplateColumns: 'repeat(3, 1fr)',
                            gap: '12px'
                          }}>
                            <DetailMetric
                              label="Median Wear-Days"
                              value={v.sensor_metrics.median_wear_days.toString()}
                            />
                            <DetailMetric
                              label=">7 Consecutive Days"
                              value={`${v.sensor_metrics.pct_7_consecutive_days}%`}
                            />
                            <DetailMetric
                              label=">30 Consecutive Days"
                              value={`${v.sensor_metrics.pct_30_consecutive_days}%`}
                            />
                          </div>
                          <p style={{
                            marginTop: '12px',
                            fontSize: '12px',
                            color: 'rgba(26, 26, 26, 0.6)',
                            fontStyle: 'italic'
                          }}>
                            These metrics determine whether sensor data is usable for longitudinal analysis or only cross-sectional snapshots
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function DetailMetric({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      padding: '12px',
      backgroundColor: '#f5f2ea',
      borderRadius: '4px'
    }}>
      <div style={{ fontSize: '11px', color: 'rgba(26, 26, 26, 0.6)', marginBottom: '4px', textTransform: 'uppercase' }}>
        {label}
      </div>
      <div style={{ fontSize: '16px', fontWeight: 600, color: '#1a1a1a' }}>
        {value}
      </div>
    </div>
  )
}
