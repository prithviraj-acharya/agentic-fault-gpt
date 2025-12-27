from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from telemetry_pipeline.validator import TelemetryEvent


def compute_event_id(event: TelemetryEvent, *, key_fields: List[str]) -> str:
    """Deterministic event_id based on a stable subset of fields."""

    payload: Dict[str, Any] = {}
    for f in key_fields:
        if f in {"timestamp", "ts"}:
            payload[f] = event.timestamp_str
        elif f in {"ahu_id"}:
            payload[f] = event.ahu_id
        else:
            # Allow signal keys in dedup key if desired.
            if f in event.signals:
                payload[f] = event.signals.get(f)
            else:
                payload[f] = None

    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass
class OrderingStats:
    duplicate_count: int = 0
    late_count: int = 0


@dataclass(frozen=True)
class PushResult:
    event_id: str
    is_duplicate: bool
    ready: List[Tuple[str, TelemetryEvent]]


class PerAhuOrderingBuffer:
    """Small per-AHU buffer for deterministic ordering and optional de-dup."""

    def __init__(
        self,
        *,
        reorder_buffer_sec: int,
        enable_dedup: bool,
        dedup_key_fields: List[str],
    ) -> None:
        self.reorder_buffer = timedelta(seconds=int(reorder_buffer_sec))
        self.enable_dedup = bool(enable_dedup)
        self.dedup_key_fields = list(dedup_key_fields)

        self._buffers: Dict[str, List[Tuple[datetime, str, TelemetryEvent]]] = (
            defaultdict(list)
        )
        self._seen_ids: Dict[str, set[str]] = defaultdict(set)
        self._max_ts: Dict[str, datetime] = {}

        self.stats_by_ahu: Dict[str, OrderingStats] = defaultdict(OrderingStats)

    def push(self, event: TelemetryEvent) -> PushResult:
        """Add an event.

        Returns:
          - event_id: deterministic id computed from configured key fields
          - is_duplicate: True if de-dup rejected this event
          - ready: ordered events safe to process now
        """

        ahu = event.ahu_id
        eid = compute_event_id(event, key_fields=self.dedup_key_fields)

        if self.enable_dedup:
            if eid in self._seen_ids[ahu]:
                self.stats_by_ahu[ahu].duplicate_count += 1
                return PushResult(event_id=eid, is_duplicate=True, ready=[])
            self._seen_ids[ahu].add(eid)

        max_ts = self._max_ts.get(ahu)
        if max_ts is None or event.timestamp > max_ts:
            self._max_ts[ahu] = event.timestamp
            max_ts = event.timestamp

        self._buffers[ahu].append((event.timestamp, eid, event))

        # Stable ordering: timestamp then event_id.
        self._buffers[ahu].sort(key=lambda t: (t[0], t[1]))

        watermark = max_ts - self.reorder_buffer
        ready: List[Tuple[str, TelemetryEvent]] = []
        buf = self._buffers[ahu]
        i = 0
        while i < len(buf) and buf[i][0] <= watermark:
            _, eid_i, ev_i = buf[i]
            ready.append((eid_i, ev_i))
            i += 1
        if i > 0:
            del buf[:i]

        return PushResult(event_id=eid, is_duplicate=False, ready=ready)

    def flush(self) -> Iterable[Tuple[str, TelemetryEvent]]:
        """Flush all remaining buffered events in deterministic order."""

        for ahu, buf in list(self._buffers.items()):
            buf.sort(key=lambda t: (t[0], t[1]))
            for _, eid, ev in buf:
                yield eid, ev
            buf.clear()
