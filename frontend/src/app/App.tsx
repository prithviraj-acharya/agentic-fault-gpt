import { Navigate, Route, Routes } from 'react-router-dom'
import { DashboardLayout } from './layout/DashboardLayout'
import { LiveMonitoringPage } from './pages/LiveMonitoringPage'
import { WindowAnalysisPage } from './pages/WindowAnalysisPage'

export function App() {
  return (
    <Routes>
      <Route element={<DashboardLayout />}>
        <Route path="/" element={<Navigate to="/live" replace />} />
        <Route path="/live" element={<LiveMonitoringPage />} />
        <Route path="/windows" element={<WindowAnalysisPage />} />
      </Route>
    </Routes>
  )
}
