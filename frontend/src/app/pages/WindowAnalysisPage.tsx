import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getWindowDetail, getWindowsLatest } from '../api/endpoints'
import type { WindowDetail, WindowsLatestResponse } from '../api/types'
import { Card } from '../components/Card'
import { ErrorBanner } from '../components/ErrorBanner'
import { KeyValueTable } from '../components/KeyValueTable'
import { RulesList } from '../components/RulesList'
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
  if (severity <= 2) return 'border-amber-200 bg-amber-50 hover:bg-amber-100'
  return 'border-rose-200 bg-rose-50 hover:bg-rose-100'
}

function formatTsShort(ts: string | null) {
  if (!ts) return ''
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  return d.toLocaleString([], { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' })
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
  const [detailError, setDetailError] = useState<string | null>(null)
  const [detailLoading, setDetailLoading] = useState<boolean>(false)
  const [detailById, setDetailById] = useState<Record<string, WindowDetail | null>>({})

  const detailAbortRef = useRef<AbortController | null>(null)

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

  const selectedDetail = selectedWindowId ? detailById[selectedWindowId] ?? null : null

  useEffect(() => {
    if (!selectedWindowId) return
    if (Object.prototype.hasOwnProperty.call(detailById, selectedWindowId)) return

    setDetailLoading(true)
    setDetailError(null)
    detailAbortRef.current?.abort()
    const controller = new AbortController()
    detailAbortRef.current = controller

    void (async () => {
      try {
        const detail = await getWindowDetail(selectedWindowId, controller.signal)
        if (!controller.signal.aborted) {
          setDetailById((prev) => ({ ...prev, [selectedWindowId]: detail }))
        }
      } catch (err) {
        if (controller.signal.aborted) return
        const message = err instanceof Error ? err.message : 'Fetch failed'
        setDetailError(message)
        setDetailById((prev) => ({ ...prev, [selectedWindowId]: null }))
      } finally {
        if (!controller.signal.aborted) setDetailLoading(false)
      }
    })()

    return () => controller.abort()
  }, [detailById, selectedWindowId])

  const combinedError = windowsQuery.error || detailError

  const detailSeverity =
    typeof selectedDetail?.severity === 'number' && !Number.isNaN(selectedDetail.severity)
      ? selectedDetail.severity
      : null

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-2xl font-semibold">Window Analysis</div>
          <div className="mt-1 text-sm text-slate-600">Select a window to inspect summary, features, and rules.</div>
        </div>
        <div>{selectedWindowId ? <SeverityBadge severity={detailSeverity} /> : null}</div>
      </div>

      <ErrorBanner message={combinedError} />

      <Card title="Window Timeline">
        {!timelineItems.length ? (
          <div className="text-sm text-slate-600">Waiting for data…</div>
        ) : (
          <div className="flex gap-3 overflow-x-auto pb-2">
            {timelineItems.map((w) => {
              const active = w.windowId === selectedWindowId
              return (
                <button
                  key={w.windowId}
                  type="button"
                  onClick={() => setSelectedWindowId(w.windowId)}
                  className={[
                    'shrink-0 w-64 rounded-lg border p-3 text-left',
                    severityTimelineClasses(w.severity),
                    active ? 'ring-2 ring-slate-900/20' : '',
                  ].join(' ')}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-sm font-semibold text-slate-900 truncate">{w.windowId}</div>
                    <SeverityBadge severity={w.severity} />
                  </div>
                  <div className="mt-1 text-xs text-slate-700">
                    {formatTsShort(w.startTs)}{w.endTs ? ` → ${formatTsShort(w.endTs)}` : ''}
                  </div>
                  <div className="mt-2 text-xs text-slate-700">
                    {w.diagnosis ? w.diagnosis : 'Waiting for data…'}
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="space-y-4">
          <Card title="Window Summary" right={detailLoading ? <span className="text-xs text-slate-600">Loading…</span> : null}>
            {selectedWindowId ? (
              <KeyValueTable data={selectedDetail?.summary ?? null} />
            ) : (
              <div className="text-sm text-slate-600">Waiting for data…</div>
            )}
          </Card>

          <Card title="Extracted Features">
            {selectedWindowId ? (
              <KeyValueTable data={selectedDetail?.features ?? null} />
            ) : (
              <div className="text-sm text-slate-600">Waiting for data…</div>
            )}
          </Card>
        </div>

        <div>
          <Card title="Rule Evaluation">
            {!selectedWindowId ? (
              <div className="text-sm text-slate-600">Waiting for data…</div>
            ) : (
              <div className="space-y-4">
                <RulesList title="Failed Rules" rules={selectedDetail?.rules?.failed ?? (selectedDetail as any)?.failed_rules} />
                <RulesList title="Passed Rules" rules={selectedDetail?.rules?.passed ?? (selectedDetail as any)?.passed_rules} collapsed />
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}
