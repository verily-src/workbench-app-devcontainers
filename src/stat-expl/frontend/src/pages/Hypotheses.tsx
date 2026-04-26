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

interface ComplianceCheck {
  check_name: string
  passed: boolean
  severity: string
  message: string
  details: any
}

interface ValidationState {
  checks: ComplianceCheck[]
  all_passed: boolean
  validator_name: string
  is_approved: boolean
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
  const [validationState, setValidationState] = useState<ValidationState | null>(null)
  const [isValidating, setIsValidating] = useState(false)
  const [validatorName, setValidatorName] = useState('')
  const [isExporting, setIsExporting] = useState(false)
  const [exportResult, setExportResult] = useState<any>(null)

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
    setValidationState(null)
    setExportResult(null)

    fetch(`/dashboard/api/hypotheses/build-cohort?cohort_type=${hypothesis.cohort_type}`)
      .then(r => r.json())
      .then(data => {
        setCohortData(data)
        setIsBuildingCohort(false)
        // Automatically run validation checks
        runValidationChecks(hypothesis.cohort_type, data.patient_ids)
      })
      .catch(err => {
        console.error('Failed to build cohort:', err)
        setIsBuildingCohort(false)
      })
  }

  const runValidationChecks = (cohortType: string, patientIds: string[]) => {
    setIsValidating(true)

    fetch('/dashboard/api/governance/validate-cohort', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cohort_type: cohortType,
        patient_ids: patientIds
      })
    })
      .then(r => r.json())
      .then(data => {
        setValidationState({
          checks: data.checks,
          all_passed: data.all_checks_passed,
          validator_name: '',
          is_approved: false
        })
        setIsValidating(false)
      })
      .catch(err => {
        console.error('Failed to run validation checks:', err)
        setIsValidating(false)
      })
  }

  const approveExport = () => {
    if (!validatorName.trim()) {
      alert('Please enter your name to approve the export')
      return
    }
    setValidationState(prev => prev ? { ...prev, validator_name: validatorName, is_approved: true } : null)
  }

  const exportCohortWithGovernance = () => {
    if (!selectedHypothesis || !cohortData || !validationState?.is_approved) {
      alert('Cohort must be validated and approved before export')
      return
    }

    setIsExporting(true)

    const selectionCriteria = {
      cohort_type: selectedHypothesis.cohort_type,
      hypothesis_title: selectedHypothesis.title
    }

    const sqlQuery = `/* Cohort: ${selectedHypothesis.cohort_type} - ${selectedHypothesis.title} */`

    fetch('/dashboard/api/export/cohort', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cohort_type: selectedHypothesis.cohort_type,
        patient_ids: cohortData.patient_ids,
        selection_criteria: selectionCriteria,
        sql_query: sqlQuery,
        data_sources: ['screener.DM', 'analysis.ENRDT'],
        risk_tier: 'standard',
        validated_by: validationState.validator_name
      })
    })
      .then(r => r.json())
      .then(data => {
        setExportResult(data)
        setIsExporting(false)
      })
      .catch(err => {
        console.error('Export failed:', err)
        alert('Export failed: ' + err.message)
        setIsExporting(false)
      })
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

                    {/* Validation Gate */}
                    {isValidating ? (
                      <div style={{
                        padding: '20px',
                        backgroundColor: '#f5f2ea',
                        borderRadius: '6px',
                        fontSize: '14px',
                        color: 'rgba(26, 26, 26, 0.6)',
                        fontStyle: 'italic',
                        textAlign: 'center'
                      }}>
                        Running compliance checks...
                      </div>
                    ) : validationState ? (
                      <div style={{
                        marginBottom: '24px',
                        padding: '20px',
                        backgroundColor: validationState.all_passed ? 'rgba(8, 122, 106, 0.05)' : 'rgba(211, 92, 101, 0.05)',
                        border: validationState.all_passed ? '1px solid rgba(8, 122, 106, 0.3)' : '1px solid rgba(211, 92, 101, 0.3)',
                        borderRadius: '8px'
                      }}>
                        <h4 style={{
                          fontSize: '16px',
                          fontWeight: 600,
                          color: '#1a1a1a',
                          marginBottom: '16px',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '8px'
                        }}>
                          <span style={{
                            width: '24px',
                            height: '24px',
                            borderRadius: '50%',
                            backgroundColor: validationState.all_passed ? '#087A6A' : '#D35C65',
                            color: '#fff',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontSize: '16px',
                            fontWeight: 'bold'
                          }}>
                            {validationState.all_passed ? '✓' : '!'}
                          </span>
                          Compliance Validation
                        </h4>

                        <div style={{ marginBottom: '20px' }}>
                          {validationState.checks.map((check, i) => (
                            <ComplianceCheckCard key={i} check={check} />
                          ))}
                        </div>

                        {validationState.all_passed && !validationState.is_approved && (
                          <div style={{
                            padding: '16px',
                            backgroundColor: '#fff',
                            borderRadius: '6px',
                            marginBottom: '16px'
                          }}>
                            <label style={{
                              display: 'block',
                              fontSize: '14px',
                              fontWeight: 600,
                              color: '#1a1a1a',
                              marginBottom: '8px'
                            }}>
                              Validator Name (required for export):
                            </label>
                            <input
                              type="text"
                              value={validatorName}
                              onChange={(e) => setValidatorName(e.target.value)}
                              placeholder="Enter your name"
                              style={{
                                width: '100%',
                                padding: '10px',
                                fontSize: '14px',
                                border: '1px solid #e9e4d8',
                                borderRadius: '4px',
                                marginBottom: '12px'
                              }}
                            />
                            <button
                              onClick={approveExport}
                              style={{
                                padding: '10px 20px',
                                backgroundColor: '#087A6A',
                                color: '#fff',
                                border: 'none',
                                borderRadius: '6px',
                                fontSize: '14px',
                                fontWeight: 600,
                                cursor: 'pointer'
                              }}
                            >
                              Approve for Export
                            </button>
                          </div>
                        )}

                        {validationState.is_approved && (
                          <div style={{
                            padding: '12px',
                            backgroundColor: 'rgba(8, 122, 106, 0.1)',
                            borderRadius: '6px',
                            fontSize: '14px',
                            color: '#087A6A',
                            fontWeight: 600
                          }}>
                            ✓ Approved by: {validationState.validator_name}
                          </div>
                        )}
                      </div>
                    ) : null}

                    {/* Export Button */}
                    {validationState?.is_approved ? (
                      <div>
                        <button
                          onClick={exportCohortWithGovernance}
                          disabled={isExporting}
                          style={{
                            padding: '12px 24px',
                            backgroundColor: isExporting ? '#e9e4d8' : '#087A6A',
                            color: isExporting ? 'rgba(26, 26, 26, 0.4)' : '#fff',
                            border: 'none',
                            borderRadius: '6px',
                            fontSize: '16px',
                            fontWeight: 600,
                            cursor: isExporting ? 'not-allowed' : 'pointer',
                            width: '100%'
                          }}
                        >
                          {isExporting ? 'Exporting...' : 'Export Cohort with Governance Report'}
                        </button>

                        {exportResult && (
                          <div style={{
                            marginTop: '16px',
                            padding: '16px',
                            backgroundColor: exportResult.success ? 'rgba(8, 122, 106, 0.05)' : 'rgba(211, 92, 101, 0.05)',
                            border: exportResult.success ? '1px solid rgba(8, 122, 106, 0.3)' : '1px solid rgba(211, 92, 101, 0.3)',
                            borderRadius: '6px'
                          }}>
                            <div style={{
                              fontSize: '14px',
                              fontWeight: 600,
                              color: exportResult.success ? '#087A6A' : '#D35C65',
                              marginBottom: '8px'
                            }}>
                              {exportResult.message}
                            </div>
                            {exportResult.success && (
                              <div style={{ fontSize: '12px', color: 'rgba(26, 26, 26, 0.6)' }}>
                                <div>Export: <code style={{ fontSize: '11px', backgroundColor: '#f5f2ea', padding: '2px 6px', borderRadius: '3px' }}>{exportResult.export_path}</code></div>
                                <div style={{ marginTop: '4px' }}>Governance Report: <code style={{ fontSize: '11px', backgroundColor: '#f5f2ea', padding: '2px 6px', borderRadius: '3px' }}>{exportResult.governance_report_path}</code></div>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div style={{
                        padding: '12px',
                        backgroundColor: '#f5f2ea',
                        borderRadius: '6px',
                        fontSize: '14px',
                        color: 'rgba(26, 26, 26, 0.6)',
                        textAlign: 'center',
                        fontStyle: 'italic'
                      }}>
                        Complete compliance validation and approval before exporting
                      </div>
                    )}
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

function ComplianceCheckCard({ check }: { check: ComplianceCheck }) {
  const severityColors = {
    error: { bg: 'rgba(211, 92, 101, 0.1)', border: '#D35C65', text: '#D35C65' },
    warning: { bg: 'rgba(162, 91, 197, 0.1)', border: '#A25BC5', text: '#A25BC5' },
    info: { bg: 'rgba(8, 122, 106, 0.1)', border: '#087A6A', text: '#087A6A' }
  }

  const colors = severityColors[check.severity as keyof typeof severityColors] || severityColors.info

  return (
    <div style={{
      padding: '12px',
      backgroundColor: colors.bg,
      border: `1px solid ${colors.border}`,
      borderRadius: '6px',
      marginBottom: '8px'
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        marginBottom: '4px'
      }}>
        <span style={{
          width: '18px',
          height: '18px',
          borderRadius: '50%',
          backgroundColor: check.passed ? '#087A6A' : colors.border,
          color: '#fff',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: '12px',
          fontWeight: 'bold',
          flexShrink: 0
        }}>
          {check.passed ? '✓' : '!'}
        </span>
        <div style={{
          fontSize: '13px',
          fontWeight: 600,
          color: '#1a1a1a'
        }}>
          {check.check_name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}
        </div>
        <div style={{
          marginLeft: 'auto',
          fontSize: '11px',
          fontWeight: 600,
          color: colors.text,
          textTransform: 'uppercase'
        }}>
          {check.severity}
        </div>
      </div>
      <div style={{
        fontSize: '12px',
        color: 'rgba(26, 26, 26, 0.7)',
        marginLeft: '26px'
      }}>
        {check.message}
      </div>
      {check.details && (
        <div style={{
          marginTop: '8px',
          marginLeft: '26px',
          fontSize: '11px',
          color: 'rgba(26, 26, 26, 0.6)',
          fontFamily: 'monospace',
          backgroundColor: 'rgba(0, 0, 0, 0.03)',
          padding: '6px 8px',
          borderRadius: '4px'
        }}>
          {JSON.stringify(check.details, null, 2)}
        </div>
      )}
    </div>
  )
}
