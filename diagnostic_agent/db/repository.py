from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Iterable

from . import db

ALLOWED_LIFECYCLE_STATUS = {"OPEN", "RESOLVED"}
ALLOWED_DIAGNOSIS_STATUS = {"DRAFT", "DIAGNOSING", "DIAGNOSED", "FAILED"}
ALLOWED_REVIEW_STATUS = {"NONE", "APPROVED", "REJECTED"}

TICKET_COLUMNS = {
    "ticket_id",
    "ticket_ref",
    "ahu_id",
    "incident_key",
    "detected_fault_type",
    "lifecycle_status",
    "diagnosis_status",
    "confidence",
    "diagnosis_title",
    "root_cause",
    "recommended_actions",
    "evidence_ids",
    "review_status",
    "review_notes",
    "symptom_summary",
    "window_refs",
    "signatures_seen",
    "last_window_end_ts",
    "created_at",
    "last_seen_at",
    "diagnosed_at",
    "resolved_at",
    "updated_at",
}


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat()


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def _load_json_list(raw: str | None, field: str) -> list[Any]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON list in {field}") from exc
    if not isinstance(value, list):
        raise ValueError(f"Expected JSON list in {field}")
    return value


def _ensure_status(value: str, allowed: set[str], field: str) -> None:
    if value not in allowed:
        raise ValueError(f"Invalid {field}: {value}")


