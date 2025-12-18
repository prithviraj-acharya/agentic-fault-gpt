from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

import numpy as np

Number = Union[int, float]


def _clamp(value: Number, low: Number, high: Number) -> Number:
    return max(low, min(high, value))


def _minutes_since_midnight(dt: datetime) -> float:
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.hour * 60 + dt.minute + dt.second / 60.0


@dataclass(frozen=True)
class NormalConfig:
    sa_temp_sp_c: float = 14.0
    min_oa_damper_pct: float = 20.0
    base_fan_speed_pct: float = 60.0

    # Dynamics (behavioral, not physical)
    zone_temp_setpoint_c: float = 24.0
    zone_temp_tau_sec: float = 45.0 * 60.0  # relax toward setpoint over ~45 min

    # Noise scales
    temp_noise_sigma_c: float = 0.15
    damper_noise_sigma_pct: float = 1.0
    valve_noise_sigma_pct: float = 1.5
    fan_noise_sigma_pct: float = 0.8


@dataclass
class NormalState:
    avg_zone_temp_c: float = 24.0


class NormalProfile:
    """Behavioral 'normal operation' AHU profile.

    The simulator is expected to call `step()` once per timestep.
    Output keys follow docs/specifications/simulation/telemetry_schema.md.
    """

    def __init__(
        self,
        config: Optional[NormalConfig] = None,
        state: Optional[NormalState] = None,
    ) -> None:
        self.config = config or NormalConfig()
        self.state = state or NormalState()

    def reset(self, *, start_time: datetime, rng: np.random.Generator) -> None:
        # Start zone temp near setpoint with small variation.
        self.state.avg_zone_temp_c = float(
            self.config.zone_temp_setpoint_c + rng.normal(0.0, 0.3)
        )

    def step(
        self,
        *,
        timestamp: datetime,
        dt_seconds: int,
        rng: np.random.Generator,
    ) -> Dict[str, Any]:
        cfg = self.config

        # Outside air temperature: simple diurnal pattern + noise.
        minutes = _minutes_since_midnight(timestamp)
        day_phase = 2.0 * np.pi * (minutes / (24.0 * 60.0))
        oa_temp_c = 26.0 + 6.0 * float(np.sin(day_phase - np.pi / 2.0))
        oa_temp_c += float(rng.normal(0.0, cfg.temp_noise_sigma_c))
        oa_temp_c = float(_clamp(oa_temp_c, 10.0, 45.0))

        # Zone temperature: relax toward zone setpoint, mild random walk.
        alpha = 1.0 - float(np.exp(-dt_seconds / cfg.zone_temp_tau_sec))
        self.state.avg_zone_temp_c = float(
            (1.0 - alpha) * self.state.avg_zone_temp_c
            + alpha * cfg.zone_temp_setpoint_c
            + rng.normal(0.0, cfg.temp_noise_sigma_c * 0.25)
        )
        avg_zone_temp_c = float(_clamp(self.state.avg_zone_temp_c, 20.0, 28.0))

        # Return air temp: near zone temp.
        ra_temp_c = float(
            _clamp(
                avg_zone_temp_c + rng.normal(0.0, cfg.temp_noise_sigma_c),
                18.0,
                30.0,
            )
        )

        # Damper positions: maintain minimum OA, return complements to ~100.
        oa_damper_pct = float(
            _clamp(
                cfg.min_oa_damper_pct + rng.normal(0.0, cfg.damper_noise_sigma_pct),
                0.0,
                100.0,
            )
        )
        ra_damper_pct = float(_clamp(100.0 - oa_damper_pct, 0.0, 100.0))

        oa_frac = oa_damper_pct / max(1e-9, (oa_damper_pct + ra_damper_pct))
        ra_frac = 1.0 - oa_frac

        # Mixed air temperature: behavioral mix.
        ma_temp_c = float(
            _clamp(
                (oa_frac * oa_temp_c + ra_frac * ra_temp_c)
                + rng.normal(0.0, cfg.temp_noise_sigma_c * 0.5),
                min(oa_temp_c, ra_temp_c),
                max(oa_temp_c, ra_temp_c),
            )
        )

        # Supply air setpoint: stable setpoint with tiny jitter.
        sa_temp_sp_c = float(
            _clamp(cfg.sa_temp_sp_c + rng.normal(0.0, 0.05), 12.0, 18.0)
        )

        # Cooling demand is higher when mixed air is warmer than setpoint.
        demand = float(_clamp((ma_temp_c - sa_temp_sp_c) / 10.0, 0.0, 1.0))

        cc_valve_pct = float(
            _clamp(
                15.0 + 85.0 * demand + rng.normal(0.0, cfg.valve_noise_sigma_pct),
                0.0,
                100.0,
            )
        )

        # Supply air temperature approaches setpoint as valve opens.
        effectiveness = 0.15 + 0.8 * (cc_valve_pct / 100.0)
        sa_temp_c = float(ma_temp_c - effectiveness * (ma_temp_c - sa_temp_sp_c))
        sa_temp_c += float(rng.normal(0.0, cfg.temp_noise_sigma_c * 0.4))
        sa_temp_c = float(_clamp(sa_temp_c, 10.0, 20.0))

        # Fan speed: base + modest increase with demand.
        sa_fan_speed_pct = float(
            _clamp(
                cfg.base_fan_speed_pct
                + 25.0 * demand
                + rng.normal(0.0, cfg.fan_noise_sigma_pct),
                0.0,
                100.0,
            )
        )

        return {
            "oa_temp": round(oa_temp_c, 3),
            "ra_temp": round(ra_temp_c, 3),
            "ma_temp": round(ma_temp_c, 3),
            "sa_temp": round(sa_temp_c, 3),
            "sa_temp_sp": round(sa_temp_sp_c, 3),
            "avg_zone_temp": round(avg_zone_temp_c, 3),
            "cc_valve": round(cc_valve_pct, 3),
            "oa_damper": round(oa_damper_pct, 3),
            "ra_damper": round(ra_damper_pct, 3),
            "sa_fan_speed": round(sa_fan_speed_pct, 3),
        }
