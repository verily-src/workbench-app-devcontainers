import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { CohortProvider } from './context/CohortContext';
import { Nav } from './components/Nav';
import { Passport } from './pages/Passport';
import { Population } from './pages/Population';
import { Variables } from './pages/Variables';
import { Quality } from './pages/Quality';
import { Hypotheses } from './pages/Hypotheses';
import { TestPage } from './pages/TestPage';

function App() {
  return (
    <BrowserRouter basename="/dashboard">
      <CohortProvider>
        <div className="min-h-screen bg-gray-50">
          <Nav />
          <main>
            <Routes>
              <Route path="/" element={<Navigate to="/passport" replace />} />
              <Route path="/passport" element={<Passport />} />
              <Route path="/population" element={<Population />} />
              <Route path="/variables" element={<Variables />} />
              <Route path="/quality" element={<Quality />} />
              <Route path="/hypotheses" element={<Hypotheses />} />
              <Route path="/test" element={<TestPage />} />
            </Routes>
          </main>
        </div>
      </CohortProvider>
    </BrowserRouter>
  );
}

export default App;
