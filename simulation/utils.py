from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Tuple

PHASE2_FAULT_TYPES: set[str] = {
    "cooling_coil_fault",
    "stuck_damper_fault",
    "zone_temp_sensor_drift",
    "normal_operation",
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def effective_magnitude(episode: "FaultEpisode", *, timestamp: datetime) -> float:
    """Compute effective fault magnitude at a given timestamp.

    Supports optional per-episode ramp-in:
    - fault_params.ramp_minutes (float, default 0)

    If ramp_minutes > 0, magnitude scales linearly from 0 to full magnitude
    over the first ramp_minutes of the episode.
    """

    base = _clamp(float(episode.magnitude), 0.0, 1.0)
    ramp_minutes = float(episode.fault_params.get("ramp_minutes", 0.0))
    if ramp_minutes <= 0.0:
        return base

    ramp_seconds = ramp_minutes * 60.0
    elapsed_seconds = (timestamp - episode.start_time).total_seconds()
    ramp = _clamp(elapsed_seconds / ramp_seconds, 0.0, 1.0)
    return base * ramp


def parse_iso8601(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp.

    Supports trailing 'Z' for UTC.
    Always returns a timezone-aware datetime normalized to UTC.
    """

    if not isinstance(ts, str) or not ts:
        raise ValueError("Timestamp must be a non-empty string")
    normalized = ts.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def isoformat_z(dt: datetime) -> str:
    """Format datetime as ISO-8601 with trailing 'Z' (UTC)."""

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (
        dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def shift_window_and_episodes_to_start(
    *,
    start_time: datetime,
    end_time: datetime,
    episodes: List["FaultEpisode"],
    new_start_time: datetime,
) -> Tuple[datetime, datetime, List["FaultEpisode"]]:
    """Shift the scenario window and fault episode windows by a constant delta.

    This keeps the relative offsets between episodes and the scenario window,
    but re-anchors the whole run at a new start time (e.g. current time).
    """

    if new_start_time.tzinfo is None:
        new_start_time = new_start_time.replace(tzinfo=timezone.utc)
    new_start_time = new_start_time.astimezone(timezone.utc).replace(microsecond=0)

    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    start_time = start_time.astimezone(timezone.utc).replace(microsecond=0)

    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone.utc)
    end_time = end_time.astimezone(timezone.utc).replace(microsecond=0)

    delta = new_start_time - start_time

    shifted_start = new_start_time
    shifted_end = end_time + delta

    shifted_episodes: List[FaultEpisode] = []
    for ep in episodes:
        shifted_episodes.append(
            FaultEpisode(
                episode_id=ep.episode_id,
                fault_type=ep.fault_type,
                start_time=ep.start_time + delta,
                end_time=ep.end_time + delta,
                magnitude=ep.magnitude,
                target_signals=list(ep.target_signals),
                fault_params=dict(ep.fault_params),
                description=ep.description,
            )
        )

    return shifted_start, shifted_end, shifted_episodes


@dataclass(frozen=True)
class FaultEpisode:
    episode_id: str
    fault_type: str
    start_time: datetime
    end_time: datetime
    magnitude: float
    target_signals: List[str]
    fault_params: Dict[str, Any]
    description: str


def parse_fault_episodes(raw: Any) -> List[FaultEpisode]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("fault_episodes must be a list")

    episodes: List[FaultEpisode] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Each fault episode must be an object")

        target_signals = item.get("target_signals", [])
        if not isinstance(target_signals, list) or not all(
            isinstance(s, str) for s in target_signals
        ):
            raise ValueError("fault episode target_signals must be a list of strings")

        magnitude = float(item.get("magnitude", 0.0))
        if not (0.0 <= magnitude <= 1.0):
            raise ValueError("fault episode magnitude must be within [0.0, 1.0]")

        fault_type = str(item.get("fault_type", ""))
        if fault_type and fault_type not in PHASE2_FAULT_TYPES:
            raise ValueError(
                f"Unsupported fault_type '{fault_type}' (Phase 2 supported: {sorted(PHASE2_FAULT_TYPES)})"
            )

        fault_params = dict(item.get("fault_params", {}))
        if "ramp_minutes" in fault_params:
            ramp_minutes = float(fault_params["ramp_minutes"])
            if ramp_minutes < 0.0:
                raise ValueError("fault_params.ramp_minutes must be >= 0")

        episodes.append(
            FaultEpisode(
                episode_id=str(item.get("episode_id", "")),
                fault_type=fault_type,
                start_time=parse_iso8601(str(item.get("start_time", ""))),
                end_time=parse_iso8601(str(item.get("end_time", ""))),
                magnitude=magnitude,
                target_signals=list(target_signals),
                fault_params=fault_params,
                description=str(item.get("description", "")),
            )
        )
    return episodes


def validate_non_overlapping(
    episodes: Iterable[FaultEpisode],
    *,
    allow_touching_boundaries: bool = True,
) -> None:
    eps = sorted(episodes, key=lambda e: e.start_time)
    for i in range(len(eps)):
        e = eps[i]
        if e.episode_id == "" or e.fault_type == "":
            raise ValueError("Each fault episode must have episode_id and fault_type")
        if e.end_time <= e.start_time:
            raise ValueError(f"Fault episode {e.episode_id} has end_time <= start_time")
        if i == 0:
            continue
        prev = eps[i - 1]
        if allow_touching_boundaries:
            overlap = e.start_time < prev.end_time
        else:
            overlap = e.start_time <= prev.end_time
        if overlap:
            raise ValueError(
                f"Fault episodes overlap: {prev.episode_id} ({isoformat_z(prev.start_time)}..{isoformat_z(prev.end_time)}) "
                f"and {e.episode_id} ({isoformat_z(e.start_time)}..{isoformat_z(e.end_time)})"
            )


def validate_scenario(
    scenario: Dict[str, Any],
) -> Tuple[datetime, datetime, int, List[FaultEpisode]]:
    required = [
        "run_id",
        "scenario_name",
        "ahu_id",
        "start_time",
        "end_time",
        "sampling_interval_sec",
        "seed",
        "signals",
    ]
    missing = [k for k in required if k not in scenario]
    if missing:
        raise ValueError(f"Scenario missing required keys: {missing}")

    start = parse_iso8601(str(scenario["start_time"]))
    end = parse_iso8601(str(scenario["end_time"]))
    if end <= start:
        raise ValueError("end_time must be after start_time")

    interval = int(scenario["sampling_interval_sec"])
    if interval <= 0:
        raise ValueError("sampling_interval_sec must be > 0")

    signals = scenario.get("signals")
    if not isinstance(signals, list) or not signals:
        raise ValueError("signals must be a non-empty list")

    episodes = parse_fault_episodes(scenario.get("fault_episodes", []))
    validate_non_overlapping(episodes, allow_touching_boundaries=True)
    for ep in episodes:
        if ep.start_time < start or ep.end_time > end:
            raise ValueError(
                f"Fault episode {ep.episode_id} must fall within scenario window ({isoformat_z(start)}..{isoformat_z(end)})"
            )

    return start, end, interval, episodes
