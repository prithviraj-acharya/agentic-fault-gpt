import { ReactNode } from 'react'

export function StatCard({
  title,
  value,
  footer,
}: {
  title: string
  value: ReactNode
  footer?: ReactNode
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="text-sm text-slate-600">{title}</div>
      <div className="mt-2 text-2xl font-semibold text-slate-900">{value}</div>
      {footer ? <div className="mt-3">{footer}</div> : null}
    </div>
  )
}
