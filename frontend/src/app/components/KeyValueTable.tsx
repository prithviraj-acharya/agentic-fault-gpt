import { asRecord } from '../utils/safe'

export function KeyValueTable({ data }: { data: unknown }) {
  const record = asRecord(data)
  const entries = Object.entries(record)

  if (!entries.length) {
    return <div className="text-sm text-slate-600">Waiting for data…</div>
  }

  // Add contextual hint for extracted features, using value
  function getHint(label: string, value: string): string | null {
    // Try to extract numeric value (strip units)
    const num = parseFloat(value)
    if (label === 'Supply Air Temperature Mean Minus Setpoint') {
      if (!isNaN(num)) {
        if (num > 0) return '(above target)'
        if (num < 0) return '(below target)'
      }
    }
    if (label === 'Cooling Coil Valve Mean') {
      if (!isNaN(num) && num >= 90) return '(near saturation)'
    }
    if (label === 'Supply Air Temperature Mean') {
      // If value is more than 0.5 above or below setpoint, show up/down
      // (Assume setpoint is 15°C for hinting; adjust if you have the real value)
      const setpoint = 15
      if (!isNaN(num)) {
        if (num > setpoint + 0.5) return '(↑ vs setpoint)'
        if (num < setpoint - 0.5) return '(↓ vs setpoint)'
      }
    }
    return null
  }

  return (
    <div className="space-y-2">
      {entries.map(([k, v]) => {
        const valueStr = String(v)
        const hint = getHint(k, valueStr)
        return (
          <div key={k} className="flex items-start justify-between gap-3">
            <div className="text-sm text-slate-600">{k}</div>
            <div className="text-sm font-medium text-slate-900 text-right break-all">
              {valueStr}{' '}
              {hint && <span className="text-xs text-slate-500 font-normal ml-1">{hint}</span>}
            </div>
          </div>
        )
      })}
    </div>
  )
}
