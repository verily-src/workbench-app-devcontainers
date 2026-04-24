import { useState, useEffect } from 'react'

interface Disease {
  diagnosis: string
  total_patients: number
  sensor_coverage_pct: number
  vitals_coverage_pct: number
  rwe_ready: boolean
}

interface Medication {
  drug_class: string
  total_patients: number
  sensor_coverage_pct: number
  vitals_coverage_pct: number
  rwe_ready: boolean
}

interface Hypothesis {
  id: number
  title: string
  question: string
  data_required: string[]
  feasibility: string
  patient_pool: string
  cohort_type: string
}

interface CohortData {
  cohort_size: number
  data_availability: {
    vitals: { count: number; pct: number }
    labs: { count: number; pct: number }
    medications: { count: number; pct: number }
    diagnoses: { count: number; pct: number }
    sensor: { count: number; pct: number }
    pro: { count: number; pct: number }
  }
  patient_ids: string[]
}

export default function Hypotheses() {
  const [diseases, setDiseases] = useState<Disease[]>([])
  const [medications, setMedications] = useState<Medication[]>([])
  const [hypotheses, setHypotheses] = useState<Hypothesis[]>([])
  const [summary, setSummary] = useState<any>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [selectedTab, setSelectedTab] = useState<'hypotheses' | 'diseases' | 'medications'>('hypotheses')
  const [selectedHypothesis, setSelectedHypothesis] = useState<Hypothesis | null>(null)
  const [cohortData, setCohortData] = useState<CohortData | null>(null)
  const [isBuildingCohort, setIsBuildingCohort] = useState(false)

  useEffect(() => {
    fetch('/dashboard/api/hypotheses/rwe-opportunities')
      .then(r => r.json())
      .then(data => {
        setDiseases(data.diseases)
        setMedications(data.medications)
        setHypotheses(data.example_hypotheses)
        setSummary(data.summary)
        setIsLoading(false)
      })
      .catch(err => {
        console.error('Failed to load RWE opportunities:', err)
        setIsLoading(false)
      })
  }, [])

  const buildCohort = (hypothesis: Hypothesis) => {
    setSelectedHypothesis(hypothesis)
    setIsBuildingCohort(true)
    setCohortData(null)

    fetch(`/dashboard/api/hypotheses/build-cohort?cohort_type=${hypothesis.cohort_type}`)
      .then(r => r.json())
      .then(data => {
        setCohortData(data)
        setIsBuildingCohort(false)
      })
      .catch(err => {
        console.error('Failed to build cohort:', err)
        setIsBuildingCohort(false)
      })
  }

  const exportCohort = () => {
    if (!selectedHypothesis) return
    window.open(`/dashboard/api/hypotheses/export-cohort?cohort_type=${selectedHypothesis.cohort_type}`, '_blank')
  }

  if (isLoading) {
    return <div style={{ color: 'rgba(26, 26, 26, 0.6)' }}>Loading hypothesis generator...</div>
  }

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
          Real-World Evidence Opportunities
        </h2>
        <p style={{ color: 'rgba(26, 26, 26, 0.6)', fontSize: '14px', marginBottom: '24px' }}>
          Potential research hypotheses using sensor data + clinical measurements
        </p>

        {/* Summary Card */}
        {summary && (
          <div style={{
            padding: '20px',
            backgroundColor: 'rgba(8, 122, 106, 0.05)',
            border: '1px solid rgba(8, 122, 106, 0.2)',
            borderRadius: '8px',
            marginBottom: '32px'
          }}>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(4, 1fr)',
              gap: '24px'
            }}>
              <SummaryMetric label="RWE-Ready Diseases" value={summary.total_rwe_ready_diseases.toString()} />
              <SummaryMetric label="RWE-Ready Medications" value={summary.total_rwe_ready_medications.toString()} />
              <SummaryMetric label="Patients with Sensors" value={summary.total_patients_with_sensor.toLocaleString()} />
              <SummaryMetric label="Sensor Coverage" value={`${summary.sensor_coverage_pct}%`} />
            </div>
            <p style={{
              marginTop: '16px',
              fontSize: '13px',
              color: 'rgba(26, 26, 26, 0.6)',
              fontStyle: 'italic'
            }}>
              RWE-Ready = ≥70% of patients have both sensor data and clinical measurements
            </p>
          </div>
        )}

        {/* Tabs */}
        <div style={{
          display: 'flex',
          gap: '8px',
          marginBottom: '24px',
          borderBottom: '2px solid #e9e4d8'
        }}>
          <TabButton
            label="Example Hypotheses"
            active={selectedTab === 'hypotheses'}
            onClick={() => setSelectedTab('hypotheses')}
          />
          <TabButton
            label={`Diseases (${diseases.length})`}
            active={selectedTab === 'diseases'}
            onClick={() => setSelectedTab('diseases')}
          />
          <TabButton
            label={`Medications (${medications.length})`}
            active={selectedTab === 'medications'}
            onClick={() => setSelectedTab('medications')}
          />
        </div>

        {/* Content */}
        {selectedTab === 'hypotheses' && (
          <div>
            <p style={{
              fontSize: '14px',
              color: 'rgba(26, 26, 26, 0.7)',
              marginBottom: '24px',
              padding: '16px',
              backgroundColor: '#f5f2ea',
              borderRadius: '6px'
            }}>
              These are example research questions that can be answered using the combination of sensor data,
              clinical measurements, diagnoses, and medications in this dataset. Click any hypothesis to build a cohort and see data availability.
            </p>
            {hypotheses.map(h => (
              <HypothesisCard key={h.id} hypothesis={h} onClick={() => buildCohort(h)} />
            ))}

            {/* Cohort Builder Panel */}
            {selectedHypothesis && (
              <div style={{
                marginTop: '32px',
                padding: '24px',
                backgroundColor: '#fff',
                border: '2px solid #087A6A',
                borderRadius: '8px'
              }}>
                <h3 style={{
                  fontSize: '20px',
                  fontWeight: 600,
                  color: '#087A6A',
                  marginBottom: '16px'
                }}>
                  Cohort Builder: {selectedHypothesis.title}
                </h3>

                {isBuildingCohort ? (
                  <div style={{ fontSize: '14px', color: 'rgba(26, 26, 26, 0.6)', fontStyle: 'italic' }}>
                    Building cohort...
                  </div>
                ) : cohortData ? (
                  <div>
                    {/* Cohort Size */}
                    <div style={{
                      marginBottom: '24px',
                      padding: '20px',
                      backgroundColor: 'rgba(8, 122, 106, 0.05)',
                      border: '1px solid rgba(8, 122, 106, 0.2)',
                      borderRadius: '6px'
                    }}>
                      <div style={{
                        fontSize: '14px',
                        color: 'rgba(26, 26, 26, 0.6)',
                        marginBottom: '8px',
                        textTransform: 'uppercase',
                        fontWeight: 600
                      }}>
                        Total Participants
                      </div>
                      <div style={{
                        fontSize: '48px',
                        fontWeight: 600,
                        color: '#087A6A',
                        lineHeight: 1.1
                      }}>
                        N = {cohortData.cohort_size.toLocaleString()}
                      </div>
                    </div>

                    {/* Data Availability Breakdown */}
                    <div style={{ marginBottom: '24px' }}>
                      <h4 style={{
                        fontSize: '16px',
                        fontWeight: 600,
                        color: '#1a1a1a',
                        marginBottom: '16px'
                      }}>
                        Data Availability Across Domains
                      </h4>
                      <div style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(3, 1fr)',
                        gap: '12px'
                      }}>
                        {Object.entries(cohortData.data_availability).map(([domain, data]: [string, any]) => (
                          <DataAvailabilityCard key={domain} domain={domain} data={data} totalN={cohortData.cohort_size} />
                        ))}
                      </div>
                    </div>

                    {/* Participant List */}
                    <div style={{ marginBottom: '24px' }}>
                      <h4 style={{
                        fontSize: '16px',
                        fontWeight: 600,
                        color: '#1a1a1a',
                        marginBottom: '16px'
                      }}>
                        Participant IDs ({cohortData.patient_ids.length.toLocaleString()} total)
                      </h4>
                      <div style={{
                        padding: '16px',
                        backgroundColor: '#f5f2ea',
                        borderRadius: '6px',
                        maxHeight: '300px',
                        overflowY: 'auto',
                        fontFamily: 'monospace',
                        fontSize: '12px',
                        lineHeight: '1.6'
                      }}>
                        {cohortData.patient_ids.map((id: string, i: number) => (
                          <div key={id} style={{
                            display: 'inline-block',
                            width: '25%',
                            padding: '2px 4px'
                          }}>
                            {id}
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Export Button */}
                    <button
                      onClick={exportCohort}
                      style={{
                        padding: '12px 24px',
                        backgroundColor: '#087A6A',
                        color: '#fff',
                        border: 'none',
                        borderRadius: '6px',
                        fontSize: '16px',
                        fontWeight: 600,
                        cursor: 'pointer',
                        width: '100%'
                      }}
                    >
                      Export Cohort as CSV
                    </button>
                  </div>
                ) : null}
              </div>
            )}
          </div>
        )}

        {selectedTab === 'diseases' && (
          <div>
            <p style={{
              fontSize: '14px',
              color: 'rgba(26, 26, 26, 0.7)',
              marginBottom: '24px',
              padding: '16px',
              backgroundColor: '#f5f2ea',
              borderRadius: '6px'
            }}>
              Diseases with ≥100 patients and ≥50 patients with sensor data. Green indicates RWE-ready (≥70% coverage for both sensors and vitals).
            </p>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(1, 1fr)',
              gap: '12px'
            }}>
              {diseases.map(d => (
                <DiseaseCard key={d.diagnosis} disease={d} />
              ))}
            </div>
          </div>
        )}

        {selectedTab === 'medications' && (
          <div>
            <p style={{
              fontSize: '14px',
              color: 'rgba(26, 26, 26, 0.7)',
              marginBottom: '24px',
              padding: '16px',
              backgroundColor: '#f5f2ea',
              borderRadius: '6px'
            }}>
              Medication classes with ≥100 patients. Green indicates RWE-ready (≥70% coverage for both sensors and vitals).
            </p>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(1, 1fr)',
              gap: '12px'
            }}>
              {medications.map(m => (
                <MedicationCard key={m.drug_class} medication={m} />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function TabButton({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '12px 20px',
        fontSize: '14px',
        fontWeight: 600,
        color: active ? '#087A6A' : 'rgba(26, 26, 26, 0.6)',
        backgroundColor: 'transparent',
        border: 'none',
        borderBottom: active ? '2px solid #087A6A' : '2px solid transparent',
        cursor: 'pointer',
        transition: 'all 0.2s'
      }}
    >
      {label}
    </button>
  )
}

function SummaryMetric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{
        fontSize: '12px',
        color: 'rgba(26, 26, 26, 0.6)',
        marginBottom: '4px',
        textTransform: 'uppercase',
        fontWeight: 600
      }}>
        {label}
      </div>
      <div style={{
        fontSize: '24px',
        fontWeight: 600,
        color: '#087A6A'
      }}>
        {value}
      </div>
    </div>
  )
}

