# Metadata Schema — Phase 2

## Purpose

Defines metadata associated with a simulation run.
Metadata captures configuration and ground truth, not telemetry.

---

## Scenario-Level Metadata

| Field                 | Description                              |
| --------------------- | ---------------------------------------- |
| run_id                | Unique identifier for the simulation run |
| scenario_name         | Human-readable scenario name             |
| ahu_id                | AHU identifier                           |
| start_time            | Simulation start timestamp               |
| end_time              | Simulation end timestamp                 |
| sampling_interval_sec | Time between telemetry events            |
| seed                  | Random seed for deterministic behavior   |
| signals               | List of telemetry fields used            |
| notes                 | Optional description                     |

---

## Design Rules

- Metadata is generated once per run
- Metadata is NOT consumed by Phase 3
- Metadata is used for validation and evaluation only
