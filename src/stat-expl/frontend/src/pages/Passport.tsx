import { useData } from '../context/DataContext'

export default function Passport() {
  const { passportMetrics, domainCoverage, isLoading } = useData()

  if (isLoading) {
    return (
      <div style={{ color: 'rgba(26, 26, 26, 0.6)' }}>
        Loading passport data...
      </div>
    )
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
          Dataset Passport
        </h2>
        <p style={{ color: 'rgba(26, 26, 26, 0.6)', fontSize: '14px', marginBottom: '24px' }}>
          High-level overview of dataset provenance, structure, and coverage
        </p>

        {/* Key Metrics Header Card */}
        {passportMetrics && (
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: '16px',
            marginBottom: '32px'
          }}>
            <MetricCard
              label="Unique Patients"
              value={passportMetrics.total_participants.toLocaleString()}
            />
            <MetricCard
              label="Date Range"
              value={`${formatDate(passportMetrics.enrollment_start)} - ${formatDate(passportMetrics.enrollment_end)}`}
              small
            />
            <MetricCard
              label="Last Data Refresh"
              value={formatDateTime(passportMetrics.last_refresh)}
              small
            />
            <MetricCard
              label="Median Follow-up"
              value={`${passportMetrics.median_followup_days} days`}
              subtitle={`IQR: ${passportMetrics.followup_q25}-${passportMetrics.followup_q75} days`}
            />
          </div>
        )}

        {/* Domain Coverage Checklist */}
        {domainCoverage && (
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
              {domainCoverage.domains.map(domain => (
                <DomainCard key={domain.name} domain={domain} />
              ))}
            </div>
            <p style={{
              marginTop: '16px',
              fontSize: '13px',
              color: 'rgba(26, 26, 26, 0.6)',
              fontStyle: 'italic'
            }}>
              Coverage shows percentage of {domainCoverage.total_participants.toLocaleString()} total participants with at least one record in each domain
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

function MetricCard({ label, value, subtitle, small }: { label: string; value: string; subtitle?: string; small?: boolean }) {
  return (
    <div style={{
      backgroundColor: '#f5f2ea',
      border: '1px solid #e9e4d8',
      borderRadius: '6px',
      padding: '16px'
    }}>
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
        fontSize: small ? '16px' : '24px',
        fontWeight: 600,
        color: '#1a1a1a',
        marginBottom: subtitle ? '4px' : '0'
      }}>
        {value}
      </div>
      {subtitle && (
        <div style={{
          fontSize: '12px',
          color: 'rgba(26, 26, 26, 0.5)'
        }}>
          {subtitle}
        </div>
      )}
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

function formatDate(dateString: string | null): string {
  if (!dateString) return 'N/A'
  const date = new Date(dateString)
  return date.toLocaleDateString('en-US', { year: 'numeric', month: 'short' })
}

function formatDateTime(dateString: string | null): string {
  if (!dateString) return 'N/A'
  const date = new Date(dateString)
  return date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
}
