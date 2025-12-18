from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

import numpy as np
import pandas as pd

from simulation.profiles.cooling_coil_fault import apply_cooling_coil_fault
from simulation.profiles.normal import NormalProfile
from simulation.profiles.stuck_damper_fault import apply_stuck_damper_fault
from simulation.profiles.zone_temp_drift_fault import apply_zone_temp_sensor_drift
from simulation.utils import FaultEpisode, isoformat_z, validate_scenario


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_and_validate_scenario(
    *, scenario_path: Path
) -> Tuple[Dict[str, Any], datetime, datetime, int, List[FaultEpisode]]:
    """Load a scenario JSON file and return the normalized, validated runtime inputs."""

    scenario = _load_json(scenario_path)
    start_time, end_time, interval_sec, episodes = validate_scenario(scenario)
    return scenario, start_time, end_time, interval_sec, episodes


def _select_active_episode(
    episodes: List[FaultEpisode], ts: datetime
) -> FaultEpisode | None:
    # Decide whether a fault episode is active at the current simulation timestamp.
    #
    # Time-window rule (half-open interval):
    #   start_time is inclusive, end_time is exclusive
    #   i.e., active when: start_time <= ts < end_time
    # This means the fault starts exactly at start_time and stops exactly at end_time.
    #
    # Phase 2 rule: at most one active episode at a time (validated as non-overlapping)
    # so we can return the first match.
    for ep in episodes:
        if ep.start_time <= ts < ep.end_time:
            return ep
    return None


def iter_telemetry_events(
    *,
    scenario: Dict[str, Any],
    start_time: datetime,
    end_time: datetime,
    interval_sec: int,
    episodes: List[FaultEpisode],
) -> Iterator[Dict[str, Any]]:
    """Yield one telemetry event per timestep.

    This is the shared "source of truth" for row generation, used by both:
    - the offline simulator (CSV/metadata)
    - the streaming producer (local print / Kafka)
    """

    rng = np.random.default_rng(int(scenario["seed"]))
    profile = NormalProfile()
    profile.reset(start_time=start_time, rng=rng)

    ahu_id = scenario["ahu_id"]

    ts = start_time
    dt = timedelta(seconds=interval_sec)
    while ts < end_time:
        active_episode = _select_active_episode(episodes, ts)
        row = profile.step(timestamp=ts, dt_seconds=interval_sec, rng=rng)

        if active_episode is not None:
            if active_episode.fault_type == "cooling_coil_fault":
                row = apply_cooling_coil_fault(
                    row, episode=active_episode, timestamp=ts, rng=rng
                )
            elif active_episode.fault_type == "stuck_damper_fault":
                row = apply_stuck_damper_fault(
                    row, episode=active_episode, timestamp=ts, rng=rng
                )
            elif active_episode.fault_type == "zone_temp_sensor_drift":
                row = apply_zone_temp_sensor_drift(
                    row, episode=active_episode, timestamp=ts, rng=rng
                )
            elif active_episode.fault_type == "normal_operation":
                pass
            else:
                raise ValueError(f"Unhandled fault_type: {active_episode.fault_type}")

        row = dict(row)
        row["timestamp"] = isoformat_z(ts)
        row["ahu_id"] = ahu_id
        yield row

        ts = ts + dt


def build_metadata(
    *,
    scenario: Dict[str, Any],
    scenario_path: Path,
    start_time: datetime,
    end_time: datetime,
    interval_sec: int,
    episodes: List[FaultEpisode],
) -> Dict[str, Any]:
    return {
        "run_id": scenario["run_id"],
        "scenario_name": scenario["scenario_name"],
        "ahu_id": scenario["ahu_id"],
        "start_time": isoformat_z(start_time),
        "end_time": isoformat_z(end_time),
        "sampling_interval_sec": interval_sec,
        "seed": int(scenario["seed"]),
        "signals": list(scenario["signals"]),
        "notes": scenario.get("notes", ""),
        "fault_episodes": [
            asdict(ep)
            | {
                "start_time": isoformat_z(ep.start_time),
                "end_time": isoformat_z(ep.end_time),
            }
            for ep in episodes
        ],
        "scenario_source": str(scenario_path.as_posix()),
    }


def run_scenario(*, scenario_path: Path, output_dir: Path) -> Dict[str, Path]:
    scenario, start_time, end_time, interval_sec, episodes = load_and_validate_scenario(
        scenario_path=scenario_path
    )
    signals: List[str] = list(scenario["signals"])
    run_id = str(scenario["run_id"])

    rows = list(
        iter_telemetry_events(
            scenario=scenario,
            start_time=start_time,
            end_time=end_time,
            interval_sec=interval_sec,
            episodes=episodes,
        )
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    telemetry_path = output_dir / f"{run_id}_telemetry.csv"
    metadata_path = output_dir / f"{run_id}_metadata.json"

    df = pd.DataFrame(rows)
    # Ensure requested signals exist and preserve ordering
    missing = [s for s in signals if s not in df.columns]
    if missing:
        raise ValueError(
            f"Scenario signals include fields not produced by simulator: {missing}"
        )
    df = df[signals]
    df.to_csv(telemetry_path, index=False)

    metadata = build_metadata(
        scenario=scenario,
        scenario_path=scenario_path,
        start_time=start_time,
        end_time=end_time,
        interval_sec=interval_sec,
        episodes=episodes,
    )
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return {"telemetry": telemetry_path, "metadata": metadata_path}


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 2 AHU behavioral simulator")
    parser.add_argument(
        "--scenario",
        required=True,
        type=Path,
        help="Path to scenario JSON (e.g. simulation/scenarios/scenario_v1.json)",
    )
    parser.add_argument(
        "--out",
        default=Path("data/generated"),
        type=Path,
        help="Output directory (default: data/generated)",
    )
    args = parser.parse_args(argv)

    # Resolve relative paths from repo root (current working dir)
    scenario_path = args.scenario
    if not scenario_path.is_absolute():
        scenario_path = Path.cwd() / scenario_path
    out_dir = args.out
    if not out_dir.is_absolute():
        out_dir = Path.cwd() / out_dir

    outputs = run_scenario(scenario_path=scenario_path, output_dir=out_dir)
    print(f"Wrote telemetry: {outputs['telemetry']}")
    print(f"Wrote metadata: {outputs['metadata']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
