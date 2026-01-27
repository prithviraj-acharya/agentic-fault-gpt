import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useEffect, useMemo, useState } from 'react';
import { ConfidenceBar, StatusBadge } from '../components/TicketTableWidgets';

const TABS = ['Similar Cases', 'System Manuals'] as const;

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
  const [tab, setTab] = useState<(typeof TABS)[number]>('Similar Cases');
  const [ticket, setTicket] = useState<TicketApi | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [notes, setNotes] = useState('');
  const [notesDirty, setNotesDirty] = useState(false);
  const [submitting, setSubmitting] = useState<'APPROVED' | 'REJECTED' | null>(null);

  const API_BASE_URL = (import.meta as any).env?.VITE_API_BASE_URL ?? '';

  const formatters = useMemo(() => {
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

    return { formatFaultLabel, formatAhuLabel };
  }, []);

  const confidencePct = useMemo(() => {
    const raw = Number(ticket?.confidence ?? 0) || 0;
    return Math.max(0, Math.min(100, Math.round(raw * 100)));
  }, [ticket?.confidence]);

  const confidenceLabel = useMemo(() => {
    if (confidencePct >= 80) return `${confidencePct}% (High)`;
    if (confidencePct >= 60) return `${confidencePct}% (Moderate)`;
    return `${confidencePct}% (Low)`;
  }, [confidencePct]);

  const confidenceToneClass = useMemo(() => {
    if (confidencePct < 50) return 'text-rose-700';
    if (confidencePct < 70) return 'text-amber-800';
    return 'text-emerald-700';
  }, [confidencePct]);

  const reasoningEvidenceView = useMemo(() => {
    const rawEvidenceIds = (ticket?.evidence_ids ?? []).filter(Boolean).map(String);
    const rawWindowRefs = (ticket?.window_refs ?? []).filter(Boolean).map(String);
    const rawSignatures = (ticket?.signatures_seen ?? []).filter(Boolean).map(String);

    const uniq = (items: string[]) => {
      const seen = new Set<string>();
      const out: string[] = [];
      for (const it of items) {
        if (seen.has(it)) continue;
        seen.add(it);
        out.push(it);
      }
      return out;
    };

    const isTelemetryWindow = (id: string) => id.includes('_300s_tumbling') || id.toLowerCase().startsWith('window:');
    const isGuidelineChunk = (id: string) => id.includes('::chunk::');
    const isPastCase = (id: string) => id.startsWith('CASE_') || id.includes('CASE');

    const telemetryWindows = uniq(rawEvidenceIds.filter(isTelemetryWindow));
    const guidelineChunks = uniq(rawEvidenceIds.filter(isGuidelineChunk));
    const pastCases = uniq(rawEvidenceIds.filter(isPastCase));
    const otherEvidence = uniq(
      rawEvidenceIds.filter(id => !isTelemetryWindow(id) && !isGuidelineChunk(id) && !isPastCase(id)),
    );

    const parseChunkId = (id: string) => {
      const parts = id.split('::chunk::');
      if (parts.length < 2) return { docIdRaw: id, docName: id, chunk: '' };
      const docIdRaw = parts[0];
      const chunk = parts[1];
      const docNameRaw = docIdRaw.includes(':') ? docIdRaw.split(':').slice(-1)[0] : docIdRaw;
      const docName = docNameRaw.replace(/_/g, ' ').trim();
      return { docIdRaw, docName, chunk };
    };

    const truncateLabel = (s: string, max = 24) => {
      const t = String(s);
      if (t.length <= max) return t;
      return `${t.slice(0, Math.max(0, max - 1))}…`;
    };

    const chipTextGuideline = (id: string) => {
      const { docName, chunk } = parseChunkId(id);
      if (!chunk) return truncateLabel(docName);
      return `${truncateLabel(docName, 20)} · chunk ${chunk}`;
    };

    const chipTitleGuideline = (id: string) => {
      const { docIdRaw, docName, chunk } = parseChunkId(id);
      if (!chunk) return docIdRaw;
      return `${docName} (chunk ${chunk})\n${docIdRaw}::chunk::${chunk}`;
    };

    const truncateHash = (s: string) => {
      const t = String(s);
      if (t.length <= 14) return t;
      return `${t.slice(0, 8)}…${t.slice(-4)}`;
    };

    const inferredWindows = telemetryWindows;
    const windowRefs = uniq(rawWindowRefs.length > 0 ? rawWindowRefs : inferredWindows);
    const windowRefsLast2 = windowRefs.slice(-2);

    const symptom = String(ticket?.symptom_summary ?? '');
    const sigFromSymptom = (() => {
      const m = symptom.match(/signature=([a-f0-9]{8,})/i);
      return m?.[1] ? [m[1]] : [];
    })();

    const signatures = uniq(rawSignatures.length > 0 ? rawSignatures : sigFromSymptom);
    const signaturesTop3 = signatures.slice(0, 3);

    const manuals = uniq(guidelineChunks.map(id => parseChunkId(id).docName)).filter(Boolean);

    return {
      evidence: {
        telemetryWindows,
        guidelineChunks,
        pastCases,
        otherEvidence,
        all: rawEvidenceIds,
        chipTextGuideline,
        chipTitleGuideline,
        manuals,
      },
      windowRefs: {
        all: windowRefs,
        last2: windowRefsLast2,
      },
      signatures: {
        all: signatures,
        top3: signaturesTop3,
        truncateHash,
      },
    };
  }, [ticket?.evidence_ids, ticket?.window_refs, ticket?.signatures_seen, ticket?.symptom_summary]);

  const faultSummaryView = useMemo(() => {
    const evidencePattern = /\s*\(evidence:\s*([^)]*)\)\.?\s*$/i;
    const normalizeEvidenceIds = (raw: string): string[] => {
      return raw
        .split(/[,;\s]+/)
        .map(s => s.trim())
        .filter(Boolean);
    };

    const stripEvidenceSuffix = (text: string): string => {
      return text.replace(evidencePattern, '').trim();
    };

    const extractEvidenceSuffix = (text: string): string[] => {
      const m = text.match(evidencePattern);
      if (!m?.[1]) return [];
      return normalizeEvidenceIds(m[1]);
    };

    const splitRootCause = (rootCauseRaw: string) => {
      const marker = 'Reasoning:';
      const idx = rootCauseRaw.indexOf(marker);
      if (idx === -1) {
        return { primary: rootCauseRaw.trim(), reasoning: '' };
      }
      const primary = rootCauseRaw.slice(0, idx).trim().replace(/\s+$/, '');
      const reasoning = rootCauseRaw.slice(idx).trim();
      return { primary, reasoning };
    };

    const parseKeySymptoms = (summary: string) => {
      const out: {
        windowText?: string;
        anomalies: string[];
        metrics: Array<{ label: string; value: string }>;
      } = { anomalies: [], metrics: [] };

      const windowMatch = summary.match(/window\s+([^:]+):/i);
      if (windowMatch?.[1]) out.windowText = windowMatch[1].trim();

      const anomaliesMatch = summary.match(/anomalies=([^.]*)/i);
      if (anomaliesMatch?.[1]) {
        out.anomalies = anomaliesMatch[1]
          .split(',')
          .map(s => s.trim())
          .filter(Boolean);
      }

      const takeMetric = (key: string, label: string) => {
        const m = summary.match(new RegExp(`${key}=(-?\\d+(?:\\.\\d+)?)`, 'i'));
        if (m?.[1]) out.metrics.push({ label, value: m[1] });
      };

      takeMetric('sa_temp_mean', 'SAT mean');
      takeMetric('sa_temp_mean_minus_sp', 'SAT − setpoint');
      takeMetric('cc_valve_mean', 'Cooling coil valve mean (%)');
      takeMetric('avg_zone_temp_mean', 'Avg zone temp mean');

      return out;
    };

    const recommendedActionsRaw = ticket?.recommended_actions;
    const recommendedActions: string[] = Array.isArray(recommendedActionsRaw)
      ? recommendedActionsRaw.filter(Boolean).map(String)
      : typeof recommendedActionsRaw === 'string' && recommendedActionsRaw.trim()
        ? [recommendedActionsRaw]
        : recommendedActionsRaw
          ? [JSON.stringify(recommendedActionsRaw)]
          : [];

    const rootCauseRaw = String(ticket?.root_cause ?? '').trim();
    const rootCauseSplit = rootCauseRaw ? splitRootCause(rootCauseRaw) : { primary: '', reasoning: '' };

    const rootCauseEvidence = rootCauseRaw ? extractEvidenceSuffix(rootCauseRaw) : [];
    const rootCauseDisplay = rootCauseRaw ? stripEvidenceSuffix(rootCauseRaw) : '';
    const rootCauseDisplaySplit = rootCauseDisplay
      ? splitRootCause(rootCauseDisplay)
      : { primary: '', reasoning: '' };

    const actionsDisplay = recommendedActions.map(a => stripEvidenceSuffix(a));
    const actionsEvidence = recommendedActions.map(a => extractEvidenceSuffix(a));

    const symptomSummary = String(ticket?.symptom_summary ?? '').trim();
    const symptoms = symptomSummary ? parseKeySymptoms(symptomSummary) : { anomalies: [], metrics: [] as Array<{ label: string; value: string }> };

    return {
      diagnosisTitle: String(ticket?.diagnosis_title ?? '').trim(),
      rootCause: {
        raw: rootCauseRaw,
        primary: rootCauseDisplaySplit.primary,
        reasoning: rootCauseDisplaySplit.reasoning,
        evidenceIds: rootCauseEvidence,
        rawSplit: rootCauseSplit,
      },
      symptoms: {
        summary: symptomSummary,
        windowText: symptoms.windowText,
        anomalies: symptoms.anomalies,
        metrics: symptoms.metrics,
      },
      actions: {
        raw: recommendedActions,
        display: actionsDisplay,
        evidenceByAction: actionsEvidence,
      },
    };
  }, [ticket?.diagnosis_title, ticket?.recommended_actions, ticket?.root_cause, ticket?.symptom_summary]);

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
              {loading && !ticket
                ? 'Loading ticket…'
                : `Ticket #${ticket?.ticket_ref ?? ticketId}: ${formatters.formatFaultLabel(ticket?.detected_fault_type)}`}
            </div>
            <div className="text-sm text-slate-500 mt-1">{formatters.formatAhuLabel(ticket?.ahu_id)} • AI Detected</div>
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

              {/* Diagnosis */}
              <div className="mt-4">
                <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Diagnosis</div>
                <div className="text-slate-900 font-semibold">
                  {faultSummaryView.diagnosisTitle || formatters.formatFaultLabel(ticket?.detected_fault_type)}
                </div>
              </div>

              {/* Primary Root Cause */}
              <div className="mt-5">
                <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Primary Root Cause</div>
                {faultSummaryView.rootCause.primary || faultSummaryView.rootCause.reasoning ? (
                  <div className="space-y-2">
                    {faultSummaryView.rootCause.primary && (
                      <div className="text-slate-900">{faultSummaryView.rootCause.primary}</div>
                    )}
                    {faultSummaryView.rootCause.reasoning && (
                      <div className="text-slate-700">
                        <span className="font-medium text-slate-900">{faultSummaryView.rootCause.reasoning}</span>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="text-slate-500">—</div>
                )}
              </div>

              {/* Key Symptoms */}
              <div className="mt-5">
                <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Key Symptoms</div>
                {faultSummaryView.symptoms.windowText && (
                  <div className="text-sm text-slate-600 mb-3">
                    <span className="font-medium text-slate-900">Window:</span> {faultSummaryView.symptoms.windowText}
                  </div>
                )}

                {(faultSummaryView.symptoms.metrics?.length ?? 0) > 0 ? (
                  <div className="overflow-hidden rounded border border-slate-200">
                    <table className="w-full text-sm">
                      <tbody>
                        {faultSummaryView.symptoms.metrics.map(m => (
                          <tr key={m.label} className="border-t border-slate-100 first:border-t-0">
                            <td className="px-3 py-2 text-slate-600 bg-slate-50 w-1/2">{m.label}</td>
                            <td className="px-3 py-2 text-slate-900 font-medium">{m.value}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="text-sm text-slate-500">No structured metrics found in symptom summary.</div>
                )}

                {(faultSummaryView.symptoms.anomalies?.length ?? 0) > 0 && (
                  <div className="mt-3">
                    <div className="text-xs text-slate-500 mb-1">Detected anomaly rules</div>
                    <ul className="list-disc pl-5 text-sm text-slate-700">
                      {faultSummaryView.symptoms.anomalies.map(a => (
                        <li key={a}>{a}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>

              {/* Confidence */}
              <div className="mt-5">
                <div className="text-xs uppercase tracking-wide text-slate-500 mb-1">Confidence</div>
                <div className="flex items-center gap-3">
                  <div className="flex-1">
                    <ConfidenceBar value={confidencePct} />
                  </div>
                  <div className={`text-sm font-semibold w-14 text-right ${confidenceToneClass}`}>{confidencePct}%</div>
                </div>
                <div className="text-xs text-slate-500 mt-1">
                  Model-reported confidence; verify using the evidence and symptoms below.
                </div>
              </div>

              {/* Recommended Actions */}
              <div className="mt-5">
                <div className="text-xs uppercase tracking-wide text-slate-500 mb-2">Recommended Actions</div>
                {(faultSummaryView.actions.display?.length ?? 0) > 0 ? (
                  <ol className="list-decimal pl-5 space-y-2 text-sm text-slate-700">
                    {faultSummaryView.actions.display.map((action, idx) => (
                      <li key={`${idx}-${action.slice(0, 16)}`} className="leading-relaxed">
                        {action}
                      </li>
                    ))}
                  </ol>
                ) : (
                  <div className="text-slate-500">—</div>
                )}
              </div>

              {/* Evidence (collapsed) */}
              <div className="mt-5">
                <details className="rounded border border-slate-200 bg-slate-50">
                  <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium text-slate-900">
                    Evidence
                    <span className="ml-2 text-xs font-normal text-slate-500">
                      (IDs and references)
                    </span>
                  </summary>
                  <div className="px-3 pb-3 pt-1 space-y-3">
                    {(ticket?.evidence_ids?.length ?? 0) > 0 && (
                      <div>
                        <div className="text-xs text-slate-500 mb-1">Evidence IDs</div>
                        <div className="text-sm text-slate-700 break-words">
                          {ticket?.evidence_ids?.join(', ')}
                        </div>
                      </div>
                    )}
                    {(ticket?.window_refs?.length ?? 0) > 0 && (
                      <div>
                        <div className="text-xs text-slate-500 mb-1">Window Refs</div>
                        <div className="text-sm text-slate-700 break-words">
                          {ticket?.window_refs?.join(', ')}
                        </div>
                      </div>
                    )}
                    {(ticket?.signatures_seen?.length ?? 0) > 0 && (
                      <div>
                        <div className="text-xs text-slate-500 mb-1">Signatures Seen</div>
                        <div className="text-sm text-slate-700 break-words">
                          {ticket?.signatures_seen?.join(', ')}
                        </div>
                      </div>
                    )}

                    {(faultSummaryView.rootCause.evidenceIds?.length ?? 0) > 0 && (
                      <div>
                        <div className="text-xs text-slate-500 mb-1">Evidence referenced in root cause</div>
                        <div className="text-sm text-slate-700 break-words">
                          {faultSummaryView.rootCause.evidenceIds.join(', ')}
                        </div>
                      </div>
                    )}

                    {(faultSummaryView.actions.evidenceByAction?.some(arr => (arr?.length ?? 0) > 0) ?? false) && (
                      <div>
                        <div className="text-xs text-slate-500 mb-1">Evidence referenced in actions</div>
                        <ul className="list-disc pl-5 text-sm text-slate-700">
                          {faultSummaryView.actions.evidenceByAction.map((ids, idx) =>
                            (ids?.length ?? 0) > 0 ? (
                              <li key={`action-evidence-${idx}`}>
                                Action {idx + 1}: {ids.join(', ')}
                              </li>
                            ) : null,
                          )}
                        </ul>
                      </div>
                    )}

                    {(ticket?.evidence_ids?.length ?? 0) === 0 &&
                      (ticket?.window_refs?.length ?? 0) === 0 &&
                      (ticket?.signatures_seen?.length ?? 0) === 0 &&
                      (faultSummaryView.rootCause.evidenceIds?.length ?? 0) === 0 &&
                      !(faultSummaryView.actions.evidenceByAction?.some(arr => (arr?.length ?? 0) > 0) ?? false) && (
                        <div className="text-sm text-slate-500">—</div>
                      )}
                  </div>
                </details>
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
                <div className={`text-sm font-semibold whitespace-nowrap ${confidenceToneClass}`}>{confidenceLabel}</div>
              </div>
              <div className="text-xs text-slate-500 mb-1">Evidence / References</div>

              {/* Grouped evidence chips */}
              <div className="space-y-3">
                <div>
                  <div className="text-xs font-medium text-slate-700 mb-1">Telemetry Windows ({reasoningEvidenceView.evidence.telemetryWindows.length})</div>
                  <div className="flex flex-wrap gap-2">
                    {reasoningEvidenceView.evidence.telemetryWindows.length > 0 ? (
                      <>
                        {reasoningEvidenceView.evidence.telemetryWindows.slice(0, 3).map(id => (
                          <span key={id} className="px-2 py-1 rounded-full bg-purple-50 text-purple-800 border border-purple-100 text-xs">
                            {id}
                          </span>
                        ))}
                        {reasoningEvidenceView.evidence.telemetryWindows.length > 3 && (
                          <span className="px-2 py-1 rounded-full bg-slate-50 text-slate-600 border border-slate-200 text-xs">
                            +{reasoningEvidenceView.evidence.telemetryWindows.length - 3} more
                          </span>
                        )}
                      </>
                    ) : (
                      <span className="text-sm text-slate-500">—</span>
                    )}
                  </div>
                </div>

                <div>
                  <div className="text-xs font-medium text-slate-700 mb-1">Guidelines ({reasoningEvidenceView.evidence.guidelineChunks.length})</div>
                  <div className="flex flex-wrap gap-2">
                    {reasoningEvidenceView.evidence.guidelineChunks.length > 0 ? (
                      <>
                        {reasoningEvidenceView.evidence.guidelineChunks.slice(0, 5).map(id => (
                          <span
                            key={id}
                            title={reasoningEvidenceView.evidence.chipTitleGuideline(id)}
                            className="px-2 py-1 rounded-full bg-emerald-50 text-emerald-800 border border-emerald-100 text-xs"
                          >
                            {reasoningEvidenceView.evidence.chipTextGuideline(id)}
                          </span>
                        ))}
                        {reasoningEvidenceView.evidence.guidelineChunks.length > 5 && (
                          <span className="px-2 py-1 rounded-full bg-slate-50 text-slate-600 border border-slate-200 text-xs">
                            +{reasoningEvidenceView.evidence.guidelineChunks.length - 5} more
                          </span>
                        )}
                      </>
                    ) : (
                      <span className="text-sm text-slate-500">—</span>
                    )}
                  </div>
                </div>

                <div>
                  <div className="text-xs font-medium text-slate-700 mb-1">Past Cases ({reasoningEvidenceView.evidence.pastCases.length})</div>
                  <div className="flex flex-wrap gap-2">
                    {reasoningEvidenceView.evidence.pastCases.length > 0 ? (
                      <>
                        {reasoningEvidenceView.evidence.pastCases.slice(0, 5).map(id => (
                          <span key={id} className="px-2 py-1 rounded-full bg-amber-50 text-amber-900 border border-amber-100 text-xs">
                            {id}
                          </span>
                        ))}
                        {reasoningEvidenceView.evidence.pastCases.length > 5 && (
                          <span className="px-2 py-1 rounded-full bg-slate-50 text-slate-600 border border-slate-200 text-xs">
                            +{reasoningEvidenceView.evidence.pastCases.length - 5} more
                          </span>
                        )}
                      </>
                    ) : (
                      <span className="text-sm text-slate-500">—</span>
                    )}
                  </div>
                </div>

                {/* Window refs + signatures */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <div className="text-xs font-medium text-slate-700 mb-1">Window Refs</div>
                    <div className="flex flex-wrap gap-2">
                      {reasoningEvidenceView.windowRefs.last2.length > 0 ? (
                        reasoningEvidenceView.windowRefs.last2.map(id => (
                          <span key={id} className="px-2 py-1 rounded-full bg-slate-50 text-slate-700 border border-slate-200 text-xs">
                            {id}
                          </span>
                        ))
                      ) : (
                        <span className="text-sm text-slate-500">—</span>
                      )}
                    </div>
                    {reasoningEvidenceView.windowRefs.all.length > 2 && (
                      <div className="text-[11px] text-slate-500 mt-1">Showing last 2 of {reasoningEvidenceView.windowRefs.all.length}</div>
                    )}
                  </div>
                  <div>
                    <div className="text-xs font-medium text-slate-700 mb-1">Signatures Seen</div>
                    <div className="flex flex-wrap gap-2">
                      {reasoningEvidenceView.signatures.top3.length > 0 ? (
                        reasoningEvidenceView.signatures.top3.map(sig => (
                          <span key={sig} className="px-2 py-1 rounded-full bg-slate-50 text-slate-700 border border-slate-200 text-xs font-mono">
                            {reasoningEvidenceView.signatures.truncateHash(sig)}
                          </span>
                        ))
                      ) : (
                        <span className="text-sm text-slate-500">—</span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Collapsible full evidence */}
                <details className="rounded border border-slate-200 bg-slate-50">
                  <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium text-slate-900">
                    Show all evidence
                    <span className="ml-2 text-xs font-normal text-slate-500">({reasoningEvidenceView.evidence.all.length} total)</span>
                  </summary>
                  <div className="px-3 pb-3 pt-1 space-y-3">
                    <div>
                      <div className="text-xs text-slate-500 mb-1">Evidence IDs</div>
                      <div className="text-sm text-slate-700 break-words">
                        {reasoningEvidenceView.evidence.all.length > 0 ? reasoningEvidenceView.evidence.all.join(', ') : '—'}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-slate-500 mb-1">Window Refs</div>
                      <div className="text-sm text-slate-700 break-words">
                        {reasoningEvidenceView.windowRefs.all.length > 0 ? reasoningEvidenceView.windowRefs.all.join(', ') : '—'}
                      </div>
                    </div>
                    <div>
                      <div className="text-xs text-slate-500 mb-1">Signatures Seen</div>
                      <div className="text-sm text-slate-700 break-words font-mono">
                        {reasoningEvidenceView.signatures.all.length > 0 ? reasoningEvidenceView.signatures.all.join(', ') : '—'}
                      </div>
                    </div>
                    {reasoningEvidenceView.evidence.otherEvidence.length > 0 && (
                      <div>
                        <div className="text-xs text-slate-500 mb-1">Other Evidence</div>
                        <div className="text-sm text-slate-700 break-words">
                          {reasoningEvidenceView.evidence.otherEvidence.join(', ')}
                        </div>
                      </div>
                    )}
                  </div>
                </details>
              </div>
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

              {tab === 'Similar Cases' && (
                <div>
                  <div className="text-sm font-medium text-slate-900 mb-2">Similar Cases</div>
                  <div className="text-xs text-slate-500 mb-3">Derived from evidence IDs (UI-only).</div>

                  {reasoningEvidenceView.evidence.pastCases.length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                      {reasoningEvidenceView.evidence.pastCases.map(id => (
                        <span key={id} className="px-2 py-1 rounded-full bg-amber-50 text-amber-900 border border-amber-100 text-xs">
                          {id}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <div className="text-sm text-slate-500">—</div>
                  )}
                </div>
              )}

              {tab === 'System Manuals' && (
                <div>
                  <div className="text-sm font-medium text-slate-900 mb-2">System Manuals</div>
                  <div className="text-xs text-slate-500 mb-3">Derived from guideline chunk IDs (UI-only).</div>

                  {reasoningEvidenceView.evidence.manuals.length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                      {reasoningEvidenceView.evidence.manuals.map(name => (
                        <span key={name} className="px-2 py-1 rounded-full bg-emerald-50 text-emerald-900 border border-emerald-100 text-xs">
                          {name}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <div className="text-sm text-slate-500">—</div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
