import Plot from 'react-plotly.js'
import Plotly from 'plotly.js-dist-min'
import { useData } from '../context/DataContext'

export default function Passport() {
  const { datasets, sensorData, apiStatus, isLoading } = useData()

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

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
          <div></div>
          <a
            href="/dashboard/api/export?format=csv"
            download
            style={{
              padding: '10px 20px',
              backgroundColor: '#3b82f6',
              color: '#fff',
              border: 'none',
              borderRadius: '6px',
              fontSize: '14px',
              fontWeight: 600,
              textDecoration: 'none',
              cursor: 'pointer',
              display: 'inline-block'
            }}
          >
            📥 Export Sample Data (CSV)
          </a>
        </div>

        {isLoading ? (
          <p style={{ color: '#64748b' }}>Loading dataset information...</p>
        ) : (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '16px', marginBottom: '32px' }}>
              <MetricCard label="Project" value={datasets?.project || 'N/A'} />
              <MetricCard label="Datasets" value={datasets?.datasets.length || 0} />
              <MetricCard label="Total Tables" value={datasets?.total_tables || 0} />
              <MetricCard label="API Status" value={apiStatus || 'checking...'} />
            </div>

        {/* Sensor Data Overview */}
        {sensorData && (
          <div style={{
            backgroundColor: '#f0f9ff',
            border: '1px solid #bae6fd',
            borderRadius: '6px',
            padding: '16px',
            marginBottom: '24px'
          }}>
            <h3 style={{ fontSize: '16px', fontWeight: 600, color: '#0369a1', marginBottom: '12px' }}>
              Wearable Sensor Data Available
            </h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px' }}>
              <div>
                <div style={{ fontSize: '11px', color: '#0284c7', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                  Participants with Data
                </div>
                <div style={{ fontSize: '20px', fontWeight: 600, color: '#0369a1' }}>
                  {sensorData.participants_with_step_data.toLocaleString()} <span style={{ fontSize: '14px', color: '#0284c7' }}>({sensorData.data_coverage_pct}%)</span>
                </div>
              </div>
              <div>
                <div style={{ fontSize: '11px', color: '#0284c7', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                  Step Records
                </div>
                <div style={{ fontSize: '20px', fontWeight: 600, color: '#0369a1' }}>
                  {(sensorData.total_step_records / 1e9).toFixed(1)}B
                </div>
              </div>
              <div>
                <div style={{ fontSize: '11px', color: '#0284c7', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                  Pulse Records
                </div>
                <div style={{ fontSize: '20px', fontWeight: 600, color: '#0369a1' }}>
                  {(sensorData.total_pulse_records / 1e9).toFixed(1)}B
                </div>
              </div>
              <div>
                <div style={{ fontSize: '11px', color: '#0284c7', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
                  Sleep Records
                </div>
                <div style={{ fontSize: '20px', fontWeight: 600, color: '#0369a1' }}>
                  {(sensorData.total_sleep_records / 1e6).toFixed(1)}M
                </div>
              </div>
            </div>
          </div>
        )}

            <div style={{
              backgroundColor: '#f8fafc',
              border: '1px solid #e2e8f0',
              borderRadius: '6px',
              padding: '16px',
              marginBottom: '24px'
            }}>
              <h3 style={{ fontSize: '16px', fontWeight: 600, color: '#1e293b', marginBottom: '12px' }}>
                Available Datasets
              </h3>
              {datasets && (
                <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                  {datasets.datasets.map(ds => (
                    <li key={ds.name} style={{ padding: '8px 0', borderBottom: '1px solid #e2e8f0', color: '#475569' }}>
                      <code style={{ backgroundColor: '#e2e8f0', padding: '2px 8px', borderRadius: '4px', fontSize: '13px', fontWeight: 600 }}>
                        {ds.name}
                      </code>
                      <span style={{ marginLeft: '12px', color: '#64748b' }}>
                        {ds.table_count} tables
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {datasets && (
              <div style={{
                backgroundColor: '#fff',
                border: '1px solid #e2e8f0',
                borderRadius: '6px',
                padding: '16px'
              }}>
                <h3 style={{ fontSize: '16px', fontWeight: 600, color: '#1e293b', marginBottom: '12px' }}>
                  Dataset Distribution
                </h3>
                <Plot
                  plotly={Plotly}
                  data={[
                    {
                      x: datasets.datasets.map(d => d.name),
                      y: datasets.datasets.map(d => d.table_count),
                      type: 'bar',
                      marker: { color: '#3b82f6' },
                    },
                  ]}
                  layout={{
                    width: 800,
                    height: 300,
                    margin: { t: 20, r: 20, b: 80, l: 40 },
                    xaxis: { title: 'Dataset', tickangle: -45 },
                    yaxis: { title: 'Number of Tables' },
                    plot_bgcolor: '#f8fafc',
                    paper_bgcolor: '#fff',
                  }}
                  config={{ displayModeBar: false }}
                />
              </div>
            )}
          </>
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
      <div style={{ fontSize: '24px', fontWeight: 600, color: '#1e293b' }}>
        {value}
      </div>
    </div>
  )
}
