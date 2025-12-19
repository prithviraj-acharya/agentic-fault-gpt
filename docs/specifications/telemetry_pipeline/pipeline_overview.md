# Telemetry Pipeline Overview — Phase 3

## Purpose

Defines the Phase 3 telemetry processing pipeline that transforms raw AHU telemetry events
into deterministic **window summaries** suitable for downstream indexing, retrieval, reasoning,
UI display, and evaluation.

Phase 3 is the **contract + compression layer**:

- Input: high-frequency, single-timestamp telemetry events (Phase 2 output)
- Output: low-frequency, aggregated, explainable window summaries (Phase 3 output)

---

## Design Rules

- Pipeline consumes **telemetry events only** (no access to fault labels during processing).
- Output is **deterministic** for a given input stream and configuration.
- Window summaries are the **canonical event** for Phases 4–10 (downstream phases should not
  depend on raw telemetry).
- Text summaries are **template-based** (non-LLM) to preserve determinism and auditability.
- All anomaly signals emitted are **symptoms**, not diagnoses.

---

## Pipeline Stages (Logical)

1. **Consume**
   - Read events from Kafka (or file replay in local mode).
2. **Validate & Normalize**
   - Enforce schema, coerce types, handle missing values per policy.
3. **Deduplicate & Order**
   - Remove duplicates; ensure stable ordering per AHU stream (bounded buffer).
4. **Window**
   - Group events into tumbling/sliding windows using event timestamps.
5. **Feature Extraction**
   - Compute window-level statistical and trend features (mean/variance/slope/delta).
6. **Rule-Based Symptom Detection**
   - Trigger anomaly symptoms using features; attach numerical evidence.
7. **Summarize**
   - Emit canonical `window_summary` JSON + deterministic text summary.
8. **Persist / Publish**
   - Write JSONL artifacts (local) and/or publish to downstream queues/topics.

---

## Inputs

Primary input object: **Telemetry Event** (see `specifications/simulation/telemetry_schema.md`)

Expected properties (conceptual):

- `timestamp` (ISO 8601)
- `ahu_id`
- telemetry fields/signals (temperatures, damper positions, valve position, fan speed, etc.)

---

## Outputs

Primary output object: **Window Summary** (see `window_summary_schema.md`)

Saved artifacts (local-first reference):

- `data/generated/window_summaries/<run_id>.jsonl` (append-only)
- optional: `data/generated/window_features/<run_id>.csv` (debugging/plots)

---

## Non-Goals (Phase 3)

- No fault diagnosis or root-cause assignment.
- No LLM usage or retrieval (belongs to Phases 4–7).
- No complex late-event/watermark semantics (kept minimal for local-first).

---

## Notes

- Phase 3 windowing should use **event time** (the telemetry `timestamp` field), not wall-clock
  arrival time.

  - Producer pacing controls (e.g., replay speed / fixed emit interval) may change when messages
    arrive, but should not change event-time window boundaries.

- Kafka consumer cadence is a polling/throttling detail (implementation choice), not a windowing rule.

  - A typical dev default is `poll_timeout_s ≈ 1s`.
  - Optional consumer throttling (e.g., `min_interval_s`) can reduce downstream compute load
    without changing event-time semantics.

- Consumer offsets / reproducibility:
  - Re-running with the **same** Kafka `group.id` will typically continue from committed offsets.
  - To reprocess a topic “from the beginning” for a new experiment without deleting data, use a
    **new** `group.id` (and `auto.offset.reset=earliest` for groups with no committed offsets).
  - Topic deletion/clearing is reserved for demos or schema resets; it is not required for Phase 3.
- Any simulation fault labels must be used only for evaluation and must be isolated
  under an explicit `evaluation` section if included in artifacts.
