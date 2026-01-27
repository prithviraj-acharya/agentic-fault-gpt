from __future__ import annotations

from typing import Protocol

from diagnostic_agent.controller.schemas import DiagnosisResult, IncidentContext


class DiagnosisReasoner(Protocol):
    """Phase 7 interface (stateless/pure).

    Implementations must NOT:
    - call ticket APIs
    - call Kafka
    - manage lifecycle transitions
    """

    def diagnose(self, ctx: IncidentContext) -> DiagnosisResult:  # pragma: no cover
        ...
