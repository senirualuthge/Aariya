# System Architecture

The AI Girl architecture is a highly distributed, real-time agentic system integrating a 3D avatar frontend with an autonomous Cognitive Kernel and an Agent Operating System (AOS) on the backend. The project is organized into kernel/runtime homes (`server/aariya/`, `server/aos/`, `server/cognitive_kernel/`, `server/brain/`), 63 subsystem dirs under `server/systems/`, and platform/governance layers.

## Core Tiers

### 1. Presentation & Embodiment Layer (Frontend)
- **Technology**: React 19, Vite 8, three.js / @react-three/fiber (WebGL), TensorFlow + mediapipe face detection, Zustand.
- **Function**: Handles the 3D rendering of the AI, capturing user inputs (audio/video), and playing back AI responses with facial tension and lip-syncing.
- **Key Subsystems**: DialogueSystem, EmotionSystem, VisionSystem, VoiceSystem, TrustSystem, PersonalitySystem, MemorySystem (`src/systems/`).
- **Runtime plumbing**: `src/core/` (EventBus, wsClient, thermalController, tripleLoopRuntime, performance system).

### 2. Executive Intelligence Layer (EIL)
- **Location**: `server/core/executive/`.
- **Function**: Acts as the "CEO" of the AI. It sits above all planning and reasoning modules.
- **Key Subsystems**:
  - *Attention Manager*: Scores incoming events based on Urgency, Importance, Risk, and Novelty.
  - *Executive Controller*: Intercepts urgent events and interrupts running background tasks.
  - *Goal Manager*: Maintains the strict hierarchical tree of Mission -> Project -> Task -> Action.
  - *Agent Coordinator*: Delegates sub-tasks to specialized agents rather than relying on a monolithic planner.

### 3. Reasoning & Cognition Layer (The CTE)
- **Technology**: Python, LLM orchestration via `ModelRegistry` (`server/llm/`).
- **Function**: Processes complex information before execution to prevent hallucinations and improve logic.
- **Key Subsystems (Critical Thinking Engine)**:
  - *Hypothesis Generator* & *Evidence Evaluator*
  - *Fact Checker* & *Counterargument Generator*
  - *Confidence Scorer* & *Strategy Manager*
- **Additional cognition**: Synoptic Engine (`server/systems/synoptic/`), Theory of Mind v2, Recorrection system, contradiction detector, salience engine.

### 4. World Model & Capability Layer
- **Technology**: Capability SDK, Python OS libraries (`psutil`).
- **Function**: Gives the AI a grounding in reality and strict tools to interact with it.
- **Key Subsystems**:
  - *World Model* (`server/world/`, `server/world_intelligence/`): Maintains real-time state of the `Desktop`, `Browser`, `People`, and `Environment`.
  - *Capability SDK* (`server/sdk/`, `server/capabilities/`): Strict contracts, manifests, and health checks for every action the AI can take (OSINT, Email, etc.).

### 5. Runtime & Event Bus Layer
- **Technology**: Redis Streams, Python `asyncio`.
- **Function**: The nervous system of the AI.
- **Key Subsystems**:
  - *Runtime Scheduler* (`server/runtime/`): Priority-based async event loop with retry logic.
  - *Cognitive Event Bus*: Redis-backed pub/sub with `AuditLogMiddleware` and `AuthMiddleware` (`server/core/event_bus.py`, `server/aos/event_bus.py`).

### 6. Governance, Safety, & Self-Healing Layer
- **Function**: Ensures the AI operates securely and reliably over long durations.
- **Key Subsystems**: Safety Governor, Integrity Agents, Security Policies (`server/safety/`, `server/systems/safety/` — GoalGuardian, ConstraintEngine, ActionValidator, `server/systems/security/` — SAST/SCA scanners).

### 7. Swarm & Multi-Agent Layer
- **Location**: `server/swarm/`, `server/systems/agent/`, `server/systems/swarm/`.
- **Function**: Coordination of multiple specialized agents with consensus and communication.
- **Key Subsystems**: Swarm Intelligence, Consensus Engine, Notifier, agent auto-discovery (AST-based registry).

## Kernel & Runtime Homes

The codebase contains several overlapping kernel/runtime implementations; the canonical runtime story is still consolidating:

- **`server/aariya/`** — Aariya kernel v2.0.0-beta (build 2026-07-19). `core/kernel/` (event_bus, runtime, scheduler, lifecycle, state), `memory/` (semantic_memory, knowledge_graph, memory_retriever).
- **`server/aos/`** — Agent Operating System: kernel, governor, memory, worker, event_bus.
- **`server/cognitive_kernel/`** — Orchestrator, agents, execution, goals, memory, planning, reflection, llm_router.
- **`server/brain/`** — Controller, router, execution_engine, planning, memory, policy, reflex, registry, runtime.
- **`server/systems/brain_v2.py`** — Canonical `CognitivePipeline` used by `server/main.py`, orchestrating the systems layer.

## Data Stores

- **PostgreSQL** — users, sessions, auth_events, trust_events, osint_investigations/osint_entities.
- **SQLite** — cognitive memory: memories, reflections, beliefs, theory_of_mind, goals, plans, patterns, skills, personalizations.
- **Redis** — `event_stream` (Cognitive Event Bus) + pub/sub.
- **ChromaDB** — RAG vector store (`sentence-transformers` embeddings).

## Obsidian Dual-Vault Memory

`server/systems/rag/obsidian_indexer.py` syncs two markdown vaults into RAG memory:
- **Developer vault** (`OBSIDIAN_DEVELOPER_VAULT_PATH`) -> `mem_type=obsidian_developer` (read-only context for the AI to understand its own architecture).
- **Runtime vault** (`OBSIDIAN_RUNTIME_VAULT_PATH`) -> `mem_type=obsidian_runtime` (AI-written episodic logs).

Chunks are `From <filename>:`-prefixed and deduplicated against existing memories before insertion.

## Voice Pipeline

VAD -> ASR (faster-whisper) -> TTS (ElevenLabs + XTTS providers) -> lip sync, with streaming, voice fatigue, and PPO/RL tuning (`server/systems/voice/voice_ppo.py`).

## Data Flow (Simplified)
1. Event occurs (User speaks, or System triggers).
2. Event pushed to **Cognitive Event Bus**.
3. **Attention Manager** (in EIL) scores the event. If urgent, **Executive Controller** interrupts current focus.
4. **Agent Coordinator** delegates to specialized agents (optionally via Swarm/consensus).
5. **Critical Thinking Engine (CTE)** evaluates the task and formulates a robust plan based on the **World Model**.
6. **Capability SDK** executes the plan safely.
7. Frontend renders the output visually and audibly.

## Deployment
- **Docker**: `Dockerfile.server`, `Dockerfile.ui`, `docker-compose.full.yml`, `pulse-news/docker-compose.yml` (dev infra).
- **Kubernetes**: `k8s/` production manifests (namespace, configmaps, Postgres statefulset, ingress, kustomization).
- **Mobile**: Flutter clients (`mobile/` aariya_mobile, `mobile_achi/` Achi Shell) over WebSocket protocol.
