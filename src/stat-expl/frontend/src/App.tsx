import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { DataProvider, useData } from './context/DataContext'
import { CohortProvider } from './context/CohortContext'
import Nav from './components/Nav'
import LoadingScreen from './components/LoadingScreen'
import Passport from './pages/Passport'
import Population from './pages/Population'
import Variables from './pages/Variables'
import Quality from './pages/Quality'
import Hypotheses from './pages/Hypotheses'

function AppContent() {
  const { isLoading } = useData()

  if (isLoading) {
    return (
      <div style={{
        minHeight: '100vh',
        backgroundColor: '#f5f5f5',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
      }}>
        <Nav />
        <LoadingScreen />
      </div>
    )
  }

  return (
    <div style={{
      minHeight: '100vh',
      backgroundColor: '#f5f5f5',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
    }}>
      <Nav />
      <div style={{ maxWidth: '1400px', margin: '0 auto', padding: '24px' }}>
        <Routes>
          <Route path="/" element={<Navigate to="/passport" replace />} />
          <Route path="/passport" element={<Passport />} />
          <Route path="/population" element={<Population />} />
          <Route path="/variables" element={<Variables />} />
          <Route path="/quality" element={<Quality />} />
          <Route path="/hypotheses" element={<Hypotheses />} />
        </Routes>
      </div>
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
