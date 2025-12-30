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

export function getWindowsLatest(signal: AbortSignal, limit = 50) {
  return apiGetJson<WindowsLatestResponse>(`/api/windows/latest?limit=${encodeURIComponent(String(limit))}`, { signal })
}

export function getWindowDetail(windowId: string, signal: AbortSignal) {
  return apiGetJson<WindowDetail>(`/api/windows/${encodeURIComponent(windowId)}`, { signal })
}
