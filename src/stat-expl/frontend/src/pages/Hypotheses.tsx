import { useState } from 'react'
import { useCohort } from '../context/CohortContext'

const sampleHypotheses = [
  {
    question: 'Does BMI correlate with cardiovascular events?',
    canAnswer: true,
    requiredVars: ['bmi', 'cv_events'],
    availability: 'Both variables present with 94% and 89% completeness',
    powerEstimate: 'Adequate (n=1,247, power=0.85)',
  },
  {
    question: 'What is the effect of medication adherence on outcomes?',
    canAnswer: true,
    requiredVars: ['medication_adherence', 'clinical_outcomes'],
    availability: 'Both available, 78% and 92% completeness',
    powerEstimate: 'Adequate (n=980, power=0.82)',
  },
  {
    question: 'How does exercise frequency impact glucose levels?',
    canAnswer: false,
    requiredVars: ['exercise_frequency', 'glucose_levels'],
    availability: 'Exercise frequency not captured',
    powerEstimate: 'N/A - missing data',
  },
  {
    question: 'Association between sleep quality and depression scores?',
    canAnswer: false,
    requiredVars: ['sleep_quality', 'depression_score'],
    availability: 'Sleep quality only available for 23% of cohort',
    powerEstimate: 'Insufficient (n=287, power=0.45)',
  },
]

export default function Hypotheses() {
  const { flags } = useCohort()
  const [showOnlyAnswerable, setShowOnlyAnswerable] = useState(false)

  const filteredHypotheses = showOnlyAnswerable
    ? sampleHypotheses.filter(h => h.canAnswer)
    : sampleHypotheses

  const canAnswer = sampleHypotheses.filter(h => h.canAnswer).length
  const cannot = sampleHypotheses.filter(h => !h.canAnswer).length

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
          Hypothesis Assessment
        </h2>
        <p style={{ color: '#64748b', fontSize: '14px', marginBottom: '24px' }}>
          Assess whether your research questions can be answered with this dataset
        </p>

        {/* Summary Stats */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '16px', marginBottom: '24px' }}>
          <MetricCard label="Can Answer" value={canAnswer} color="#10b981" />
          <MetricCard label="Cannot Answer" value={cannot} color="#dc2626" />
          <MetricCard label="Answerability Rate" value={`${Math.round((canAnswer / sampleHypotheses.length) * 100)}%`} color="#3b82f6" />
        </div>

        {/* Flags Summary */}
        {flags.length > 0 && (
          <div style={{
            backgroundColor: '#fef3c7',
            border: '1px solid #fbbf24',
            borderRadius: '6px',
            padding: '16px',
            marginBottom: '24px'
          }}>
            <h3 style={{ fontSize: '14px', fontWeight: 600, color: '#92400e', marginBottom: '8px' }}>
              ⚠ Active Flags ({flags.length})
            </h3>
            <ul style={{ margin: 0, paddingLeft: '20px', color: '#78350f' }}>
              {flags.map((flag, idx) => (
                <li key={idx} style={{ marginBottom: '4px', fontSize: '14px' }}>{flag}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Filter */}
        <div style={{ marginBottom: '24px' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '14px', color: '#1e293b' }}>
            <input
              type="checkbox"
              checked={showOnlyAnswerable}
              onChange={e => setShowOnlyAnswerable(e.target.checked)}
              style={{ cursor: 'pointer' }}
            />
            Show only answerable hypotheses
          </label>
        </div>

        {/* Hypotheses Cards */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {filteredHypotheses.map((hyp, idx) => (
            <div
              key={idx}
              style={{
                backgroundColor: '#fff',
                border: `2px solid ${hyp.canAnswer ? '#86efac' : '#fca5a5'}`,
                borderRadius: '8px',
                padding: '20px'
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: '12px' }}>
                <h3 style={{ fontSize: '16px', fontWeight: 600, color: '#1e293b', margin: 0, flex: 1 }}>
                  {hyp.question}
                </h3>
                <span style={{
                  backgroundColor: hyp.canAnswer ? '#dcfce7' : '#fee2e2',
                  color: hyp.canAnswer ? '#166534' : '#991b1b',
                  padding: '4px 12px',
                  borderRadius: '4px',
                  fontSize: '12px',
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  whiteSpace: 'nowrap',
                  marginLeft: '16px'
                }}>
                  {hyp.canAnswer ? '✓ Can Answer' : '✗ Cannot Answer'}
                </span>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', fontSize: '14px' }}>
                <div>
                  <div style={{ color: '#64748b', marginBottom: '4px', fontSize: '12px', fontWeight: 600, textTransform: 'uppercase' }}>
                    Required Variables
                  </div>
                  <div style={{ color: '#1e293b', fontFamily: 'monospace', fontSize: '13px' }}>
                    {hyp.requiredVars.join(', ')}
                  </div>
                </div>

                <div>
                  <div style={{ color: '#64748b', marginBottom: '4px', fontSize: '12px', fontWeight: 600, textTransform: 'uppercase' }}>
                    Power Estimate
                  </div>
                  <div style={{ color: '#1e293b' }}>
                    {hyp.powerEstimate}
                  </div>
                </div>
              </div>

              <div style={{ marginTop: '12px', paddingTop: '12px', borderTop: '1px solid #e2e8f0' }}>
                <div style={{ color: '#64748b', marginBottom: '4px', fontSize: '12px', fontWeight: 600, textTransform: 'uppercase' }}>
                  Data Availability
                </div>
                <div style={{ color: hyp.canAnswer ? '#15803d' : '#991b1b' }}>
                  {hyp.availability}
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Cannot Answer Section - Always Populated */}
        <div style={{
          backgroundColor: '#fef2f2',
          border: '2px solid #fca5a5',
          borderRadius: '8px',
          padding: '20px',
          marginTop: '24px'
        }}>
          <h3 style={{ fontSize: '18px', fontWeight: 600, color: '#991b1b', marginBottom: '12px' }}>
            Limitations: Questions This Dataset Cannot Answer
          </h3>
          <ul style={{ margin: 0, paddingLeft: '20px', color: '#7f1d1d' }}>
            {sampleHypotheses.filter(h => !h.canAnswer).map((hyp, idx) => (
              <li key={idx} style={{ marginBottom: '8px', fontSize: '14px' }}>
                <strong>{hyp.question}</strong>
                <div style={{ color: '#991b1b', fontSize: '13px', marginTop: '4px' }}>
                  Reason: {hyp.availability}
                </div>
              </li>
            ))}
            <li style={{ marginBottom: '8px', fontSize: '14px' }}>
              <strong>Genetic markers analysis?</strong>
              <div style={{ color: '#991b1b', fontSize: '13px', marginTop: '4px' }}>
                Reason: No genomic data collected
              </div>
            </li>
            <li style={{ marginBottom: '8px', fontSize: '14px' }}>
              <strong>Long-term mortality outcomes (&gt;10 years)?</strong>
              <div style={{ color: '#991b1b', fontSize: '13px', marginTop: '4px' }}>
                Reason: Study duration only 2 years
              </div>
            </li>
          </ul>
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
