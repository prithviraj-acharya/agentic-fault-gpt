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
import { Link } from 'react-router-dom'

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

type ParsedSnapshot = {
  fault: string | null
  summaryLines: string[]
  activeWindowLabel: string | null
}

function formatTimeRange(startValue: unknown, endValue: unknown): string | null {
  const start =
    startValue instanceof Date
      ? startValue
      : typeof startValue === 'number'
        ? new Date(startValue > 1e12 ? startValue : startValue * 1000)
        : typeof startValue === 'string'
          ? new Date(startValue)
          : null
  const end =
    endValue instanceof Date
      ? endValue
      : typeof endValue === 'number'
        ? new Date(endValue > 1e12 ? endValue : endValue * 1000)
        : typeof endValue === 'string'
          ? new Date(endValue)
          : null

  if (!start || !end) return null
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return null

  const startLabel = start.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  const endLabel = end.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  const mins = Math.max(0, Math.round((end.getTime() - start.getTime()) / 60000))
  const durationLabel = mins === 1 ? '1 minute' : `${mins} minutes`
  return `${startLabel} – ${endLabel} (${durationLabel})`
}

function parseDiagnosticSnapshot(raw: unknown, fallbackStartTs: unknown, fallbackEndTs: unknown): ParsedSnapshot {
  const text = typeof raw === 'string' ? raw : raw === null || raw === undefined ? '' : String(raw)

  const windowRangeMatch =
    /window\s+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))\s*[–—-]\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))\s*:?/i.exec(text)
  const parsedStart = windowRangeMatch?.[1] ?? null
  const parsedEnd = windowRangeMatch?.[2] ?? null

  const saTempMean = /sa_temp_mean=([-+]?\d*\.?\d+)/i.exec(text)?.[1]
  const saTempMinusSp = /sa_temp_mean_minus_sp=([-+]?\d*\.?\d+)/i.exec(text)?.[1]
  const ccValveMean = /cc_valve_mean=([-+]?\d*\.?\d+)/i.exec(text)?.[1]
  const avgZoneTempMean = /avg_zone_temp_mean=([-+]?\d*\.?\d+)/i.exec(text)?.[1]
  const anomaliesRaw = /anomalies=([^\.\n]+)/i.exec(text)?.[1]

  const anomalies = anomaliesRaw
    ? anomaliesRaw.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean)
    : []

  const fault = anomalies.length ? anomalies.join(', ') : null

  const summaryLines: string[] = []
  if (ccValveMean) summaryLines.push(`Cooling valve: ${formatNumber(Number(ccValveMean), 0)}% open`)
  if (saTempMean && saTempMinusSp) {
    const delta = Number(saTempMinusSp)
    const deltaLabel = `${Math.abs(delta).toFixed(2)}°C ${delta >= 0 ? 'above' : 'below'} setpoint`
    summaryLines.push(`Supply air temperature: ${formatNumber(Number(saTempMean), 2)}°C (${deltaLabel})`)
  } else if (saTempMean) {
    summaryLines.push(`Supply air temperature: ${formatNumber(Number(saTempMean), 2)}°C`)
  }
  if (avgZoneTempMean) summaryLines.push(`Average zone temperature: ${formatNumber(Number(avgZoneTempMean), 2)}°C`)

  const activeWindowLabel =
    parsedStart && parsedEnd
      ? formatTimeRange(parsedStart, parsedEnd)
      : formatTimeRange(fallbackStartTs, fallbackEndTs)

  return { fault, summaryLines, activeWindowLabel }
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
          <div className="text-2xl font-semibold">Live Monitoring Dashboard</div>
          <div className="mt-1 text-sm text-slate-600">Last updated: {formatTimeAgo(lastUpdatedAt)}</div>
        </div>
        <div className="flex items-center gap-2">
          <OnlineBadge online={systemOnline} />
        </div>
      </div>

      <ErrorBanner message={combinedError} />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title="Supply Air Temp (SAT)"
          value={waitingValue(latestPoint?.sat, ' °C')}
          footer={<CompactLineChart points={(points ?? []) as any} dataKey="sat" unit="°C" colorClass="text-purple-600" />}
        />
        <StatCard
          title="Return Air Temp (RAT)"
          value={waitingValue(latestPoint?.rat, ' °C')}
          footer={<CompactLineChart points={(points ?? []) as any} dataKey="rat" unit="°C" colorClass="text-purple-600" />}
        />
        <StatCard
          title="Valve Position"
          value={waitingValue(latestPoint?.valve_pos, '%')}
          footer={<ProgressBar value={typeof latestPoint?.valve_pos === 'number' ? latestPoint.valve_pos : null} />}
        />
        <StatCard
          title="Fan Speed"
          value={typeof latestPoint?.fan_speed === 'number' ? `${formatNumber(latestPoint.fan_speed)} / 100` : waitingValue(latestPoint?.fan_speed)}
          footer={<ProgressBar value={typeof latestPoint?.fan_speed === 'number' ? latestPoint.fan_speed : null} />}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card title="System Anomaly Analysis (last 30 mins)">
            <LiveChart points={points} />
          </Card>
        </div>

        <div>
          <Card
            title={
              <div>
                <div>Diagnostic Snapshot</div>
                <div className="text-xs text-slate-500 mt-0.5">Current Diagnosis</div>
              </div>
            }
            right={<SeverityBadge severity={(latestWindow as any)?.severity ?? null} />}
          >
            {(() => {
              const windowId = (latestWindow as any)?.window_id ? String((latestWindow as any).window_id) : null
              const { fault, summaryLines, activeWindowLabel } = parseDiagnosticSnapshot(
                (latestWindow as any)?.diagnosis,
                (latestWindow as any)?.start_ts,
                (latestWindow as any)?.end_ts,
              )

              return (
                <div className="space-y-4">
                  <div>
                    <div className="text-xs uppercase tracking-wide text-slate-500">Fault</div>
                    <div className="mt-1 text-sm font-medium text-slate-900">
                      {fault ? fault : <span className="text-slate-600">Waiting for data…</span>}
                    </div>
                  </div>

                  <div>
                    <div className="text-xs uppercase tracking-wide text-slate-500">Summary</div>
                    {!summaryLines.length ? (
                      <div className="mt-1 text-sm text-slate-600">Waiting for data…</div>
                    ) : (
                      <ul className="mt-1 space-y-1 text-sm text-slate-700">
                        {summaryLines.map((line) => (
                          <li key={line}>{line}</li>
                        ))}
                      </ul>
                    )}
                  </div>

                  <div>
                    <div className="text-xs uppercase tracking-wide text-slate-500">Active Window</div>
                    <div className="mt-1 text-sm font-medium text-slate-900">
                      {activeWindowLabel ? activeWindowLabel : <span className="text-slate-600">Waiting for data…</span>}
                    </div>
                  </div>

                  {windowId ? (
                    <div>
                      <Link
                        to={`/windows?window_id=${encodeURIComponent(windowId)}`}
                        className="inline-flex items-center rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-purple-700 hover:bg-purple-50"
                      >
                        View Technical Evidence
                      </Link>
                    </div>
                  ) : null}
                </div>
              )
            })()}
          </Card>
        </div>
      </div>
    </div>
  )
}
