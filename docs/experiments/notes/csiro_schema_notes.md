# CSIRO AHU FDD Dataset – Schema Notes (Inspected)

## Purpose

These notes summarize the structure of the CSIRO AHU Fault Detection Dataset
after direct inspection of Parquet files for AHU9, AHU10, and the fault episode
registry. The dataset is used strictly as a **reference and validation baseline**,
not as a direct input to the simulator pipeline.

---

## Files Inspected

### 1) AHU9.parquet (Telemetry)

- Shape: **(457,653 rows, 17 columns)**
- Timestamp index range:
  - **Start:** 2013-05-01 09:00:00
  - **End:** 2015-05-22 17:00:00
- Sampling cadence appears to be **30 seconds** (e.g., 09:00:00 → 09:00:30 → 09:01:00 ...).
- All columns are **float64**.

Columns (signal families):

- Zone temperatures (multiple zones + average):
  - `AHU9ahuZoneTemp`, `AHU9ahuZoneTemp.1`, `AHU9ahuZoneTemp.2`
  - `AHU9ahuAvgZoneTemp`
- Valve commands:
  - `AHU9ahuCcValve` (cooling coil valve)
  - `AHU9ahuHcValve` (heating coil valve)
- Air temperatures:
  - `AHU9ahuMaTemp` (mixed air temp)
  - `AHU9ahuOaTemp` (outside air temp)
  - `AHU9ahuRaTemp` (return air temp)
  - `AHU9ahuSaTemp` (supply air temp)
  - `AHU9ahuSaTempSP` (supply air temp setpoint)
- Dampers:
  - `AHU9ahuOaDamper` (outside air damper)
  - `AHU9ahuRaDamper` (return air damper)
- Humidity:
  - `AHU9ahuRaRH` (return air RH)
  - `AHU9ahuSaRH` (supply air RH)
- Fan / pressure:
  - `AHU9ahuSaFanSpeed`
  - `AHU9ahuSaPressure`

Notes:

- Some RH values observed can exceed 100 (e.g., >100). Treat as dataset-specific scaling/noise,
  not necessarily physically bounded %RH.

---

### 2) AHU10.parquet (Telemetry)

- Shape: **(422,169 rows, 17 columns)**
- Timestamp index range:
  - **Start:** 2013-05-01 09:00:00
  - **End:** 2015-04-20 17:00:00
- Sampling cadence appears to be **30 seconds**.
- All columns are **float64**.

Same signal families as AHU9, with prefix `AHU10...`:

- Zone temps (3 zones + average)
- Cooling/heating valve
- Mixed/outside/return/supply temps + supply setpoint
- OA/RA dampers
- Return/supply RH
- Supply fan speed + supply pressure

---

### 3) fault-experiments.parquet (Fault Episode Registry / Metadata)

- Shape: **(391 rows, 8 columns)**
- Purpose: defines **fault episodes** as time-bounded experiments.

Columns:

- `AHU` (int): AHU identifier (e.g., 9, 10, 15…)
- `Fault Type` (object): category (e.g., valve stuck, setpoint bias, etc.)
- `Fault Name` (object): human-friendly name (often includes magnitude)
- `Magnitude` (float): numeric intensity (meaning depends on fault type)
- `Duration (h:mm)` (object): duration string
- `Fault Description` (object): sometimes None, sometimes long text
- `Start Datetime` (datetime)
- `End Datetime` (datetime)

This file is **not telemetry**; it is the authoritative source for fault segments.

---

## Architectural Insight (Most Important)

The dataset follows a clean separation:

1. **Telemetry streams** (AHU\*.parquet): time-indexed sensor/control signals.
2. **Fault episode registry** (fault-experiments.parquet): start/end/type/magnitude.

This directly supports our Phase 2 design principle:

- Faults are injected as **episodes (segments)**, not randomly per timestep.
- Telemetry is treated as an **event stream** independent of where it is stored.

---

## How This Informs Our Phase 2 Simulator (Design Guidance)

Recommended mapping for our project:

- Telemetry event schema should cover:
  - temps: OA/MA/RA/SA + SA setpoint
  - actuators: OA/RA damper, CC/HW valves
  - context: zone temps (optionally 1–3 + avg)
  - optional: fan speed, pressure, RH
- Fault specification should be episode-based:
  - `(fault_type, magnitude, start_time, end_time, target_ahu/signals)`

We will mirror the **conceptual separation** used by CSIRO, while keeping simulation behavioural
and deterministic (seeded) to support agentic reasoning experiments.

---

## Usage in This Project

- CSIRO dataset is **reference-only**:
  - to validate signal choices
  - to understand fault episode semantics
  - to compare high-level fault distributions during evaluation
- Our system’s simulator generates independent telemetry and metadata using a lightweight
  behavioural model (not physics-based).
