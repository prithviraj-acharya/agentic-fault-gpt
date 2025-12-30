export type LiveOverview = {
  system_online?: boolean | null
  last_updated?: string | null

  sat?: number | null
  rat?: number | null
  valve_pos?: number | null
  fan_speed?: number | null

  diagnosis?: string | null
  confidence?: number | null
  severity?: number | null
  active_window_id?: string | null
}

export type LiveTimeseriesPoint = {
  ts?: string | number | null
  sat?: number | null
  rat?: number | null
  oat?: number | null
  valve_pos?: number | null
  fan_speed?: number | null
}

export type LiveTimeseriesResponse = {
  points?: LiveTimeseriesPoint[] | null
  // allow alternate shapes
  data?: LiveTimeseriesPoint[] | null
}

export type LiveLastResponse = {
  system_online?: boolean | null
  last_updated?: string | null
  signals?: string[] | null
  points?: LiveTimeseriesPoint[] | null
}

export type WindowListItem = {
  window_id?: string | null
  start_ts?: string | null
  end_ts?: string | null
  severity?: number | null
  diagnosis?: string | null
}

export type WindowsLatestResponse = {
  windows?: WindowListItem[] | null
  data?: WindowListItem[] | null
}

export type WindowDetail = {
  window_id?: string | null
  start_ts?: string | null
  end_ts?: string | null
  severity?: number | null
  diagnosis?: string | null
  confidence?: number | null

  summary?: Record<string, unknown> | null
  features?: Record<string, unknown> | null

  rules?: {
    failed?: Array<Record<string, unknown>> | null
    passed?: Array<Record<string, unknown>> | null
  } | null
}
