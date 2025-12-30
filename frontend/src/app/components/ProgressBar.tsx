export function ProgressBar({ value }: { value: number | null | undefined }) {
  const v = typeof value === 'number' && !Number.isNaN(value) ? Math.max(0, Math.min(100, value)) : null

  return (
    <div className="w-full">
      <div className="h-2 w-full rounded bg-slate-100">
        <div
          className="h-2 rounded bg-slate-900"
          style={{ width: v === null ? '0%' : `${v}%` }}
        />
      </div>
      <div className="mt-1 text-xs text-slate-600">{v === null ? 'Waiting for data…' : `${Math.round(v)}%`}</div>
    </div>
  )
}
