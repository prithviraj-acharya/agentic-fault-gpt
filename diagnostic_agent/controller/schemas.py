from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


LifecycleStatus = Literal["OPEN", "RESOLVED"]
DiagnosisStatus = Literal["DRAFT", "DIAGNOSING", "DIAGNOSED", "FAILED"]
ReviewStatus = Literal["NONE", "APPROVED", "REJECTED"]


class WindowSummaryMinimal(BaseModel):
    ahu_id: str
    window_id: Optional[str] = None
    time: Optional[Dict[str, Any]] = None
    anomalies: List[Dict[str, Any]] = Field(default_factory=list)
    signature: Optional[str] = None
    summary_text: Optional[str] = None

    @property
    def window_end_ts(self) -> Optional[int]:
        t = self.time if isinstance(self.time, dict) else None
        if not t:
            return None
        end = t.get("end")
        if isinstance(end, (int, float)):
            return int(end)
        # If ISO8601, we keep raw; controller may parse if needed.
        return None


class RetrievedDoc(BaseModel):
    corpus: str
    doc_id: str
    # Chroma returns *distance* (lower is better) when include=['distances'].
    distance: Optional[float] = Field(default=None, validation_alias="score")
    text: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def score(self) -> Optional[float]:  # pragma: no cover
        # Backward-compatible alias for older code.
        return self.distance


class RetrievalStats(BaseModel):
    manuals_count: int = 0
    past_cases_count: int = 0
    case_history_count: int = 0

    manuals_has_any: bool = False
    past_cases_has_any: bool = False

    # Distances (lower is better)
    min_distance: Optional[float] = Field(default=None, validation_alias="min_score")
    avg_distance: Optional[float] = Field(default=None, validation_alias="avg_score")

    error: Optional[str] = None

    @property
    def coverage_ok(self) -> bool:
        return bool(self.manuals_has_any and self.past_cases_has_any)


class DiagnosisResult(BaseModel):
    title: str
    root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)

    recommended_actions: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)

    conflict: bool = False


IncidentKey = Tuple[str, str]  # (ahu_id, detected_fault_type)


class IncidentContext(BaseModel):
    incident_key: IncidentKey
    ahu_id: str
    detected_fault_type: str

    seen_streak: int
    clear_streak: int
    last_seen_at: Optional[str] = None

    recent_windows: List[WindowSummaryMinimal] = Field(default_factory=list)

    stage: int = 1
    retrieval_stats: RetrievalStats = Field(default_factory=RetrievalStats)
    retrieved_docs: List[RetrievedDoc] = Field(default_factory=list)


class DiagnosisJob(BaseModel):
    incident_key: IncidentKey
    ticket_id: str

    stage: int = 1
    allow_refine: bool = True

    enqueued_at: str = Field(default_factory=utc_now_iso)
