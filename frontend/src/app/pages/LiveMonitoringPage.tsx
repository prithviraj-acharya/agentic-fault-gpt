import { getLiveLast, getWindowsLatest } from '../api/endpoints'
import type { LiveLastResponse, WindowsLatestResponse } from '../api/types'
import { Card } from '../components/Card'
import { ErrorBanner } from '../components/ErrorBanner'
import { LiveChart } from '../components/LiveChart'
import { CompactLineChart } from '../components/CompactLineChart'
import { ProgressBar } from '../components/ProgressBar'
import { SeverityBadge } from '../components/SeverityBadge'
import { StatCard } from '../components/StatCard'
import { usePollingQuery } from '../hooks/usePollingQuery'
import { formatNumber, formatTimeAgo } from '../utils/format'

function OnlineBadge({ online }: { online: boolean | null }) {
  if (online === null) {
    return (
      <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-medium text-slate-700">
        Unknown
      </span>
    )
  }
  if (online) {
    return (
      <span className="inline-flex items-center rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-800">
        Online
      </span>
    )
  }
  return (
    <span className="inline-flex items-center rounded-full border border-rose-200 bg-rose-50 px-2 py-0.5 text-xs font-medium text-rose-900">
      Offline
    </span>
  )
}

function waitingValue(value: number | null | undefined, suffix?: string) {
  if (typeof value !== 'number' || Number.isNaN(value)) return <span className="text-slate-600">Waiting for data…</span>
  return `${formatNumber(value)}${suffix ?? ''}`
}


 

export function LiveMonitoringPage() {
  const telemetryQuery = usePollingQuery<LiveLastResponse>('live-last', (signal) => getLiveLast(signal), 2500)
  const windowsQuery = usePollingQuery<WindowsLatestResponse>('windows-latest-1', (signal) => getWindowsLatest(signal, 1), 5000)

  const points = telemetryQuery.data?.points ?? null
  const latestPoint = (points && points.length ? points[points.length - 1] : null) as any

  const combinedError = telemetryQuery.error || windowsQuery.error
  const lastUpdatedAt = Math.max(telemetryQuery.lastUpdatedAt ?? 0, windowsQuery.lastUpdatedAt ?? 0) || null

  const systemOnline: boolean | null =
    typeof telemetryQuery.data?.system_online === 'boolean' ? telemetryQuery.data.system_online : telemetryQuery.data ? true : null

  const latestWindow = ((windowsQuery.data?.windows ?? windowsQuery.data?.data ?? []) as any[])[0] ?? null

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-2xl font-semibold">Live Monitoring</div>
          <div className="mt-1 text-sm text-slate-600">Last updated: {formatTimeAgo(lastUpdatedAt)}</div>
        </div>
        <div className="flex items-center gap-2">
          <OnlineBadge online={systemOnline} />
        </div>
      </div>

      <ErrorBanner message={combinedError} />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title="SAT"
          value={waitingValue(latestPoint?.sat, ' °C')}
          footer={<CompactLineChart points={(points ?? []) as any} dataKey="sat" unit="°C" colorClass="text-sky-600" />}
        />
        <StatCard
          title="RAT"
          value={waitingValue(latestPoint?.rat, ' °C')}
          footer={<CompactLineChart points={(points ?? []) as any} dataKey="rat" unit="°C" colorClass="text-amber-600" />}
        />
        <StatCard
          title="Valve Position"
          value={waitingValue(latestPoint?.valve_pos, '%')}
          footer={<ProgressBar value={typeof latestPoint?.valve_pos === 'number' ? latestPoint.valve_pos : null} />}
        />
        <StatCard title="Fan Speed" value={waitingValue(latestPoint?.fan_speed)} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card title="SAT & RAT (last 30 mins)">
            <LiveChart points={points} />
          </Card>
        </div>

        <div>
          <Card title="Diagnostic Snapshot" right={<SeverityBadge severity={(latestWindow as any)?.severity ?? null} />}>
            <div className="space-y-3">
              <div>
                <div className="text-xs uppercase tracking-wide text-slate-500">Diagnosis</div>
                <div className="mt-1 text-sm font-medium text-slate-900">
                  {(latestWindow as any)?.diagnosis ? String((latestWindow as any).diagnosis) : (
                    <span className="text-slate-600">Waiting for data…</span>
                  )}
                </div>
              </div>

              <div>
                <div className="text-xs uppercase tracking-wide text-slate-500">Confidence</div>
                <div className="mt-1 text-sm font-medium text-slate-900">
                  <span className="text-slate-600">Waiting for data…</span>
                </div>
              </div>

              <div>
                <div className="text-xs uppercase tracking-wide text-slate-500">Active Window ID</div>
                <div className="mt-1 text-sm font-medium text-slate-900 break-all">
                  {(latestWindow as any)?.window_id ? String((latestWindow as any).window_id) : (
                    <span className="text-slate-600">Waiting for data…</span>
                  )}
                </div>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
