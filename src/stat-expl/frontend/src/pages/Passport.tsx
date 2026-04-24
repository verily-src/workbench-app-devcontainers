import { useState, useEffect } from 'react'
import { useData } from '../context/DataContext'
import Plot from 'react-plotly.js'
import Plotly from 'plotly.js-dist-min'

export default function Passport() {
  const { passportMetrics, timeline, isLoading } = useData()
  const [activeParticipantsTimeline, setActiveParticipantsTimeline] = useState<any[]>([])

  // Load active participants timeline
  useEffect(() => {
    fetch('/dashboard/api/passport/active-participants')
      .then(r => r.json())
      .then(data => setActiveParticipantsTimeline(data.timeline))
      .catch(err => console.error('Failed to load active participants:', err))
  }, [])

  if (isLoading) {
    return (
      <div style={{ color: 'rgba(26, 26, 26, 0.6)' }}>
        Loading passport data...
      </div>
    )
  }

  const displayCount = passportMetrics?.total_participants || 2502
  const domainData = passportMetrics?.domains || []

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
            Total Participants
          </div>
          <div style={{ fontSize: '48px', fontWeight: 600, color: '#087A6A', lineHeight: 1.1 }}>
            N = {displayCount.toLocaleString()}
          </div>
        </div>


        {/* Active Participants Over Time Graph */}
        {activeParticipantsTimeline && activeParticipantsTimeline.length > 0 && (
          <div style={{ marginBottom: '32px' }}>
            <h3 style={{
              fontSize: '18px',
              fontWeight: 600,
              color: '#1a1a1a',
              marginBottom: '16px'
            }}>
              Active Participants Over Time
            </h3>
            <p style={{
              fontSize: '13px',
              color: 'rgba(26, 26, 26, 0.6)',
              marginBottom: '12px'
            }}>
              Total number of people actively in the study (enrollments - dropouts). Dropout defined as 30 days after last sensor data.
            </p>
            <Plot
              plotly={Plotly}
              data={[
                {
                  x: activeParticipantsTimeline.map(t => t.month),
                  y: activeParticipantsTimeline.map(t => t.active_participants),
                  type: 'scatter',
                  mode: 'lines',
                  fill: 'tozeroy',
                  marker: { color: '#087A6A' },
                  line: { color: '#087A6A', width: 3 },
                  name: 'Active Participants'
                },
              ]}
              layout={{
                width: 900,
                height: 300,
                margin: { t: 20, r: 20, b: 60, l: 60 },
                xaxis: { title: 'Month' },
                yaxis: { title: 'Active Participants' },
                plot_bgcolor: '#f5f2ea',
                paper_bgcolor: '#fff',
              }}
              config={{ displayModeBar: false }}
            />
          </div>
        )}

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
