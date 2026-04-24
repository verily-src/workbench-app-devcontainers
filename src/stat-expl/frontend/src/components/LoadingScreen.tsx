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
        boxShadow: '0 2px 4px rgba(0,0,0,0.08)',
        border: '1px solid #e9e4d8',
        maxWidth: '500px',
        width: '100%'
      }}>
        <h2 style={{
          fontSize: '24px',
          fontWeight: 600,
          color: '#1a1a1a',
          marginBottom: '24px',
          textAlign: 'center'
        }}>
          Loading Dataset Explorer
        </h2>

        {/* Progress Bar */}
        <div style={{
          backgroundColor: '#e9e4d8',
          borderRadius: '8px',
          height: '12px',
          marginBottom: '16px',
          overflow: 'hidden'
        }}>
          <div style={{
            backgroundColor: errorSteps > 0 ? '#D35C65' : '#087A6A',
            height: '100%',
            width: `${progress}%`,
            transition: 'width 0.3s ease'
          }} />
        </div>

        {/* Progress Text */}
        <p style={{
          textAlign: 'center',
          color: 'rgba(26, 26, 26, 0.6)',
          fontSize: '14px',
          marginBottom: '24px'
        }}>
          {completedSteps} of {totalSteps} complete
          {errorSteps > 0 && ` (${errorSteps} failed)`}
        </p>

        {/* Current Action */}
        <p style={{
          textAlign: 'center',
          color: '#1a1a1a',
          fontSize: '16px',
          marginBottom: '24px',
          fontWeight: 500
        }}>
          {loadingMessage}
        </p>

        {/* Detailed Progress */}
        <div style={{
          backgroundColor: '#f5f2ea',
          borderRadius: '6px',
          padding: '16px'
        }}>
          <h3 style={{
            fontSize: '12px',
            fontWeight: 600,
            color: 'rgba(26, 26, 26, 0.6)',
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
              borderBottom: '1px solid #e9e4d8',
              fontSize: '13px'
            }}>
              <span style={{ color: '#1a1a1a', textTransform: 'capitalize' }}>
                {key}
              </span>
              <span style={{
                color: status === 'complete' ? '#087A6A' :
                       status === 'error' ? '#D35C65' :
                       status === 'loading' ? '#087A6A' : 'rgba(26, 26, 26, 0.4)',
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
            backgroundColor: 'rgba(211, 92, 101, 0.1)',
            border: '1px solid #D35C65',
            borderRadius: '6px',
            fontSize: '13px',
            color: '#8B3A3F'
          }}>
            Some data failed to load but the app will continue with available data.
          </div>
        )}
      </div>
    </div>
  )
}
