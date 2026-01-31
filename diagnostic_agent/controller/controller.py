from __future__ import annotations

import json
import logging
import os
import queue
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Set

from diagnostic_agent.controller.diagnosis_worker import DiagnosisWorker, WorkerConfig
from diagnostic_agent.controller.fault_type_resolver import FaultTypeResolver
from diagnostic_agent.controller.incident_manager import IncidentManager
from diagnostic_agent.controller.retrieval_router import (
    RetrievalRouter,
    RetrievalRouterConfig,
)
from diagnostic_agent.controller.schemas import (
    DiagnosisJob,
    IncidentKey,
    WindowSummaryMinimal,
    utc_now_iso,
)
from diagnostic_agent.controller.ticket_api_client import TicketApiClient
from diagnostic_agent.reasoner.base import DiagnosisReasoner

logger = logging.getLogger(__name__)


def _log(event: str, **fields) -> None:
    payload = {"event": event, **fields}
    logger.info("%s", payload)


OpenAIMode = Literal["cheap", "strong"]


def _parse_openai_mode(raw: str) -> Optional[OpenAIMode]:
    v = (raw or "").strip().lower()
    if v == "cheap":
        return "cheap"
    if v == "strong":
        return "strong"
    return None


@dataclass
class Phase6Config:
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic: str = "window_summaries"
    kafka_group_id: str = "phase6-controller"
    kafka_from_beginning: bool = True

    api_base_url: str = "http://localhost:8000/api"

    n_trigger: int = 2
    k_clear_windows: int = 3

    poll_timeout_s: float = 0.5

    # Confidence threshold below which we try an additional refinement pass.
    # Interpreted as a fraction in [0, 1].
    refine_threshold: float = 0.50


