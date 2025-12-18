from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

import numpy as np

from simulation.utils import FaultEpisode, effective_magnitude


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def apply_zone_temp_sensor_drift(
    row: Dict[str, Any],
    *,
    episode: FaultEpisode,
    timestamp: datetime,
    rng: np.random.Generator,
) -> Dict[str, Any]:
    """Zone temperature sensor drift fault.

    This is a *sensor fault*:
    - Only modifies the reported avg_zone_temp.
    - Does not affect actual control signals.

    Scenario param:
    - drift_c_per_hour (float): drift rate in °C/hour.

    Magnitude scales the drift (0..1).
    """

    # Fault is disabled when magnitude is 0.
    if episode.magnitude <= 0.0:
        return row

    # Convert the scenario's episode magnitude into an "effective" magnitude at this
    # timestamp (supports optional ramp-in via fault_params.ramp_minutes).
    magnitude = effective_magnitude(episode, timestamp=timestamp)
    # Scenario knob: drift rate in °C/hour (magnitude scales this rate).
    drift_c_per_hour = float(episode.fault_params.get("drift_c_per_hour", 0.5))

    # (1) Drift accumulates over time since episode start:
    # This models a sensor that slowly deviates rather than an abrupt offset.
    elapsed_hours = max(0.0, (timestamp - episode.start_time).total_seconds() / 3600.0)
    drift_c = drift_c_per_hour * elapsed_hours * magnitude
    # Tiny noise so drift isn't perfectly linear.
    drift_c += float(rng.normal(0.0, 0.02))

    # (2) This is a sensor fault: only the *reported* avg_zone_temp changes.
    # We intentionally do not modify control/plant variables here.
    avg_zone_temp = float(row["avg_zone_temp"])
    avg_zone_temp_faulty = _clamp(avg_zone_temp + drift_c, 20.0, 28.0)

    out = dict(row)
    out["avg_zone_temp"] = round(avg_zone_temp_faulty, 3)
    return out
