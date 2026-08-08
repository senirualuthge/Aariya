# AI Girl (Aariya)

AI Girl is an advanced, autonomous AI agent platform featuring a real-time 3D avatar, deep cognitive capabilities, and computer interaction skills. It goes beyond simple chatbot interactions by incorporating a strict Executive Intelligence Layer (EIL), a rigorous Critical Thinking Engine (CTE), and a real-time World Model. The project is evolving into an Agent Operating System (AOS) with a dedicated kernel (`server/aariya/`), Swarm Intelligence (`server/swarm/`), and RL-tuned voice.

## Key Features
- **Embodied AI**: A highly realistic 3D avatar frontend (React 19 / Vite 8 / WebGL three.js) featuring real-time lip-sync, micro-expressions, gaze behavior, and TensorFlow-based face detection.
- **Executive Intelligence Layer (EIL)**: The AI's "CEO". Dynamically manages attention, handles interruptions for urgent events, and coordinates specialized sub-agents via a hierarchical goal structure (`server/core/executive/`).
- **Critical Thinking Engine (CTE)**: Multi-stage reasoning pipeline (Hypothesis Generation, Evidence Evaluation, Fact Checking, Confidence Scoring) ensuring hallucination-resistant planning.
- **World Model & Capability SDK**: The AI maintains a grounded understanding of its OS environment (`psutil`, desktop, browser) and interacts safely through a strict permission-based Capability SDK (`server/world/`, `server/sdk/`, `server/capabilities/`).
- **Cognitive Event Bus**: High-throughput Redis-backed nervous system orchestrating asynchronous tasks via a Priority Scheduler.
- **Dual-Vault Obsidian Memory**: Syncs the Developer and Runtime markdown vaults into RAG memory (`server/systems/rag/obsidian_indexer.py`).
- **Swarm & Multi-Agent**: Swarm Intelligence, consensus, and agent auto-discovery (`server/swarm/`, `server/systems/agent/`).
- **RL-Tuned Voice**: PPO-based voice pipeline (VAD, faster-whisper ASR, ElevenLabs/XTTS, lip sync) with fatigue and turn-taking tuning.

## Getting Started

### Prerequisites
- Node.js (v18+)
- Python 3.10+
- Redis (v4.6.0+)
- PostgreSQL
- ChromaDB (`pip install chromadb sentence-transformers`) for RAG
- Go (for the Pulse News microservice)
- Docker (for dev infrastructure: `pulse-news` and PostgreSQL/Redis containers)

### Running the Project
The project uses `concurrently` via `package.json` to launch the various subsystems together.

From the root directory, run:
```bash
npm install
npm run dev
```

`npm run dev` starts the Vite UI, the FastAPI brain (`server/main.py`), and the Pulse News backend together. Dev infra (Docker) is brought up automatically by `npm run dev:docker` via `predev`.

### Tests & Quality
```bash
npm run lint        # ESLint (src/)
npm run typecheck   # Vite build + TypeScript
npm test            # Vitest suites (per-system: dialogue, voice, agents, systems)
python -m pytest    # backend tests (server/tests)
```

## Repository Layout
- `server/` - Python FastAPI backend: kernel (`aariya/`, `aos/`, `cognitive_kernel/`, `brain/`), EIL (`core/executive/`), CTE + reasoning, `systems/` (63 subsystems), RAG, voice, RL, safety/security, world model, swarm.
- `src/` - React 19 frontend: avatar components, systems (Dialogue, Emotion, Vision, Voice, Trust, Memory), Zustand store, WebSocket hooks, brain UI.
- `pulse-news/` - Go microservice + backend for news intelligence.
- `mobile/`, `mobile_achi/` - Flutter mobile clients.
- `dashboard/` - FastAPI developer dashboard with WebSocket metrics + Prometheus `/metrics`.
- `HabitTracker/` - Standalone habits tracking sub-app.
- `prediction_engine/` - Prediction/market-backtest engine.
- `k8s/` - Production Kubernetes manifests (kustomize).
- `scripts/` - Dev/test scripts (camera, GUI, backtests, security tests).

## Documentation
- [System Architecture](SYSTEM_ARCHITECTURE.md) - Overview of the EIL, CTE, World Model, and kernel layers.
- [Database Schema](DATABASE_SCHEMA.md) - Breakdown of Postgres, SQLite memory, Redis streams, and ChromaDB vectors.
- [Technical Analysis](TECHNICAL_ANALYSIS.md) - Stack details, design patterns, and SDK contracts.
- [File Structure](FileStructure.md) - Map of the backend layout (kernel + systems + platform dirs).

## Kubernetes
Production deployment manifests live in `k8s/` (namespace, configmaps, Postgres statefulset, ingress, kustomization). See `k8s/README.md`.
