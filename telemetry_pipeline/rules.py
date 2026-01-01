from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Trigger:
    rule_id: str
    severity: str
    evidence: Dict[str, Any]
    message: str = ""


def _trigger(
    rule_id: str,
    severity: str,
    evidence: Dict[str, Any],
    message: str = "",
) -> Trigger:
    return Trigger(
        rule_id=rule_id, severity=severity, evidence=evidence, message=message
    )


class RuleEngine:
    """Evaluate Phase-3 symptom rules on window-level features.

    This module is intentionally independent of Kafka/windowing. It consumes:
      - features: flat dict of numeric features (e.g., sa_temp_mean, cc_valve_mean)
      - stats: window stats (e.g., sample_count, missing_count, num_signals)

    It emits a list of JSON-serializable trigger dicts.
    """

    def __init__(self, rules_cfg: Dict[str, Any], signals_cfg: Dict[str, Any]):
        self.rules_cfg = dict(rules_cfg.get("rules", {}))
        self.signal_bounds = dict(signals_cfg.get("signals", {}))

    def evaluate(
        self, features: Dict[str, float], *, stats: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        triggers: List[Trigger] = []

        t = self._sat_not_dropping_when_valve_high(features, stats)
        if t:
            triggers.append(t)

        t = self._sat_too_high_when_valve_high(features)
        if t:
            triggers.append(t)

        t = self._damper_stuck(
            features, damper_prefix="oa_damper", rule_id="OA_DAMPER_STUCK_OR_FLATLINE"
        )
        if t:
            triggers.append(t)

        t = self._damper_stuck(
            features, damper_prefix="ra_damper", rule_id="RA_DAMPER_STUCK_OR_FLATLINE"
        )
        if t:
            triggers.append(t)

        t = self._zone_temp_persistent_trend(features)
        if t:
            triggers.append(t)

        t = self._zone_temp_noisy(features)
        if t:
            triggers.append(t)

        t = self._missing_data_high(stats)
        if t:
            triggers.append(t)

        t = self._out_of_range(features)
        if t:
            triggers.append(t)

        return [
            {
                "rule_id": tr.rule_id,
                "severity": tr.severity,
                "evidence": tr.evidence,
                "message": tr.message,
            }
            for tr in triggers
        ]

    def _is_enabled(self, rule_id: str) -> bool:
        return bool(self.rules_cfg.get(rule_id, {}).get("enabled", True))

    def _params(self, rule_id: str) -> Dict[str, Any]:
        return dict(self.rules_cfg.get(rule_id, {}).get("params", {}))

    def _severity(self, rule_id: str) -> str:
        return str(self.rules_cfg.get(rule_id, {}).get("severity", "low"))

    def _sat_not_dropping_when_valve_high(
        self, f: Dict[str, float], stats: Dict[str, Any]
    ) -> Optional[Trigger]:
        rule_id = "SAT_NOT_DROPPING_WHEN_VALVE_HIGH"
        if not self._is_enabled(rule_id):
            return None
        p = self._params(rule_id)

        if stats.get("sample_count", 0) < p.get("min_samples", 0):
            return None

        valve = f.get("cc_valve_mean")
        slope = f.get("sa_temp_slope")
        if valve is None or slope is None:
            return None

        min_mean_minus_sp = float(p.get("sa_temp_mean_minus_sp_min", 0.0) or 0.0)
        mean_minus_sp = f.get("sa_temp_mean_minus_sp")
        if mean_minus_sp is None:
            mean_minus_sp = 0.0
        if mean_minus_sp < min_mean_minus_sp:
            return None

        if valve > p["valve_high_pct"] and slope >= p["sat_slope_min"]:
            evidence: Dict[str, Any] = {
                "cc_valve_mean": valve,
                "sa_temp_slope": slope,
                "sa_temp_mean_minus_sp": mean_minus_sp,
                "thresholds": p,
            }
            delta = f.get("sa_temp_delta")
            if delta is not None:
                evidence["sa_temp_delta"] = delta

            return _trigger(
                rule_id,
                self._severity(rule_id),
                evidence,
                "Cooling demand high but supply air temperature not dropping.",
            )
        return None

    def _sat_too_high_when_valve_high(self, f: Dict[str, float]) -> Optional[Trigger]:
        rule_id = "SAT_TOO_HIGH_WHEN_VALVE_HIGH"
        if not self._is_enabled(rule_id):
            return None
        p = self._params(rule_id)

        valve = f.get("cc_valve_mean")
        diff = f.get("sa_temp_mean_minus_sp")
        if valve is None or diff is None:
            return None

        if valve > p["valve_high_pct"] and diff > p["sa_temp_mean_minus_sp_high"]:
            return _trigger(
                rule_id,
                self._severity(rule_id),
                {
                    "cc_valve_mean": valve,
                    "sa_temp_mean_minus_sp": diff,
                    "sa_temp_mean": f.get("sa_temp_mean"),
                    "sa_temp_sp_mean": f.get("sa_temp_sp_mean"),
                    "thresholds": p,
                },
                "Supply air temperature above setpoint while cooling demand is high.",
            )
        return None

    def _damper_stuck(
        self, f: Dict[str, float], *, damper_prefix: str, rule_id: str
    ) -> Optional[Trigger]:
        if not self._is_enabled(rule_id):
            return None
        p = self._params(rule_id)

        var_key = f"{damper_prefix}_var"
        mean_key = f"{damper_prefix}_mean"
        var_val = f.get(var_key)
        mean_val = f.get(mean_key)
        if var_val is None:
            return None

        if var_val < p["damper_var_eps"]:
            return _trigger(
                rule_id,
                self._severity(rule_id),
                {var_key: var_val, mean_key: mean_val, "thresholds": p},
                f"{damper_prefix} shows near-zero variance (possible stuck/flatline).",
            )
        return None

    def _zone_temp_persistent_trend(self, f: Dict[str, float]) -> Optional[Trigger]:
        rule_id = "ZONE_TEMP_PERSISTENT_TREND"
        if not self._is_enabled(rule_id):
            return None
        p = self._params(rule_id)

        sat_minus_sp = f.get("sa_temp_mean_minus_sp")
        max_sat_minus_sp = p.get("sa_temp_mean_minus_sp_max")
        if sat_minus_sp is not None and max_sat_minus_sp is not None:
            try:
                if float(sat_minus_sp) > float(max_sat_minus_sp):
                    return None
            except Exception:
                pass

        slope = f.get("avg_zone_temp_slope")
        if slope is None:
            return None

        delta = f.get("avg_zone_temp_delta")
        if delta is None:
            delta = 0.0

        min_delta = float(p.get("zone_delta_min", 0.0) or 0.0)

        if slope > p["zone_slope_high"] and delta >= min_delta:
            return _trigger(
                rule_id,
                self._severity(rule_id),
                {
                    "avg_zone_temp_slope": slope,
                    "avg_zone_temp_delta": delta,
                    "avg_zone_temp_var": f.get("avg_zone_temp_var"),
                    "thresholds": p,
                },
                "Zone temperature shows sustained upward trend.",
            )
        return None

    def _zone_temp_noisy(self, f: Dict[str, float]) -> Optional[Trigger]:
        rule_id = "ZONE_TEMP_SENSOR_NOISY"
        if not self._is_enabled(rule_id):
            return None
        p = self._params(rule_id)

        var_val = f.get("avg_zone_temp_var")
        if var_val is None:
            return None

        if var_val > p["zone_var_high"]:
            return _trigger(
                rule_id,
                self._severity(rule_id),
                {"avg_zone_temp_var": var_val, "thresholds": p},
                "Zone temperature variance unusually high (possible sensor noise).",
            )
        return None

    def _missing_data_high(self, stats: Dict[str, Any]) -> Optional[Trigger]:
        rule_id = "MISSING_DATA_HIGH"
        if not self._is_enabled(rule_id):
            return None
        p = self._params(rule_id)

        sample_count = int(stats.get("sample_count", 0) or 0)
        missing_count = int(stats.get("missing_count", 0) or 0)
        num_signals = int(stats.get("num_signals", 1) or 1)

        denom = max(sample_count * max(num_signals, 1), 1)
        ratio = missing_count / denom

        if ratio > p["missing_ratio_high"]:
            return _trigger(
                rule_id,
                self._severity(rule_id),
                {
                    "missing_ratio": ratio,
                    "missing_count": missing_count,
                    "sample_count": sample_count,
                    "num_signals": num_signals,
                    "thresholds": p,
                },
                "High missing data ratio in window.",
            )
        return None

    def _out_of_range(self, f: Dict[str, float]) -> Optional[Trigger]:
        rule_id = "OUT_OF_RANGE_VALUES"
        if not self._is_enabled(rule_id):
            return None
        p = self._params(rule_id)

        if not p.get("use_signal_bounds", True):
            return None

        offenders: Dict[str, Any] = {}

        for sig, meta in self.signal_bounds.items():
            lo, hi = meta.get("min"), meta.get("max")
            mn = f.get(f"{sig}_min")
            mx = f.get(f"{sig}_max")

            if mn is not None and lo is not None and mn < lo:
                offenders[f"{sig}_min"] = {"value": mn, "min": lo, "max": hi}
            if mx is not None and hi is not None and mx > hi:
                offenders[f"{sig}_max"] = {"value": mx, "min": lo, "max": hi}

        if offenders:
            return _trigger(
                rule_id,
                self._severity(rule_id),
                {"offenders": offenders},
                "One or more signals exceeded configured bounds.",
            )
        return None
