from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

import numpy as np

from simulation.utils import FaultEpisode, effective_magnitude


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def apply_cooling_coil_fault(
    row: Dict[str, Any],
    *,
    episode: FaultEpisode,
    timestamp: datetime,
    rng: np.random.Generator,
) -> Dict[str, Any]:
    """Cooling coil fault: reduced cooling effectiveness.

    Behavioral effect:
    - Control tries to compensate by opening cc_valve.
    - Supply air temperature doesn't reach setpoint as well.
    - Zone temperature drifts slightly upward over the episode.

    Expected inputs in row: ma_temp, sa_temp_sp, cc_valve, sa_temp, avg_zone_temp
    All units follow telemetry schema (°C, %).
    """

    # Fault is disabled when magnitude is 0.
    if episode.magnitude <= 0.0:
        return row

    # Convert the scenario's episode magnitude into an "effective" magnitude at this
    # timestamp (supports optional ramp-in via fault_params.ramp_minutes).
    magnitude = effective_magnitude(episode, timestamp=timestamp)
    # Scenario can provide an absolute effectiveness factor in [0,1].
    # Lower means worse cooling.
    param_eff = float(episode.fault_params.get("cooling_effectiveness", 0.3))
    param_eff = _clamp(param_eff, 0.0, 1.0)

    ma_temp = float(row["ma_temp"])
    sa_sp = float(row["sa_temp_sp"])
    cc_valve = float(row["cc_valve"])
    sa_temp = float(row["sa_temp"])
    avg_zone_temp = float(row["avg_zone_temp"])

    # (1) Controller compensation signal:
    # With reduced cooling effectiveness, the controller would typically try to open
    # the cooling coil valve further to compensate.
    cc_valve_faulty = _clamp(
        cc_valve + (100.0 - cc_valve) * (0.75 * magnitude), 0.0, 100.0
    )

    # (2) Thermal effect on supply air temperature:
    # Baseline behavior: sa_temp is already between ma_temp and setpoint.
    # This fault reduces how much sa_temp can approach the setpoint.
    # We estimate "progress" from MA -> SP and then reduce that progress depending
    # on magnitude and a configurable effectiveness factor.
    baseline_progress = 0.0
    denom = ma_temp - sa_sp
    if abs(denom) > 1e-9:
        baseline_progress = _clamp((ma_temp - sa_temp) / denom, 0.0, 1.0)

    degraded_progress = baseline_progress * (1.0 - magnitude) + baseline_progress * (
        param_eff * magnitude
    )
    degraded_progress = _clamp(degraded_progress, 0.0, 1.0)
    sa_temp_faulty = ma_temp - degraded_progress * (ma_temp - sa_sp)
    # Add a small sensor/plant noise so the trace is less "too perfect".
    sa_temp_faulty += float(rng.normal(0.0, 0.08))
    sa_temp_faulty = _clamp(sa_temp_faulty, 10.0, 20.0)

    # (3) Downstream zone impact:
    # When supply air isn't cooled enough, zones tend to warm. We add a small
    # uplift that increases through the episode duration.
    total_sec = max(1.0, (episode.end_time - episode.start_time).total_seconds())
    elapsed_sec = _clamp(
        (timestamp - episode.start_time).total_seconds(), 0.0, total_sec
    )
    ramp = elapsed_sec / total_sec
    zone_uplift_c = 0.8 * magnitude * ramp  # up to ~0.8C by the end at magnitude=1
    avg_zone_temp_faulty = _clamp(avg_zone_temp + zone_uplift_c, 20.0, 28.0)

    out = dict(row)
    out["cc_valve"] = round(cc_valve_faulty, 3)
    out["sa_temp"] = round(sa_temp_faulty, 3)
    out["avg_zone_temp"] = round(avg_zone_temp_faulty, 3)
    return out
