import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useLocation, useSearchParams } from 'react-router-dom';
import { ConfidenceBar, StatusBadge } from '../components/TicketTableWidgets';
import { ArrowRightIcon } from '@heroicons/react/20/solid';

type TicketApi = {
  ticket_id: string;
  ticket_ref: string;
  ahu_id: string;
  detected_fault_type: string;
  lifecycle_status: 'OPEN' | 'RESOLVED' | string;
  diagnosis_status: 'DRAFT' | 'DIAGNOSING' | 'DIAGNOSED' | 'FAILED' | string;
  review_status: 'NONE' | 'APPROVED' | 'REJECTED' | string;
  confidence?: number | null;
  created_at: string;
  updated_at: string;
};

type TicketListResponse = {
  items: TicketApi[];
  limit: number;
  offset: number;
  total: number;
};

type TicketMetricsResponse = {
  active_count: number;
  awaiting_review_count: number;
  approved_count: number;
  rejected_count: number;
  high_confidence_count: number;
};

function formatDateTime(value: string): string {
  if (!value) return '';
  // Handle ISO strings with microseconds (Python) by trimming beyond milliseconds.
  let normalized = value.includes('.') ? value.replace(/\.(\d{3})\d+/, '.$1') : value;
  // If no timezone, treat as UTC (backend emits UTC with no offset)
  if (!/Z|[+-]\d{2}:?\d{2}$/.test(normalized)) {
    normalized += 'Z';
  }
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
}

const STATUS_OPTIONS = ['All Review', 'Awaiting Review', 'Approved', 'Rejected'] as const;
const FAULT_TYPE_OPTIONS = ['All Fault Types', 'Cooling', 'Zone', 'Damper'] as const;

import { MagnifyingGlassIcon, FunnelIcon } from '@heroicons/react/24/solid';

