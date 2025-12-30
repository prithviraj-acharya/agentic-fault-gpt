import { Navigate, Route, Routes } from 'react-router-dom'
import { DashboardLayout } from './layout/DashboardLayout'
import { LiveMonitoringPage } from './pages/LiveMonitoringPage'
import { WindowAnalysisPage } from './pages/WindowAnalysisPage'
import { TicketsPage } from './pages/TicketsPage'
import { TicketDetailPage } from './pages/TicketDetailPage'

export function App() {
  return (
    <Routes>
      <Route element={<DashboardLayout />}>
        <Route path="/" element={<Navigate to="/live" replace />} />
        <Route path="/live" element={<LiveMonitoringPage />} />
        <Route path="/windows" element={<WindowAnalysisPage />} />
        <Route path="/tickets" element={<TicketsPage />} />
        <Route path="/tickets/:ticketId" element={<TicketDetailPage />} />
      </Route>
    </Routes>
  )
}
