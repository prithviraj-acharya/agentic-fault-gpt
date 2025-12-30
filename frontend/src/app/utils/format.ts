export function formatNumber(value: unknown, decimals = 1): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—'
  return value.toFixed(decimals)
}

export function formatPercent(value: unknown, decimals = 0): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—'
  return `${value.toFixed(decimals)}%`
}

export function formatTimeAgo(tsMs: number | null): string {
  if (!tsMs) return '—'
  const deltaSec = Math.max(0, Math.floor((Date.now() - tsMs) / 1000))
  if (deltaSec < 5) return 'just now'
  if (deltaSec < 60) return `${deltaSec}s ago`
  const mins = Math.floor(deltaSec / 60)
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  return `${hours}h ago`
}

export function safeString(value: unknown): string {
  if (typeof value === 'string') return value
  if (value === null || value === undefined) return ''
  try {
    return String(value)
  } catch {
    return ''
  }
}
