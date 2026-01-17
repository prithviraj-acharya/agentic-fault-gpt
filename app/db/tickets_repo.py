from __future__ import annotations

import json
import sqlite3
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


def _ensure_status(value: str, allowed: set[str], field: str) -> None:
    if value not in allowed:
        raise ValueError(f"Invalid {field}: {value}")


def _safe_like(value: str) -> str:
    # SQLite LIKE wildcards: %, _. Escape char is backslash.
    s = str(value)
    s = s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return s


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
        sql = """
        SELECT
          SUM(CASE WHEN lifecycle_status = 'OPEN' THEN 1 ELSE 0 END) AS active_count,
          SUM(CASE WHEN review_status = 'NONE' AND diagnosis_status = 'DIAGNOSED' THEN 1 ELSE 0 END) AS awaiting_review_count,
          SUM(CASE WHEN review_status = 'APPROVED' THEN 1 ELSE 0 END) AS approved_count,
          SUM(CASE WHEN review_status = 'REJECTED' THEN 1 ELSE 0 END) AS rejected_count,
          SUM(CASE WHEN diagnosis_status = 'DIAGNOSED' AND confidence >= 0.85 THEN 1 ELSE 0 END) AS high_confidence_count
        FROM tickets
        """

        with self._connect() as conn:
            row = conn.execute(sql).fetchone()

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
