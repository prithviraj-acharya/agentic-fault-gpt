from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.db.tickets_repo import (
    ALLOWED_DIAGNOSIS_STATUS,
    ALLOWED_LIFECYCLE_STATUS,
    ALLOWED_REVIEW_STATUS,
    TicketRepository,
    parse_jsonish_list,
    parse_jsonish_value,
)

router = APIRouter(prefix="/tickets", tags=["tickets"])


class Ticket(BaseModel):
    ticket_id: str
    ticket_ref: str
    ahu_id: str
    detected_fault_type: str

    lifecycle_status: str
    diagnosis_status: str
    review_status: str

    confidence: Optional[float] = None

    created_at: str
    updated_at: str
    last_seen_at: str
    diagnosed_at: Optional[str] = None
    resolved_at: Optional[str] = None

    last_window_end_ts: Optional[int] = None

    diagnosis_title: Optional[str] = None
    root_cause: Optional[str] = None
    recommended_actions: Optional[Any] = None

    evidence_ids: List[Any] = Field(default_factory=list)
    window_refs: List[Any] = Field(default_factory=list)
    signatures_seen: List[Any] = Field(default_factory=list)

    review_notes: Optional[str] = None

    symptom_summary: Optional[str] = None


class TicketListResponse(BaseModel):
    items: List[Ticket]
    limit: int
    offset: int
    total: int


class ReviewPatchRequest(BaseModel):
    review_status: str
    review_notes: Optional[str] = None


class MetricsResponse(BaseModel):
    active_count: int
    awaiting_review_count: int
    approved_count: int
    rejected_count: int
    high_confidence_count: int


def _ticket_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
    # Normalize JSON-ish DB columns into JSON-friendly API types.
    out = dict(row)
    out["evidence_ids"] = parse_jsonish_list(out.get("evidence_ids"))
    out["window_refs"] = parse_jsonish_list(out.get("window_refs"))
    out["signatures_seen"] = parse_jsonish_list(out.get("signatures_seen"))
    out["recommended_actions"] = parse_jsonish_value(out.get("recommended_actions"))
    return out


@router.get("/metrics", response_model=MetricsResponse)
def tickets_metrics() -> Dict[str, int]:
    repo = TicketRepository()
    return repo.metrics()


@router.get("", response_model=TicketListResponse)
def list_tickets(
    lifecycle_status: Optional[str] = Query(None),
    diagnosis_status: Optional[str] = Query(None),
    review_status: Optional[str] = Query(None),
    ahu_id: Optional[str] = Query(None),
    fault_type: Optional[str] = Query(None, description="Maps to detected_fault_type"),
    min_confidence: Optional[float] = Query(None, ge=0.0, le=1.0),
    q: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort: str = Query("updated_at"),
    order: str = Query("desc"),
) -> Dict[str, Any]:
    # Validate enums early to return 400 instead of 500.
    if (
        lifecycle_status is not None
        and lifecycle_status not in ALLOWED_LIFECYCLE_STATUS
    ):
        raise HTTPException(
            status_code=400, detail={"error": "invalid_lifecycle_status"}
        )
    if (
        diagnosis_status is not None
        and diagnosis_status not in ALLOWED_DIAGNOSIS_STATUS
    ):
        raise HTTPException(
            status_code=400, detail={"error": "invalid_diagnosis_status"}
        )
    if review_status is not None and review_status not in ALLOWED_REVIEW_STATUS:
        raise HTTPException(status_code=400, detail={"error": "invalid_review_status"})

    filters: Dict[str, Any] = {
        "lifecycle_status": lifecycle_status,
        "diagnosis_status": diagnosis_status,
        "review_status": review_status,
        "ahu_id": ahu_id,
        "fault_type": fault_type,
        "min_confidence": min_confidence,
        "q": q,
    }

    repo = TicketRepository()
    try:
        result = repo.list_tickets(
            filters=filters,
            limit=int(limit),
            offset=int(offset),
            sort=str(sort),
            order=str(order),
            include_total=True,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail={"error": "bad_request", "message": str(exc)}
        ) from exc

    items = [_ticket_from_row(r) for r in result.items]
    return {
        "items": items,
        "limit": int(limit),
        "offset": int(offset),
        "total": int(result.total),
    }


@router.get("/{ticket_id}", response_model=Ticket)
def get_ticket(ticket_id: str) -> Dict[str, Any]:
    repo = TicketRepository()
    if str(ticket_id).startswith("TCK-"):
        row = repo.get_ticket_by_ref(ticket_id)
    else:
        row = repo.get_ticket(ticket_id)

    if row is None:
        raise HTTPException(status_code=404, detail={"error": "ticket_not_found"})
    return _ticket_from_row(row)


@router.patch("/{ticket_id}/review", response_model=Ticket)
def patch_review(ticket_id: str, body: ReviewPatchRequest) -> Dict[str, Any]:
    if body.review_status not in ALLOWED_REVIEW_STATUS:
        raise HTTPException(status_code=400, detail={"error": "invalid_review_status"})

    repo = TicketRepository()
    try:
        row = repo.update_review(
            ticket_id=ticket_id,
            review_status=body.review_status,
            review_notes=body.review_notes,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail={"error": "ticket_not_found"}
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail={"error": "bad_request", "message": str(exc)}
        ) from exc

    return _ticket_from_row(row)
