# Telemetry Schema — Phase 2

## Purpose

Defines the structure and semantics of AHU telemetry events generated
by the Phase 2 Behavioral Simulator.

Each telemetry event represents the AHU state at a single timestamp.

---

## Design Rules

- Telemetry contains NO fault labels
- Faults are represented only via signal behavior
- Timestamps are strictly increasing
- Deterministic output for a given seed

---

## Telemetry Fields

| Field         | Description                     | Units / Range  |
| ------------- | ------------------------------- | -------------- |
| timestamp     | Event timestamp (ISO 8601)      | datetime       |
| ahu_id        | AHU identifier                  | int / string   |
| oa_temp       | Outside air temperature         | °C (10–45)     |
| ra_temp       | Return air temperature          | °C (18–30)     |
| ma_temp       | Mixed air temperature           | °C (OA–RA mix) |
| sa_temp       | Supply air temperature          | °C (10–20)     |
| sa_temp_sp    | Supply air temperature setpoint | °C (12–18)     |
| avg_zone_temp | Average zone temperature        | °C (20–28)     |
| cc_valve      | Chilled water valve position    | % (0–100)      |
| oa_damper     | Outside air damper position     | % (0–100)      |
| ra_damper     | Return air damper position      | % (0–100)      |
| sa_fan_speed  | Supply air fan speed            | % (0–100)      |

---

## Notes

- Mixed air temperature should reflect damper behavior behaviourally.
- Supply air temperature should respond to cooling demand in normal mode.
