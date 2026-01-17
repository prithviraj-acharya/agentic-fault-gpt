# app/db/smoke_test_db.py
"""
Smoke test for Tickets DB (SQLite) + repository layer.

Run inside container:
  python -m app.db.smoke_test_db
"""

from __future__ import annotations

import os

from app.db.tickets_repo import TicketRepository


def main() -> None:
    print("== Tickets DB Smoke Test ==")
    print(f"TICKETS_DB_PATH={os.getenv('TICKETS_DB_PATH', '(default)')}")
    print()

    repo = TicketRepository()
    repo.init_db()

    payload = {
        "ticket_id": "smoke-ticket-001",
        "ahu_id": "AHU-SMOKE-1",
        "detected_fault_type": "Smoke test fault",
        "symptom_summary": "Smoke test ticket created via upsert.",
        "diagnosis_status": "DRAFT",
        "review_status": "NONE",
    }

    ticket, created = repo.upsert_ticket(payload)
    print(f"Upsert created={created} ticket_id={ticket.get('ticket_id')}")

    result = repo.list_tickets(filters=None, limit=10, offset=0, include_total=True)
    print(f"Rows: {result.total}")


if __name__ == "__main__":
    main()
