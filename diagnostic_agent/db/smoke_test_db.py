# diagnostic_agent/db/smoke_test_db.py
"""
Smoke test for Tickets DB (SQLite) + repository layer.

Runs an end-to-end flow:
1) init_db
2) create 2 tickets
3) append windows (with idempotency check)
4) set diagnosis
5) update review
6) mark resolved
7) list filtered tickets and print detailed ticket views

Run:
  python -m diagnostic_agent.db.smoke_test_db

Tip (recommended):
  Set a dedicated smoke DB path so you don't mix with real runs:
    Windows PowerShell:
            $env:TICKETS_DB_PATH="data/tickets_smoke.db"
      python -m diagnostic_agent.db.smoke_test_db
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

# Adjust import to your repo structure if needed
from diagnostic_agent.db.repository import TicketRepository


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _json_list_len(value: Any) -> int:
    """
    Returns len(list) if value is a JSON list string or list.
    Safe fallback: returns 0.
    """
    if value is None:
        return 0
    if isinstance(value, list):
        return len(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return len(parsed)
        except Exception:
            return 0
    return 0


def _pretty_json(value: Any) -> str:
    """
    Pretty prints a JSON string/list; otherwise returns str(value).
    """
    if value is None:
        return "null"
    if isinstance(value, list):
        return json.dumps(value, indent=2, ensure_ascii=False)
    if isinstance(value, str):
        s = value.strip()
        # Try to parse JSON; if not JSON, return raw.
        try:
            parsed = json.loads(s)
            return json.dumps(parsed, indent=2, ensure_ascii=False)
        except Exception:
            return value
    return str(value)


def print_ticket(ticket: Dict[str, Any], prefix: str = "") -> None:
    """
    Rich, human-readable ticket dump for debugging and confidence.
    """
    ticket_id = ticket.get("ticket_id", "")
    ticket_ref = ticket.get("ticket_ref") or ticket.get("ticket_no") or ""
    ahu_id = ticket.get("ahu_id", "")
    detected_fault_type = ticket.get("detected_fault_type", "")

    lifecycle = ticket.get("lifecycle_status", "")
    diag_status = ticket.get("diagnosis_status", "")
    review = ticket.get("review_status", "")

    confidence = ticket.get("confidence", None)

    print(f"{prefix}Ticket: {ticket_ref} | {ticket_id}")
    print(f"  AHU: {ahu_id}")
    print(f"  Detected Fault Type: {detected_fault_type}")
    print(f"  Status: lifecycle={lifecycle} diagnosis={diag_status} review={review}")

    if confidence is not None:
        try:
            print(
                f"  Diagnosis Confidence: {float(confidence):.2f} ({float(confidence)*100:.0f}%)"
            )
        except Exception:
            print(f"  Diagnosis Confidence: {confidence}")

    # Timestamps
    print("  Timestamps:")
    print(f"    created_at:   {ticket.get('created_at')}")
    print(f"    last_seen_at: {ticket.get('last_seen_at')}")
    print(f"    diagnosed_at: {ticket.get('diagnosed_at')}")
    print(f"    resolved_at:  {ticket.get('resolved_at')}")
    print(f"    updated_at:   {ticket.get('updated_at')}")

    # Streaming/evidence trail
    window_refs = ticket.get("window_refs", "[]")
    signatures_seen = ticket.get("signatures_seen", "[]")
    evidence_ids = ticket.get("evidence_ids", "[]")

    print("  Evidence Trail:")
    print(f"    window_refs:     { _json_list_len(window_refs) } items")
    print(f"    signatures_seen: { _json_list_len(signatures_seen) } items")
    print(f"    evidence_ids:    { _json_list_len(evidence_ids) } items")
    if ticket.get("last_window_end_ts") is not None:
        print(f"    last_window_end_ts: {ticket.get('last_window_end_ts')}")

    # Diagnosis text fields
    if ticket.get("symptom_summary"):
        print("  Symptom Summary:")
        print(f"    {ticket.get('symptom_summary')}")

    if ticket.get("diagnosis_title"):
        print("  Diagnosis Title:")
        print(f"    {ticket.get('diagnosis_title')}")

    if ticket.get("root_cause"):
        print("  Root Cause:")
        # keep it readable without excessive formatting
        root = str(ticket.get("root_cause"))
        for line in root.splitlines():
            print(f"    {line}")

    if ticket.get("recommended_actions"):
        print("  Recommended Actions (raw/JSON):")
        pretty = _pretty_json(ticket.get("recommended_actions"))
        for line in pretty.splitlines():
            print(f"    {line}")

    if ticket.get("review_notes"):
        print("  Review Notes:")
        print(f"    {ticket.get('review_notes')}")

    print("-" * 72)


def main() -> None:
    print("== Tickets DB Smoke Test ==")
    print(f"TICKETS_DB_PATH={os.getenv('TICKETS_DB_PATH', '(default)')}")
    print()

    repo = TicketRepository()
    repo.init_db()

    # 1) Create two tickets
    t1_id = "ticket-" + os.urandom(4).hex()
    t2_id = "ticket-" + os.urandom(4).hex()

    ticket1 = repo.create_ticket(
        {
            "ticket_id": t1_id,
            "ahu_id": "AHU-1",
            "detected_fault_type": "Filter clogging",
            "symptom_summary": "Supply airflow appears constrained; rising ΔP across filter (simulated).",
        }
    )
    print_ticket(ticket1, prefix="[CREATED] ")

    ticket2 = repo.create_ticket(
        {
            "ticket_id": t2_id,
            "ahu_id": "AHU-2",
            "detected_fault_type": "OA damper stuck",
            "symptom_summary": "OA damper command changes but position remains flat (simulated).",
        }
    )
    print_ticket(ticket2, prefix="[CREATED] ")

    # 2) Append windows (incl. idempotency check)
    ticket1 = repo.append_window(
        ticket_id=t1_id,
        window_id="win-001",
        signature="SIG_FILTER_CLOG_1",
        last_window_end_ts=1730000000,
    )
    print_ticket(ticket1, prefix="[WINDOW APPENDED] ")

    ticket1 = repo.append_window(
        ticket_id=t1_id,
        window_id="win-002",
        signature="SIG_FILTER_CLOG_2",
        last_window_end_ts=1730000300,
    )
    print_ticket(ticket1, prefix="[WINDOW APPENDED] ")

    # Idempotency: append same window again — should NOT duplicate
    ticket1 = repo.append_window(
        ticket_id=t1_id,
        window_id="win-002",
        signature="SIG_FILTER_CLOG_2",
        last_window_end_ts=1730000300,
    )
    print_ticket(ticket1, prefix="[IDEMPOTENCY CHECK] ")

    # 3) Set diagnosis (Phase 7-like payload)
    ticket1 = repo.set_diagnosis(
        ticket_id=t1_id,
        diagnosis_payload={
            "confidence": 0.92,
            "diagnosis_title": "Filter likely clogged/restricted",
            "root_cause": (
                "Observed persistent airflow restriction indicators and repeating signatures "
                "consistent with a loaded filter. Recommend inspection and replacement."
            ),
            "recommended_actions": [
                "Inspect AHU filter bank for visible loading",
                "Replace filters if ΔP exceeds threshold",
                "Verify supply airflow returns to baseline post replacement",
            ],
            "evidence_ids": ["manuals::chunk::12", "past_cases::case::34"],
        },
    )
    print_ticket(ticket1, prefix="[DIAGNOSED] ")

    # 4) Update review (UI action)
    ticket1 = repo.update_review(
        ticket_id=t1_id,
        review_status="APPROVED",
        review_notes="Approved for maintenance. Schedule filter replacement.",
    )
    print_ticket(ticket1, prefix="[REVIEW UPDATED] ")

    # 5) Mark resolved (stream lifecycle ended)
    ticket1 = repo.mark_resolved(ticket_id=t1_id, resolved_at_iso=_now_iso())
    print_ticket(ticket1, prefix="[RESOLVED] ")

    # 6) Filtered list
    filtered = repo.list_tickets(
        filters={"review_status": "APPROVED", "min_confidence": 0.9},
        limit=50,
        offset=0,
    )

    print("\nFiltered tickets (review=APPROVED, confidence>=0.9):\n")
    for t in filtered:
        print_ticket(t)

    print("Smoke test complete ✅")


if __name__ == "__main__":
    main()
