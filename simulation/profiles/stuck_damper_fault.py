from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

import numpy as np

from simulation.utils import FaultEpisode, effective_magnitude


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def apply_stuck_damper_fault(
    row: Dict[str, Any],
    *,
    episode: FaultEpisode,
    timestamp: datetime,
    rng: np.random.Generator,
) -> Dict[str, Any]:
    """Stuck damper fault.

    Behavioral effect:
    - Forces one damper (oa_damper or ra_damper) to a stuck value.
    - Recomputes the complementary damper.
    - Recomputes mixed air temperature, then adjusts cc_valve/sa_temp/fan
      in a simple control-consistent way.
    """

    # Fault is disabled when magnitude is 0.
    if episode.magnitude <= 0.0:
        return row

    # Convert the scenario's episode magnitude into an "effective" magnitude at this
    # timestamp (supports optional ramp-in via fault_params.ramp_minutes).
    magnitude = effective_magnitude(episode, timestamp=timestamp)

    # Scenario knobs:
    # - damper: which damper is stuck (oa_damper or ra_damper)
    # - stuck_value: stuck position in percent (0..100)
    damper_name = str(episode.fault_params.get("damper", "oa_damper"))
    stuck_value = float(episode.fault_params.get("stuck_value", 100.0))
    stuck_value = _clamp(stuck_value, 0.0, 100.0)

    oa_temp = float(row["oa_temp"])
    ra_temp = float(row["ra_temp"])
    sa_sp = float(row["sa_temp_sp"])

    oa_damper = float(row["oa_damper"])
    ra_damper = float(row["ra_damper"])

    # (1) Mechanical fault effect:
    # Blend the selected damper toward its stuck position based on magnitude.
    # At magnitude=1 the damper snaps to stuck_value; at magnitude=0 no change.
    #
    # (Simplification) We force OA% + RA% = 100%.
    if damper_name == "oa_damper":
        oa_damper_faulty = _clamp(
            oa_damper + (stuck_value - oa_damper) * magnitude, 0.0, 100.0
        )
        ra_damper_faulty = _clamp(100.0 - oa_damper_faulty, 0.0, 100.0)
    elif damper_name == "ra_damper":
        ra_damper_faulty = _clamp(
            ra_damper + (stuck_value - ra_damper) * magnitude, 0.0, 100.0
        )
        oa_damper_faulty = _clamp(100.0 - ra_damper_faulty, 0.0, 100.0)
    else:
        # Unknown damper name; do nothing rather than silently corrupt.
        return row

    # (2) Mixing impact:
    # With the damper stuck, the outside-air fraction changes, so the mixed-air
    # temperature shifts toward OA temp (if OA damper stuck open) or toward RA temp
    # (if OA damper stuck closed / RA damper stuck open).
    oa_frac = oa_damper_faulty / 100.0
    ma_temp = oa_frac * oa_temp + (1.0 - oa_frac) * ra_temp
    ma_temp += float(rng.normal(0.0, 0.12))

    # (3) Simple controller response:
    # If mixed air is warmer than the supply setpoint, we create a "demand" signal
    # that increases cooling valve position and slightly increases fan speed.
    demand = _clamp((ma_temp - sa_sp) / 10.0, 0.0, 1.0)
    cc_valve = _clamp(15.0 + 85.0 * demand + float(rng.normal(0.0, 1.2)), 0.0, 100.0)

    effectiveness = 0.15 + 0.8 * (cc_valve / 100.0)
    sa_temp = ma_temp - effectiveness * (ma_temp - sa_sp)
    sa_temp += float(rng.normal(0.0, 0.10))
    sa_temp = _clamp(sa_temp, 10.0, 20.0)

    # Fan response is scaled by fault magnitude so that stronger faults tend to
    # drive stronger compensation signals.
    sa_fan_speed = _clamp(
        float(row["sa_fan_speed"])
        + 15.0 * demand * magnitude
        + float(rng.normal(0.0, 0.7)),
        0.0,
        100.0,
    )

    out = dict(row)
    out["oa_damper"] = round(oa_damper_faulty, 3)
    out["ra_damper"] = round(ra_damper_faulty, 3)
    out["ma_temp"] = round(ma_temp, 3)
    out["cc_valve"] = round(cc_valve, 3)
    out["sa_temp"] = round(sa_temp, 3)
    out["sa_fan_speed"] = round(sa_fan_speed, 3)
    return out
