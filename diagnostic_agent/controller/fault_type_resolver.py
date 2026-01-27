from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Set


@dataclass(frozen=True)
class FaultTypeResolver:
    """Deterministically map window_summary anomalies to canonical fault types.

    Identity is locked elsewhere as (ahu_id, detected_fault_type). This resolver only
    emits evidence-based fault type labels.
    """

    ignore_unknown: bool = True

    def resolve_fault_types(self, window_summary: Mapping[str, Any]) -> Set[str]:
        anomalies_obj = window_summary.get("anomalies")
        anomalies: List[Dict[str, Any]] = (
            anomalies_obj if isinstance(anomalies_obj, list) else []
        )

        # Primary: fault_hypotheses if present
        hypotheses = self._extract_hypotheses(anomalies)
        out: Set[str] = set()
        for token in hypotheses:
            mapped = self._map_hypothesis(token)
            if mapped:
                out.add(mapped)

        # Fallback: map from rule_id
        if not out:
            for rid in self._extract_rule_ids(anomalies):
                mapped = self._map_rule_id(rid)
                if mapped:
                    out.add(mapped)

        # If still empty, attempt rule_id mapping even when hypotheses exist
        # (allows multi-fault windows)
        for rid in self._extract_rule_ids(anomalies):
            mapped = self._map_rule_id(rid)
            if mapped:
                out.add(mapped)

        if not out and not self.ignore_unknown:
            out.add("UNKNOWN")

        if self.ignore_unknown and "UNKNOWN" in out:
            out.discard("UNKNOWN")

        return out

    def _extract_rule_ids(self, anomalies: Iterable[Mapping[str, Any]]) -> List[str]:
        out: List[str] = []
        for a in anomalies:
            rid = str(a.get("rule_id") or "").strip()
            if rid:
                out.append(rid)
        return out

    def _extract_hypotheses(self, anomalies: Iterable[Mapping[str, Any]]) -> List[str]:
        tokens: List[str] = []
        for a in anomalies:
            raw = a.get("fault_hypotheses")
            if raw is None:
                continue
            if isinstance(raw, str):
                parts = [p.strip() for p in raw.split(",")]
                tokens.extend([p for p in parts if p])
            elif isinstance(raw, list):
                for item in raw:
                    if isinstance(item, str):
                        s = item.strip()
                        if s:
                            tokens.append(s)
                    elif isinstance(item, dict):
                        tokens.extend(
                            [str(k).strip() for k in item.keys() if str(k).strip()]
                        )
            elif isinstance(raw, dict):
                tokens.extend([str(k).strip() for k in raw.keys() if str(k).strip()])

        # Stable de-dupe preserving order
        seen = set()
        out: List[str] = []
        for t in tokens:
            if t not in seen:
                out.append(t)
                seen.add(t)
        return out

    def _map_rule_id(self, rule_id: str) -> str | None:
        rid = str(rule_id).strip().upper()
        if not rid:
            return None

        if rid in {"SAT_NOT_DROPPING_WHEN_VALVE_HIGH", "SAT_TOO_HIGH_WHEN_VALVE_HIGH"}:
            return "COOLING_COIL_FAULT"

        if rid == "OA_DAMPER_STUCK_OR_FLATLINE":
            return "OA_DAMPER_STUCK"
        if rid == "RA_DAMPER_STUCK_OR_FLATLINE":
            return "RA_DAMPER_STUCK"

        if rid in {"ZONE_TEMP_PERSISTENT_TREND", "ZONE_TEMP_SENSOR_NOISY"}:
            return "ZONE_TEMP_SENSOR_DRIFT"

        return "UNKNOWN"

    def _map_hypothesis(self, token: str) -> str | None:
        s = re.sub(r"\s+", " ", str(token).strip().lower())
        if not s:
            return None

        # A few robust patterns; keep deterministic.
        if "cooling" in s and ("coil" in s or "valve" in s or "sat" in s):
            return "COOLING_COIL_FAULT"

        if "outdoor" in s or "oa" in s:
            if "damper" in s and ("stuck" in s or "flat" in s):
                return "OA_DAMPER_STUCK"

        if "return" in s or "ra" in s:
            if "damper" in s and ("stuck" in s or "flat" in s):
                return "RA_DAMPER_STUCK"

        if ("zone" in s and "temp" in s) and (
            "drift" in s or "trend" in s or "noise" in s
        ):
            return "ZONE_TEMP_SENSOR_DRIFT"

        return "UNKNOWN"
