from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from typing import Any, Optional

from diagnostic_agent.controller.incident_manager import IncidentManager
from diagnostic_agent.controller.retrieval_router import (
    RetrievalRouter,
    build_retrieval_query,
)
from diagnostic_agent.controller.schemas import (
    DiagnosisJob,
    IncidentContext,
    RetrievalStats,
    RetrievedDoc,
    WindowSummaryMinimal,
    utc_now_iso,
)
from diagnostic_agent.controller.ticket_api_client import TicketApiClient
from diagnostic_agent.reasoner.base import DiagnosisReasoner

logger = logging.getLogger(__name__)


def _log(event: str, **fields) -> None:
    payload = {"event": event, **fields}
    logger.info("%s", payload)


@dataclass
class WorkerConfig:
    refine_threshold: float = 0.85
    allow_stage2: bool = True


class DiagnosisWorker:
    def __init__(
        self,
        *,
        jobs: "queue.Queue[DiagnosisJob]",
        incident_manager: IncidentManager,
        ticket_client: TicketApiClient,
        retrieval_router: RetrievalRouter,
        reasoner: DiagnosisReasoner,
        cfg: Optional[WorkerConfig] = None,
    ) -> None:
        self.jobs = jobs
        self.incident_manager = incident_manager
        self.ticket_client = ticket_client
        self.retrieval_router = retrieval_router
        self.reasoner = reasoner
        self.cfg = cfg or WorkerConfig()

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, name="diagnosis-worker", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self.jobs.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                self._process(job)
            except Exception as exc:
                _log(
                    "phase6.diagnosis_job_failed",
                    incident_key=list(job.incident_key),
                    ticket_id=job.ticket_id,
                    error=f"{type(exc).__name__}:{exc}",
                )
                try:
                    self.ticket_client.patch_ticket(
                        job.ticket_id,
                        {
                            "diagnosis_status": "FAILED",
                            "diagnosed_at": utc_now_iso(),
                        },
                    )
                except Exception as exc2:
                    _log(
                        "phase6.ticket_patch_failed",
                        ticket_id=job.ticket_id,
                        error=f"{type(exc2).__name__}:{exc2}",
                    )
            finally:
                self.incident_manager.set_in_progress(job.incident_key, False)
                self.incident_manager.set_pending(job.incident_key, False)
                self.jobs.task_done()

    def _process(self, job: DiagnosisJob) -> None:
        ahu_id, fault_type = job.incident_key
        self.incident_manager.set_in_progress(job.incident_key, True)
        st = self.incident_manager.snapshot_state(job.incident_key)
        recent_windows = self.incident_manager.snapshot_windows(job.incident_key)
        ctx = IncidentContext(
            incident_key=job.incident_key,
            ahu_id=ahu_id,
            detected_fault_type=fault_type,
            seen_streak=st.seen_streak,
            clear_streak=st.clear_streak,
            last_seen_at=st.last_seen_at,
            recent_windows=recent_windows,
            stage=1,
        )

        rule_ids = _top_rule_ids(recent_windows)
        symptom_summary = _symptom_summary(recent_windows)
        query = build_retrieval_query(
            detected_fault_type=fault_type,
            rule_ids=rule_ids,
            symptom_summary=symptom_summary,
        )

        # Stage 1 corpora (manuals/past_cases) are global and typically have no `ahu_id`.
        docs1, stats1 = self.retrieval_router.stage1(query=query, where=None)

        # This procedural retrieval pass augments diagnostic grounding with technician-verifiable actions without altering the core reasoning pipeline.
        procedural_docs: list[RetrievedDoc] = []
        try:
            from static_layer.retrievers import retrieve_manuals

            procedural_query = procedural_bias_query(query)
            manuals_raw = retrieve_manuals(
                query=procedural_query,
                top_k=self.retrieval_router.cfg.manuals_top_k,
                where=None,
            )
            for r in manuals_raw or []:
                if not isinstance(r, dict):
                    continue
                procedural_docs.append(
                    RetrievedDoc(
                        corpus="manuals",
                        doc_id=str(r.get("id") or ""),
                        distance=r.get("score"),
                        text=str(r.get("text_snippet") or ""),
                        metadata=dict(r.get("metadata") or {}),
                    )
                )
        except Exception as exc:
            _log(
                "phase6.procedural_manuals_retrieval_failed",
                incident_key=list(job.incident_key),
                error=f"{type(exc).__name__}:{exc}",
            )

        docs_final = merge_and_dedup_docs(docs1, procedural_docs)

        ctx.retrieved_docs = docs_final
        ctx.retrieval_stats = stats1

        _log(
            "phase6.stage1_retrieval",
            incident_key=list(job.incident_key),
            manuals=stats1.manuals_count,
            past_cases=stats1.past_cases_count,
            procedural_manuals_added=max(0, len(docs_final) - len(docs1)),
            coverage_ok=stats1.coverage_ok,
            error=stats1.error,
        )

        calls = 0
        res1 = self.reasoner.diagnose(ctx)
        calls += 1

        refine = False
        if job.allow_refine and self.cfg.allow_stage2:
            if float(res1.confidence) < float(self.cfg.refine_threshold):
                refine = True
            if not stats1.coverage_ok:
                refine = True
            if bool(res1.conflict):
                refine = True

        if refine:
            docs2, stats2 = self.retrieval_router.stage2_case_history(
                query=query, where={"ahu_id": ahu_id} if ahu_id else None
            )
            ctx.stage = 2
            ctx.retrieved_docs = merge_and_dedup_docs(docs_final, docs2)
            # Merge stats shallowly
            merged = RetrievalStats(**stats1.model_dump())
            merged.case_history_count = stats2.case_history_count
            merged.error = stats1.error or stats2.error
            ctx.retrieval_stats = merged

            _log(
                "phase6.stage2_invoked",
                incident_key=list(job.incident_key),
                reason="low_confidence_or_weak_coverage",
                case_history=stats2.case_history_count,
                error=stats2.error,
            )

            res = self.reasoner.diagnose(ctx)
            calls += 1
        else:
            _log(
                "phase6.stage2_skipped",
                incident_key=list(job.incident_key),
                reason="sufficient_confidence_and_coverage",
                confidence=res1.confidence,
            )
            res = res1

        patch = {
            "diagnosis_status": "DIAGNOSED",
            "diagnosed_at": utc_now_iso(),
            "confidence": float(res.confidence),
            "diagnosis_title": res.title,
            "root_cause": res.root_cause,
            "recommended_actions": res.recommended_actions,
            "evidence_ids": res.evidence_ids,
        }
        self.ticket_client.patch_ticket(job.ticket_id, patch)

        self.incident_manager.set_diagnosis_status(job.incident_key, "DIAGNOSED")

        _log(
            "phase6.diagnosis_completed",
            incident_key=list(job.incident_key),
            ticket_id=job.ticket_id,
            confidence=res.confidence,
            reasoner_calls=calls,
        )