class TicketRepository:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or db.get_db_path()

    def _connect(self) -> sqlite3.Connection:
        conn = db.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _generate_ticket_ref(self) -> str:
        # Keep it short and UI-friendly while ensuring uniqueness.
        for _ in range(10):
            candidate = f"TCK-{uuid.uuid4().hex[:4].upper()}"
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT 1 FROM tickets WHERE ticket_ref = ?",
                    (candidate,),
                ).fetchone()
            if row is None:
                return candidate
        raise RuntimeError("Unable to generate unique ticket_ref")

    def init_db(self) -> None:
        db.init_db(self._db_path)

    def create_ticket(self, ticket: dict[str, Any]) -> dict[str, Any]:
        missing = [key for key in ("ahu_id", "detected_fault_type") if not ticket.get(key)]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")

        now = _utc_now_iso()
        payload = dict(ticket)
        payload.setdefault("ticket_id", str(uuid.uuid4()))
        payload.setdefault("ticket_ref", self._generate_ticket_ref())
        payload.setdefault("incident_key", f"{payload['ahu_id']}|{payload['detected_fault_type']}")
        payload.setdefault("lifecycle_status", "OPEN")
        payload.setdefault("diagnosis_status", "DRAFT")
        payload.setdefault("review_status", "NONE")
        payload.setdefault("window_refs", "[]")
        payload.setdefault("signatures_seen", "[]")
        payload.setdefault("evidence_ids", "[]")
        payload.setdefault("created_at", now)
        payload.setdefault("last_seen_at", now)
        payload.setdefault("updated_at", now)

        if "lifecycle_status" in payload:
            _ensure_status(payload["lifecycle_status"], ALLOWED_LIFECYCLE_STATUS, "lifecycle_status")
        if "diagnosis_status" in payload:
            _ensure_status(payload["diagnosis_status"], ALLOWED_DIAGNOSIS_STATUS, "diagnosis_status")
        if "review_status" in payload:
            _ensure_status(payload["review_status"], ALLOWED_REVIEW_STATUS, "review_status")

        columns = [col for col in payload.keys() if col in TICKET_COLUMNS]
        if not columns:
            raise ValueError("No valid ticket fields provided")
        values = [payload[col] for col in columns]
        placeholders = ", ".join(["?"] * len(columns))
        column_sql = ", ".join(columns)
        sql = f"INSERT INTO tickets ({column_sql}) VALUES ({placeholders})"

        with self._connect() as conn:
            conn.execute(sql, values)
        return self.get_ticket(payload["ticket_id"])  # type: ignore[return-value]

    def get_ticket(self, ticket_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)).fetchone()
        return _row_to_dict(row)

    def list_tickets(
        self, filters: dict[str, Any], limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        where_clauses: list[str] = []
        params: list[Any] = []

        if not filters:
            filters = {}

        if "lifecycle_status" in filters:
            _ensure_status(filters["lifecycle_status"], ALLOWED_LIFECYCLE_STATUS, "lifecycle_status")
            where_clauses.append("lifecycle_status = ?")
            params.append(filters["lifecycle_status"])
        if "diagnosis_status" in filters:
            _ensure_status(filters["diagnosis_status"], ALLOWED_DIAGNOSIS_STATUS, "diagnosis_status")
            where_clauses.append("diagnosis_status = ?")
            params.append(filters["diagnosis_status"])
        if "review_status" in filters:
            _ensure_status(filters["review_status"], ALLOWED_REVIEW_STATUS, "review_status")
            where_clauses.append("review_status = ?")
            params.append(filters["review_status"])
        if "ahu_id" in filters:
            where_clauses.append("ahu_id = ?")
            params.append(filters["ahu_id"])
        if "detected_fault_type" in filters:
            where_clauses.append("detected_fault_type = ?")
            params.append(filters["detected_fault_type"])
        if "min_confidence" in filters and filters["min_confidence"] is not None:
            where_clauses.append("confidence >= ?")
            params.append(filters["min_confidence"])
        if "q" in filters and filters["q"]:
            q = f"%{filters['q']}%"
            where_clauses.append(
                "(ticket_id LIKE ? OR detected_fault_type LIKE ? OR diagnosis_title LIKE ?)"
            )
            params.extend([q, q, q])

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        sql = f"SELECT * FROM tickets {where_sql} ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def update_ticket(self, ticket_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        if "ticket_id" in patch:
            raise ValueError("ticket_id cannot be updated")

        for field in ("lifecycle_status", "diagnosis_status", "review_status"):
            if field in patch and patch[field] is not None:
                if field == "lifecycle_status":
                    _ensure_status(patch[field], ALLOWED_LIFECYCLE_STATUS, field)
                elif field == "diagnosis_status":
                    _ensure_status(patch[field], ALLOWED_DIAGNOSIS_STATUS, field)
                else:
                    _ensure_status(patch[field], ALLOWED_REVIEW_STATUS, field)

        update_fields = {k: v for k, v in patch.items() if k in TICKET_COLUMNS}
        now = _utc_now_iso()
        update_fields["updated_at"] = now

        if not update_fields:
            raise ValueError("No valid fields to update")

        set_clause = ", ".join([f"{key} = ?" for key in update_fields.keys()])
        params = list(update_fields.values()) + [ticket_id]
        sql = f"UPDATE tickets SET {set_clause} WHERE ticket_id = ?"

        with self._connect() as conn:
            cur = conn.execute(sql, params)
            if cur.rowcount == 0:
                raise KeyError(f"Ticket not found: {ticket_id}")
        return self.get_ticket(ticket_id)  # type: ignore[return-value]

    def update_review(
        self, ticket_id: str, review_status: str, review_notes: str | None = None
    ) -> dict[str, Any]:
        _ensure_status(review_status, ALLOWED_REVIEW_STATUS, "review_status")
        patch = {"review_status": review_status, "review_notes": review_notes}
        return self.update_ticket(ticket_id, patch)

    def append_window(
        self,
        ticket_id: str,
        window_id: str,
        signature: str | None = None,
        last_window_end_ts: int | None = None,
    ) -> dict[str, Any]:
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            raise KeyError(f"Ticket not found: {ticket_id}")

        window_refs = _load_json_list(ticket.get("window_refs"), "window_refs")
        signatures_seen = _load_json_list(ticket.get("signatures_seen"), "signatures_seen")

        if window_id not in window_refs:
            window_refs.append(window_id)
        if signature and signature not in signatures_seen:
            signatures_seen.append(signature)

        now = _utc_now_iso()
        patch: dict[str, Any] = {
            "window_refs": json.dumps(window_refs),
            "signatures_seen": json.dumps(signatures_seen),
            "last_seen_at": now,
            "updated_at": now,
        }
        if last_window_end_ts is not None:
            patch["last_window_end_ts"] = last_window_end_ts

        return self.update_ticket(ticket_id, patch)

    def set_diagnosis(self, ticket_id: str, diagnosis_payload: dict[str, Any]) -> dict[str, Any]:
        now = _utc_now_iso()
        patch: dict[str, Any] = {
            "diagnosis_status": "DIAGNOSED",
            "diagnosed_at": now,
            "updated_at": now,
        }

        if "confidence" in diagnosis_payload:
            confidence = diagnosis_payload["confidence"]
            if confidence is not None and not (0.0 <= confidence <= 1.0):
                raise ValueError("confidence must be between 0 and 1")
            patch["confidence"] = confidence
        if "diagnosis_title" in diagnosis_payload:
            patch["diagnosis_title"] = diagnosis_payload["diagnosis_title"]
        if "root_cause" in diagnosis_payload:
            patch["root_cause"] = diagnosis_payload["root_cause"]
        if "recommended_actions" in diagnosis_payload:
            value = diagnosis_payload["recommended_actions"]
            if value is not None and not isinstance(value, str):
                value = json.dumps(value)
            patch["recommended_actions"] = value
        if "evidence_ids" in diagnosis_payload:
            value = diagnosis_payload["evidence_ids"]
            if value is not None and not isinstance(value, str):
                value = json.dumps(value)
            patch["evidence_ids"] = value

        return self.update_ticket(ticket_id, patch)

    def mark_resolved(self, ticket_id: str, resolved_at_iso: str | None = None) -> dict[str, Any]:
        now = _utc_now_iso()
        patch = {
            "lifecycle_status": "RESOLVED",
            "resolved_at": resolved_at_iso or now,
            "updated_at": now,
        }
        return self.update_ticket(ticket_id, patch)
