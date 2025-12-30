import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getWindowsLatest } from '../api/endpoints'
import type { WindowsLatestResponse } from '../api/types'
import { Card } from '../components/Card'
import { ErrorBanner } from '../components/ErrorBanner'
import { KeyValueTable } from '../components/KeyValueTable'
import { SeverityBadge } from '../components/SeverityBadge'
import { usePollingQuery } from '../hooks/usePollingQuery'
import { asArray, asNumber, asString } from '../utils/safe'

type TimelineItem = {
  windowId: string
  startTs: string | null
  endTs: string | null
  severity: number | null
  diagnosis: string | null
}

function severityTimelineClasses(severity: number | null) {
  if (severity === null) return 'border-slate-200 bg-white hover:bg-slate-50'
  if (severity <= 0) return 'border-emerald-200 bg-emerald-50 hover:bg-emerald-100'
  if (severity === 1) return 'border-amber-200 bg-amber-50 hover:bg-amber-100'
  return 'border-rose-200 bg-rose-50 hover:bg-rose-100'
}

function formatTsShort(ts: string | null) {
  if (!ts) return ''
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  return d.toLocaleString([], { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function formatTsTime(ts: string | null) {
  if (!ts) return ''
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function parseDiagnosisFeatures(diagnosis: string | null): Record<string, unknown> {
  if (!diagnosis) return {}

  const keyMeta: Record<string, { label: string; unit: string }> = {
    sa_temp_mean: { label: 'Supply Air Temperature Mean', unit: '°C' },
    sa_temp_mean_minus_sp: { label: 'Supply Air Temperature Mean Minus Setpoint', unit: '°C' },
    cc_valve_mean: { label: 'Cooling Coil Valve Mean', unit: '%' },
    avg_zone_temp_mean: { label: 'Average Zone Temperature Mean', unit: '°C' },
  }

  const allowedKeys = Object.keys(keyMeta)
  const re = new RegExp(`\\b(${allowedKeys.join('|')})=(-?[0-9]+(?:\\.[0-9]+)?)`, 'g')

  const out: Record<string, unknown> = {}
  let match: RegExpExecArray | null
  while ((match = re.exec(diagnosis)) !== null) {
    const rawKey = match[1]
    const rawVal = match[2]
    const meta = keyMeta[rawKey]
    const label = meta?.label ?? rawKey
    const n = Number(rawVal)
    const formatted = Number.isFinite(n) ? n.toFixed(2) : rawVal
    out[label] = meta?.unit ? `${formatted} ${meta.unit}` : formatted
  }
  return out
}

function formatDuration(startTs: string | null, endTs: string | null) {
  if (!startTs || !endTs) return '—'
  const start = new Date(startTs)
  const end = new Date(endTs)
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return '—'
  const minutes = Math.round((end.getTime() - start.getTime()) / 60000)
  if (!Number.isFinite(minutes) || minutes <= 0) return '—'
  if (minutes < 60) return `${minutes} minutes`
  const hours = Math.round((minutes / 60) * 10) / 10
  return `${hours} hours`
}

function extractField(text: string | null, key: string) {
  if (!text) return null
  const idx = text.indexOf(key)
  if (idx < 0) return null
  const rest = text.slice(idx + key.length)
  const endIdx = Math.min(
    ...[rest.indexOf(' signature='), rest.indexOf(' anomalies='), rest.indexOf('.'), rest.indexOf('\n')].filter((n) => n >= 0),
    rest.length,
  )
  const value = rest.slice(0, endIdx).trim()
  return value || null
}

function anomalyToFriendlyCondition(ruleId: string): string {
  switch (ruleId) {
    case 'SAT_NOT_DROPPING_WHEN_VALVE_HIGH':
      return 'Supply air temperature is not dropping despite high cooling demand.'
    case 'SAT_TOO_HIGH_WHEN_VALVE_HIGH':
      return 'Supply air temperature is above the setpoint while cooling demand is high.'
    case 'OA_DAMPER_STUCK_OR_FLATLINE':
      return 'Outdoor air damper shows near-zero variance (possible stuck or flatline).'
    case 'RA_DAMPER_STUCK_OR_FLATLINE':
      return 'Return air damper shows near-zero variance (possible stuck or flatline).'
    case 'ZONE_TEMP_PERSISTENT_TREND':
      return 'Average zone temperature shows a sustained upward trend.'
    case 'ZONE_TEMP_SENSOR_NOISY':
      return 'Average zone temperature variance is unusually high (possible sensor noise).'
    case 'MISSING_DATA_HIGH':
      return 'High missing data ratio in this window.'
    case 'OUT_OF_RANGE_VALUES':
      return 'Signals are outside configured bounds.'
    default:
      return ruleId
        .split('_')
        .map((w) => (w ? w[0]!.toUpperCase() + w.slice(1).toLowerCase() : ''))
        .join(' ')
        .trim()
  }
}

export function WindowAnalysisPage() {
  const [searchParams] = useSearchParams()
  const requestedWindowId = searchParams.get('window_id')
  const windowsQuery = usePollingQuery<WindowsLatestResponse>('windows-latest', (signal) => getWindowsLatest(signal), 5000)

  const timelineItems: TimelineItem[] = useMemo(() => {
    const raw = windowsQuery.data?.windows ?? windowsQuery.data?.data ?? []
    const items = asArray<Record<string, unknown>>(raw)
      .map((w) => {
        const windowId = asString(w['window_id'])
        if (!windowId) return null
        return {
          windowId,
          startTs: asString(w['start_ts']),
          endTs: asString(w['end_ts']),
          severity: asNumber(w['severity']),
          diagnosis: asString(w['diagnosis']),
        } satisfies TimelineItem
      })
      .filter(Boolean) as TimelineItem[]

    return items
  }, [windowsQuery.data])

  const [selectedWindowId, setSelectedWindowId] = useState<string | null>(null)

  useEffect(() => {
    if (!timelineItems.length) {
      if (selectedWindowId) setSelectedWindowId(null)
      return
    }

    if (requestedWindowId) {
      const exists = timelineItems.some((w) => w.windowId === requestedWindowId)
      if (exists && selectedWindowId !== requestedWindowId) {
        setSelectedWindowId(requestedWindowId)
        return
      }
    }

    if (!selectedWindowId) {
      setSelectedWindowId(timelineItems[0]!.windowId)
      return
    }
    const stillExists = timelineItems.some((w) => w.windowId === selectedWindowId)
    if (!stillExists) setSelectedWindowId(timelineItems[0]!.windowId)
  }, [requestedWindowId, selectedWindowId, timelineItems])

  const combinedError = windowsQuery.loading ? null : windowsQuery.error

  const selectedWindow = useMemo(() => {
    if (!selectedWindowId) return null
    return timelineItems.find((w) => w.windowId === selectedWindowId) ?? null
  }, [selectedWindowId, timelineItems])

  const summaryTableData = useMemo(() => {
    if (!selectedWindowId) return null

    const diagnosis = selectedWindow?.diagnosis ?? null
    const anomaliesRaw = extractField(diagnosis, 'anomalies=')
    const anomalies = anomaliesRaw ? anomaliesRaw.split(',').map((s) => s.trim()).filter(Boolean) : []

    const detectedCondition = anomalies.length ? anomalies.map(anomalyToFriendlyCondition).join(' | ') : '—'

    return {
      'Window ID': selectedWindowId,
      Duration: formatDuration(selectedWindow?.startTs ?? null, selectedWindow?.endTs ?? null),
      'Detected Condition': detectedCondition,
    }
  }, [selectedWindow, selectedWindowId])

  const extractedFeaturesData = useMemo(() => {
    const diagnosis = selectedWindow?.diagnosis ?? null
    const parsed = parseDiagnosisFeatures(diagnosis)
    if (Object.keys(parsed).length) return parsed

    return null
  }, [selectedWindow])

  const detailSeverity = selectedWindow?.severity ?? null

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-2xl font-semibold">Window Analysis</div>
          <div className="mt-1 text-sm text-slate-600">Select a window to inspect summary, features, and rules.</div>
        </div>
        <div>{selectedWindowId && detailSeverity !== null ? <SeverityBadge severity={detailSeverity} /> : null}</div>
      </div>

      <ErrorBanner message={combinedError} />

      <Card title="Window Timeline">
        {!timelineItems.length ? (
          <div className="text-sm text-slate-600">Waiting for data…</div>
        ) : (
          <div className="flex gap-3 overflow-x-auto pb-2">
            {timelineItems.map((w, idx) => {
              const active = w.windowId === selectedWindowId
              const displayWindowNumber = timelineItems.length - idx
              return (
                <button
                  key={w.windowId}
                  type="button"
                  onClick={() => setSelectedWindowId(w.windowId)}
                  className={[
                    'shrink-0 w-64 rounded-lg border p-3 text-left focus:outline-none',
                    severityTimelineClasses(w.severity),
                    active ? 'border-slate-900' : '',
                  ].join(' ')}
                >
                  <div className="flex items-center gap-2">
                    <div className="text-sm font-semibold text-slate-900 truncate flex-1">Window {displayWindowNumber}</div>
                    <span className="flex-none"><SeverityBadge severity={w.severity} /></span>
                  </div>
                  <div className="mt-1 text-xs text-slate-700">
                    {formatTsTime(w.startTs)}{w.endTs ? ` → ${formatTsTime(w.endTs)}` : ''}
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="space-y-4">
          <Card title="Window Summary">
            {selectedWindowId ? <KeyValueTable data={summaryTableData} /> : <div className="text-sm text-slate-600">Waiting for data…</div>}
          </Card>

          <Card title="Extracted Features">
            {!selectedWindowId ? (
              <div className="text-sm text-slate-600">Waiting for data…</div>
            ) : extractedFeaturesData ? (
              <KeyValueTable data={extractedFeaturesData} />
            ) : (
              <div className="text-sm text-slate-600">Work in progress</div>
            )}
          </Card>
        </div>

        <div>
          <Card title="Agent Conclusion (Phase 4+)">
            <div className="text-sm text-slate-600">This section will populate once agentic reasoning is enabled.</div>
          </Card>
        </div>
      </div>
    </div>
  )
}
