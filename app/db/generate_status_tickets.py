"""app/db/generate_status_tickets.py

Generate a burst of demo tickets that cover *all combinations* of status enums,
spaced a few seconds apart, so you can watch the frontend polling update.

This writes to the tickets API (backend running in Docker is the only SQLite writer).

Examples:
    # Create one ticket per (lifecycle, diagnosis, review) combination, 2s apart
    python -m app.db.generate_status_tickets --delay 2

    # Delete all demo tickets created by this script (prefix match)
    python -m app.db.generate_status_tickets --cleanup-only

Tip:
    Use a dedicated API URL if needed:
        Windows PowerShell:
            $env:TICKETS_API_URL="http://localhost:8000/api/tickets/upsert"
            python -m app.db.generate_status_tickets --delay 2
"""

from __future__ import annotations

import argparse
import os
import time
import uuid
from datetime import datetime

import httpx

ALLOWED_LIFECYCLE_STATUS = {"OPEN", "RESOLVED"}
ALLOWED_DIAGNOSIS_STATUS = {"DRAFT", "DIAGNOSING", "DIAGNOSED", "FAILED"}
ALLOWED_REVIEW_STATUS = {"NONE", "APPROVED", "REJECTED"}


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat()


def _make_demo_payload(
    *,
    lifecycle_status: str,
    diagnosis_status: str,
    review_status: str,
    index: int,
) -> dict:
    now = _utc_now_iso()
    short = uuid.uuid4().hex[:6]

    # Make tickets easy to spot in the UI.
    title = f"Status Demo {index:02d}"
    combo = f"{lifecycle_status}/{diagnosis_status}/{review_status}"

    payload: dict = {
        "ticket_id": f"status-demo-{short}",
        "ahu_id": f"AHU-DEMO-{index % 4 + 1}",
        "detected_fault_type": f"STATUS_DEMO {combo}",
        "symptom_summary": f"{title} — {combo}",
        "lifecycle_status": lifecycle_status,
        "diagnosis_status": diagnosis_status,
        "review_status": review_status,
        "created_at": now,
        "last_seen_at": now,
        "updated_at": now,
    }

    if diagnosis_status == "DIAGNOSED":
        payload.update(
            {
                "diagnosed_at": now,
                "confidence": 0.9,
                "diagnosis_title": f"Diagnosed ({combo})",
                "root_cause": "Demo root cause text.",
                # Send JSON-native types; the backend repo will serialize to SQLite.
                "recommended_actions": [
                    "Demo action 1",
                    "Demo action 2",
                ],
                "evidence_ids": ["demo::evidence::1"],
            }
        )

    if diagnosis_status == "FAILED":
        payload.update(
            {
                "confidence": 0.0,
                "diagnosis_title": f"Diagnosis failed ({combo})",
            }
        )

    if lifecycle_status == "RESOLVED":
        payload["resolved_at"] = now

    if review_status == "APPROVED":
        payload["review_notes"] = "Approved (demo)."
    elif review_status == "REJECTED":
        payload["review_notes"] = "Rejected (demo)."
    else:
        payload["review_notes"] = None

    return payload


def _cleanup_demo_tickets(prefix: str) -> int:
    print("Cleanup is not supported via API. Skipping.")
    return 0


def _post_ticket(api_url: str, payload: dict) -> dict:
    with httpx.Client(timeout=10.0) as client:
        resp = client.post(api_url, json=payload)
        resp.raise_for_status()
        return resp.json()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate demo tickets for every status combination (spaced apart)."
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Seconds to wait between writes (default: 2.0)",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default="status-demo-",
        help="ticket_id prefix used for created demo records (default: status-demo-)",
    )
    parser.add_argument(
        "--cleanup-only",
        action="store_true",
        help="Delete demo tickets (by prefix) and exit.",
    )
    parser.add_argument(
        "--cleanup-after",
        type=float,
        default=None,
        help="If set, wait N seconds after creating tickets, then delete them.",
    )
    parser.add_argument(
        "--api-url",
        type=str,
        default=os.getenv(
            "TICKETS_API_URL", "http://localhost:8000/api/tickets/upsert"
        ),
        help="Tickets upsert API endpoint.",
    )

    args = parser.parse_args()

    api_url = str(args.api_url)

    if args.cleanup_only:
        deleted = _cleanup_demo_tickets(args.prefix)
        print("== Cleanup Demo Tickets ==")
        print(f"TICKETS_API_URL={api_url}")
        print(f"Deleted rows: {deleted} (ticket_id LIKE '{args.prefix}%')")
        return

    lifecycle_values = sorted(ALLOWED_LIFECYCLE_STATUS)
    diagnosis_values = sorted(ALLOWED_DIAGNOSIS_STATUS)
    review_values = sorted(ALLOWED_REVIEW_STATUS)

    combos: list[tuple[str, str, str]] = [
        (lc, ds, rs)
        for lc in lifecycle_values
        for ds in diagnosis_values
        for rs in review_values
    ]

    print("== Generate Status Demo Tickets ==")
    print(f"TICKETS_API_URL={api_url}")
    print(
        f"Combos: {len(combos)} (lifecycle={lifecycle_values}, diagnosis={diagnosis_values}, review={review_values})"
    )
    print(f"Delay: {args.delay}s")
    print()

    for idx, (lc, ds, rs) in enumerate(combos, start=1):
        payload = _make_demo_payload(
            lifecycle_status=lc,
            diagnosis_status=ds,
            review_status=rs,
            index=idx,
        )
        payload["ticket_id"] = f"{args.prefix}{uuid.uuid4().hex[:6]}"
        t = _post_ticket(api_url, payload)
        print(
            f"[{idx:02d}/{len(combos)}] upserted id={t.get('ticket_id')} created={t.get('created')} status={lc}/{ds}/{rs}"
        )
        time.sleep(args.delay)

    print("\nDone. (Created demo tickets.)")

    if args.cleanup_after is not None:
        seconds = float(args.cleanup_after)
        if seconds > 0:
            print(f"Waiting {seconds:.1f}s before cleanup…")
            time.sleep(seconds)
        deleted = _cleanup_demo_tickets(args.prefix)
        print(
            f"Cleanup complete. Deleted rows: {deleted} (ticket_id LIKE '{args.prefix}%')"
        )


if __name__ == "__main__":
    main()
