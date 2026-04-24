import { useState, useEffect } from 'react'
import Plot from 'react-plotly.js'
import Plotly from 'plotly.js-dist-min'

export default function Passport() {
  const [health, setHealth] = useState<any>(null)

  useEffect(() => {
    fetch('/dashboard/api/health')
      .then(r => r.json())
      .then(d => setHealth(d))
      .catch(e => console.error('Health check failed:', e))
  }, [])

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
          Dataset Passport
        </h2>
        <p style={{ color: '#64748b', fontSize: '14px', marginBottom: '24px' }}>
          High-level overview of dataset provenance, structure, and coverage
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '16px', marginBottom: '32px' }}>
          <MetricCard label="Project" value="wb-spotless-eggplant-4340" />
          <MetricCard label="Datasets" value="3" />
          <MetricCard label="Total Tables" value="~15" />
          <MetricCard label="API Status" value={health?.status || 'checking...'} />
        </div>

        <div style={{
          backgroundColor: '#f8fafc',
          border: '1px solid #e2e8f0',
          borderRadius: '6px',
          padding: '16px',
          marginBottom: '24px'
        }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, color: '#1e293b', marginBottom: '12px' }}>
            Known Datasets
          </h3>
          <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
            <li style={{ padding: '8px 0', borderBottom: '1px solid #e2e8f0', color: '#475569' }}>
              <code style={{ backgroundColor: '#e2e8f0', padding: '2px 8px', borderRadius: '4px', fontSize: '13px' }}>
                analysis
              </code> — Analysis results and derived tables
            </li>
            <li style={{ padding: '8px 0', borderBottom: '1px solid #e2e8f0', color: '#475569' }}>
              <code style={{ backgroundColor: '#e2e8f0', padding: '2px 8px', borderRadius: '4px', fontSize: '13px' }}>
                crf
              </code> — Case report forms (clinical data)
            </li>
            <li style={{ padding: '8px 0', color: '#475569' }}>
              <code style={{ backgroundColor: '#e2e8f0', padding: '2px 8px', borderRadius: '4px', fontSize: '13px' }}>
                sensordata
              </code> — Time-series sensor measurements
            </li>
          </ul>
        </div>

        <div style={{
          backgroundColor: '#fff',
          border: '1px solid #e2e8f0',
          borderRadius: '6px',
          padding: '16px'
        }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, color: '#1e293b', marginBottom: '12px' }}>
            Test Chart: Dataset Distribution
          </h3>
          <Plot
            plotly={Plotly}
            data={[
              {
                x: ['analysis', 'crf', 'sensordata'],
                y: [5, 7, 3],
                type: 'bar',
                marker: { color: '#3b82f6' },
              },
            ]}
            layout={{
              width: 800,
              height: 300,
              margin: { t: 20, r: 20, b: 40, l: 40 },
              xaxis: { title: 'Dataset' },
              yaxis: { title: 'Number of Tables' },
              plot_bgcolor: '#f8fafc',
              paper_bgcolor: '#fff',
            }}
            config={{ displayModeBar: false }}
          />
        </div>
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
      <div style={{ fontSize: '24px', fontWeight: 600, color: '#1e293b' }}>
        {value}
      </div>
    </div>
  )
}
