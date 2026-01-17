import { CheckCircleIcon, XCircleIcon, ArrowRightIcon } from '@heroicons/react/20/solid';

export function ConfidenceBar({ value }: { value: number }) {
  let color = 'bg-green-500';
  if (value < 70) color = 'bg-rose-500';
  else if (value < 85) color = 'bg-amber-400';
  return (
    <div className="flex items-center gap-2 min-w-[90px]">
      <div className="relative w-20 h-2 bg-slate-100 rounded">
        <div className={`absolute left-0 top-0 h-2 rounded ${color}`} style={{ width: `${value}%` }} />
      </div>
      <span className="text-xs font-medium text-slate-700 w-8 text-right">{value}%</span>
    </div>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const normalized = String(status ?? '').trim();
  const key = normalized.toUpperCase();

  const labelMap: Record<string, string> = {
    // Review (backend)
    NONE: 'Awaiting Review',
    APPROVED: 'Approved',
    REJECTED: 'Rejected',

    // Diagnosis (backend)
    DRAFT: 'Draft',
    DIAGNOSING: 'Diagnosing',
    DIAGNOSED: 'Diagnosed',
    FAILED: 'Failed',

    // Lifecycle (backend)
    OPEN: 'Open',
    RESOLVED: 'Resolved',

    // Legacy/extra (safe fallbacks)
    PENDING: 'Pending',
    UNDIAGNOSED: 'Undiagnosed',
    ACKNOWLEDGED: 'Acknowledged',
    ESCALATED: 'Escalated',
    CLOSED: 'Closed',
  };

  // Use exact hex codes for background/text
  const styleMap: Record<string, { backgroundColor: string; color: string }> = {
    // Review
    NONE: { backgroundColor: '#fffbeb', color: '#b45309' },
    APPROVED: { backgroundColor: '#f0fdf4', color: '#15803d' },
    REJECTED: { backgroundColor: '#fef2f2', color: '#b91c1c' },

    // Diagnosis
    DRAFT: { backgroundColor: '#f1f5f9', color: '#334155' },
    DIAGNOSING: { backgroundColor: '#eff6ff', color: '#1d4ed8' },
    DIAGNOSED: { backgroundColor: '#f0fdf4', color: '#15803d' },
    FAILED: { backgroundColor: '#fef2f2', color: '#b91c1c' },

    // Lifecycle
    OPEN: { backgroundColor: '#eff6ff', color: '#1d4ed8' },
    RESOLVED: { backgroundColor: '#f1f5f9', color: '#334155' },

    // Legacy/extra
    PENDING: { backgroundColor: '#fffbeb', color: '#b45309' },
    UNDIAGNOSED: { backgroundColor: '#f1f5f9', color: '#334155' },
    ACKNOWLEDGED: { backgroundColor: '#eef2ff', color: '#4338ca' },
    ESCALATED: { backgroundColor: '#fff7ed', color: '#c2410c' },
    CLOSED: { backgroundColor: '#f1f5f9', color: '#334155' },
  };

  const style = styleMap[key] ?? { backgroundColor: '#f1f5f9', color: '#334155' };
  const label = labelMap[key] ?? normalized;
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium"
      style={style}
    >
      {label}
    </span>
  );
}
