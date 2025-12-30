import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

type Point = {
  tsLabel: string
  sat: number | null
  rat: number | null
}

function toLabel(ts: unknown): string {
  if (typeof ts === 'string') {
    const d = new Date(ts)
    return Number.isNaN(d.getTime()) ? ts : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }
  if (typeof ts === 'number') {
    const d = new Date(ts)
    return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }
  return ''
}

export function LiveChart({ points }: { points: Array<{ ts?: unknown; sat?: unknown; rat?: unknown }> | null }) {
  const data: Point[] = (points ?? []).map((p) => ({
    tsLabel: toLabel(p.ts),
    sat: typeof p.sat === 'number' && !Number.isNaN(p.sat) ? p.sat : null,
    rat: typeof p.rat === 'number' && !Number.isNaN(p.rat) ? p.rat : null,
  }))

  if (!data.length) {
    return (
      <div className="h-80 flex items-center justify-center text-slate-600">Waiting for data…</div>
    )
  }

  const hasAnySeriesValue = data.some((p) => p.sat !== null || p.rat !== null)
  if (!hasAnySeriesValue) {
    return (
      <div className="h-80 flex items-center justify-center text-slate-600">Waiting for SAT/RAT…</div>
    )
  }

  return (
    <div className="h-80">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 10, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="tsLabel" tick={{ fontSize: 12 }} minTickGap={20} />
          <YAxis tick={{ fontSize: 12 }} />
          <Tooltip />
          <Legend />
          <Line type="monotone" dataKey="sat" name="SAT" dot={false} isAnimationActive={false} />
          <Line type="monotone" dataKey="rat" name="RAT" dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