function HypothesisCard({ hypothesis, onClick }: { hypothesis: Hypothesis; onClick: () => void }) {
  const feasibilityColor = hypothesis.feasibility === 'high' ? '#087A6A' : hypothesis.feasibility === 'medium' ? '#A25BC5' : '#D35C65'

  return (
    <div
      onClick={onClick}
      style={{
        padding: '20px',
        backgroundColor: '#f5f2ea',
        border: '1px solid #e9e4d8',
        borderRadius: '8px',
        marginBottom: '16px',
        cursor: 'pointer',
        transition: 'all 0.2s'
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.backgroundColor = '#e9e4d8'
        e.currentTarget.style.borderColor = '#087A6A'
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.backgroundColor = '#f5f2ea'
        e.currentTarget.style.borderColor = '#e9e4d8'
      }}
    >
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        marginBottom: '12px'
      }}>
        <h3 style={{
          fontSize: '16px',
          fontWeight: 600,
          color: '#1a1a1a',
          margin: 0
        }}>
          {hypothesis.title}
        </h3>
        <span style={{
          padding: '4px 12px',
          backgroundColor: feasibilityColor,
          color: '#fff',
          fontSize: '12px',
          fontWeight: 600,
          borderRadius: '12px',
          textTransform: 'uppercase'
        }}>
          {hypothesis.feasibility} feasibility
        </span>
      </div>

      <p style={{
        fontSize: '14px',
        color: '#1a1a1a',
        marginBottom: '16px',
        fontStyle: 'italic'
      }}>
        "{hypothesis.question}"
      </p>

      <div style={{ marginBottom: '16px' }}>
        <div style={{
          fontSize: '12px',
          fontWeight: 600,
          color: 'rgba(26, 26, 26, 0.7)',
          marginBottom: '8px',
          textTransform: 'uppercase'
        }}>
          Data Required:
        </div>
        <ul style={{
          margin: 0,
          paddingLeft: '20px',
          fontSize: '13px',
          color: 'rgba(26, 26, 26, 0.8)'
        }}>
          {hypothesis.data_required.map((req, i) => (
            <li key={i} style={{ marginBottom: '4px' }}>{req}</li>
          ))}
        </ul>
      </div>

      <div style={{
        padding: '12px',
        backgroundColor: '#fff',
        borderRadius: '4px',
        fontSize: '13px',
        color: 'rgba(26, 26, 26, 0.7)'
      }}>
        <strong>Patient Pool:</strong> {hypothesis.patient_pool}
      </div>
    </div>
  )
}

