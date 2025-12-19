# Windowing Specification — Phase 3 (Telemetry Pipeline)

## Purpose

Defines how validated telemetry events are grouped into deterministic time windows
for feature extraction and symptom detection.

Each window represents AHU behavior over a fixed interval.

---

## Design Rules

- Window assignment uses **event time** (`timestamp`) only.
- Windowing is **deterministic** for a given input stream and configuration.
- Windowing operates on **validated, normalized events** only.
- Windowing does not use fault labels or diagnosis logic.

---

## Window Types

### Tumbling Window (Default)
- Fixed-size, non-overlapping windows.
- Example: 12:00:00–12:05:00, 12:05:00–12:10:00.

### Sliding Window (Optional)
- Fixed-size windows emitted at a fixed step.
- Example: 5-minute window emitted every 1 minute.

---

## Default Configuration

| Parameter        | Value (Default) |
|-----------------|------------------|
| window_type     | tumbling         |
| window_size_sec | 300              |
| step_sec        | N/A (tumbling)   |
| timestamp_field | timestamp        |

Development recommendation (fast iteration):
- window_size_sec = 60 (tumbling)

Demo/evaluation recommendation (stable aggregation):
- window_size_sec = 300 (tumbling)

---

## Window Boundary Rules

### Tumbling
- `window_start` is aligned to a fixed boundary (configurable).
  Recommended: align to epoch (floor by window_size_sec).
- `window_end = window_start + window_size_sec`
- An event belongs to the window where:
  - `window_start <= event.timestamp < window_end`

### Sliding
- Windows are defined by (start, end) with fixed size.
- A new window is emitted every `step_sec`.

---

## Window Close Rule

A window is considered **closed** when the pipeline observes an event timestamp
greater than or equal to the window end time.

Upon close:
- the window’s events are finalized
- features and anomaly rules are computed
- a `window_summary` is emitted

---

## Deterministic Window ID

Window ID must be computed deterministically.

Recommended format:
- `window_id = "{ahu_id}_{window_start_iso}_{window_size_sec}s_{window_type}"`

Example:
- `ahu_01_2025-12-19T12:00:00Z_300s_tumbling`

---

## Ordering & Duplicates Policy

- Events may be deduplicated using a stable key:
  - recommended: hash of (`ahu_id`, `timestamp`) or explicit `event_id` if provided.
- Ordering is enforced per AHU stream using a bounded buffer:
  - sort by timestamp within the buffer before assignment.

---

## Missing Data Policy

- Missing signal values are allowed but must be counted.
- Window summary must include:
  - `sample_count`
  - `missing_count` (per signal optional; total required)

---

## Notes

- Late-event handling (watermarks) is out of scope for local-first.
  If late events occur, they may be dropped with logging, or included only if they
  fall within the active (not-yet-closed) window.
