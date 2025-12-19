# Simulation Overview — Phase 2

## Purpose

This document provides a high-level overview of the Phase 2 AHU behavioral simulator:

- what it generates
- how scenarios control timing + faults
- how to run it (offline files, local streaming, Kafka streaming)

---

## Outputs

A run produces:

- Telemetry (row/event stream): `data/generated/<run_id>_telemetry.csv`
- Run metadata (ground truth configuration): `data/generated/<run_id>_metadata.json`

Telemetry contains no explicit fault labels. Fault “ground truth” is captured only in metadata.

---

## Scenario-Driven Simulation

Scenarios live in `simulation/scenarios/` and define:

- Simulation window: `start_time`, `end_time`
- Sampling cadence: `sampling_interval_sec`
- Determinism: `seed`
- Output columns/order: `signals`
- Fault schedule: `fault_episodes`

### Time and sampling

The simulator generates one telemetry event per timestep.
If `sampling_interval_sec = 60`, timestamps increment by 60 seconds each event.

### Fault scheduling

Faults are injected using time windows. An episode is active when:

- `episode.start_time <= timestamp < episode.end_time`

Phase 2 assumes fault episodes are non-overlapping (at most one active at a time).

See:

- `docs/specifications/simulation/fault_episode_spec.md`

---

## Streaming vs Offline

### Offline (CSV + metadata only)

Use when you want files but no streaming:

- `python -m simulation.simulator --scenario simulation/scenarios/scenario_v1.json --out data/generated`

### Streaming (scenario -> events)

Use when you want an event stream and also want files written:

- Local stdout (JSON lines):

  - `python -m simulation.producer --scenario simulation/scenarios/scenario_v1.json --mode local --out data/generated`

- Kafka:
  - `python -m simulation.producer --scenario simulation/scenarios/scenario_v1.json --mode kafka --bootstrap-servers localhost:9092 --topic ahu.telemetry --out data/generated`

---

## Replay Timing Controls (Producer)

The producer can control wall-clock pacing independently from the event timestamps.

- `--speed`

  - `1.0` = replay using real-time gaps between event timestamps
  - `0` = no sleeping (as fast as possible)

- `--emit-interval-s`
  - If set to `> 0`, emits events with a fixed delay between events.
  - Overrides timestamp-based pacing.

---

## “Start Now” Runs (Shift Scenario Timeline)

By default, scenarios define absolute timestamps.
For demo and live-like streaming, the producer supports shifting the scenario timeline to start at current UTC time:

- `--start-now`

This shifts:

- the simulation window (`start_time` / `end_time`)
- all fault episode windows

by the same constant offset, preserving the same fault offsets (e.g., +90 minutes after run start).

Note: This affects generated timestamps and metadata; it does not modify the scenario JSON on disk.

---

## Operational Notes

- UTC timestamps are recommended for event-time processing and reproducibility.
- For demo readability, keep timestamps in UTC and render local time in presentation layers (e.g., consumer output/UI).

---

## Related Specs

- Telemetry schema: `docs/specifications/simulation/telemetry_schema.md`
- Metadata schema: `docs/specifications/simulation/metadata_schema.md`
- Fault episode specification: `docs/specifications/simulation/fault_episode_spec.md`
