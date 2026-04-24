import { useState, useEffect } from 'react'
import Plot from 'react-plotly.js'
import Plotly from 'plotly.js-dist-min'

interface AgeHistogramBin {
  age_min: number
  age_max: number
  count: number
}

interface Diagnosis {
  name: string
  patient_count: number
}

interface Medication {
  drug_class: string
  patient_count: number
}

interface Demographics {
  sex: { sex: string; count: number }[]
  race: { race: string; count: number }[]
  ethnicity: { ethnicity: string; count: number }[]
  sites: { site: string; count: number }[]
  total_participants: number
  data_capture_note: string
}

export default function Population() {
  const [ageHistogram, setAgeHistogram] = useState<AgeHistogramBin[]>([])
  const [diagnoses, setDiagnoses] = useState<Diagnosis[]>([])
  const [medications, setMedications] = useState<Medication[]>([])
  const [demographics, setDemographics] = useState<Demographics | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<any>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isSearching, setIsSearching] = useState(false)

  // Load initial data
  useEffect(() => {
    Promise.all([
      fetch('/dashboard/api/population/age-histogram').then(r => r.json()),
      fetch('/dashboard/api/population/top-diagnoses').then(r => r.json()),
      fetch('/dashboard/api/population/top-medications').then(r => r.json()),
      fetch('/dashboard/api/population/demographics').then(r => r.json())
    ])
      .then(([ageData, dxData, medData, demoData]) => {
        setAgeHistogram(ageData.bins)
        setDiagnoses(dxData.diagnoses)
        setMedications(medData.medications)
        setDemographics(demoData)
        setIsLoading(false)
      })
      .catch(err => {
        console.error('Failed to load population data:', err)
        setIsLoading(false)
      })
  }, [])

  // Handle search with debounce
  useEffect(() => {
    if (!searchQuery.trim()) {
      setSearchResults(null)
      return
    }

    setIsSearching(true)
    const timer = setTimeout(() => {
      fetch(`/dashboard/api/population/search?query=${encodeURIComponent(searchQuery)}`)
        .then(r => r.json())
        .then(data => {
          setSearchResults(data)
          setIsSearching(false)
        })
        .catch(err => {
          console.error('Search failed:', err)
          setIsSearching(false)
        })
    }, 500)

    return () => clearTimeout(timer)
  }, [searchQuery])

  if (isLoading) {
    return <div style={{ color: 'rgba(26, 26, 26, 0.6)' }}>Loading population data...</div>
  }

  const displayAgeHist = searchResults ? searchResults.age_histogram : ageHistogram
  const displayN = searchResults ? searchResults.matched_patients : (demographics?.total_participants || 2502)
  const totalN = demographics?.total_participants || 2502

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
          Population Characteristics
        </h2>
        <p style={{ color: 'rgba(26, 26, 26, 0.6)', fontSize: '14px', marginBottom: '24px' }}>
          Demographics, diagnoses, and medications for cohort discovery
        </p>

        {/* Search Box */}
        <div style={{ marginBottom: '32px' }}>
          <label style={{
            display: 'block',
            fontSize: '14px',
            fontWeight: 600,
            color: '#1a1a1a',
            marginBottom: '8px'
          }}>
            Search by Clinical Concept
          </label>
          <input
            type="text"
            placeholder="Type a diagnosis (e.g., heart failure, diabetes, hypertension)..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              width: '100%',
              padding: '12px 16px',
              fontSize: '16px',
              border: '2px solid #e9e4d8',
              borderRadius: '8px',
              outline: 'none',
              transition: 'border-color 0.2s'
            }}
            onFocus={(e) => e.currentTarget.style.borderColor = '#087A6A'}
            onBlur={(e) => e.currentTarget.style.borderColor = '#e9e4d8'}
          />
          {searchResults && (
            <div style={{
              marginTop: '12px',
              padding: '12px 16px',
              backgroundColor: 'rgba(8, 122, 106, 0.05)',
              border: '1px solid rgba(8, 122, 106, 0.2)',
              borderRadius: '6px',
              fontSize: '14px',
              color: '#087A6A',
              fontWeight: 600
            }}>
              Found {searchResults.matched_patients.toLocaleString()} patients matching "{searchResults.search_query}"
              <span style={{ fontWeight: 400, marginLeft: '8px' }}>
                ({Math.round(100 * searchResults.matched_patients / totalN)}% of cohort)
              </span>
            </div>
          )}
          {isSearching && (
            <div style={{
              marginTop: '12px',
              fontSize: '14px',
              color: 'rgba(26, 26, 26, 0.6)',
              fontStyle: 'italic'
            }}>
              Searching...
            </div>
          )}
        </div>

        {/* Current N Display */}
        <div style={{
          marginBottom: '32px',
          padding: '16px',
          backgroundColor: '#f5f2ea',
          border: '1px solid #e9e4d8',
          borderRadius: '6px'
        }}>
          <div style={{ fontSize: '12px', color: 'rgba(26, 26, 26, 0.6)', marginBottom: '4px', textTransform: 'uppercase', fontWeight: 600 }}>
            Current Cohort Size
          </div>
          <div style={{ fontSize: '32px', fontWeight: 600, color: '#1a1a1a' }}>
            N = {displayN.toLocaleString()}
            {searchResults && (
              <span style={{ fontSize: '16px', fontWeight: 400, color: 'rgba(26, 26, 26, 0.6)', marginLeft: '16px' }}>
                of {totalN.toLocaleString()} total
              </span>
            )}
          </div>
        </div>

        {/* Age Histogram */}
        <div style={{ marginBottom: '32px' }}>
          <h3 style={{ fontSize: '18px', fontWeight: 600, color: '#1a1a1a', marginBottom: '16px' }}>
            Age Distribution
          </h3>
          {displayAgeHist.length > 0 ? (
            <Plot
              plotly={Plotly}
              data={[
                {
                  x: displayAgeHist.map(b => `${b.age_min}-${b.age_max}`),
                  y: displayAgeHist.map(b => b.count),
                  type: 'bar',
                  marker: { color: '#087A6A' },
                  text: displayAgeHist.map(b => b.count.toString()),
                  textposition: 'auto',
                },
              ]}
              layout={{
                width: 900,
                height: 300,
                margin: { t: 20, r: 20, b: 60, l: 60 },
                xaxis: { title: 'Age Group (years)', tickangle: -45 },
                yaxis: { title: 'Number of Participants' },
                plot_bgcolor: '#f5f2ea',
                paper_bgcolor: '#fff',
              }}
              config={{ displayModeBar: false }}
            />
          ) : (
            <p style={{ color: 'rgba(26, 26, 26, 0.6)', fontStyle: 'italic' }}>No age data for selected cohort</p>
          )}
        </div>

        {/* Sex and Demographics Grid */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(2, 1fr)',
          gap: '24px',
          marginBottom: '32px'
        }}>
          {/* Sex Breakdown */}
          {demographics && (
            <div>
              <h3 style={{ fontSize: '18px', fontWeight: 600, color: '#1a1a1a', marginBottom: '16px' }}>
                Sex Distribution
              </h3>
              {demographics.sex.map(item => (
                <div key={item.sex} style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '12px 16px',
                  marginBottom: '8px',
                  backgroundColor: '#f5f2ea',
                  borderRadius: '6px'
                }}>
                  <span style={{ fontSize: '14px', fontWeight: 500, color: '#1a1a1a' }}>{item.sex}</span>
                  <span style={{ fontSize: '14px', fontWeight: 600, color: '#087A6A' }}>
                    {item.count.toLocaleString()} ({Math.round(100 * item.count / totalN)}%)
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Race Breakdown */}
          {demographics && (
            <div>
              <h3 style={{ fontSize: '18px', fontWeight: 600, color: '#1a1a1a', marginBottom: '16px' }}>
                Race
              </h3>
              {demographics.race.map(item => (
                <div key={item.race} style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '12px 16px',
                  marginBottom: '8px',
                  backgroundColor: '#f5f2ea',
                  borderRadius: '6px'
                }}>
                  <span style={{ fontSize: '14px', fontWeight: 500, color: '#1a1a1a' }}>{item.race}</span>
                  <span style={{ fontSize: '14px', fontWeight: 600, color: '#087A6A' }}>
                    {item.count.toLocaleString()} ({Math.round(100 * item.count / totalN)}%)
                  </span>
                </div>
              ))}
              <p style={{
                marginTop: '12px',
                fontSize: '12px',
                color: 'rgba(26, 26, 26, 0.6)',
                fontStyle: 'italic'
              }}>
                {demographics.data_capture_note}
              </p>
            </div>
          )}
        </div>

        {/* Top Diagnoses */}
        <div style={{ marginBottom: '32px' }}>
          <h3 style={{ fontSize: '18px', fontWeight: 600, color: '#1a1a1a', marginBottom: '16px' }}>
            Top 20 Diagnoses
          </h3>
          <div style={{
            backgroundColor: '#f5f2ea',
            borderRadius: '6px',
            padding: '16px',
            maxHeight: '400px',
            overflowY: 'auto'
          }}>
            {diagnoses.map((dx, i) => (
              <div key={dx.name} style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '10px 12px',
                marginBottom: '4px',
                backgroundColor: '#fff',
                borderRadius: '4px'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <span style={{
                    fontSize: '12px',
                    fontWeight: 600,
                    color: 'rgba(26, 26, 26, 0.4)',
                    minWidth: '24px'
                  }}>
                    {i + 1}
                  </span>
                  <span style={{ fontSize: '14px', color: '#1a1a1a' }}>
                    {dx.name}
                  </span>
                </div>
                <span style={{ fontSize: '14px', fontWeight: 600, color: '#087A6A' }}>
                  {dx.patient_count.toLocaleString()}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Top Medication Classes */}
        <div style={{ marginBottom: '32px' }}>
          <h3 style={{ fontSize: '18px', fontWeight: 600, color: '#1a1a1a', marginBottom: '16px' }}>
            Top 20 Medication Classes
          </h3>
          <div style={{
            backgroundColor: '#f5f2ea',
            borderRadius: '6px',
            padding: '16px',
            maxHeight: '400px',
            overflowY: 'auto'
          }}>
            {medications.map((med, i) => (
              <div key={med.drug_class} style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '10px 12px',
                marginBottom: '4px',
                backgroundColor: '#fff',
                borderRadius: '4px'
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <span style={{
                    fontSize: '12px',
                    fontWeight: 600,
                    color: 'rgba(26, 26, 26, 0.4)',
                    minWidth: '24px'
                  }}>
                    {i + 1}
                  </span>
                  <span style={{ fontSize: '14px', color: '#1a1a1a' }}>
                    {med.drug_class}
                  </span>
                </div>
                <span style={{ fontSize: '14px', fontWeight: 600, color: '#087A6A' }}>
                  {med.patient_count.toLocaleString()}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
