from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from app.db import tickets_db

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
    "occurrence_count",
    "diagnosis_title",
    "root_cause",
    "recommended_actions",
    "evidence_ids",
    "review_status",
    "review_notes",
    "symptom_summary",
    "window_refs",
    "signatures_seen",
    "last_window_id",
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


def _ensure_status(value: str, allowed: set[str], field: str) -> None:
    if value not in allowed:
        raise ValueError(f"Invalid {field}: {value}")


def _safe_like(value: str) -> str:
    # SQLite LIKE wildcards: %, _. Escape char is backslash.
    s = str(value)
    s = s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return s


def _json_dump_if_needed(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value)


@dataclass(frozen=True)
class TicketListResult:
    items: list[dict[str, Any]]
    total: int


class TicketRepository:
    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or tickets_db.get_db_path()

    def _connect(self) -> sqlite3.Connection:
        conn = tickets_db.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _generate_ticket_ref(self, conn: sqlite3.Connection) -> str:
        for _ in range(10):
            candidate = f"TCK-{uuid.uuid4().hex[:4].upper()}"
            row = conn.execute(
                "SELECT 1 FROM tickets WHERE ticket_ref = ?",
                (candidate,),
            ).fetchone()
            if row is None:
                return candidate
        raise RuntimeError("Unable to generate unique ticket_ref")

    def init_db(self) -> None:
        with self._connect():
            pass

    def get_ticket(self, ticket_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tickets WHERE ticket_id = ?",
                (ticket_id,),
            ).fetchone()
        return _row_to_dict(row)

    def get_ticket_by_ref(self, ticket_ref: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM tickets WHERE ticket_ref = ?",
                (ticket_ref,),
            ).fetchone()
        return _row_to_dict(row)

    def list_tickets(
        self,
        filters: dict[str, Any] | None,
        limit: int = 100,
        offset: int = 0,
        sort: str = "updated_at",
        order: str = "desc",
        include_total: bool = True,
    ) -> TicketListResult:
        where_clauses: list[str] = []
        params: list[Any] = []

        f = filters or {}

        if "lifecycle_status" in f and f["lifecycle_status"]:
            _ensure_status(
                str(f["lifecycle_status"]), ALLOWED_LIFECYCLE_STATUS, "lifecycle_status"
            )
            where_clauses.append("lifecycle_status = ?")
            params.append(str(f["lifecycle_status"]))

        if "diagnosis_status" in f and f["diagnosis_status"]:
            _ensure_status(
                str(f["diagnosis_status"]), ALLOWED_DIAGNOSIS_STATUS, "diagnosis_status"
            )
            where_clauses.append("diagnosis_status = ?")
            params.append(str(f["diagnosis_status"]))

        if "review_status" in f and f["review_status"]:
            _ensure_status(
                str(f["review_status"]), ALLOWED_REVIEW_STATUS, "review_status"
            )
            where_clauses.append("review_status = ?")
            params.append(str(f["review_status"]))

        if "ahu_id" in f and f["ahu_id"]:
            where_clauses.append("ahu_id = ?")
            params.append(str(f["ahu_id"]))

        detected_fault_type = f.get("detected_fault_type") or f.get("fault_type")
        if detected_fault_type:
            where_clauses.append("detected_fault_type = ?")
            params.append(str(detected_fault_type))

        if "min_confidence" in f and f["min_confidence"] is not None:
            where_clauses.append("confidence >= ?")
            params.append(float(f["min_confidence"]))

        if "q" in f and f["q"]:
            q_raw = _safe_like(str(f["q"]))
            q = f"%{q_raw}%"
            where_clauses.append(
                "(ticket_ref LIKE ? ESCAPE '\\' OR ticket_id LIKE ? ESCAPE '\\' OR detected_fault_type LIKE ? ESCAPE '\\' OR diagnosis_title LIKE ? ESCAPE '\\')"
            )
            params.extend([q, q, q, q])

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        allowed_sort = {
            "updated_at",
            "created_at",
            "last_seen_at",
            "diagnosed_at",
            "resolved_at",
            "confidence",
            "ticket_ref",
        }
        sort_col = sort if sort in allowed_sort else "updated_at"
        order_sql = "ASC" if str(order).lower() == "asc" else "DESC"

        lim = max(1, int(limit))
        off = max(0, int(offset))

        total = -1
        if include_total:
            with self._connect() as conn:
                row = conn.execute(
                    f"SELECT COUNT(1) AS c FROM tickets {where_sql}",
                    params,
                ).fetchone()
                total = int(row["c"]) if row is not None else 0

        sql = f"SELECT * FROM tickets {where_sql} ORDER BY {sort_col} {order_sql} LIMIT ? OFFSET ?"
        query_params = list(params) + [lim, off]

        with self._connect() as conn:
            rows = conn.execute(sql, query_params).fetchall()
        return TicketListResult(
            items=[dict(r) for r in rows], total=(total if total >= 0 else len(rows))
        )

    def create_ticket(self, ticket: dict[str, Any]) -> dict[str, Any]:
        missing = [
            key for key in ("ahu_id", "detected_fault_type") if not ticket.get(key)
        ]
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(missing)}")

        now = _utc_now_iso()
        payload = dict(ticket)
        payload.setdefault("ticket_id", str(uuid.uuid4()))
        payload.setdefault(
            "incident_key", f"{payload['ahu_id']}|{payload['detected_fault_type']}"
        )
        payload.setdefault("lifecycle_status", "OPEN")
        payload.setdefault("diagnosis_status", "DRAFT")
        payload.setdefault("review_status", "NONE")
        payload.setdefault("occurrence_count", 0)
        payload.setdefault("window_refs", "[]")
        payload.setdefault("signatures_seen", "[]")
        payload.setdefault("evidence_ids", "[]")
        payload.setdefault("created_at", now)
        payload.setdefault("last_seen_at", now)
        payload.setdefault("updated_at", now)

        if "lifecycle_status" in payload:
            _ensure_status(
                payload["lifecycle_status"],
                ALLOWED_LIFECYCLE_STATUS,
                "lifecycle_status",
            )
        if "diagnosis_status" in payload:
            _ensure_status(
                payload["diagnosis_status"],
                ALLOWED_DIAGNOSIS_STATUS,
                "diagnosis_status",
            )
        if "review_status" in payload:
            _ensure_status(
                payload["review_status"], ALLOWED_REVIEW_STATUS, "review_status"
            )

        if "recommended_actions" in payload:
            payload["recommended_actions"] = _json_dump_if_needed(
                payload.get("recommended_actions")
            )
        if "window_refs" in payload:
            payload["window_refs"] = (
                _json_dump_if_needed(payload.get("window_refs")) or "[]"
            )
        if "signatures_seen" in payload:
            payload["signatures_seen"] = (
                _json_dump_if_needed(payload.get("signatures_seen")) or "[]"
            )
        if "evidence_ids" in payload:
            payload["evidence_ids"] = (
                _json_dump_if_needed(payload.get("evidence_ids")) or "[]"
            )

        with self._connect() as conn:
            if not payload.get("ticket_ref"):
                payload["ticket_ref"] = self._generate_ticket_ref(conn)
            columns = [col for col in payload.keys() if col in TICKET_COLUMNS]
            if not columns:
                raise ValueError("No valid ticket fields provided")
            values = [payload[col] for col in columns]
            placeholders = ", ".join(["?"] * len(columns))
            column_sql = ", ".join(columns)
            sql = f"INSERT INTO tickets ({column_sql}) VALUES ({placeholders})"
            conn.execute(sql, values)
        return self.get_ticket(payload["ticket_id"])  # type: ignore[return-value]

    def upsert_ticket(self, ticket: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        ticket_id = ticket.get("ticket_id")
        if not ticket_id:
            raise ValueError("ticket_id is required")

        now = _utc_now_iso()
        created = False

        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM tickets WHERE ticket_id = ?",
                (ticket_id,),
            ).fetchone()

            if exists:
                update_fields = {
                    key: value
                    for key, value in ticket.items()
                    if key in TICKET_COLUMNS
                    and key
                    not in {
                        "ticket_id",
                        "ticket_ref",
                        "incident_key",
                        "created_at",
                    }
                    and value is not None
                }

                if "lifecycle_status" in update_fields:
                    _ensure_status(
                        update_fields["lifecycle_status"],
                        ALLOWED_LIFECYCLE_STATUS,
                        "lifecycle_status",
                    )
                if "diagnosis_status" in update_fields:
                    _ensure_status(
                        update_fields["diagnosis_status"],
                        ALLOWED_DIAGNOSIS_STATUS,
                        "diagnosis_status",
                    )
                if "review_status" in update_fields:
                    _ensure_status(
                        update_fields["review_status"],
                        ALLOWED_REVIEW_STATUS,
                        "review_status",
                    )

                if "recommended_actions" in update_fields:
                    update_fields["recommended_actions"] = _json_dump_if_needed(
                        update_fields["recommended_actions"]
                    )
                if "evidence_ids" in update_fields:
                    update_fields["evidence_ids"] = _json_dump_if_needed(
                        update_fields["evidence_ids"]
                    )
                if "window_refs" in update_fields:
                    update_fields["window_refs"] = (
                        _json_dump_if_needed(update_fields["window_refs"]) or "[]"
                    )
                if "signatures_seen" in update_fields:
                    update_fields["signatures_seen"] = (
                        _json_dump_if_needed(update_fields["signatures_seen"]) or "[]"
                    )

                update_fields["updated_at"] = now

                if update_fields:
                    set_clause = ", ".join(
                        [f"{key} = ?" for key in update_fields.keys()]
                    )
                    params = list(update_fields.values()) + [ticket_id]
                    conn.execute(
                        f"UPDATE tickets SET {set_clause} WHERE ticket_id = ?",
                        params,
                    )
            else:
                payload = dict(ticket)
                missing = [
                    key
                    for key in ("ahu_id", "detected_fault_type")
                    if not payload.get(key)
                ]
                if missing:
                    raise ValueError(f"Missing required fields: {', '.join(missing)}")

                payload.setdefault("ticket_ref", self._generate_ticket_ref(conn))
                payload.setdefault(
                    "incident_key",
                    f"{payload['ahu_id']}|{payload['detected_fault_type']}",
                )
                payload.setdefault("lifecycle_status", "OPEN")
                payload.setdefault("diagnosis_status", "DRAFT")
                payload.setdefault("review_status", "NONE")
                payload.setdefault("occurrence_count", 0)
                payload.setdefault("window_refs", "[]")
                payload.setdefault("signatures_seen", "[]")

                payload["evidence_ids"] = (
                    _json_dump_if_needed(payload.get("evidence_ids")) or "[]"
                )
                payload["recommended_actions"] = _json_dump_if_needed(
                    payload.get("recommended_actions")
                )
                payload["window_refs"] = (
                    _json_dump_if_needed(payload.get("window_refs")) or "[]"
                )
                payload["signatures_seen"] = (
                    _json_dump_if_needed(payload.get("signatures_seen")) or "[]"
                )

                payload.setdefault("created_at", now)
                payload.setdefault("last_seen_at", payload.get("created_at", now))
                payload.setdefault("updated_at", payload.get("created_at", now))

                if "lifecycle_status" in payload:
                    _ensure_status(
                        payload["lifecycle_status"],
                        ALLOWED_LIFECYCLE_STATUS,
                        "lifecycle_status",
                    )
                if "diagnosis_status" in payload:
                    _ensure_status(
                        payload["diagnosis_status"],
                        ALLOWED_DIAGNOSIS_STATUS,
                        "diagnosis_status",
                    )
                if "review_status" in payload:
                    _ensure_status(
                        payload["review_status"], ALLOWED_REVIEW_STATUS, "review_status"
                    )

                columns = [col for col in payload.keys() if col in TICKET_COLUMNS]
                values = [payload[col] for col in columns]
                placeholders = ", ".join(["?"] * len(columns))
                column_sql = ", ".join(columns)
                conn.execute(
                    f"INSERT INTO tickets ({column_sql}) VALUES ({placeholders})",
                    values,
                )
                created = True

        row = self.get_ticket(ticket_id)
        if row is None:
            raise KeyError(f"Ticket not found: {ticket_id}")
        return row, created

    def update_review(
        self,
        ticket_id: str,
        review_status: str,
        review_notes: str | None = None,
    ) -> dict[str, Any]:
        _ensure_status(review_status, ALLOWED_REVIEW_STATUS, "review_status")

        now = _utc_now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE tickets SET review_status = ?, review_notes = ?, updated_at = ? WHERE ticket_id = ?",
                (review_status, review_notes, now, ticket_id),
            )
            if cur.rowcount == 0:
                raise KeyError(f"Ticket not found: {ticket_id}")

        ticket = self.get_ticket(ticket_id)
        if ticket is None:
            raise KeyError(f"Ticket not found: {ticket_id}")
        return ticket

    def metrics(self) -> dict[str, int]:
        # "High confidence" is a presentation/metrics concept; keep it configurable.
        # Defaults to 0.60 (60%). Supports percent-style values like "60" -> 0.60.
        raw_threshold = (os.getenv("TICKETS_HIGH_CONFIDENCE_THRESHOLD") or "").strip()
        threshold = 0.60
        if raw_threshold:
            try:
                parsed = float(raw_threshold)
                if parsed > 1.0:
                    parsed = parsed / 100.0
                threshold = max(0.0, min(1.0, parsed))
            except Exception:
                threshold = 0.60

        sql = """
        SELECT
          SUM(CASE WHEN lifecycle_status = 'OPEN' THEN 1 ELSE 0 END) AS active_count,
          SUM(CASE WHEN review_status = 'NONE' AND diagnosis_status = 'DIAGNOSED' THEN 1 ELSE 0 END) AS awaiting_review_count,
          SUM(CASE WHEN review_status = 'APPROVED' THEN 1 ELSE 0 END) AS approved_count,
          SUM(CASE WHEN review_status = 'REJECTED' THEN 1 ELSE 0 END) AS rejected_count,
          SUM(CASE WHEN diagnosis_status = 'DIAGNOSED' AND confidence >= ? THEN 1 ELSE 0 END) AS high_confidence_count
        FROM tickets
        """

        with self._connect() as conn:
            row = conn.execute(sql, (float(threshold),)).fetchone()

        def _i(value: Any) -> int:
            return int(value or 0)

        if row is None:
            return {
                "active_count": 0,
                "awaiting_review_count": 0,
                "approved_count": 0,
                "rejected_count": 0,
                "high_confidence_count": 0,
            }

        return {
            "active_count": _i(row["active_count"]),
            "awaiting_review_count": _i(row["awaiting_review_count"]),
            "approved_count": _i(row["approved_count"]),
            "rejected_count": _i(row["rejected_count"]),
            "high_confidence_count": _i(row["high_confidence_count"]),
        }


def parse_jsonish_list(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        try:
            value = json.loads(s)
        except json.JSONDecodeError:
            return []
        return value if isinstance(value, list) else []
    return []


def parse_jsonish_value(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list, int, float, bool)):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return raw
    return raw
