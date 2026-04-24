import { Link, useLocation } from 'react-router-dom'
import { useCohort } from '../context/CohortContext'

const pages = [
  { path: '/passport', label: 'Passport' },
  { path: '/population', label: 'Population' },
  { path: '/variables', label: 'Variables' },
  { path: '/quality', label: 'Quality' },
  { path: '/hypotheses', label: 'Hypotheses' },
]

export default function Nav() {
  const location = useLocation()
  const { flags } = useCohort()

  return (
    <nav style={{
      backgroundColor: '#1e293b',
      borderBottom: '1px solid #334155',
      padding: '0 24px',
    }}>
      <div style={{ maxWidth: '1400px', margin: '0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <h1 style={{
            color: '#fff',
            fontSize: '18px',
            fontWeight: 600,
            margin: '16px 0',
            padding: '0 16px 0 0',
            borderRight: '1px solid #475569'
          }}>
            Dataset Statistical Explorer
          </h1>
          <div style={{ display: 'flex', gap: '4px' }}>
            {pages.map(page => {
              const isActive = location.pathname === page.path
              return (
                <Link
                  key={page.path}
                  to={page.path}
                  style={{
                    color: isActive ? '#fff' : '#94a3b8',
                    backgroundColor: isActive ? '#334155' : 'transparent',
                    padding: '8px 16px',
                    borderRadius: '4px',
                    textDecoration: 'none',
                    fontSize: '14px',
                    fontWeight: 500,
                    transition: 'all 0.2s',
                  }}
                  onMouseEnter={e => {
                    if (!isActive) {
                      e.currentTarget.style.backgroundColor = '#334155'
                      e.currentTarget.style.color = '#fff'
                    }
                  }}
                  onMouseLeave={e => {
                    if (!isActive) {
                      e.currentTarget.style.backgroundColor = 'transparent'
                      e.currentTarget.style.color = '#94a3b8'
                    }
                  }}
                >
                  {page.label}
                </Link>
              )
            })}
          </div>
        </div>
        {flags.length > 0 && (
          <div style={{
            color: '#fbbf24',
            fontSize: '14px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}>
            <span>⚠</span>
            <span>{flags.length} flag{flags.length !== 1 ? 's' : ''}</span>
          </div>
        )}
      </div>
    </nav>
  )
}