function DiseaseCard({ disease }: { disease: Disease }) {
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '2fr 1fr 1fr 1fr',
      alignItems: 'center',
      padding: '16px',
      backgroundColor: disease.rwe_ready ? 'rgba(8, 122, 106, 0.05)' : '#f5f2ea',
      border: disease.rwe_ready ? '1px solid rgba(8, 122, 106, 0.3)' : '1px solid #e9e4d8',
      borderRadius: '6px'
    }}>
      <div>
        <div style={{
          fontSize: '14px',
          fontWeight: 600,
          color: '#1a1a1a'
        }}>
          {disease.diagnosis}
        </div>
        <div style={{
          fontSize: '12px',
          color: 'rgba(26, 26, 26, 0.6)',
          marginTop: '4px'
        }}>
          {disease.total_patients.toLocaleString()} patients
        </div>
      </div>
      <div style={{ textAlign: 'center' }}>
        <div style={{
          fontSize: '18px',
          fontWeight: 600,
          color: disease.sensor_coverage_pct >= 70 ? '#087A6A' : 'rgba(26, 26, 26, 0.6)'
        }}>
          {disease.sensor_coverage_pct}%
        </div>
        <div style={{
          fontSize: '11px',
          color: 'rgba(26, 26, 26, 0.6)'
        }}>
          Sensor Data
        </div>
      </div>
      <div style={{ textAlign: 'center' }}>
        <div style={{
          fontSize: '18px',
          fontWeight: 600,
          color: disease.vitals_coverage_pct >= 70 ? '#087A6A' : 'rgba(26, 26, 26, 0.6)'
        }}>
          {disease.vitals_coverage_pct}%
        </div>
        <div style={{
          fontSize: '11px',
          color: 'rgba(26, 26, 26, 0.6)'
        }}>
          Vitals Data
        </div>
      </div>
      <div style={{ textAlign: 'center' }}>
        {disease.rwe_ready ? (
          <span style={{
            padding: '6px 12px',
            backgroundColor: '#087A6A',
            color: '#fff',
            fontSize: '12px',
            fontWeight: 600,
            borderRadius: '12px'
          }}>
            RWE-READY
          </span>
        ) : (
          <span style={{
            padding: '6px 12px',
            backgroundColor: '#e9e4d8',
            color: 'rgba(26, 26, 26, 0.6)',
            fontSize: '12px',
            fontWeight: 600,
            borderRadius: '12px'
          }}>
            LIMITED
          </span>
        )}
      </div>
    </div>
  )
}

