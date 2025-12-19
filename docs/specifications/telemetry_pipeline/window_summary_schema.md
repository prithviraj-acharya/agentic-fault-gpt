# Window Summary Schema — Phase 3 (Canonical Output)

## Purpose

Defines the canonical **window_summary** object produced by the Phase 3 telemetry pipeline.

Window summaries are the primary input to:
- Phase 4 retrieval (manuals/past-cases grounding)
- Phase 5 case-history indexing
- Phase 6 controller routing
- Phase 7 LLM reasoning
- Phase 9 UI monitoring and ticket review
- Phase 10 evaluation

---

## Design Rules

- Window summaries are **immutable** once emitted.
- Features must be **deterministic** for a given input + config.
- Anomaly triggers must be **symptoms** (not diagnosis labels).
- Text summaries must be **template-based** (non-LLM) for determinism.
- Simulation fault labels, if stored, must be isolated under `evaluation` and must
  not be used in anomaly detection or reasoning.

---

## Required Top-Level Fields

| Field         | Description |
|--------------|-------------|
| window_id     | Deterministic identifier for the window |
| ahu_id        | AHU identifier |
| time          | Window timing metadata |
| stats         | Sample/missing/quality metadata |
| features      | Numeric feature vector (flat key-value) |
| anomalies     | List of triggered symptom rules with evidence |
| text_summary  | Deterministic human-readable summary |

Optional:
- `evaluation` (truth labels for offline evaluation only)
- `provenance` (links to stored artifacts, if applicable)

---

## Field Details

### 1) `time` (required)

| Key              | Type   | Notes |
|------------------|--------|------|
| start            | string | ISO 8601 |
| end              | string | ISO 8601 |
| window_type      | string | `tumbling` or `sliding` |
| window_size_sec  | int    | e.g., 300 |
| step_sec         | int?   | only for sliding |

### 2) `stats` (required)

| Key            | Type | Notes |
|----------------|------|------|
| sample_count   | int  | number of events in window |
| missing_count  | int  | total missing signal values (or total missing events) |
| duplicate_count| int  | optional but recommended |
| late_count     | int  | optional; if late policy enabled |

### 3) `features` (required)

A flat key-value dict of window features.

Naming convention:
- `{signal}_{stat}`

Minimum recommended stats per signal:
- `mean`
- `var` (or `std`)
- `slope`
- `delta`

Example keys:
- `sa_temp_mean`
- `sa_temp_var`
- `sa_temp_slope`
- `sa_temp_delta`
- `cc_valve_mean`
- `oa_damper_var`
- `avg_zone_temp_slope`

Optional cross-signal features:
- `rat_minus_sat_mean`
- `sat_minus_mat_mean`

### 4) `anomalies` (required, can be empty)

Each anomaly trigger is a dict:

| Key       | Type   | Description |
|-----------|--------|-------------|
| rule_id   | string | Stable identifier (see `anomaly_rules_spec.md`) |
| severity  | string | `low` / `medium` / `high` |
| evidence  | object | Numerical evidence used to trigger |
| message   | string | Optional short deterministic message |

Example:
```json
{
  "rule_id": "SAT_NOT_DROPPING_WHEN_VALVE_HIGH",
  "severity": "medium",
  "evidence": {"cc_valve_mean": 82.0, "sa_temp_slope": 0.01}
}
```

### 5) `text_summary` (required)

Deterministic, template-generated summary.

Must include:
- window time range
- 2–4 key feature highlights
- triggered rule IDs (if any)

No free-form LLM generation in Phase 3.

---

## Optional: `evaluation`

Used only for offline evaluation (Phase 10). Must not be referenced by Phase 3 rules.

Recommended keys:
- `fault_active` (bool)
- `fault_type` (string)
- `fault_episode_id` (string)
- `scenario_id` (string)
- `seed` (int)

---

## Notes

- The exact set of `features` keys is controlled by configuration but should remain
  stable once frozen for the dissertation evaluation.
- Window summaries are the “basic event” that later phases store, retrieve, reason over,
  and display to users.
