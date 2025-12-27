from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Mapping, Optional

from simulation.utils import parse_iso8601


@dataclass(frozen=True)
class TelemetryEvent:
    """Validated, normalized telemetry event (internal representation)."""

    timestamp: datetime
    timestamp_str: str
    ahu_id: str
    signals: Dict[str, Optional[float]]


def _to_float_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        # NaN handling
        try:
            if value != value:  # type: ignore[comparison-overlap]
                return None
        except Exception:
            pass
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        lowered = s.lower()
        if lowered in {"nan", "null", "none"}:
            return None
        try:
            return float(s)
        except Exception:
            return None
    return None


class EventValidator:
    def __init__(
        self, *, signals_cfg: Mapping[str, Any], windowing_cfg: Mapping[str, Any]
    ):
        self._signals_cfg = dict(signals_cfg)
        self._windowing_cfg = dict(windowing_cfg)

        schema = dict(self._signals_cfg.get("schema", {}))
        self.timestamp_field = str(schema.get("timestamp_field", "timestamp"))
        self.ahu_id_field = str(schema.get("ahu_id_field", "ahu_id"))

        self.signals_meta: Dict[str, Dict[str, Any]] = {
            str(k): dict(v)
            for k, v in dict(self._signals_cfg.get("signals", {})).items()
        }

        missing_cfg = dict(self._windowing_cfg.get("missing_data", {}))
        self.allow_missing_values = bool(missing_cfg.get("allow_missing_values", True))
        self.drop_event_if_missing_timestamp = bool(
            missing_cfg.get("drop_event_if_missing_timestamp", True)
        )
        self.drop_event_if_missing_ahu_id = bool(
            missing_cfg.get("drop_event_if_missing_ahu_id", True)
        )

    def validate_and_normalize(
        self, raw: Mapping[str, Any]
    ) -> Optional[TelemetryEvent]:
        """Return normalized TelemetryEvent or None if rejected."""

        # Accept either flat schema, or nested `signals` payload.
        raw_obj: Dict[str, Any] = {str(k): v for k, v in dict(raw).items()}
        nested_signals = raw_obj.get("signals")

        timestamp_raw = (
            raw_obj.get(self.timestamp_field)
            or raw_obj.get("timestamp")
            or raw_obj.get("ts")
        )
        if timestamp_raw is None:
            if self.drop_event_if_missing_timestamp:
                return None
            # Keep as empty string but it will fail parsing below.
            timestamp_raw = ""

        if not isinstance(timestamp_raw, str):
            timestamp_raw = str(timestamp_raw)
        timestamp_raw = timestamp_raw.strip()
        if not timestamp_raw:
            return None

        try:
            ts_dt = parse_iso8601(timestamp_raw)
        except Exception:
            return None

        ahu_raw = raw_obj.get(self.ahu_id_field) or raw_obj.get("ahu_id")
        if ahu_raw is None:
            if self.drop_event_if_missing_ahu_id:
                return None
            ahu_raw = ""
        ahu_id = str(ahu_raw).strip()
        if not ahu_id and self.drop_event_if_missing_ahu_id:
            return None

        # Signal extraction: only the frozen vocabulary from signals.yaml
        if isinstance(nested_signals, dict):
            source = {str(k): v for k, v in nested_signals.items()}
        else:
            source = raw_obj

        normalized_signals: Dict[str, Optional[float]] = {}
        for sig in self.signals_meta.keys():
            normalized_signals[sig] = _to_float_or_none(source.get(sig))

        if not self.allow_missing_values:
            # Drop the event if any expected signal is missing.
            if any(v is None for v in normalized_signals.values()):
                return None

        return TelemetryEvent(
            timestamp=ts_dt,
            timestamp_str=timestamp_raw,
            ahu_id=ahu_id,
            signals=normalized_signals,
        )

    @staticmethod
    def count_missing_values(signals: Mapping[str, Optional[float]]) -> int:
        return sum(1 for v in signals.values() if v is None)
