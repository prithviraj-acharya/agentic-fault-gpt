# Agentic AI Framework for Building Management Systems

This repository contains the implementation for the BITS Pilani Dissertation project  
**"Agentic AI Framework for Building Management Systems: Towards Intelligent and Autonomous Building Operations."**

The project aims to develop an agentic AI-based diagnostic pipeline for context-aware fault analysis in HVAC systems, integrating simulation-driven evaluation, reasoning-driven retrieval, and transparent decision workflows.

---

## 🔍 Project Overview

Modern Building Management Systems (BMS) generate high-frequency telemetry across HVAC components such as Air Handling Units (AHUs). Traditional diagnostic tools rely on rule-based logic, limiting adaptability. This project explores how **Agentic AI**—retrieval-augmented reasoning, context-use, multi-stage inference, and autonomous refinement—can enhance diagnostic accuracy and transparency.

### Implemented So Far (Current Repo State)

- Scenario-driven AHU telemetry simulator (Phase 2)
- Deterministic offline generation (seeded RNG) to CSV + metadata JSON
- Fault schedule support via non-overlapping, time-bounded fault episodes
- Fault injection modules (row modifiers) with optional ramp-in (`ramp_minutes`)
- Scenario validation (UTC timestamps, episode window containment, basic bounds/type checks)

### Planned (Next Phases)

- Streaming + windowing layer (Kafka producer/consumer)
- Hierarchical RAG-based diagnostic engine
- Retrieval over manuals, past cases, and dynamic memory
- Ticketing layer for explainable maintenance workflows
- Streamlit dashboard for interactive visualization

---

## ✅ What You Can Run Today

### Run the Simulator

The main simulator entrypoint is:

```bash
python -m simulation.simulator --scenario simulation/scenarios/scenario_v1.json --out data/generated
```

This will generate two files (filenames include the scenario `run_id`):

- `data/generated/<run_id>_telemetry.csv`
- `data/generated/<run_id>_metadata.json`

### Scenario File

Scenarios live under:

- `simulation/scenarios/`

The scenario contains:

- Simulation window: `start_time`, `end_time`, `sampling_interval_sec`
- Determinism: `seed`
- Output columns: `signals` (used to order the telemetry CSV)
- Fault schedule: `fault_episodes` (each with `start_time`, `end_time`, `fault_type`, `magnitude`, `fault_params`)

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
venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment

Create a `.env` file (ignored by Git):

```
ENV=development
LOG_LEVEL=INFO
```

---

## 📅 Project Timeline Alignment

This repository follows a structured 13-week timeline aligned with BITS WILP dissertation milestones.

Key checkpoints:

- **Mid-Sem Report:** Simulation + Consumer Layers
- **Final Report:** Full RAG pipeline + Dashboard
- **Final Viva:** End-to-end demo + evaluation metrics

---

## 📘 Documentation

Simulation specifications and notes live under:

- `docs/specifications/simulation/`

This includes schema and fault-episode rules used by the simulator/validator.

---

## 🤝 Supervisor & Collaboration

This repository is shared with the project supervisor for visibility into progress and alignment with BITS Pilani dissertation guidelines.

---

## 📜 License

This project is intended for academic and research use under the BITS Pilani WILP program.
