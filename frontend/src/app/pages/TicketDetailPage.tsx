import { useNavigate, useParams } from 'react-router-dom';
import { useState } from 'react';

const MOCK_TICKET = {
  id: '8492',
  ahu: 'AHU-01',
  status: 'Pending',
  statusColor: 'bg-amber-100 text-amber-800 border-amber-200',
  diagnosis: 'Stuck Damper Actuator',
  signals: [
    { label: 'Valve', value: '45%' },
    { label: 'Supply Air Temperature (SAT)', value: '55.4°F' },
  ],
  confidence: 87,
  severity: 'High',
  severityColor: 'bg-rose-100 text-rose-800 border-rose-200',
  recommendation: 'Inspect damper linkage and actuator voltage.',
  aiHypothesis: 'Stuck Damper Actuator',
  alternatives: ['Sensor Drift', 'Low Refrigerant'],
  chart: {
    times: ['13:30', '13:35', '13:40', '13:45', '13:50', '13:55'],
    valve: [40, 45, 45, 45, 45, 45],
    sat: [54.0, 54.8, 55.0, 55.2, 55.3, 55.4],
    highlightIdx: 5,
  },
};

const TABS = ['Correlation Analysis', 'Similar Cases', 'System Manuals'];

export function TicketDetailPage() {
  const navigate = useNavigate();
  const { ticketId } = useParams();
  const [tab, setTab] = useState(TABS[0]);
  const [notes, setNotes] = useState('');

  const t = MOCK_TICKET;

  return (
    <div className="min-h-screen bg-slate-50 py-8 px-4">
      <div className="max-w-6xl mx-auto mb-4">
        <div className="bg-red-50 border border-red-200 text-red-800 rounded px-4 py-2 text-sm">
          <strong>Demo:</strong> This page is currently static and displays dummy data only.
        </div>
      </div>
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-6 gap-2">
          <div>
            <button onClick={() => navigate('/tickets')} className="text-sm text-purple-700 hover:underline mb-1">← Back to Tickets</button>
            <div className="text-2xl font-semibold text-slate-900">Ticket #{t.id}: Cooling Inefficiency</div>
            <div className="text-sm text-slate-500 mt-1">{t.ahu} • AI Detected</div>
          </div>
          <span className={`inline-flex items-center rounded-full border px-3 py-1 text-sm font-medium ${t.statusColor}`}>{t.status}</span>
        </div>
        {/* Main layout */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Left column */}
          <div className="space-y-6">
            {/* Fault Summary */}
            <div className="rounded-lg bg-white shadow-sm border border-slate-200 p-6">
              <div className="text-lg font-medium text-slate-900 mb-2">Fault Summary</div>
              <div className="text-slate-700 mb-2">Diagnosis: <span className="font-semibold text-slate-900">{t.diagnosis}</span></div>
              <ul className="list-disc pl-5 mb-2 text-slate-700">
                {t.signals.map((s) => (
                  <li key={s.label}><span className="font-medium text-slate-900">{s.label}:</span> {s.value}</li>
                ))}
              </ul>
              <div className="flex items-center gap-3 mb-2">
                <div className="w-40">
                  <div className="text-xs text-slate-500 mb-1">Confidence</div>
                  <div className="w-full h-2 bg-slate-100 rounded">
                    <div className="h-2 rounded bg-purple-600" style={{ width: `${t.confidence}%` }} />
                  </div>
                </div>
                <div className="text-xs text-slate-500">{t.confidence}%</div>
                <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${t.severityColor}`}>{t.severity}</span>
              </div>
              <div className="text-slate-700 mt-2">
                <span className="font-medium text-slate-900">Recommendation:</span> {t.recommendation}
              </div>
            </div>
            {/* Human Review */}
            <div className="rounded-lg bg-white shadow-sm border border-slate-200 p-6 flex flex-col min-h-[340px]">
              <div className="text-lg font-medium text-slate-900 mb-2">Human Review</div>
              <label className="text-xs text-slate-500 mb-1" htmlFor="notes">Technician Notes</label>
              <textarea
                id="notes"
                className="border border-slate-200 rounded p-2 text-sm mb-4 min-h-[80px] max-h-32 resize-none bg-slate-50"
                placeholder="Add your observations…"
                value={notes}
                onChange={e => setNotes(e.target.value)}
              />
              <div className="flex gap-3 mt-auto pt-2">
                <button className="flex-1 bg-green-600 hover:bg-green-700 text-white font-semibold py-2 rounded-lg text-lg shadow transition">Approve</button>
                <button className="flex-1 bg-rose-100 hover:bg-rose-200 text-rose-800 font-semibold py-2 rounded-lg text-lg border border-rose-200 shadow transition">Reject</button>
              </div>
            </div>
          </div>
          {/* Right column */}
          <div className="space-y-6">
            {/* Reasoning Summary */}
            <div className="rounded-lg bg-white shadow-sm border border-slate-200 p-6">
              <div className="text-lg font-medium text-slate-900 mb-2">Reasoning Summary</div>
              <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Primary Hypothesis</div>
              <div className="text-slate-900 font-semibold mb-2">{t.aiHypothesis}</div>
              <div className="flex items-center gap-2 mb-2">
                <div className="w-full h-2 bg-slate-100 rounded">
                  <div className="h-2 rounded bg-purple-600" style={{ width: `${t.confidence}%` }} />
                </div>
                <div className="text-xs text-slate-500">{t.confidence}%</div>
              </div>
              <div className="text-xs text-slate-500 mb-1">Alternatives (Top-2)</div>
              <ul className="list-disc pl-5 mb-2 text-slate-700">
                {t.alternatives.map((alt) => (
                  <li key={alt}>{alt}</li>
                ))}
              </ul>
              <button className="text-xs text-purple-700 hover:underline">Show full trace</button>
            </div>
            {/* Analysis Tabs */}
            <div className="rounded-lg bg-white shadow-sm border border-slate-200 p-6">
              <div className="flex gap-4 border-b border-slate-100 mb-4">
                {TABS.map((tabName) => (
                  <button
                    key={tabName}
                    className={`pb-2 text-sm font-medium border-b-2 transition ${tab === tabName ? 'border-purple-600 text-purple-700' : 'border-transparent text-slate-500 hover:text-slate-700'}`}
                    onClick={() => setTab(tabName)}
                  >
                    {tabName}
                  </button>
                ))}
              </div>
              {tab === 'Correlation Analysis' && (
                <div>
                  <div className="text-sm font-medium text-slate-900 mb-2">Valve Position vs SAT</div>
                  {/* Simple static chart mockup */}
                  <div className="bg-slate-50 rounded p-4 flex flex-col items-center">
                    <div className="w-full flex justify-between text-xs text-slate-500 mb-1">
                      <span>{t.chart.times[0]}</span>
                      <span>{t.chart.times[t.chart.times.length - 1]}</span>
                    </div>
                    <svg width="100%" height="120" viewBox="0 0 320 120" className="mb-2">
                      {/* Valve position line (purple) */}
                      <polyline
                        fill="none"
                        stroke="#9333ea"
                        strokeWidth="3"
                        points="40,80 80,60 120,60 160,60 200,60 240,60"
                      />
                      {/* SAT line (slate) */}
                      <polyline
                        fill="none"
                        stroke="#64748b"
                        strokeWidth="3"
                        points="40,90 80,95 120,97 160,99 200,100 240,102"
                      />
                      {/* Highlighted data point */}
                      <circle cx="240" cy="60" r="6" fill="#9333ea" stroke="#fff" strokeWidth="2" />
                    </svg>
                    <div className="flex justify-between w-full text-xs">
                      <span className="text-purple-700 font-medium">Valve Position (%)</span>
                      <span className="text-slate-500">SAT (°F)</span>
                    </div>
                  </div>
                </div>
              )}
              {tab === 'Similar Cases' && (
                <div className="text-slate-500 text-sm">No similar cases found.</div>
              )}
              {tab === 'System Manuals' && (
                <div className="text-slate-500 text-sm">Manuals and reference material coming soon.</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