export function TicketsPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();

  // Initialize from URL params
  const [search, setSearch] = useState(() => searchParams.get('q') ?? '');
  const [status, setStatus] = useState<(typeof STATUS_OPTIONS)[number]>(
    (searchParams.get('status') as (typeof STATUS_OPTIONS)[number]) || 'All Review'
  );
  const [faultType, setFaultType] = useState(
    searchParams.get('faultType') || 'All Fault Types'
  );

  const [tickets, setTickets] = useState<TicketApi[]>([]);
  const [metrics, setMetrics] = useState<TicketMetricsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const API_BASE_URL = (import.meta as any).env?.VITE_API_BASE_URL ?? '';

  const reviewStatusParam = useMemo(() => {
    if (status === 'All Review') return undefined;
    if (status === 'Awaiting Review') return 'NONE';
    if (status === 'Approved') return 'APPROVED';
    if (status === 'Rejected') return 'REJECTED';
    return undefined;
  }, [status]);

  const qParam = useMemo(() => {
    const trimmed = search.trim();
    return trimmed.length > 0 ? trimmed : undefined;
  }, [search]);

  const faultTypeParam = useMemo(() => {
    if (faultType === 'All Fault Types') return undefined;
    // Keep existing dropdown values but pass through as backend "fault_type" filter.
    return faultType;
  }, [faultType]);

  // Sync state to URL params
  useEffect(() => {
    const params: Record<string, string> = {};
    if (search) params.q = search;
    if (status && status !== 'All Review') params.status = status;
    if (faultType && faultType !== 'All Fault Types') params.faultType = faultType;
    setSearchParams(params, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, status, faultType]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    const fetchAll = async () => {
      try {
        setError(null);
        const params = new URLSearchParams();
        params.set('limit', '200');
        params.set('offset', '0');
        params.set('sort', 'updated_at');
        params.set('order', 'desc');
        if (reviewStatusParam) params.set('review_status', reviewStatusParam);
        if (faultTypeParam) params.set('fault_type', faultTypeParam);
        if (qParam) params.set('q', qParam);

        const [listRes, metricsRes] = await Promise.all([
          fetch(`${API_BASE_URL}/api/tickets?${params.toString()}`),
          fetch(`${API_BASE_URL}/api/tickets/metrics`),
        ]);

        if (!listRes.ok) {
          throw new Error(`Tickets fetch failed (${listRes.status})`);
        }
        if (!metricsRes.ok) {
          throw new Error(`Metrics fetch failed (${metricsRes.status})`);
        }

        const listJson = (await listRes.json()) as TicketListResponse;
        const metricsJson = (await metricsRes.json()) as TicketMetricsResponse;
        if (cancelled) return;
        setTickets(Array.isArray(listJson.items) ? listJson.items : []);
        setMetrics(metricsJson);
      } catch (e: any) {
        if (cancelled) return;
        setError(e?.message ?? 'Failed to load tickets');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchAll();
    timer = window.setInterval(fetchAll, 5000);

    return () => {
      cancelled = true;
      if (timer) window.clearInterval(timer);
    };
  }, [API_BASE_URL, reviewStatusParam, faultTypeParam, qParam]);

  const rows = useMemo(() => {
    const toTitleCase = (s: string) =>
      s
        .toLowerCase()
        .split(/\s+/)
        .filter(Boolean)
        .map(w => w.charAt(0).toUpperCase() + w.slice(1))
        .join(' ');

    const formatFaultLabel = (raw: unknown) => {
      const s = String(raw ?? '').trim();
      if (!s) return '—';
      // Keep trailing "FAULT" as a user-facing word (e.g., COOLING_COIL_FAULT -> "Cooling Coil Fault")
      const cleaned = s.replace(/_/g, ' ').trim();
      return toTitleCase(cleaned);
    };

    const formatAhuLabel = (raw: unknown) => {
      const s = String(raw ?? '').trim();
      if (!s) return '—';
      if (/^ahu\s*\d+/i.test(s)) return s.replace(/^ahu\s*/i, 'AHU ');
      if (/^\d+$/.test(s)) return `AHU ${s}`;
      return s;
    };

    return tickets.map((t) => {
      const confidencePct = Math.max(0, Math.min(100, Math.round((Number(t.confidence ?? 0) || 0) * 100)));
      return {
        ticket_id: t.ticket_id,
        ticket_ref: t.ticket_ref,
        fault: formatFaultLabel(t.detected_fault_type),
        location: formatAhuLabel(t.ahu_id),
        confidencePct,
        updated: formatDateTime(t.updated_at),
        lifecycle_status: t.lifecycle_status,
        review_status: t.review_status,
      };
    });
  }, [tickets]);

  return (
    <div className="space-y-6 px-6">
      {error && (
        <div className="bg-rose-50 border border-rose-200 text-rose-900 rounded px-4 py-2 text-sm mb-2">
          <strong>Error:</strong> {error}
        </div>
      )}
      {/* Header Title Bar */}
      <div className="flex items-center justify-between pt-6 pb-2">
        <div className="text-2xl font-semibold text-slate-900">Ticket Management</div>
      </div>

      {/* Summary Cards Row */}
      <div className="flex gap-6">
        <div className="flex-1 rounded-lg bg-white shadow-sm border border-slate-200 p-5 flex flex-col items-start">
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Awaiting Review</div>
          <div className="text-3xl font-bold text-slate-900">{metrics?.awaiting_review_count ?? (loading ? '…' : 0)}</div>
        </div>
        <div className="flex-1 rounded-lg bg-white shadow-sm border border-slate-200 p-5 flex flex-col items-start">
          <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">High Confidence Tickets</div>
          <div className="text-3xl font-bold text-slate-900">{metrics?.high_confidence_count ?? (loading ? '…' : 0)}</div>
        </div>
      </div>

      {/* Filter & Search Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 pt-4 pb-2">
        {/* Search input with icon */}
        <div className="relative flex-1 max-w-xs">
          <span className="absolute inset-y-0 left-0 flex items-center pl-3 pointer-events-none">
            <MagnifyingGlassIcon className="w-5 h-5 text-slate-400" />
          </span>
          <input
            type="text"
            placeholder="Search tickets..."
            className="w-full border border-slate-200 rounded pl-10 pr-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-purple-200"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        {/* Filter dropdowns with icon */}
        <div className="flex gap-2">
          <div className="relative">
            <FunnelIcon className="w-4 h-4 text-slate-400 absolute left-2 top-1/2 -translate-y-1/2 pointer-events-none" />
            <select
              className="appearance-none border border-slate-200 rounded pl-8 pr-6 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-purple-200"
              value={status}
              onChange={(e) => setStatus(e.target.value as (typeof STATUS_OPTIONS)[number])}
            >
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          <div className="relative">
            <FunnelIcon className="w-4 h-4 text-slate-400 absolute left-2 top-1/2 -translate-y-1/2 pointer-events-none" />
            <select
              className="appearance-none border border-slate-200 rounded pl-8 pr-6 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-purple-200"
              value={faultType}
              onChange={(e) => setFaultType(e.target.value)}
            >
              {FAULT_TYPE_OPTIONS.map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Ticket List Table (unchanged) */}
      <div className="overflow-x-auto">
        <table className="min-w-full table-fixed border border-slate-200 rounded bg-white">
          <colgroup>
            <col style={{ width: '120px' }} />
            <col style={{ width: '260px' }} />
            <col style={{ width: '140px' }} />
            <col style={{ width: '160px' }} />
            <col style={{ width: '120px' }} />
            <col style={{ width: '40px' }} />
          </colgroup>
          <thead>
            <tr className="bg-slate-50 text-slate-500 text-xs uppercase">
              <th className="px-4 py-2 border-b font-semibold text-left align-middle">Ticket ID</th>
              <th className="px-4 py-2 border-b font-semibold text-left align-middle">Fault Name + Location</th>
              <th className="px-4 py-2 border-b font-semibold text-left align-middle">Confidence</th>
              <th className="px-4 py-2 border-b font-semibold text-left align-middle">Updated</th>
              <th className="px-4 py-2 border-b font-semibold text-left align-middle">Status</th>
              <th className="px-2 py-2 border-b font-semibold text-left align-middle"></th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="text-center text-slate-500 py-6">No tickets found.</td>
              </tr>
            ) : (
              rows.map((t) => {
                // Preserve filters in navigation
                const params = new URLSearchParams();
                if (search) params.set('q', search);
                if (status && status !== 'All Review') params.set('status', status);
                if (faultType && faultType !== 'All Fault Types') params.set('faultType', faultType);
                const detailUrl = `/tickets/${t.ticket_id}?${params.toString()}`;
                return (
                  <tr
                    key={t.ticket_id}
                    className="border-b last:border-b-0 hover:bg-slate-50 transition cursor-pointer group"
                    onClick={() => navigate(detailUrl)}
                  >
                    <td className="px-4 py-2 font-mono text-sm align-middle">
                      <Link to={detailUrl} className="text-purple-700 hover:underline">{t.ticket_ref}</Link>
                    </td>
                    <td className="px-4 py-2 text-sm align-middle">
                      <div className="font-medium text-slate-900 leading-tight">{t.fault}</div>
                      <div className="text-xs text-slate-500 leading-tight">{t.location}</div>
                    </td>
                    <td className="px-4 py-2 align-middle">
                      <ConfidenceBar value={t.confidencePct} />
                    </td>
                    <td className="px-4 py-2 text-sm align-middle">{t.updated}</td>
                    <td className="px-4 py-2 align-middle">
                      <div className="flex flex-col gap-1 items-start">
                        <StatusBadge status={t.lifecycle_status} />
                        <StatusBadge status={t.review_status} />
                      </div>
                    </td>
                    <td className="px-2 py-2 align-middle text-right">
                      <ArrowRightIcon className="w-5 h-5 text-slate-400 group-hover:text-purple-600 inline-block align-middle" />
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
