# Agentic AI Framework for Building Management Systems

This repository contains the implementation for the BITS Pilani Dissertation project  
**"Agentic AI Framework for Building Management Systems: Towards Intelligent and Autonomous Building Operations."**

The project aims to develop an agentic AI-based diagnostic pipeline for context-aware fault analysis in HVAC systems, integrating simulation-driven evaluation, reasoning-driven retrieval, and transparent decision workflows.

---

## 🔍 Project Overview

Modern Building Management Systems (BMS) generate high-frequency telemetry across HVAC components such as Air Handling Units (AHUs). Traditional diagnostic tools rely on rule-based logic, limiting adaptability. This project explores how **Agentic AI**—retrieval-augmented reasoning, context-use, multi-stage inference, and autonomous refinement—can enhance diagnostic accuracy and transparency.

The final system will include:

- Behavioral AHU telemetry simulator
- Streaming and windowing layer
- Hierarchical RAG-based diagnostic engine
- Retrieval over manuals, past cases, and dynamic memory
- Ticketing layer for explainable maintenance workflows
- Streamlit dashboard for interactive visualization

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

Additional documentation (architecture diagrams, design notes, RAG workflows) will be added under a future `/docs` folder.

---

## 🤝 Supervisor & Collaboration

This repository is shared with the project supervisor for visibility into progress and alignment with BITS Pilani dissertation guidelines.

---

## 📜 License

This project is intended for academic and research use under the BITS Pilani WILP program.
