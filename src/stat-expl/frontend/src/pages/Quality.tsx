import { useCohort } from '../context/CohortContext'
import Plot from 'react-plotly.js'
import Plotly from 'plotly.js-dist-min'

const qualityIssues = [
  { issue: 'Missing BMI values', severity: 'medium', affected: 73, percentage: 5.8 },
  { issue: 'Outlier blood pressure readings', severity: 'low', affected: 12, percentage: 1.0 },
  { issue: 'Duplicate patient records', severity: 'high', affected: 8, percentage: 0.6 },
  { issue: 'Inconsistent date formats', severity: 'medium', affected: 145, percentage: 11.6 },
  { issue: 'Missing diagnosis codes', severity: 'high', affected: 108, percentage: 8.7 },
]

export default function Quality() {
  const { addFlag } = useCohort()

  const severityColor = (severity: string) => {
    switch (severity) {
      case 'high': return '#dc2626'
      case 'medium': return '#f59e0b'
      case 'low': return '#10b981'
      default: return '#64748b'
    }
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
          Data Quality
        </h2>
        <p style={{ color: '#64748b', fontSize: '14px', marginBottom: '24px' }}>
          Missingness patterns, outliers, duplicates, and data integrity checks
        </p>

        {/* Quality Score */}
        <div style={{
          backgroundColor: '#f0fdf4',
          border: '2px solid #86efac',
          borderRadius: '8px',
          padding: '20px',
          marginBottom: '24px',
          textAlign: 'center'
        }}>
          <div style={{ fontSize: '14px', color: '#166534', marginBottom: '8px', fontWeight: 600, textTransform: 'uppercase' }}>
            Overall Data Quality Score
          </div>
          <div style={{ fontSize: '48px', fontWeight: 700, color: '#166534' }}>
            82.3<span style={{ fontSize: '24px', color: '#16a34a' }}>/100</span>
          </div>
          <div style={{ fontSize: '14px', color: '#15803d', marginTop: '4px' }}>
            Good quality — minor issues detected
          </div>
        </div>

        {/* Quality Metrics */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '16px', marginBottom: '24px' }}>
          <MetricCard label="Issues Found" value={qualityIssues.length} color="#dc2626" />
          <MetricCard label="High Severity" value={qualityIssues.filter(i => i.severity === 'high').length} color="#dc2626" />
          <MetricCard label="Records Affected" value="346" color="#f59e0b" />
          <MetricCard label="Clean Records" value="901" color="#10b981" />
        </div>

        {/* Issues Table */}
        <div style={{
          backgroundColor: '#fff',
          border: '1px solid #e2e8f0',
          borderRadius: '6px',
          overflow: 'hidden',
          marginBottom: '24px'
        }}>
          <div style={{
            backgroundColor: '#f8fafc',
            padding: '16px',
            borderBottom: '1px solid #e2e8f0'
          }}>
            <h3 style={{ fontSize: '16px', fontWeight: 600, color: '#1e293b' }}>
              Data Quality Issues
            </h3>
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ backgroundColor: '#f8fafc', borderBottom: '1px solid #e2e8f0' }}>
                <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: '12px', fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>Issue</th>
                <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: '12px', fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>Severity</th>
                <th style={{ padding: '12px 16px', textAlign: 'right', fontSize: '12px', fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>Affected</th>
                <th style={{ padding: '12px 16px', textAlign: 'right', fontSize: '12px', fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>% of Total</th>
                <th style={{ padding: '12px 16px', textAlign: 'left', fontSize: '12px', fontWeight: 600, color: '#64748b', textTransform: 'uppercase' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {qualityIssues.map((issue, idx) => (
                <tr key={idx} style={{ borderBottom: '1px solid #e2e8f0' }}>
                  <td style={{ padding: '12px 16px', fontSize: '14px', color: '#1e293b' }}>
                    {issue.issue}
                  </td>
                  <td style={{ padding: '12px 16px' }}>
                    <span style={{
                      backgroundColor: `${severityColor(issue.severity)}15`,
                      color: severityColor(issue.severity),
                      padding: '4px 12px',
                      borderRadius: '4px',
                      fontSize: '12px',
                      fontWeight: 600,
                      textTransform: 'uppercase'
                    }}>
                      {issue.severity}
                    </span>
                  </td>
                  <td style={{ padding: '12px 16px', fontSize: '14px', color: '#1e293b', textAlign: 'right', fontWeight: 600 }}>
                    {issue.affected}
                  </td>
                  <td style={{ padding: '12px 16px', fontSize: '14px', color: '#64748b', textAlign: 'right' }}>
                    {issue.percentage.toFixed(1)}%
                  </td>
                  <td style={{ padding: '12px 16px' }}>
                    {issue.severity === 'high' && (
                      <button
                        onClick={() => addFlag(`Data quality issue: ${issue.issue}`)}
                        style={{
                          padding: '4px 12px',
                          backgroundColor: '#fee2e2',
                          color: '#991b1b',
                          border: '1px solid #dc2626',
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

        {/* Issue Distribution Chart */}
        <div style={{
          backgroundColor: '#fff',
          border: '1px solid #e2e8f0',
          borderRadius: '6px',
          padding: '16px',
          marginBottom: '24px'
        }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, color: '#1e293b', marginBottom: '12px' }}>
            Issues by Severity
          </h3>
          <Plot
            plotly={Plotly}
            data={[
              {
                labels: ['High', 'Medium', 'Low'],
                values: [
                  qualityIssues.filter(i => i.severity === 'high').length,
                  qualityIssues.filter(i => i.severity === 'medium').length,
                  qualityIssues.filter(i => i.severity === 'low').length,
                ],
                type: 'pie',
                marker: { colors: ['#dc2626', '#f59e0b', '#10b981'] },
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

        {/* Completeness Over Time */}
        <div style={{
          backgroundColor: '#fff',
          border: '1px solid #e2e8f0',
          borderRadius: '6px',
          padding: '16px'
        }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600, color: '#1e293b', marginBottom: '12px' }}>
            Data Completeness Trend
          </h3>
          <Plot
            plotly={Plotly}
            data={[
              {
                x: ['2022-Q1', '2022-Q2', '2022-Q3', '2022-Q4', '2023-Q1', '2023-Q2', '2023-Q3', '2023-Q4', '2024-Q1'],
                y: [68, 72, 78, 81, 83, 85, 87, 86, 82],
                type: 'scatter',
                mode: 'lines+markers',
                marker: { color: '#3b82f6', size: 8 },
                line: { color: '#3b82f6', width: 3 }
              },
            ]}
            layout={{
              width: 800,
              height: 300,
              margin: { t: 20, r: 20, b: 60, l: 60 },
              xaxis: { title: 'Quarter' },
              yaxis: { title: 'Completeness (%)', range: [60, 95] },
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

function MetricCard({ label, value, color }: { label: string; value: string | number; color: string }) {
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
      <div style={{ fontSize: '24px', fontWeight: 600, color }}>
        {value}
      </div>
    </div>
  )
}
