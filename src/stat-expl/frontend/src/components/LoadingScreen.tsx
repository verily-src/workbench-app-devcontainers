import { useData } from '../context/DataContext'

export default function LoadingScreen() {
  const { loadingProgress, loadingMessage } = useData()

  const totalSteps = Object.keys(loadingProgress).length
  const completedSteps = Object.values(loadingProgress).filter(s => s === 'complete').length
  const errorSteps = Object.values(loadingProgress).filter(s => s === 'error').length
  const progress = totalSteps > 0 ? (completedSteps / totalSteps) * 100 : 0

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: '60vh',
      padding: '40px'
    }}>
      <div style={{
        backgroundColor: '#fff',
        borderRadius: '12px',
        padding: '40px',
        boxShadow: '0 4px 6px rgba(0,0,0,0.1)',
        maxWidth: '500px',
        width: '100%'
      }}>
        <h2 style={{
          fontSize: '24px',
          fontWeight: 600,
          color: '#1e293b',
          marginBottom: '24px',
          textAlign: 'center'
        }}>
          Loading Dataset Explorer
        </h2>

        {/* Progress Bar */}
        <div style={{
          backgroundColor: '#e2e8f0',
          borderRadius: '8px',
          height: '12px',
          marginBottom: '16px',
          overflow: 'hidden'
        }}>
          <div style={{
            backgroundColor: errorSteps > 0 ? '#f59e0b' : '#3b82f6',
            height: '100%',
            width: `${progress}%`,
            transition: 'width 0.3s ease'
          }} />
        </div>

        {/* Progress Text */}
        <p style={{
          textAlign: 'center',
          color: '#64748b',
          fontSize: '14px',
          marginBottom: '24px'
        }}>
          {completedSteps} of {totalSteps} complete
          {errorSteps > 0 && ` (${errorSteps} failed)`}
        </p>

        {/* Current Action */}
        <p style={{
          textAlign: 'center',
          color: '#475569',
          fontSize: '16px',
          marginBottom: '24px',
          fontWeight: 500
        }}>
          {loadingMessage}
        </p>

        {/* Detailed Progress */}
        <div style={{
          backgroundColor: '#f8fafc',
          borderRadius: '6px',
          padding: '16px'
        }}>
          <h3 style={{
            fontSize: '12px',
            fontWeight: 600,
            color: '#64748b',
            marginBottom: '12px',
            textTransform: 'uppercase'
          }}>
            Loading Progress
          </h3>
          {Object.entries(loadingProgress).map(([key, status]) => (
            <div key={key} style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '6px 0',
              borderBottom: '1px solid #e2e8f0',
              fontSize: '13px'
            }}>
              <span style={{ color: '#475569', textTransform: 'capitalize' }}>
                {key}
              </span>
              <span style={{
                color: status === 'complete' ? '#10b981' :
                       status === 'error' ? '#ef4444' :
                       status === 'loading' ? '#3b82f6' : '#94a3b8',
                fontWeight: 500
              }}>
                {status === 'complete' ? '✓ Complete' :
                 status === 'error' ? '✗ Failed' :
                 status === 'loading' ? '⏳ Loading...' : 'Pending'}
              </span>
            </div>
          ))}
        </div>

        {errorSteps > 0 && (
          <div style={{
            marginTop: '16px',
            padding: '12px',
            backgroundColor: '#fef3c7',
            border: '1px solid #fbbf24',
            borderRadius: '6px',
            fontSize: '13px',
            color: '#92400e'
          }}>
            Some data failed to load but the app will continue with available data.
          </div>
        )}
      </div>
    </div>
  )
}
