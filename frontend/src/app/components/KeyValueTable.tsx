import { asRecord } from '../utils/safe'

export function KeyValueTable({ data }: { data: unknown }) {
  const record = asRecord(data)
  const entries = Object.entries(record)

  if (!entries.length) {
    return <div className="text-sm text-slate-600">Waiting for data…</div>
  }

  return (
    <div className="space-y-2">
      {entries.map(([k, v]) => (
        <div key={k} className="flex items-start justify-between gap-3">
          <div className="text-sm text-slate-600">{k}</div>
          <div className="text-sm font-medium text-slate-900 text-right break-all">{String(v)}</div>
        </div>
      ))}
    </div>
  )
}
