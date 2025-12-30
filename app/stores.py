from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any, Deque, Dict, Iterable, List, Mapping, Optional, Tuple

from app.utils import isoformat_z


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _severity_to_int(sev: Any) -> int:
    s = str(sev or "").strip().lower()
    if s == "high":
        return 3
    if s == "medium":
        return 2
    if s == "low":
        return 1
    return 0


def _downsample(
    points: List[Tuple[datetime, Dict[str, float]]], *, max_points: int
) -> List[Tuple[datetime, Dict[str, float]]]:
    if max_points <= 0 or len(points) <= max_points:
        return points
    step = (len(points) + max_points - 1) // max_points
    out = points[::step]
    if out and out[-1] != points[-1]:
        out.append(points[-1])
    return out


@dataclass
class TelemetryStore:
    retention_mins: int
    max_points: int

    def __post_init__(self) -> None:
        self._lock = RLock()
        self._data: Dict[str, List[Tuple[datetime, Dict[str, float]]]] = defaultdict(
            list
        )

    def add(self, ahu_id: str, ts: datetime, values: Dict[str, float]) -> None:
        with self._lock:
            series = self._data[str(ahu_id)]
            series.append((ts, dict(values)))
            # Keep sorted for range queries (small buffers; stable for demo).
            series.sort(key=lambda x: x[0])
            # Retain the last N minutes relative to the newest observed timestamp
            # (works for both live ingestion and historical replays).
            newest_ts = series[-1][0]
            cutoff = newest_ts - timedelta(minutes=int(self.retention_mins))
            # Evict by time
            i = 0
            while i < len(series) and series[i][0] < cutoff:
                i += 1
            if i > 0:
                del series[:i]

    def latest(self, ahu_id: str) -> Optional[Tuple[datetime, Dict[str, float]]]:
        with self._lock:
            series = self._data.get(str(ahu_id))
            if not series:
                return None
            return series[-1]

    def range(
        self,
        ahu_id: str,
        from_ts: datetime,
        to_ts: datetime,
        signals: List[str],
    ) -> List[Dict[str, Any]]:
        with self._lock:
            series = list(self._data.get(str(ahu_id), []))

        points = [(ts, vals) for ts, vals in series if from_ts <= ts <= to_ts]
        points = _downsample(points, max_points=int(self.max_points))

        out: List[Dict[str, Any]] = []
        for ts, vals in points:
            row: Dict[str, Any] = {"ts": isoformat_z(ts)}
            for s in signals:
                v = vals.get(s)
                if v is not None:
                    row[s] = float(v)
            out.append(row)
        return out

    def last_n(
        self,
        ahu_id: str,
        limit: int,
        signals: List[str],
    ) -> List[Dict[str, Any]]:
        lim = max(int(limit), 0)
        if lim <= 0:
            return []

        with self._lock:
            series = list(self._data.get(str(ahu_id), []))

        points = series[-lim:]
        out: List[Dict[str, Any]] = []
        for ts, vals in points:
            row: Dict[str, Any] = {"ts": isoformat_z(ts)}
            for s in signals:
                v = vals.get(s)
                if v is not None:
                    row[s] = float(v)
            out.append(row)
        return out

    def ahus(self) -> List[str]:
        with self._lock:
            return sorted(self._data.keys())

    def points_cached_total(self) -> int:
        with self._lock:
            return sum(len(v) for v in self._data.values())

    def last_ts(self) -> Optional[datetime]:
        with self._lock:
            last: Optional[datetime] = None
            for series in self._data.values():
                if not series:
                    continue
                ts = series[-1][0]
                if last is None or ts > last:
                    last = ts
            return last