def load_phase6_config() -> Phase6Config:
    default_cfg = Phase6Config()

    def _env(name: str, default: str) -> str:
        v = os.getenv(name)
        return default if v is None else str(v)

    def _env_int(name: str, default: int) -> int:
        v = os.getenv(name)
        try:
            return int(v) if v is not None else int(default)
        except Exception:
            return int(default)

    def _env_bool(name: str, default: bool) -> bool:
        v = os.getenv(name)
        if v is None:
            return bool(default)
        return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}

    def _env_float(name: str, default: float) -> float:
        v = os.getenv(name)
        if v is None:
            return float(default)
        try:
            parsed = float(str(v).strip())
        except Exception:
            return float(default)

        # Convenience: allow percent-like values (e.g., 50 -> 0.50)
        if parsed > 1.0:
            parsed = parsed / 100.0

        # Clamp to [0, 1]
        if parsed < 0.0:
            return 0.0
        if parsed > 1.0:
            return 1.0
        return parsed

    return Phase6Config(
        kafka_bootstrap_servers=_env("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        kafka_topic=_env("PHASE6_KAFKA_WINDOW_TOPIC", "window_summaries"),
        kafka_group_id=_env("PHASE6_KAFKA_GROUP_ID", "phase6-controller"),
        kafka_from_beginning=_env_bool("PHASE6_KAFKA_FROM_BEGINNING", True),
        api_base_url=_env("PHASE6_TICKETS_API_BASE_URL", "http://localhost:8000/api"),
        n_trigger=_env_int("PHASE6_N_TRIGGER", 2),
        k_clear_windows=_env_int("PHASE6_K_CLEAR_WINDOWS", 3),
        poll_timeout_s=float(_env("PHASE6_POLL_TIMEOUT_S", "0.5")),
        refine_threshold=_env_float(
            "PHASE6_REFINE_THRESHOLD", default_cfg.refine_threshold
        ),
    )


class Phase6Controller:
    def __init__(
        self, *, reasoner: DiagnosisReasoner, cfg: Optional[Phase6Config] = None
    ) -> None:
        self.cfg = cfg or load_phase6_config()

        self.fault_resolver = FaultTypeResolver(ignore_unknown=True)
        self.incidents = IncidentManager(cache_windows=2)
        self.ticket_client = TicketApiClient(base_url=self.cfg.api_base_url)
        self.retrieval_router = RetrievalRouter(RetrievalRouterConfig())

        self.jobs: "queue.Queue[DiagnosisJob]" = queue.Queue()
        self.worker = DiagnosisWorker(
            jobs=self.jobs,
            incident_manager=self.incidents,
            ticket_client=self.ticket_client,
            retrieval_router=self.retrieval_router,
            reasoner=reasoner,
            cfg=WorkerConfig(refine_threshold=self.cfg.refine_threshold),
        )

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.worker.start()
        self._thread = threading.Thread(
            target=self._run, name="phase6-controller", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.worker.stop()

    def _run(self) -> None:
        try:
            from telemetry_pipeline.consumer import iter_kafka_events_raw
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "Kafka consumption requires telemetry_pipeline.consumer"
            ) from exc

        for raw in iter_kafka_events_raw(
            bootstrap_servers=self.cfg.kafka_bootstrap_servers,
            topic=self.cfg.kafka_topic,
            group_id=self.cfg.kafka_group_id,
            from_beginning=self.cfg.kafka_from_beginning,
            poll_timeout_s=self.cfg.poll_timeout_s,
            idle_timeout_s=None,
        ):
            if self._stop.is_set():
                return
            if not isinstance(raw, dict):
                continue
            self.handle_window_summary(raw)

    def handle_window_summary(self, raw: Dict[str, Any]) -> None:
        ahu_id = str(raw.get("ahu_id") or "").strip()
        if not ahu_id:
            return

        window = WindowSummaryMinimal(
            ahu_id=ahu_id,
            window_id=str(raw.get("window_id") or "") or None,
            time=raw.get("time") if isinstance(raw.get("time"), dict) else None,
            anomalies=[a for a in (raw.get("anomalies") or []) if isinstance(a, dict)],
            signature=str(raw.get("signature") or "") or None,
            summary_text=str(raw.get("text_summary") or raw.get("summary_text") or "")
            or None,
        )

        fault_types = self.fault_resolver.resolve_fault_types(raw)
        now_iso = utc_now_iso()

        if not fault_types:
            # Update clear streaks for all known incidents for this AHU.
            self._update_absence(ahu_id)
            return

        # Mark seen incidents
        for ft in sorted(fault_types):
            key: IncidentKey = (ahu_id, ft)
            st = self.incidents.mark_seen(key, window, now_iso=now_iso)

            ticket = None
            if not st.ticket_id:
                try:
                    ticket = self.ticket_client.get_active_ticket(
                        ahu_id=ahu_id, detected_fault_type=ft
                    )
                except Exception as exc:
                    _log(
                        "phase6.ticket_lookup_failed",
                        incident_key=[ahu_id, ft],
                        error=f"{type(exc).__name__}:{exc}",
                    )
                    ticket = None

                if ticket and isinstance(ticket, dict):
                    ticket_id = str(ticket.get("ticket_id") or "")
                    if ticket_id:
                        self.incidents.set_ticket(
                            key,
                            ticket_id=ticket_id,
                            diagnosis_status=str(
                                ticket.get("diagnosis_status") or "DRAFT"
                            ),
                            occurrence_count=int(ticket.get("occurrence_count") or 0),
                        )

            if not st.ticket_id:
                payload = {
                    "ahu_id": ahu_id,
                    "detected_fault_type": ft,
                    "lifecycle_status": "OPEN",
                    "diagnosis_status": "DRAFT",
                    "review_status": "NONE",
                    "last_seen_at": now_iso,
                    "occurrence_count": 0,
                    "symptom_summary": window.summary_text,
                    "last_window_id": window.window_id,
                }
                if st.seen_streak >= int(self.cfg.n_trigger):
                    created = self.ticket_client.create_ticket(payload)
                    ticket_id = str(created.get("ticket_id") or "")
                    self.incidents.set_ticket(
                        key,
                        ticket_id=ticket_id,
                        diagnosis_status=str(created.get("diagnosis_status") or "DRAFT"),
                        occurrence_count=int(created.get("occurrence_count") or 0),
                    )
                    _log(
                        "phase6.ticket_created",
                        incident_key=[ahu_id, ft],
                        ticket_id=ticket_id,
                    )

            # Update ticket each time incident seen
            st = self.incidents.get(key)
            new_count = self.incidents.bump_occurrence(key, 1)

            # Track evidence refs (best-effort; backend stores JSON)
            window_refs = [
                w.window_id for w in self.incidents.snapshot_windows(key) if w.window_id
            ]
            signatures = [
                w.signature for w in self.incidents.snapshot_windows(key) if w.signature
            ]
            patch = {
                "lifecycle_status": "OPEN",
                "last_seen_at": now_iso,
                "occurrence_count": new_count,
                "last_window_id": window.window_id,
                "window_refs": window_refs,
                "signatures_seen": signatures,
                "symptom_summary": window.summary_text,
            }
            try:
                self.ticket_client.patch_ticket(st.ticket_id, patch)  # type: ignore[arg-type]
                _log(
                    "phase6.ticket_updated",
                    incident_key=[ahu_id, ft],
                    ticket_id=st.ticket_id,
                    occurrence_count=new_count,
                )
            except Exception as exc:
                _log(
                    "phase6.ticket_update_failed",
                    incident_key=[ahu_id, ft],
                    ticket_id=st.ticket_id,
                    error=f"{type(exc).__name__}:{exc}",
                )

            # Trigger diagnosis exactly once per episode
            self._maybe_trigger_diagnosis(key)

        # Also update absences for incidents of this AHU not present in this window
        self._update_absence(ahu_id, present_fault_types=fault_types)

    def _update_absence(
        self, ahu_id: str, present_fault_types: Optional[Set[str]] = None
    ) -> None:
        present = set(present_fault_types or set())
        for key in self.incidents.active_keys():
            k_ahu, k_ft = key
            if k_ahu != ahu_id:
                continue
            if k_ft in present:
                continue

            st = self.incidents.mark_not_seen(key)
            if st is None or not st.ticket_id:
                continue

            if st.clear_streak >= int(self.cfg.k_clear_windows):
                if bool(st.pending) or bool(st.in_progress):
                    _log(
                        "phase6.ticket_resolve_delayed",
                        incident_key=[k_ahu, k_ft],
                        ticket_id=st.ticket_id,
                        reason="pending_or_in_progress",
                        clear_streak=st.clear_streak,
                    )
                    continue
                try:
                    self.ticket_client.patch_ticket(
                        st.ticket_id,
                        {
                            "lifecycle_status": "RESOLVED",
                            "resolved_at": utc_now_iso(),
                        },
                    )
                    _log(
                        "phase6.ticket_resolved",
                        incident_key=[k_ahu, k_ft],
                        ticket_id=st.ticket_id,
                    )
                except Exception as exc:
                    _log(
                        "phase6.ticket_resolve_failed",
                        incident_key=[k_ahu, k_ft],
                        ticket_id=st.ticket_id,
                        error=f"{type(exc).__name__}:{exc}",
                    )
                finally:
                    self.incidents.reset_episode(key)

    def _maybe_trigger_diagnosis(self, key: IncidentKey) -> None:
        st = self.incidents.get(key)
        if not st.ticket_id:
            return

        force_diagnose = str(
            os.getenv("PHASE6_FORCE_DIAGNOSE") or ""
        ).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        if st.pending or st.in_progress:
            _log(
                "phase6.diagnosis_skipped",
                incident_key=list(key),
                reason="pending_or_in_progress",
            )
            return

        if st.seen_streak < int(self.cfg.n_trigger):
            _log(
                "phase6.diagnosis_skipped",
                incident_key=list(key),
                reason="seen_streak_below_threshold",
                seen_streak=st.seen_streak,
            )
            return

        if str(st.diagnosis_status) != "DRAFT" and not force_diagnose:
            _log(
                "phase6.diagnosis_skipped",
                incident_key=list(key),
                reason="ticket_not_in_draft",
                diagnosis_status=st.diagnosis_status,
            )
            return

        if force_diagnose and str(st.diagnosis_status) != "DRAFT":
            _log(
                "phase6.diagnosis_forced",
                incident_key=list(key),
                ticket_id=st.ticket_id,
                previous_status=str(st.diagnosis_status),
            )

        try:
            self.ticket_client.patch_ticket(
                st.ticket_id, {"diagnosis_status": "DIAGNOSING"}
            )
            self.incidents.set_diagnosis_status(key, "DIAGNOSING")
        except Exception as exc:
            _log(
                "phase6.diagnosis_trigger_failed",
                incident_key=list(key),
                ticket_id=st.ticket_id,
                error=f"{type(exc).__name__}:{exc}",
            )
            return

        job = DiagnosisJob(
            incident_key=key, ticket_id=st.ticket_id, stage=1, allow_refine=True
        )
        self.incidents.set_pending(key, True)
        self.jobs.put(job)
        _log(
            "phase6.diagnosis_triggered", incident_key=list(key), ticket_id=st.ticket_id
        )


def setup_logging() -> None:
    level = os.getenv("PHASE6_LOG_LEVEL", "INFO").upper().strip()
    log_level = getattr(logging, level, logging.INFO)
    fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"

    handlers: list[logging.Handler] = [logging.StreamHandler(stream=sys.stdout)]

    log_file = (os.getenv("PHASE6_LOG_FILE") or "").strip()
    if log_file:
        try:
            p = Path(log_file)
            if p.parent:
                p.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(p, encoding="utf-8"))
        except Exception as exc:
            # Fall back to stdout only if file logging can't be initialized.
            logging.getLogger(__name__).warning(
                "Failed to initialize PHASE6_LOG_FILE=%r: %s", log_file, exc
            )

    logging.basicConfig(level=log_level, format=fmt, handlers=handlers, force=True)

    # httpx can be very chatty at INFO (e.g., "HTTP Request: POST ...").
    # Keep those logs off by default; our structured trace logs are more useful.
    httpx_level_name = os.getenv("PHASE6_HTTPX_LOG_LEVEL", "WARNING").upper().strip()
    httpx_level = getattr(logging, httpx_level_name, logging.WARNING)
    logging.getLogger("httpx").setLevel(httpx_level)
    logging.getLogger("httpcore").setLevel(httpx_level)


