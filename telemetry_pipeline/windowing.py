from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from simulation.utils import isoformat_z
from telemetry_pipeline.validator import EventValidator, TelemetryEvent


@dataclass
class Window:
    ahu_id: str
    start: datetime
    end: datetime
    window_type: str
    window_size_sec: int
    step_sec: Optional[int]
    events: List[TelemetryEvent]
    stats: Dict[str, Any]

    def start_iso(self) -> str:
        return isoformat_z(self.start)

    def end_iso(self) -> str:
        return isoformat_z(self.end)


def _align_floor_epoch(ts: datetime, *, window_size_sec: int) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ts = ts.astimezone(timezone.utc)
    epoch = int(ts.timestamp())
    aligned = epoch - (epoch % int(window_size_sec))
    return datetime.fromtimestamp(aligned, tz=timezone.utc)


class WindowManager:
    def __init__(
        self,
        *,
        window_type: str,
        window_size_sec: int,
        step_sec: Optional[int],
        align_to_epoch: bool,
        signals_cfg: Dict[str, Any],
    ) -> None:
        self.window_type = str(window_type)
        self.window_size_sec = int(window_size_sec)
        self.step_sec = None if step_sec is None else int(step_sec)
        self.align_to_epoch = bool(align_to_epoch)

        if self.window_type not in {"tumbling", "sliding"}:
            raise ValueError("window_type must be 'tumbling' or 'sliding'")
        if self.window_size_sec <= 0:
            raise ValueError("window_size_sec must be > 0")
        if self.window_type == "sliding":
            if self.step_sec is None or self.step_sec <= 0:
                raise ValueError("sliding windows require step_sec > 0")

        self._validator = EventValidator(signals_cfg=signals_cfg, windowing_cfg={})
        self._state: Dict[str, Dict[str, Any]] = {}

    def _init_state(self, ahu_id: str, ts: datetime) -> None:
        if self.align_to_epoch:
            start = _align_floor_epoch(ts, window_size_sec=self.window_size_sec)
        else:
            start = ts.replace(microsecond=0)
        end = start + timedelta(seconds=self.window_size_sec)
        self._state[ahu_id] = {
            "start": start,
            "end": end,
            "events": [],
            "missing_count": 0,
            "duplicate_count": 0,
            "late_count": 0,
        }

    def add_event(
        self, event: TelemetryEvent, *, duplicate: bool = False
    ) -> List[Window]:
        """Add an ordered event; returns any closed windows."""

        ahu_id = event.ahu_id
        if ahu_id not in self._state:
            self._init_state(ahu_id, event.timestamp)

        st = self._state[ahu_id]
        closed: List[Window] = []

        # Late events: event time is before current window start.
        if event.timestamp < st["start"]:
            st["late_count"] += 1
            return closed

        # Advance and close windows until this event fits.
        while event.timestamp >= st["end"]:
            closed.append(self._close_current(ahu_id))
            # move to next window
            st = self._state[ahu_id]

        # Add into current window
        st["events"].append(event)
        st["missing_count"] += self._validator.count_missing_values(event.signals)
        if duplicate:
            st["duplicate_count"] += 1
        return closed

    def add_duplicate(self, *, ahu_id: str, timestamp: datetime) -> List[Window]:
        """Account for a duplicate event without including it in the sample set."""

        if ahu_id not in self._state:
            self._init_state(ahu_id, timestamp)

        st = self._state[ahu_id]
        closed: List[Window] = []

        if timestamp < st["start"]:
            st["late_count"] += 1
            return closed

        while timestamp >= st["end"]:
            closed.append(self._close_current(ahu_id))
            st = self._state[ahu_id]

        st["duplicate_count"] += 1
        return closed

    def _close_current(self, ahu_id: str) -> Window:
        st = self._state[ahu_id]
        start: datetime = st["start"]
        end: datetime = st["end"]
        events: List[TelemetryEvent] = list(st["events"])
        stats: Dict[str, Any] = {
            "sample_count": len(events),
            "missing_count": int(st["missing_count"]),
            "duplicate_count": int(st["duplicate_count"]),
            "late_count": int(st["late_count"]),
        }

        window = Window(
            ahu_id=ahu_id,
            start=start,
            end=end,
            window_type=self.window_type,
            window_size_sec=self.window_size_sec,
            step_sec=self.step_sec,
            events=events,
            stats=stats,
        )

        # Reset for next window (tumbling only for now; sliding can be added later).
        next_start = end
        next_end = next_start + timedelta(seconds=self.window_size_sec)
        self._state[ahu_id] = {
            "start": next_start,
            "end": next_end,
            "events": [],
            "missing_count": 0,
            "duplicate_count": 0,
            "late_count": 0,
        }
        return window

    def flush(self) -> List[Window]:
        """Close and return any non-empty active windows."""

        closed: List[Window] = []
        for ahu_id, st in list(self._state.items()):
            if st.get("events"):
                closed.append(self._close_current(ahu_id))
        return closed


def deterministic_window_id(window: Window) -> str:
    # Follow the spec's recommended format.
    return f"{window.ahu_id}_{window.start_iso()}_{window.window_size_sec}s_{window.window_type}"
