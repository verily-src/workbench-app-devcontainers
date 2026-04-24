import { useState, useEffect } from 'react'
import { useCohort } from '../context/CohortContext'
import Plot from 'react-plotly.js'
import Plotly from 'plotly.js-dist-min'

interface Variable {
  name: string
  type: string
  description: string
  completeness: number
  range: string
}

export default function Variables() {
  const { addFlag } = useCohort()
  const [searchTerm, setSearchTerm] = useState('')
  const [variables, setVariables] = useState<Variable[]>([])

  useEffect(() => {
    fetch('/dashboard/api/variables')
      .then(r => r.json())
      .then(d => setVariables(d.variables))
      .catch(e => console.error('Variables fetch failed:', e))
  }, [])

  const filteredVars = variables.filter(v =>
    v.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    v.description.toLowerCase().includes(searchTerm.toLowerCase())
  )

  const numericCount = variables.filter(v => v.type === 'numeric').length
  const categoricalCount = variables.filter(v => v.type === 'categorical').length
  const avgCompleteness = variables.length > 0
    ? (variables.reduce((sum, v) => sum + v.completeness, 0) / variables.length).toFixed(1)
    : '0'

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
          Variables
        </h2>
        <p style={{ color: '#64748b', fontSize: '14px', marginBottom: '24px' }}>
          Variable catalog, data types, completeness, and distributions
        </p>

        {/* Search */}
        <div style={{ marginBottom: '24px' }}>
          <input
            type="text"
            placeholder="Search variables..."
            value={searchTerm}
            onChange={e => setSearchTerm(e.target.value)}
            style={{
              width: '100%',
              maxWidth: '400px',
              padding: '10px 16px',
              border: '1px solid #cbd5e1',
              borderRadius: '6px',
              fontSize: '14px'
            }}
          />
        </div>

        {/* Variable Stats */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '24px' }}>
          <MetricCard label="Total Variables" value={variables.length} />
          <MetricCard label="Numeric" value={numericCount} />
          <MetricCard label="Categorical" value={categoricalCount} />
          <MetricCard label="Avg Completeness" value={`${avgCompleteness}%`} />
        </div>

        {/* Variable Table */}
        {variables.length > 0 ? (
          <div style={{
            backgroundColor: '#fff',
            border: '1px solid #e2e8f0',
            borderRadius: '6px',
            overflow: 'hidden',
            marginBottom: '24px'
          }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{ backgroundColor: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
                  <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: '12px', fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>Variable</th>
                  <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: '12px', fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>Description</th>
                  <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: '12px', fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>Type</th>
                  <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: '12px', fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>Completeness</th>
                  <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: '12px', fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>Range/Values</th>
                  <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: '12px', fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredVars.map(v => (
                  <tr key={v.name} style={{ borderBottom: '1px solid #e2e8f0' }}>
                    <td style={{ padding: '12px 16px', fontSize: '13px', color: '#1e293b', fontFamily: 'monospace' }}>
                      {v.name}
                    </td>
                    <td style={{ padding: '12px 16px', fontSize: '14px', color: '#475569' }}>
                      {v.description}
                    </td>
                    <td style={{ padding: '12px 16px', fontSize: '14px', color: '#64748b' }}>
                      <span style={{
                        backgroundColor: v.type === 'numeric' ? '#dbeafe' : '#fce7f3',
                        color: v.type === 'numeric' ? '#1e40af' : '#9f1239',
                        padding: '2px 8px',
                        borderRadius: '4px',
                        fontSize: '12px',
                        fontWeight: 500
                      }}>
                        {v.type}
                      </span>
                    </td>
                    <td style={{ padding: '12px 16px', fontSize: '14px', color: v.completeness < 80 ? '#dc2626' : '#1e293b' }}>
                      {v.completeness}%
                      {v.completeness < 80 && <span style={{ marginLeft: '4px', color: '#dc2626' }}>⚠</span>}
                    </td>
                    <td style={{ padding: '12px 16px', fontSize: '13px', color: '#64748b', fontFamily: 'monospace' }}>
                      {v.range}
                    </td>
                    <td style={{ padding: '12px 16px' }}>
                      {v.completeness < 80 && (
                        <button
                          onClick={() => addFlag(`Low completeness: ${v.name} (${v.completeness}%)`)}
                          style={{
                            padding: '4px 12px',
                            backgroundColor: '#fef3c7',
                            color: '#92400e',
                            border: '1px solid #fbbf24',
                            borderRadius: '4px',
                            fontSize: '12px',
                            cursor: 'pointer',
                            fontWeight: 500
                          }}
                        >
                          Flag
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p style={{ color: '#64748b' }}>Loading variables...</p>
        )}

        {/* Completeness Chart */}
        {variables.length > 0 && (
          <div style={{
            backgroundColor: '#fff',
            border: '1px solid #e2e8f0',
            borderRadius: '6px',
            padding: '16px'
          }}>
            <h3 style={{ fontSize: '16px', fontWeight: 600, color: '#1e293b', marginBottom: '12px' }}>
              Variable Completeness
            </h3>
            <Plot
              plotly={Plotly}
              data={[
                {
                  x: variables.map(v => v.name),
                  y: variables.map(v => v.completeness),
                  type: 'bar',
                  marker: {
                    color: variables.map(v => v.completeness < 80 ? '#ef4444' : '#3b82f6')
                  },
                },
              ]}
              layout={{
                width: 800,
                height: 300,
                margin: { t: 20, r: 20, b: 120, l: 60 },
                xaxis: { title: 'Variable', tickangle: -45 },
                yaxis: { title: 'Completeness (%)', range: [0, 105] },
                plot_bgcolor: '#f8fafc',
                paper_bgcolor: '#fff',
                shapes: [{
                  type: 'line',
                  x0: -0.5,
                  x1: variables.length - 0.5,
                  y0: 80,
                  y1: 80,
                  line: { color: '#ef4444', width: 2, dash: 'dash' }
                }]
              }}
              config={{ displayModeBar: false }}
            />
          </div>
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
