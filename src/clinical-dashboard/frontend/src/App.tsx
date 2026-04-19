import { useEffect, useState } from 'react'
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { api } from './api/client'
import CohortSelector from './pages/CohortSelector'
import DeviceData from './pages/DeviceData'
import ClinicalTimeline from './pages/ClinicalTimeline'

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

function useHealthProbe() {
  const [state, setState] = useState<'pending' | 'ok' | 'error'>('pending')
  const [msg, setMsg] = useState<string>('')
  useEffect(() => {
    api
      .get('health')
      .then((r) => {
        setState('ok')
        setMsg(`${r.data.env} · demo=${r.data.use_demo_tables}`)
      })
      .catch((e) => {
        setState('error')
        setMsg(
          `api/health → ${e?.response?.status ?? 'network'} · URL ${e?.config?.baseURL ?? ''}${e?.config?.url ?? ''}`,
        )
      })
  }, [])
  return { state, msg }
}

const NAV = [
  { to: '/cohort', label: 'Cohort Selector' },
  { to: '/device', label: 'Device Data' },
  { to: '/clinical', label: 'Clinical Timeline' },
]

export default function App() {
  const { pathname } = useLocation()
  const health = useHealthProbe()

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-verily-mute bg-white">
        <div className="mx-auto flex max-w-[1600px] items-center gap-6 px-6 py-3">
          <Link to="/cohort" className="flex items-center gap-2 text-verily-ink no-underline hover:no-underline">
            <VerilyMark className="h-5 w-5" />
            <span className="font-semibold tracking-tight">Cohort Multimodal Dashboard</span>
          </Link>
          <nav className="flex gap-1">
            {NAV.map((n) => {
              const active = pathname.startsWith(n.to)
              return (
                <Link
                  key={n.to}
                  to={n.to}
                  className={`rounded-md px-3 py-1.5 text-sm font-medium no-underline hover:no-underline
                    ${active
                      ? 'bg-verily-mute text-verily-ink'
                      : 'text-verily-ink/70 hover:bg-verily-mute/60'
                    }`}
                >
                  {n.label}
                </Link>
              )
            })}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-xs">
            <span className="flex items-center gap-1.5">
              <span
                className={`inline-block h-2 w-2 rounded-full ${
                  health.state === 'ok'
                    ? 'bg-verily-primary'
                    : health.state === 'error'
                      ? 'bg-verily-warm'
                      : 'bg-verily-mute'
                }`}
                title={health.msg}
              />
              <span className="text-verily-ink/50">
                {health.state === 'ok' ? 'API connected' : health.state === 'error' ? 'API offline' : 'connecting…'}
              </span>
            </span>
          </div>
        </div>
      </header>
      {health.state === 'error' ? (
        <div className="border-b border-verily-warm/30 bg-verily-warm/10 px-6 py-2 text-sm text-verily-warm">
          <span className="font-medium">Backend not reachable.</span>{' '}
          <span className="font-mono text-xs">{health.msg}</span>
        </div>
      ) : null}
      <main className="flex-1">
        <Routes>
          <Route path="/" element={<Navigate to="/cohort" replace />} />
          <Route path="/cohort" element={<CohortSelector />} />
          <Route path="/device" element={<DeviceData />} />
          <Route path="/clinical" element={<ClinicalTimeline />} />
          <Route path="*" element={<Navigate to="/cohort" replace />} />
        </Routes>
      </main>
    </div>
  )
}
