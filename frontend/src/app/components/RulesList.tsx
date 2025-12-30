import { asArray, asRecord } from '../utils/safe'

function renderRuleLabel(rule: Record<string, unknown>): string {
  const name = rule['name']
  const id = rule['id']
  if (typeof name === 'string' && name.trim()) return name
  if (typeof id === 'string' && id.trim()) return id
  return 'Rule'
}

export function RulesList({ title, rules, collapsed }: { title: string; rules: unknown; collapsed?: boolean }) {
  const list = asArray<Record<string, unknown>>(rules)

  if (!list.length) {
    return <div className="text-sm text-slate-600">Waiting for data…</div>
  }

  if (collapsed) {
    return (
      <details className="rounded-lg border border-slate-200 bg-white">
        <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium text-slate-900">
          {title} ({list.length})
        </summary>
        <div className="px-4 pb-4 pt-1 space-y-2">
          {list.map((r, idx) => {
            const rr = asRecord(r)
            return (
              <div key={idx} className="rounded border border-slate-200 bg-slate-50 px-3 py-2">
                <div className="text-sm font-medium text-slate-900">{renderRuleLabel(rr)}</div>
                {rr['message'] ? <div className="text-xs text-slate-600 mt-1">{String(rr['message'])}</div> : null}
              </div>
            )
          })}
        </div>
      </details>
    )
  }

  return (
    <div className="space-y-2">
      <div className="text-sm font-medium text-slate-900">{title} ({list.length})</div>
      {list.map((r, idx) => {
        const rr = asRecord(r)
        return (
          <div key={idx} className="rounded border border-slate-200 bg-white px-3 py-2">
            <div className="text-sm font-medium text-slate-900">{renderRuleLabel(rr)}</div>
            {rr['message'] ? <div className="text-xs text-slate-600 mt-1">{String(rr['message'])}</div> : null}
          </div>
        )
      })}
    </div>
  )
}
