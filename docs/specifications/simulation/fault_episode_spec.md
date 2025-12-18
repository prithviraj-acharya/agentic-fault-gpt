# Fault Episode Specification — Phase 2

## Purpose

Defines how faults are represented in the simulator.
Faults are modeled as time-bounded episodes.

---

## What is a Fault Episode?

A fault episode is a continuous time interval during which
a specific fault condition is active.

Faults are NOT labeled per telemetry row.

---

## Fault Episode Fields

| Field          | Description                   |
| -------------- | ----------------------------- |
| episode_id     | Unique fault episode ID       |
| fault_type     | Type of fault                 |
| start_time     | Fault start timestamp         |
| end_time       | Fault end timestamp           |
| magnitude      | Fault severity (0–1)          |
| target_signals | Signals affected by the fault |
| fault_params   | Fault-specific parameters     |
| description    | Human-readable explanation    |

---

## Fault Types Implemented (Phase 2)

- `cooling_coil_fault`
- `stuck_damper_fault`
- `zone_temp_sensor_drift`
- `normal_operation`

---

## Design Rules

- Faults are injected based on time intervals
- Only one fault episode is active at a time (Phase 2)
- Fault effects are behavioural, not physics-based
