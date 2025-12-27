from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

import numpy as np

from telemetry_pipeline.windowing import Window


def _safe_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
    except Exception:
        return None
    if np.isnan(v):
        return None
    return v


def _linear_slope_per_minute(
    times_s: np.ndarray, values: np.ndarray
) -> Optional[float]:
    if times_s.size < 2 or values.size < 2:
        return None
    # Normalize time to start at 0 to improve numerical stability.
    t0 = times_s[0]
    x_min = (times_s - t0) / 60.0
    try:
        m, _b = np.polyfit(x_min, values, 1)
    except Exception:
        return None
    return float(m)


def _delta(values: np.ndarray) -> Optional[float]:
    if values.size < 2:
        return None
    return float(values[-1] - values[0])


def _mean(values: np.ndarray) -> Optional[float]:
    if values.size == 0:
        return None
    return float(np.mean(values))


def _var(values: np.ndarray) -> Optional[float]:
    if values.size == 0:
        return None
    return float(np.var(values))


def _min(values: np.ndarray) -> Optional[float]:
    if values.size == 0:
        return None
    return float(np.min(values))


def _max(values: np.ndarray) -> Optional[float]:
    if values.size == 0:
        return None
    return float(np.max(values))


def _parse_simple_expr(expr: str) -> Tuple[str, str, str]:
    """Parse an extremely small expression grammar: 'a - b' or 'a + b'."""

    e = expr.strip()
    if "-" in e:
        left, right = e.split("-", 1)
        return left.strip(), "-", right.strip()
    if "+" in e:
        left, right = e.split("+", 1)
        return left.strip(), "+", right.strip()
    raise ValueError(f"Unsupported expr: {expr!r}")


def extract_features(
    window: Window, *, signals_cfg: Mapping[str, Any]
) -> Dict[str, float]:
    """Compute a flat deterministic feature dict for the window."""

    cfg = dict(signals_cfg)
    signals_meta = dict(cfg.get("signals", {}))
    feature_cfg = dict(cfg.get("features", {}))

    per_signal_cfg = dict(feature_cfg.get("per_signal", {}))
    stats: List[str] = list(
        per_signal_cfg.get("stats", ["mean", "var", "slope", "delta"])
    )

    # Build per-signal series (skip missing values).
    features: Dict[str, float] = {}

    # Reference times in seconds from epoch.
    times_s_all = np.array(
        [ev.timestamp.timestamp() for ev in window.events], dtype=float
    )

    for sig in signals_meta.keys():
        vals: List[float] = []
        times_s: List[float] = []
        for i, ev in enumerate(window.events):
            v = _safe_float(ev.signals.get(sig))
            if v is None:
                continue
            vals.append(v)
            times_s.append(float(times_s_all[i]))

        v_arr = np.array(vals, dtype=float)
        t_arr = np.array(times_s, dtype=float)

        if "mean" in stats:
            m = _mean(v_arr)
            if m is not None:
                features[f"{sig}_mean"] = m
        if "var" in stats:
            vv = _var(v_arr)
            if vv is not None:
                features[f"{sig}_var"] = vv
        if "std" in stats:
            vv = _var(v_arr)
            if vv is not None:
                features[f"{sig}_std"] = float(np.sqrt(vv))
        if "min" in stats:
            mn = _min(v_arr)
            if mn is not None:
                features[f"{sig}_min"] = mn
        if "max" in stats:
            mx = _max(v_arr)
            if mx is not None:
                features[f"{sig}_max"] = mx
        if "delta" in stats:
            d = _delta(v_arr)
            if d is not None:
                features[f"{sig}_delta"] = d
        if "slope" in stats:
            s = _linear_slope_per_minute(t_arr, v_arr)
            if s is not None:
                features[f"{sig}_slope"] = s

    # Cross-signal features: declared and explicit, not arbitrary eval.
    for item in list(feature_cfg.get("cross_signal", []) or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        expr = str(item.get("expr", "")).strip()
        if not name or not expr:
            continue

        try:
            left, op, right = _parse_simple_expr(expr)
        except Exception:
            continue

        lv = features.get(left)
        rv = features.get(right)
        if lv is None or rv is None:
            continue

        if op == "-":
            features[name] = float(lv - rv)
        elif op == "+":
            features[name] = float(lv + rv)

    return features
