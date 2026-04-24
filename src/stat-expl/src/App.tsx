import { useState, useEffect } from 'react'

function App() {
  const [health, setHealth] = useState<any>(null)

  useEffect(() => {
    fetch('/dashboard/api/health')
      .then(r => r.json())
      .then(d => setHealth(d))
      .catch(e => console.error('Health check failed:', e))
  }, [])

  return (
    <div style={{ fontFamily: 'system-ui', maxWidth: '800px', margin: '40px auto', padding: '20px' }}>
      <h1 style={{ color: '#2563eb' }}>stat-expl minimal debug v0.0.3</h1>
      <div style={{ background: '#dcfce7', padding: '12px', borderRadius: '4px', margin: '20px 0' }}>
        ✓ Vite React build working
      </div>
      <div style={{ background: '#f3f4f6', padding: '12px', borderRadius: '4px' }}>
        <strong>Health check response:</strong>
        <pre>{JSON.stringify(health, null, 2)}</pre>
      </div>
    </div>
  )
}

export default App