@dataclass
class WindowStore:
    maxlen: int

    def __post_init__(self) -> None:
        self._lock = RLock()
        self._by_ahu: Dict[str, Deque[Dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=int(self.maxlen))
        )
        self._index: Dict[str, Dict[str, Any]] = {}

    def add(self, window_summary: Dict[str, Any]) -> None:
        ahu_id = str(window_summary.get("ahu_id", ""))
        window_id = str(window_summary.get("window_id", ""))
        if not ahu_id or not window_id:
            return

        with self._lock:
            dq = self._by_ahu[ahu_id]
            # If deque will drop an item, remove from index.
            if dq.maxlen is not None and len(dq) == dq.maxlen:
                oldest = dq[0]
                old_id = str(oldest.get("window_id", ""))
                if old_id:
                    self._index.pop(old_id, None)

            dq.append(window_summary)
            self._index[window_id] = window_summary

    def latest_min_items(self, ahu_id: str, limit: int) -> List[Dict[str, Any]]:
        with self._lock:
            dq = list(self._by_ahu.get(str(ahu_id), deque()))

        # newest first
        dq = list(reversed(dq))
        dq = dq[: max(int(limit), 0)]
        return [min_window_item(w) for w in dq]

    def get(self, window_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            obj = self._index.get(str(window_id))
            return None if obj is None else obj

    def ahus(self) -> List[str]:
        with self._lock:
            return sorted(self._by_ahu.keys())

    def windows_cached_total(self) -> int:
        with self._lock:
            return sum(len(v) for v in self._by_ahu.values())

    def last_window_end(self) -> Optional[datetime]:
        with self._lock:
            best: Optional[datetime] = None
            for dq in self._by_ahu.values():
                if not dq:
                    continue
                w = dq[-1]
                end = _parse_window_end(w)
                if end is not None and (best is None or end > best):
                    best = end
            return best

    def windows_in_last_mins(self, ahu_id: str, mins: int) -> List[Dict[str, Any]]:
        cutoff = _now_utc() - timedelta(minutes=int(mins))
        with self._lock:
            dq = list(self._by_ahu.get(str(ahu_id), deque()))
        out: List[Dict[str, Any]] = []
        for w in dq:
            end = _parse_window_end(w)
            if end is None:
                continue
            if end >= cutoff:
                out.append(w)
        return out


def _parse_window_end(w: Mapping[str, Any]) -> Optional[datetime]:
    t = w.get("time")
    if not isinstance(t, Mapping):
        return None
    end = t.get("end")
    if not isinstance(end, str) or not end:
        return None
    # local parse, avoid import cycle
    from app.utils import parse_iso8601

    return parse_iso8601(end)


def min_window_item(w: Mapping[str, Any]) -> Dict[str, Any]:
    time_obj = w.get("time")
    time_map: Mapping[str, Any] = time_obj if isinstance(time_obj, Mapping) else {}
    start = time_map.get("start")
    end = time_map.get("end")

    anomalies_obj = w.get("anomalies")
    anomalies: List[Any] = anomalies_obj if isinstance(anomalies_obj, list) else []
    max_sev = 0
    rule_ids: List[str] = []
    for a in anomalies:
        if not isinstance(a, Mapping):
            continue
        max_sev = max(max_sev, _severity_to_int(a.get("severity")))
        rid = a.get("rule_id")
        if rid:
            rule_ids.append(str(rid))

    # top 1–3 by frequency
    c = Counter(rule_ids)
    top_rules = [rid for rid, _ in c.most_common(3)]

    return {
        "window_id": str(w.get("window_id", "")),
        "start": str(start) if start is not None else "",
        "end": str(end) if end is not None else "",
        "signature": str(w.get("signature", "")),
        "max_severity": int(max_sev),
        "top_rules": top_rules,
        "text_summary": (
            str(w.get("text_summary", "")) if w.get("text_summary") is not None else ""
        ),
    }


def compute_active_incidents(
    windows: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for w in windows:
        sig = str(w.get("signature", ""))
        if not sig:
            continue
        groups[sig].append(w)

    items: List[Dict[str, Any]] = []
    for sig, ws in groups.items():
        first: Optional[str] = None
        last: Optional[str] = None
        max_sev = 0
        rule_ids: List[str] = []

        for w in ws:
            time_obj = w.get("time")
            time_map: Mapping[str, Any] = (
                time_obj if isinstance(time_obj, Mapping) else {}
            )
            start = time_map.get("start")
            end = time_map.get("end")
            if isinstance(start, str):
                first = start if first is None else min(first, start)
            if isinstance(end, str):
                last = end if last is None else max(last, end)

            anomalies_obj = w.get("anomalies")
            anomalies: List[Any] = (
                anomalies_obj if isinstance(anomalies_obj, list) else []
            )
            for a in anomalies:
                if not isinstance(a, Mapping):
                    continue
                max_sev = max(max_sev, _severity_to_int(a.get("severity")))
                rid = a.get("rule_id")
                if rid:
                    rule_ids.append(str(rid))

        c = Counter(rule_ids)
        top_rules = [rid for rid, _ in c.most_common(3)]

        items.append(
            {
                "signature": sig,
                "first_seen": first or "",
                "last_seen": last or "",
                "count": len(ws),
                "max_severity": int(max_sev),
                "top_rules": top_rules,
            }
        )

    # newest incidents first by last_seen string (ISO sorts lexicographically)
    items.sort(key=lambda x: x.get("last_seen", ""), reverse=True)
    return items