def procedural_bias_query(query: str) -> str:
    return (query or "").rstrip() + "\nprocedure inspection steps checklist verify"


def merge_and_dedup_docs(
    primary: list[RetrievedDoc], secondary: list[RetrievedDoc]
) -> list[RetrievedDoc]:
    """Stable merge: keep `primary` order, then append novel docs from `secondary`.

    Dedup key is (corpus, doc_id) to avoid repeated chunks.
    """

    seen: set[tuple[str, str]] = set()
    out: list[RetrievedDoc] = []

    def _add(doc: RetrievedDoc) -> None:
        corpus = str(getattr(doc, "corpus", "") or "")
        doc_id = str(getattr(doc, "doc_id", "") or "")
        if not corpus or not doc_id:
            return
        key = (corpus, doc_id)
        if key in seen:
            return
        seen.add(key)
        out.append(doc)

    for d in primary or []:
        if isinstance(d, RetrievedDoc):
            _add(d)

    for d in secondary or []:
        if isinstance(d, RetrievedDoc):
            _add(d)

    return out


def _top_rule_ids(windows: list[WindowSummaryMinimal]) -> list[str]:
    counts = {}
    for w in windows:
        for a in w.anomalies or []:
            if not isinstance(a, dict):
                continue
            rid = str(a.get("rule_id") or "").strip()
            if not rid:
                continue
            counts[rid] = counts.get(rid, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [r for r, _ in ranked][:5]


def _symptom_summary(windows: list[WindowSummaryMinimal]) -> str:
    if not windows:
        return ""
    # Prefer summary_text if present, otherwise compact anomaly messages.
    for w in reversed(windows):
        if w.summary_text:
            return str(w.summary_text)
    parts: list[str] = []
    for w in windows[-2:]:
        for a in w.anomalies or []:
            if not isinstance(a, dict):
                continue
            msg = a.get("message") or a.get("symptom") or ""
            msg = str(msg).strip()
            if msg:
                parts.append(msg)
    return "; ".join(parts)[:300]
