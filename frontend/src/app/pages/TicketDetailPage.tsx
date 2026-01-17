import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useEffect, useMemo, useState } from 'react';
import { ConfidenceBar, StatusBadge } from '../components/TicketTableWidgets';

const TABS = ['Correlation Analysis', 'Similar Cases', 'System Manuals'] as const;

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
  last_seen_at: string;
  diagnosed_at?: string | null;
  resolved_at?: string | null;

  diagnosis_title?: string | null;
  root_cause?: string | null;
  recommended_actions?: any;
  symptom_summary?: string | null;

  evidence_ids?: any[];
  window_refs?: any[];
  signatures_seen?: any[];

  review_notes?: string | null;
};

export function TicketDetailPage() {
  const navigate = useNavigate();
  const { ticketId } = useParams();
  const [searchParams] = useSearchParams();
  const [tab, setTab] = useState<(typeof TABS)[number]>('Correlation Analysis');
  const [ticket, setTicket] = useState<TicketApi | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [notes, setNotes] = useState('');
  const [notesDirty, setNotesDirty] = useState(false);
  const [submitting, setSubmitting] = useState<'APPROVED' | 'REJECTED' | null>(null);

  const API_BASE_URL = (import.meta as any).env?.VITE_API_BASE_URL ?? '';

  const confidencePct = useMemo(() => {
    const raw = Number(ticket?.confidence ?? 0) || 0;
    return Math.max(0, Math.min(100, Math.round(raw * 100)));
  }, [ticket?.confidence]);

  const canReview = ticket?.diagnosis_status === 'DIAGNOSED';
  const reviewFinal = ticket?.review_status === 'APPROVED' || ticket?.review_status === 'REJECTED';

  useEffect(() => {
    if (!ticketId) return;

    let cancelled = false;
    let timer: number | undefined;

    const fetchTicket = async () => {
      try {
        setError(null);
        const res = await fetch(`${API_BASE_URL}/api/tickets/${encodeURIComponent(ticketId)}`);
        if (!res.ok) {
          throw new Error(`Ticket fetch failed (${res.status})`);
        }
        const json = (await res.json()) as TicketApi;
        if (cancelled) return;
        setTicket(json);
        if (!notesDirty) {
          setNotes(json.review_notes ?? '');
        }
      } catch (e: any) {
        if (cancelled) return;
        setError(e?.message ?? 'Failed to load ticket');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchTicket();
    timer = window.setInterval(fetchTicket, 3000);

    return () => {
      cancelled = true;
      if (timer) window.clearInterval(timer);
    };
  }, [API_BASE_URL, ticketId, notesDirty]);

  const patchReview = async (review_status: 'APPROVED' | 'REJECTED') => {
    if (!ticketId) return;
    setSubmitting(review_status);
    try {
      setError(null);
      const res = await fetch(`${API_BASE_URL}/api/tickets/${encodeURIComponent(ticketId)}/review`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ review_status, review_notes: notes }),
      });
      if (!res.ok) {
        throw new Error(`Review update failed (${res.status})`);
      }
      const json = (await res.json()) as TicketApi;
      setTicket(json);
      setNotes(json.review_notes ?? '');
      setNotesDirty(false);
    } catch (e: any) {
      setError(e?.message ?? 'Failed to update review');
    } finally {
      setSubmitting(null);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 py-8 px-4">
      {error && (
        <div className="max-w-6xl mx-auto mb-4">
          <div className="bg-rose-50 border border-rose-200 text-rose-900 rounded px-4 py-2 text-sm">
            <strong>Error:</strong> {error}
          </div>
        </div>
      )}
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-6 gap-2">
          <div>
            <button
              onClick={() => {
                // Restore filters when navigating back
                const params = searchParams.toString();
                navigate(params ? `/tickets?${params}` : '/tickets');
              }}
              className="text-sm text-purple-700 hover:underline mb-1"
            >
              ← Back to Tickets
            </button>
            <div className="text-2xl font-semibold text-slate-900">
              {loading && !ticket ? 'Loading ticket…' : `Ticket #${ticket?.ticket_ref ?? ticketId}: ${ticket?.detected_fault_type ?? ''}`}
            </div>
            <div className="text-sm text-slate-500 mt-1">{ticket?.ahu_id ?? ''} • AI Detected</div>
          </div>
          {ticket && (
            <div className="flex flex-wrap gap-2 items-center justify-end">
              <StatusBadge status={ticket.lifecycle_status} />
              <StatusBadge status={ticket.diagnosis_status} />
              <StatusBadge status={ticket.review_status} />
            </div>
          )}
        </div>
        {/* Main layout */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Left column */}
          <div className="space-y-6">
            {/* Fault Summary */}
            <div className="rounded-lg bg-white shadow-sm border border-slate-200 p-6">
              <div className="text-lg font-medium text-slate-900 mb-2">Fault Summary</div>
              <div className="text-slate-700 mb-2">
                Diagnosis: <span className="font-semibold text-slate-900">{ticket?.diagnosis_title ?? '—'}</span>
              </div>
              <div className="text-slate-700 mb-2">
                Root Cause: <span className="font-medium text-slate-900">{ticket?.root_cause ?? '—'}</span>
              </div>
              <div className="flex items-center gap-3 mb-2">
                <div>
                  <div className="text-xs text-slate-500 mb-1">Confidence</div>
                  <ConfidenceBar value={confidencePct} />
                </div>
              </div>
              <div className="text-slate-700 mt-2">
                <span className="font-medium text-slate-900">Symptom Summary:</span> {ticket?.symptom_summary ?? '—'}
              </div>
              <div className="text-slate-700 mt-2">
                <span className="font-medium text-slate-900">Recommended Actions:</span>{' '}
                {ticket?.recommended_actions ? (
                  <span className="text-slate-700">
                    {typeof ticket.recommended_actions === 'string'
                      ? ticket.recommended_actions
                      : Array.isArray(ticket.recommended_actions)
                        ? ticket.recommended_actions.join('; ')
                        : JSON.stringify(ticket.recommended_actions)}
                  </span>
                ) : (
                  '—'
                )}
              </div>
            </div>
            {/* Human Review */}
            <div className="rounded-lg bg-white shadow-sm border border-slate-200 p-6 flex flex-col min-h-[340px]">
              <div className="text-lg font-medium text-slate-900 mb-2">Human Review</div>
              <label className="text-xs text-slate-500 mb-1" htmlFor="notes">Technician Notes</label>
              <textarea
                id="notes"
                className="border border-slate-200 rounded p-2 text-sm mb-4 min-h-[80px] max-h-32 resize-none bg-slate-50"
                placeholder="Add your observations…"
                value={notes}
                onChange={e => {
                  setNotes(e.target.value);
                  setNotesDirty(true);
                }}
                disabled={reviewFinal}
              />
              {!reviewFinal ? (
                <div className="flex gap-3 mt-auto pt-2">
                  <button
                    disabled={!canReview || submitting !== null}
                    onClick={() => patchReview('APPROVED')}
                    className={`flex-1 font-semibold py-2 rounded-lg text-lg shadow transition ${
                      !canReview || submitting !== null
                        ? 'bg-green-200 text-white cursor-not-allowed'
                        : 'bg-green-600 hover:bg-green-700 text-white'
                    }`}
                  >
                    {submitting === 'APPROVED' ? 'Approving…' : 'Approve'}
                  </button>
                  <button
                    disabled={!canReview || submitting !== null}
                    onClick={() => patchReview('REJECTED')}
                    className={`flex-1 font-semibold py-2 rounded-lg text-lg border shadow transition ${
                      !canReview || submitting !== null
                        ? 'bg-rose-50 text-rose-400 border-rose-100 cursor-not-allowed'
                        : 'bg-rose-100 hover:bg-rose-200 text-rose-800 border-rose-200'
                    }`}
                  >
                    {submitting === 'REJECTED' ? 'Rejecting…' : 'Reject'}
                  </button>
                </div>
              ) : (
                <div className="mt-auto pt-2 text-sm text-slate-600">
                  This ticket has been {ticket?.review_status?.toLowerCase()}. Review actions are hidden.
                </div>
              )}
              {!canReview && !reviewFinal && (
                <div className="text-xs text-slate-500 mt-2">
                  Review is disabled until the ticket is diagnosed.
                </div>
              )}
            </div>
          </div>
          {/* Right column */}
          <div className="space-y-6">
            {/* Reasoning Summary */}
            <div className="rounded-lg bg-white shadow-sm border border-slate-200 p-6">
              <div className="text-lg font-medium text-slate-900 mb-2">Reasoning Summary</div>
              <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Primary Hypothesis</div>
              <div className="text-slate-900 font-semibold mb-2">{ticket?.diagnosis_title ?? ticket?.detected_fault_type ?? '—'}</div>
              <div className="flex items-center gap-2 mb-2">
                <ConfidenceBar value={confidencePct} />
              </div>
              <div className="text-xs text-slate-500 mb-1">Evidence / References</div>
              <ul className="list-disc pl-5 mb-2 text-slate-700">
                <li>Evidence IDs: {(ticket?.evidence_ids?.length ?? 0) > 0 ? ticket?.evidence_ids?.join(', ') : '—'}</li>
                <li>Window Refs: {(ticket?.window_refs?.length ?? 0) > 0 ? ticket?.window_refs?.join(', ') : '—'}</li>
                <li>Signatures Seen: {(ticket?.signatures_seen?.length ?? 0) > 0 ? ticket?.signatures_seen?.join(', ') : '—'}</li>
              </ul>
            </div>

            {/* Analysis Tabs (placeholder: not backed by Tickets API yet) */}
            <div className="rounded-lg bg-white shadow-sm border border-slate-200 p-6">
              <div className="flex gap-4 border-b border-slate-100 mb-4">
                {TABS.map((tabName) => (
                  <button
                    key={tabName}
                    className={`pb-2 text-sm font-medium border-b-2 transition ${tab === tabName ? 'border-purple-600 text-purple-700' : 'border-transparent text-slate-500 hover:text-slate-700'}`}
                    onClick={() => setTab(tabName)}
                  >
                    {tabName}
                  </button>
                ))}
              </div>

              {tab === 'Correlation Analysis' && (
                <div>
                  <div className="text-sm font-medium text-slate-900 mb-2">Valve Position vs SAT</div>
                  <div className="text-xs text-slate-500 mb-3">
                    Placeholder UI (not from Tickets API yet).
                  </div>
                  {/* Simple static chart mockup */}
                  <div className="bg-slate-50 rounded p-4 flex flex-col items-center">
                    <div className="w-full flex justify-between text-xs text-slate-500 mb-1">
                      <span>Start</span>
                      <span>End</span>
                    </div>
                    <svg width="100%" height="120" viewBox="0 0 320 120" className="mb-2">
                      {/* Valve position line (purple) */}
                      <polyline
                        fill="none"
                        stroke="#9333ea"
                        strokeWidth="3"
                        points="40,80 80,60 120,60 160,60 200,60 240,60"
                      />
                      {/* SAT line (slate) */}
                      <polyline
                        fill="none"
                        stroke="#64748b"
                        strokeWidth="3"
                        points="40,90 80,95 120,97 160,99 200,100 240,102"
                      />
                      {/* Highlighted data point */}
                      <circle cx="240" cy="60" r="6" fill="#9333ea" stroke="#fff" strokeWidth="2" />
                    </svg>
                    <div className="flex justify-between w-full text-xs">
                      <span className="text-purple-700 font-medium">Valve Position (%)</span>
                      <span className="text-slate-500">SAT (°F)</span>
                    </div>
                  </div>
                </div>
              )}

              {tab === 'Similar Cases' && (
                <div className="text-slate-500 text-sm">Placeholder: similar cases not implemented yet.</div>
              )}

              {tab === 'System Manuals' && (
                <div className="text-slate-500 text-sm">Placeholder: manuals not implemented yet.</div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