function MedicationCard({ medication }: { medication: Medication }) {
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '2fr 1fr 1fr 1fr',
      alignItems: 'center',
      padding: '16px',
      backgroundColor: medication.rwe_ready ? 'rgba(8, 122, 106, 0.05)' : '#f5f2ea',
      border: medication.rwe_ready ? '1px solid rgba(8, 122, 106, 0.3)' : '1px solid #e9e4d8',
      borderRadius: '6px'
    }}>
      <div>
        <div style={{
          fontSize: '14px',
          fontWeight: 600,
          color: '#1a1a1a'
        }}>
          {medication.drug_class}
        </div>
        <div style={{
          fontSize: '12px',
          color: 'rgba(26, 26, 26, 0.6)',
          marginTop: '4px'
        }}>
          {medication.total_patients.toLocaleString()} patients
        </div>
      </div>
      <div style={{ textAlign: 'center' }}>
        <div style={{
          fontSize: '18px',
          fontWeight: 600,
          color: medication.sensor_coverage_pct >= 70 ? '#087A6A' : 'rgba(26, 26, 26, 0.6)'
        }}>
          {medication.sensor_coverage_pct}%
        </div>
        <div style={{
          fontSize: '11px',
          color: 'rgba(26, 26, 26, 0.6)'
        }}>
          Sensor Data
        </div>
      </div>
      <div style={{ textAlign: 'center' }}>
        <div style={{
          fontSize: '18px',
          fontWeight: 600,
          color: medication.vitals_coverage_pct >= 70 ? '#087A6A' : 'rgba(26, 26, 26, 0.6)'
        }}>
          {medication.vitals_coverage_pct}%
        </div>
        <div style={{
          fontSize: '11px',
          color: 'rgba(26, 26, 26, 0.6)'
        }}>
          Vitals Data
        </div>
      </div>
      <div style={{ textAlign: 'center' }}>
        {medication.rwe_ready ? (
          <span style={{
            padding: '6px 12px',
            backgroundColor: '#087A6A',
            color: '#fff',
            fontSize: '12px',
            fontWeight: 600,
            borderRadius: '12px'
          }}>
            RWE-READY
          </span>
        ) : (
          <span style={{
            padding: '6px 12px',
            backgroundColor: '#e9e4d8',
            color: 'rgba(26, 26, 26, 0.6)',
            fontSize: '12px',
            fontWeight: 600,
            borderRadius: '12px'
          }}>
            LIMITED
          </span>
        )}
      </div>
    </div>
  )
}

