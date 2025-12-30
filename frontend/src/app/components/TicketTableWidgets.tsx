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
  // Use exact hex codes for background/text
  let style = {};
  if (status === 'Pending') {
    style = { backgroundColor: '#fffbeb', color: '#b45309' };
  } else if (status === 'Approved') {
    style = { backgroundColor: '#f0fdf4', color: '#15803d' };
  } else if (status === 'Rejected') {
    style = { backgroundColor: '#fef2f2', color: '#b91c1c' };
  }
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium"
      style={style}
    >
      {status}
    </span>
  );
}
