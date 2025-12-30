import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip } from 'recharts'

function toLabel(ts: unknown): string {
  if (typeof ts === 'string') {
    const d = new Date(ts)
    return Number.isNaN(d.getTime()) ? ts : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }
  return ''
}

export function CompactLineChart({
  points,
  dataKey,
  unit,
  colorClass,
}: {
  points: Array<Record<string, unknown>>
  dataKey: string
  unit: string
  colorClass: string
}) {
  const data = (points ?? []).map((p, idx) => {
    const raw = (p as any)?.[dataKey]
    const value = typeof raw === 'number' && !Number.isNaN(raw) ? raw : null
    return {
      idx,
      tsLabel: toLabel((p as any)?.ts),
      value,
    }
  })

  const hasData = data.some((d) => d.value !== null)
  if (!hasData) return <div className="h-16" />

  return (
    <div className={["h-16", colorClass].join(' ')}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
          <XAxis dataKey="tsLabel" tick={{ fontSize: 10 }} minTickGap={24} />
          <YAxis tick={{ fontSize: 10 }} width={32} domain={['auto', 'auto']} />
          <Tooltip
            formatter={(v) => (typeof v === 'number' ? `${v.toFixed(2)} ${unit}` : String(v))}
            labelFormatter={(l) => `Time: ${String(l)}`}
          />
          <Line type="monotone" dataKey="value" stroke="currentColor" dot={false} isAnimationActive={false} strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