function DataAvailabilityCard({ domain, data, totalN }: { domain: string; data: { count: number; pct: number }; totalN: number }) {
  const isGoodCoverage = data.pct >= 80
  const isModerateCoverage = data.pct >= 50 && data.pct < 80

  const domainLabels: { [key: string]: string } = {
    vitals: 'Vitals',
    labs: 'Laboratory Tests',
    medications: 'Medications',
    diagnoses: 'Diagnoses',
    sensor: 'Sensor Data',
    pro: 'PRO Surveys'
  }

  return (
    <div style={{
      backgroundColor: '#f5f2ea',
      border: '1px solid #e9e4d8',
      borderRadius: '6px',
      padding: '16px'
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
        marginBottom: '12px'
      }}>
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
        <div style={{
          fontSize: '14px',
          fontWeight: 600,
          color: '#1a1a1a'
        }}>
          {domainLabels[domain] || domain}
        </div>
      </div>
      <div style={{
        fontSize: '24px',
        fontWeight: 600,
        color: isGoodCoverage ? '#087A6A' : isModerateCoverage ? '#A25BC5' : 'rgba(26, 26, 26, 0.4)',
        marginBottom: '4px'
      }}>
        {data.pct}%
      </div>
      <div style={{
        fontSize: '12px',
        color: 'rgba(26, 26, 26, 0.6)'
      }}>
        {data.count.toLocaleString()} of {totalN.toLocaleString()} patients
      </div>
    </div>
  )
}
