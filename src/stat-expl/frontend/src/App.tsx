import { useState, useEffect } from 'react'
import Plot from 'react-plotly.js'
import Plotly from 'plotly.js-dist-min'

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
      <h1 style={{ color: '#2563eb' }}>stat-expl minimal debug v0.0.5</h1>
      <div style={{ background: '#dcfce7', padding: '12px', borderRadius: '4px', margin: '20px 0' }}>
        ✓ Vite React build working<br/>
        ✓ Plotly.js without polyfills<br/>
        ✓ backend/frontend folder structure
      </div>
      <div style={{ background: '#f3f4f6', padding: '12px', borderRadius: '4px', marginBottom: '20px' }}>
        <strong>Health check response:</strong>
        <pre>{JSON.stringify(health, null, 2)}</pre>
      </div>
      <div style={{ background: '#fff', padding: '12px', border: '1px solid #e5e7eb', borderRadius: '4px' }}>
        <strong>Test chart (Plotly):</strong>
        <Plot
          plotly={Plotly}
          data={[
            {
              x: [1, 2, 3, 4, 5],
              y: [2, 4, 3, 5, 6],
              type: 'scatter',
              mode: 'lines+markers',
              marker: { color: '#2563eb' },
            },
          ]}
          layout={{
            width: 700,
            height: 300,
            title: 'Test Chart - No Polyfills Needed',
            margin: { t: 40, r: 20, b: 40, l: 40 }
          }}
        />
      </div>
    </div>
  )
}

export default App
