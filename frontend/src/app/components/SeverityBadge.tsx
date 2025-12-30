export function SeverityBadge({ severity }: { severity: number | null | undefined }) {
  const sev = typeof severity === 'number' && !Number.isNaN(severity) ? severity : null

  const { label, classes } = (() => {
    if (sev === null) return { label: 'Unknown', classes: 'bg-slate-100 text-slate-700 border-slate-200' }
    if (sev <= 0) return { label: 'Normal', classes: 'bg-emerald-50 text-emerald-800 border-emerald-200' }
    if (sev <= 2) return { label: `Severity ${sev}`, classes: 'bg-amber-50 text-amber-900 border-amber-200' }
    return { label: `Severity ${sev}`, classes: 'bg-rose-50 text-rose-900 border-rose-200' }
  })()

  return <span className={["inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium", classes].join(' ')}>{label}</span>
}
