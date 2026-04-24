import { BrowserRouter, Routes, Route, Navigate, Link, useLocation } from 'react-router-dom'
import { DataProvider, useData } from './context/DataContext'
import { CohortProvider } from './context/CohortContext'
import LoadingScreen from './components/LoadingScreen'
import Passport from './pages/Passport'
import Population from './pages/Population'
import Variables from './pages/Variables'
import Quality from './pages/Quality'
import Hypotheses from './pages/Hypotheses'

function VerilyMark({ className = '' }: { className?: string }) {
  return (
    <svg
      viewBox="0 8 28 14"
      className={className}
      aria-label="Verily mark"
      role="img"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M16.2784 19.9267C18.9672 17.3219 24.484 11.4353 27.163 8.59909C27.6949 8.03628 28.7276 8.40091 28.7276 9.16348V21.4549H1.63477V8.58164L14.7172 8.54835V19.3005C14.7172 20.09 15.7024 20.4864 16.2784 19.9283V19.9267Z"
        fill="#087A6A"
      />
    </svg>
  )
}

const NAV_LINKS = [
  { to: '/passport', label: 'Passport' },
  { to: '/population', label: 'Population' },
  { to: '/variables', label: 'Variables' },
  { to: '/quality', label: 'Quality' },
  { to: '/hypotheses', label: 'Hypotheses' },
]

function AppContent() {
  const { isLoading, apiStatus } = useData()
  const { pathname } = useLocation()

  if (isLoading) {
    return (
      <div style={{
        minHeight: '100vh',
        backgroundColor: '#f5f2ea',
        fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
      }}>
        <LoadingScreen />
      </div>
    )
  }

  return (
    <div style={{
      minHeight: '100vh',
      backgroundColor: '#f5f2ea',
      fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
    }}>
      <header style={{
        borderBottom: '1px solid #e9e4d8',
        backgroundColor: '#fff'
      }}>
        <div style={{
          maxWidth: '1600px',
          margin: '0 auto',
          display: 'flex',
          alignItems: 'center',
          gap: '24px',
          padding: '12px 24px'
        }}>
          <Link to="/passport" style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            color: '#1a1a1a',
            textDecoration: 'none'
          }}>
            <VerilyMark className="" style={{ height: '20px', width: '20px' }} />
            <span style={{ fontWeight: 600, letterSpacing: '-0.025em' }}>Dataset Explorer</span>
          </Link>
          <nav style={{ display: 'flex', gap: '4px' }}>
            {NAV_LINKS.map((n) => {
              const active = pathname.startsWith(n.to)
              return (
                <Link
                  key={n.to}
                  to={n.to}
                  style={{
                    borderRadius: '6px',
                    padding: '6px 12px',
                    fontSize: '14px',
                    fontWeight: 500,
                    textDecoration: 'none',
                    backgroundColor: active ? '#e9e4d8' : 'transparent',
                    color: active ? '#1a1a1a' : 'rgba(26, 26, 26, 0.7)',
                  }}
                  onMouseEnter={(e) => {
                    if (!active) e.currentTarget.style.backgroundColor = 'rgba(233, 228, 216, 0.6)'
                  }}
                  onMouseLeave={(e) => {
                    if (!active) e.currentTarget.style.backgroundColor = 'transparent'
                  }}
                >
                  {n.label}
                </Link>
              )
            })}
          </nav>
          <div style={{
            marginLeft: 'auto',
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            fontSize: '12px'
          }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span
                style={{
                  display: 'inline-block',
                  height: '8px',
                  width: '8px',
                  borderRadius: '50%',
                  backgroundColor: apiStatus === 'ok' ? '#087A6A' : '#D35C65'
                }}
                title={`API: ${apiStatus || 'unknown'}`}
              />
              <span style={{ color: 'rgba(26, 26, 26, 0.5)' }}>
                {apiStatus === 'ok' ? 'API connected' : 'API offline'}
              </span>
            </span>
          </div>
        </div>
      </header>
      <main style={{ maxWidth: '1600px', margin: '0 auto', padding: '24px' }}>
        <Routes>
          <Route path="/" element={<Navigate to="/passport" replace />} />
          <Route path="/passport" element={<Passport />} />
          <Route path="/population" element={<Population />} />
          <Route path="/variables" element={<Variables />} />
          <Route path="/quality" element={<Quality />} />
          <Route path="/hypotheses" element={<Hypotheses />} />
        </Routes>
      </main>
    </div>
  )
}

function App() {
  return (
    <BrowserRouter>
      <DataProvider>
        <CohortProvider>
          <AppContent />
        </CohortProvider>
      </DataProvider>
    </BrowserRouter>
  )
}

export default App
