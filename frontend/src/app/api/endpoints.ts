import { apiGetJson } from './client'
import type {
  LiveLastResponse,
  LiveTimeseriesResponse,
  WindowDetail,
  WindowsLatestResponse,
} from './types'

export function getLiveLast(signal: AbortSignal) {
  return apiGetJson<LiveLastResponse>('/api/live/last?limit=30&signals=sat,rat,oat,valve_pos,fan_speed', { signal })
}

export function getLiveTimeseries(signal: AbortSignal) {
  return apiGetJson<LiveTimeseriesResponse>(
    '/api/live/timeseries?mins=30&signals=sat,rat,valve_pos,fan_speed',
    { signal },
  )
}

export function getWindowsLatest(signal: AbortSignal, limit?: number) {
  const qs = typeof limit === 'number' && Number.isFinite(limit)
    ? `?limit=${encodeURIComponent(String(limit))}`
    : ''
  return apiGetJson<WindowsLatestResponse>(`/api/windows/latest${qs}`, { signal })
}

export function getWindowDetail(windowId: string, signal: AbortSignal) {
  return apiGetJson<WindowDetail>(`/api/windows/${encodeURIComponent(windowId)}`, { signal })
}
