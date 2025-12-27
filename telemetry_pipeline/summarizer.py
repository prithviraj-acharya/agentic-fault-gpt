from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Mapping, Optional, Sequence

from simulation.utils import isoformat_z
from telemetry_pipeline.windowing import Window, deterministic_window_id


def compute_signature(rule_ids: List[str]) -> str:
    """Deterministic behavior fingerprint from triggered rule IDs."""

    payload = "|".join(sorted({str(r) for r in rule_ids if r}))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _fmt(v: Optional[float], *, digits: int = 2) -> str:
    if v is None:
        return "n/a"
    return f"{float(v):.{digits}f}"


def build_text_summary(
    window: Window,
    *,
    features: Mapping[str, float],
    anomalies: Sequence[Mapping[str, Any]],
    signature: str,
) -> str:
    start = isoformat_z(window.start)
    end = isoformat_z(window.end)

    highlights = []
    for key, digits in (
        ("sa_temp_mean", 2),
        ("sa_temp_mean_minus_sp", 2),
        ("cc_valve_mean", 1),
        ("avg_zone_temp_mean", 2),
    ):
        if key in features:
            highlights.append(f"{key}={_fmt(features.get(key), digits=digits)}")

    rules = [str(a.get("rule_id", "")) for a in anomalies if isinstance(a, Mapping)]
    rules = [r for r in rules if r]
    rules_str = ",".join(sorted(rules)) if rules else "none"

    hl = ", ".join(highlights) if highlights else "no feature highlights"
    return (
        f"AHU {window.ahu_id} window {start}–{end}: {hl}. "
        f"anomalies={rules_str}. signature={signature}"
    )


def build_window_summary(
    *,
    window: Window,
    features: Dict[str, float],
    anomalies: List[Dict[str, Any]],
    config_fingerprint: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    rule_ids = [a.get("rule_id", "") for a in anomalies if isinstance(a, dict)]
    signature = compute_signature([str(r) for r in rule_ids])

    summary: Dict[str, Any] = {
        "window_id": deterministic_window_id(window),
        "ahu_id": window.ahu_id,
        "time": {
            "start": isoformat_z(window.start),
            "end": isoformat_z(window.end),
            "window_type": window.window_type,
            "window_size_sec": int(window.window_size_sec),
            "step_sec": window.step_sec,
        },
        "stats": dict(window.stats),
        "features": dict(features),
        "anomalies": list(anomalies),
        "signature": signature,
        "text_summary": build_text_summary(
            window, features=features, anomalies=anomalies, signature=signature
        ),
    }

    if config_fingerprint is not None:
        summary["provenance"] = {"config": dict(config_fingerprint)}

    return summary
