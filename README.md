# Agentic AI Framework for Building Management Systems

This repository contains the implementation for the BITS Pilani Dissertation project  
**"Agentic AI Framework for Building Management Systems: Towards Intelligent and Autonomous Building Operations."**

The project aims to develop an agentic AI-based diagnostic pipeline for context-aware fault analysis in HVAC systems, integrating simulation-driven evaluation, reasoning-driven retrieval, and transparent decision workflows.

---

## 🔍 Project Overview

Modern Building Management Systems (BMS) generate high-frequency telemetry across HVAC components such as Air Handling Units (AHUs). Traditional diagnostic tools rely on rule-based logic, limiting adaptability. This project explores how **Agentic AI**—retrieval-augmented reasoning, context-use, multi-stage inference, and autonomous refinement—can enhance diagnostic accuracy and transparency.

### Implemented So Far (Current Repo State)

- Scenario-driven AHU telemetry simulator (Phase 2)
- Deterministic generation (seeded RNG) to telemetry CSV + metadata JSON
- Local-first streaming producer (scenario -> event stream, with optional Kafka sink)
- Fault schedule support via non-overlapping, time-bounded fault episodes
- Fault injection modules (row modifiers) with optional ramp-in (`ramp_minutes`)
- Scenario validation (UTC timestamps, episode window containment, basic bounds/type checks)

- Phase 3 telemetry pipeline (window summaries):
  - Event validation + normalization
  - Deterministic per-AHU ordering + de-dup buffer
  - Tumbling window manager (epoch-aligned)
  - Feature extraction (per-signal stats + cross-signal features)
  - Rule-based symptom detection (YAML-driven thresholds)
  - Canonical `window_summary` JSON output with deterministic text summary
  - Local JSONL sink (and optional Kafka sink)

### Planned (Next Phases)

- Retrieval + indexing over manuals and past cases
- Hierarchical RAG-based diagnostic engine
- Ticketing layer for explainable maintenance workflows
- Streamlit dashboard for interactive visualization

---

## ✅ What You Can Run Today

### 1) Start Kafka (Docker)

Start Kafka + Kafka UI:

```powershell
docker compose -f docker/docker-compose.kafka.yml up -d
```

Create the telemetry topic (idempotent):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\kafka_bootstrap.ps1 -Topic ahu.telemetry
```

Create the window summary topic (idempotent):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\kafka_bootstrap.ps1 -Topic window_summaries
```

### 2) Generate telemetry (offline files)

Generates the full scenario telemetry CSV + metadata JSON:

```bash
python -m simulation.simulator --scenario simulation/scenarios/scenario_v1.json --out data/generated
```

Outputs:

- `data/generated/<run_id>_telemetry.csv`
- `data/generated/<run_id>_metadata.json`

### 3) Stream telemetry to Kafka

Streams the scenario events to Kafka topic `ahu.telemetry`:

```bash
python -m simulation.producer \
	--scenario simulation/scenarios/scenario_v1.json \
	--mode kafka \
	--bootstrap-servers localhost:9092 \
	--topic ahu.telemetry \
	--start-now \
	--speed 0 \
	--out data/generated
```

### 4) Phase 3 window summaries

This runs the full Phase 3 pipeline and writes one `window_summary` JSON object per line.

#### 4a) Offline: CSV → JSONL

```bash
python -m telemetry_pipeline.run_pipeline \
	--mode csv \
	--csv data/generated/ahu_sim_run_001_telemetry.csv \
	--sink jsonl \
	--out data/generated/window_summaries.jsonl
```

#### 4b) Kafka: telemetry topic → window summary topic

Consumes `ahu.telemetry` and publishes `window_summaries`:

```bash
python -m telemetry_pipeline.run_pipeline \
	--mode kafka \
	--bootstrap-servers localhost:9092 \
	--topic ahu.telemetry \
	--from-beginning \
	--sink kafka \
	--summary-topic window_summaries
```

Notes:

- JSONL = JSON Lines: one summary per line (stream-friendly, easy to diff).
- Frozen configs live under `telemetry_pipeline/config/`:
  - `signals.yaml` (signal vocabulary + bounds + feature declarations)
  - `windowing.yaml` (window size/type + ordering + missing data policy)
  - `rules.yaml` (rule thresholds)

### 5) Dashboard backend API (Docker)

Build + run the backend API alongside Kafka:

```powershell
docker compose -f docker/docker-compose.kafka.yml -f docker/docker-compose.api.snippet.yml up --build dashboard-api
```

Health URL:

- http://localhost:8000/api/health

### Optional: local stream (no Kafka)

Generate from a scenario and print one JSON event per line (still writes CSV+metadata):

```bash
python -m simulation.producer --scenario simulation/scenarios/scenario_v1.json --mode local --speed 0 --out data/generated
```

Replay from an existing telemetry CSV:

```bash
python -m simulation.producer --input data/generated/<run_id>_telemetry.csv --mode local --speed 0
```

- `--mode local` prints one JSON event per line (good for debugging and for piping into other tools)
- `--speed 1.0` replays at real-time gaps between timestamps; `--speed 0` replays as fast as possible

### Scenario file

Scenarios live under:

- `simulation/scenarios/`

The scenario contains:

- Simulation window: `start_time`, `end_time`, `sampling_interval_sec`
- Determinism: `seed`
- Output columns: `signals` (used to order the telemetry CSV)
- Fault schedule: `fault_episodes` (each with `start_time`, `end_time`, `fault_type`, `magnitude`, `fault_params`)

See also:

- `docs/specifications/simulation/simulation_overview.md`

### Fault Types Implemented

Fault episodes are applied when `start_time <= ts < end_time` (inclusive start, exclusive end).

- `cooling_coil_fault` (reduced cooling effectiveness; impacts `cc_valve`, `sa_temp`, and slightly `avg_zone_temp`)
- `stuck_damper_fault` (OA/RA damper stuck; recomputes `ma_temp` and adjusts `cc_valve`, `sa_temp`, `sa_fan_speed`)
- `zone_temp_sensor_drift` (sensor fault; drifts only the reported `avg_zone_temp`)

Optional per-episode ramp-in:

- `fault_params.ramp_minutes`: linearly scales fault magnitude from 0 → full magnitude over the first N minutes

## 🛠️ Installation & Setup

### 1. Clone the Repository

```bash
git clone https://github.com/<your-username>/agentic-fault-gpt.git
cd agentic-fault-gpt
```

### 2. Create a Virtual Environment

```bash
python -m venv venv
# macOS / Linux
source venv/bin/activate
# Windows
venv\Scripts\Activate.ps1
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

Troubleshooting (Windows):

- If `python` opens the Microsoft Store, use the venv python directly: `venv\Scripts\python.exe ...`
- If Kafka consumer/producer complains about `confluent-kafka`, install it: `pip install -r requirements.txt`

### 4. Configure Environment

Create a `.env` file (ignored by Git):

```
ENV=development
LOG_LEVEL=INFO
```

---

## 📅 Project Timeline Alignment

(Intentionally omitted here to keep the README short.)

---

## 📘 Documentation

Simulation specifications and notes: `docs/specifications/simulation/`

Telemetry pipeline specifications (Phase 3): `docs/specifications/telemetry_pipeline/`

---

## 🤝 Supervisor & Collaboration

This repository is shared with the project supervisor for visibility into progress and alignment with BITS Pilani dissertation guidelines.

---

## 📜 License

This project is intended for academic and research use under the BITS Pilani WILP program.
