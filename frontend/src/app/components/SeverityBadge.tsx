export function SeverityBadge({ severity }: { severity: number | null | undefined }) {
  const sev = typeof severity === 'number' && !Number.isNaN(severity) ? severity : null
  if (sev === null) return null
  let label = ''
  let classes = ''
  if (sev <= 0) {
    label = 'Normal'
    classes = 'bg-emerald-50 text-emerald-800 border-emerald-200'
  } else if (sev === 1) {
    label = 'Severity 1'
    classes = 'bg-amber-50 text-amber-900 border-amber-200'
  } else {
    label = `Severity ${sev}`
    classes = 'bg-rose-50 text-rose-900 border-rose-200'
  }
  return <span className={["inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium", classes].join(' ')}>{label}</span>
}
