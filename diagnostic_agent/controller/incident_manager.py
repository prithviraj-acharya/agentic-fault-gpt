from __future__ import annotations

import copy
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional, Tuple

from diagnostic_agent.controller.schemas import IncidentKey, WindowSummaryMinimal


@dataclass
class IncidentState:
    incident_key: IncidentKey

    seen_streak: int = 0
    clear_streak: int = 0

    last_seen_at: Optional[str] = None

    pending: bool = False
    in_progress: bool = False

    ticket_id: Optional[str] = None
    diagnosis_status: str = "DRAFT"

    occurrence_count: int = 0

    windows: Deque[WindowSummaryMinimal] = field(
        default_factory=lambda: deque(maxlen=2)
    )


class IncidentManager:
    """In-memory incident tracker keyed by (ahu_id, detected_fault_type)."""

    def __init__(self, *, cache_windows: int = 2) -> None:
        self._lock = threading.Lock()
        self._states: Dict[IncidentKey, IncidentState] = {}
        self._cache_windows = max(1, int(cache_windows))

    def _get_or_create_unlocked(self, key: IncidentKey) -> IncidentState:
        st = self._states.get(key)
        if st is None:
            st = IncidentState(incident_key=key)
            st.windows = deque(maxlen=self._cache_windows)
            self._states[key] = st
        return st

    def get(self, key: IncidentKey) -> IncidentState:
        with self._lock:
            return self._get_or_create_unlocked(key)

    def mark_seen(
        self, key: IncidentKey, window: WindowSummaryMinimal, *, now_iso: str
    ) -> IncidentState:
        with self._lock:
            st = self._get_or_create_unlocked(key)

            st.seen_streak += 1
            st.clear_streak = 0
            st.last_seen_at = now_iso
            st.windows.append(window)
            return st

    def mark_not_seen(self, key: IncidentKey) -> Optional[IncidentState]:
        with self._lock:
            st = self._states.get(key)
            if st is None:
                return None
            st.clear_streak += 1
            st.seen_streak = 0
            return st

    def active_keys(self) -> Tuple[IncidentKey, ...]:
        with self._lock:
            return tuple(self._states.keys())

    def set_ticket(
        self,
        key: IncidentKey,
        *,
        ticket_id: str,
        diagnosis_status: str,
        occurrence_count: int,
    ) -> None:
        with self._lock:
            st = self._get_or_create_unlocked(key)
            st.ticket_id = ticket_id
            st.diagnosis_status = diagnosis_status
            st.occurrence_count = int(occurrence_count or 0)

    def bump_occurrence(self, key: IncidentKey, delta: int = 1) -> int:
        with self._lock:
            st = self._get_or_create_unlocked(key)
            st.occurrence_count = int(st.occurrence_count) + int(delta)
            return int(st.occurrence_count)

    def snapshot_windows(self, key: IncidentKey) -> list[WindowSummaryMinimal]:
        with self._lock:
            st = self._get_or_create_unlocked(key)
            return list(st.windows)

    def snapshot_state(self, key: IncidentKey) -> IncidentState:
        # Return a stable snapshot for safe consumption outside the lock.
        with self._lock:
            st = self._get_or_create_unlocked(key)
            return copy.deepcopy(st)

    def set_pending(self, key: IncidentKey, value: bool) -> None:
        with self._lock:
            st = self._get_or_create_unlocked(key)
            st.pending = bool(value)

    def set_in_progress(self, key: IncidentKey, value: bool) -> None:
        with self._lock:
            st = self._get_or_create_unlocked(key)
            st.in_progress = bool(value)

    def set_diagnosis_status(self, key: IncidentKey, value: str) -> None:
        with self._lock:
            st = self._get_or_create_unlocked(key)
            st.diagnosis_status = str(value)

    def reset_episode(self, key: IncidentKey) -> None:
        """Called when an incident is resolved; allows a new episode/ticket later."""
        with self._lock:
            st = self._states.get(key)
            if st is None:
                return
            st.pending = False
            st.in_progress = False
            st.ticket_id = None
            st.diagnosis_status = "DRAFT"
            st.occurrence_count = 0
            st.seen_streak = 0
            st.clear_streak = 0
            st.windows.clear()
