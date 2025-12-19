# Anomaly Rule Specification — Phase 3 (Symptom Triggers)

## Purpose

Defines the rule-based **symptom detection** layer used in Phase 3.

Rules operate on window-level features to emit structured anomaly triggers
with evidence. Rules must not directly diagnose faults.

---

## Design Rules

- Rules use **features only** (no access to fault labels).
- Each rule must emit **numerical evidence**.
- Rule IDs must be **stable** and referenced downstream (Phase 6 routing, Phase 7 prompts).
- Rules should be few, interpretable, and robust (recommended: 6–10 total).

---

## Trigger Format

Each triggered rule produces:

- `rule_id`
- `severity` (`low` / `medium` / `high`)
- `evidence` (feature values and thresholds used)
- optional deterministic `message`

---

## Recommended Rule Set (Minimal)

### A) Cooling Demand Response (Symptoms)

#### 1) SAT_NOT_DROPPING_WHEN_VALVE_HIGH

**Intent:** Cooling demand high but supply air temperature not decreasing.

Condition (example):

- `cc_valve_mean > 70`
- `sa_temp_slope >= 0`

Evidence:

- `cc_valve_mean`
- `sa_temp_slope`
- `sa_temp_delta`

Severity:

- medium → high if persists across consecutive windows

---

#### 2) SAT_TOO_HIGH_WHEN_VALVE_HIGH

**Intent:** SAT remains above setpoint while cooling demand is high.

Condition (example):

- `cc_valve_mean > 70`
- `sa_temp_mean - sa_temp_sp_mean > 1.0`

Evidence:

- `cc_valve_mean`
- `sa_temp_mean`
- `sa_temp_sp_mean`
- `sa_temp_mean_minus_sp`

Severity:

- medium

---

### B) Damper Responsiveness (Symptoms)

#### 3) OA_DAMPER_STUCK_OR_FLATLINE

**Intent:** OA damper shows near-zero variance (stuck/flatline).

Condition (example):

- `oa_damper_var < epsilon` (epsilon configurable)

Evidence:

- `oa_damper_var`
- `oa_damper_mean`

Severity:

- low → medium if persists

---

#### 4) RA_DAMPER_STUCK_OR_FLATLINE

Same structure as OA damper, for `ra_damper_*`.

---

### C) Zone Temperature Behavior (Symptoms)

#### 5) ZONE_TEMP_PERSISTENT_TREND

**Intent:** Average zone temperature trends persistently upward/downward.

Condition (example):

- `avg_zone_temp_slope > slope_threshold`

Evidence:

- `avg_zone_temp_slope`
- `avg_zone_temp_delta`
- `avg_zone_temp_var`

Severity:

- low → medium if persists

---

#### 6) ZONE_TEMP_SENSOR_NOISY

**Intent:** Zone temperature variance exceeds normal bounds.

Condition (example):

- `avg_zone_temp_var > var_threshold`

Evidence:

- `avg_zone_temp_var`

Severity:

- low/medium

---

### D) Data Quality (Symptoms)

#### 7) MISSING_DATA_HIGH

**Intent:** Too many missing values in the window.

Condition (example):

- `missing_count / (sample_count * num_signals) > missing_ratio_threshold`

Evidence:

- `missing_count`
- `sample_count`

Severity:

- medium

---

#### 8) OUT_OF_RANGE_VALUES

**Intent:** One or more signals exceed physical bounds.

Condition:

- any `{signal}_min < lower_bound` OR `{signal}_max > upper_bound`

Evidence:

- offending signal keys and min/max values

Severity:

- high

---

## Threshold Configuration

All thresholds (e.g., valve_high_pct, slope_threshold, epsilon, var_threshold) must be configurable
via a single config file, and included in logs for reproducibility.

Thresholds must be defined with the window configuration in mind:

- window duration (e.g., 60s vs 300s)
- sampling interval (e.g., 60s)
  Changing window size or sampling can change feature magnitudes (especially slopes/deltas), so the
  configuration used to evaluate rules must be recorded.

---

## Notes

- Optional persistence logic can be applied to reduce false positives:
  - e.g., rule triggers only after 2 consecutive windows satisfy the condition.
- Rule IDs should remain stable once frozen for mid-sem and final evaluation.