def main() -> None:  # pragma: no cover
    setup_logging()

    # Default stays mock for safety/local-dev; enable OpenAI explicitly via env.
    # - PHASE6_REASONER=mock|openai
    # - PHASE6_OPENAI_MODE=cheap|strong (default: cheap)
    # - PHASE6_OPENAI_MODEL=<explicit override>
    # - PHASE6_OPENAI_TIMEOUT_S=<seconds>
    reasoner_kind = (os.getenv("PHASE6_REASONER") or "mock").strip().lower()
    openai_mode = _parse_openai_mode(os.getenv("PHASE6_OPENAI_MODE") or "cheap")
    openai_model = (os.getenv("PHASE6_OPENAI_MODEL") or "").strip() or None
    try:
        timeout_s = float((os.getenv("PHASE6_OPENAI_TIMEOUT_S") or "30").strip())
    except Exception:
        timeout_s = 30.0

    if reasoner_kind == "openai":
        from diagnostic_agent.reasoner.openai_reasoner import OpenAIReasoner

        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("PHASE6_REASONER=openai requires OPENAI_API_KEY")

        reasoner = OpenAIReasoner(mode=openai_mode, timeout_s=timeout_s)
        if openai_model:
            reasoner.model = str(openai_model)
    else:
        from diagnostic_agent.reasoner.mock_reasoner import MockReasoner

        reasoner = MockReasoner()

    controller = Phase6Controller(reasoner=reasoner)  # type: ignore[arg-type]
    _log("phase6.controller_start", cfg=controller.cfg.__dict__)
    controller.start()

    try:
        while True:
            threading.Event().wait(1.0)
    except KeyboardInterrupt:
        _log("phase6.controller_stop")
        controller.stop()


if __name__ == "__main__":  # pragma: no cover
    main()
