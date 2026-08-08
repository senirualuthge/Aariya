# AI Girl - Directory Structure

Below is the directory structure for the current implementation of AI Girl. The backend (`server/`) has grown beyond the original strict 19-folder architecture into a layered layout (~91 top-level dirs) combining dedicated kernel/runtime homes with 63 subsystem dirs under `server/systems/`.

## Root Directory (`/`)
- `package.json` / `package-lock.json` - Node dependencies and top-level orchestration scripts (Vite UI, FastAPI brain, Pulse News).
- `vite.config.mjs` - Configuration for the Vite bundler used by the React frontend.
- `tsconfig.json` / `eslint.config.js` - TypeScript and ESLint configuration.
- `server/` - Python backend (FastAPI) housing the kernel, Agent Operating System, and Cognitive Architecture.
- `src/` - React 19 frontend: UI, WebSockets, and 3D Avatar integration components (Aariya).
- `pulse-news/` - Go-based microservice + backend for news intelligence.
- `mobile/`, `mobile_achi/` - Flutter mobile clients (aariya_mobile, Achi Shell).
- `dashboard/` - FastAPI developer dashboard (WebSocket metrics + Prometheus `/metrics`).
- `HabitTracker/` - Standalone habits tracking sub-app.
- `prediction_engine/` - Prediction/backtest engine.
- `k8s/` - Production Kubernetes manifests (kustomize).
- `scripts/` - Dev/test scripts (camera, GUI, backtests, security tests).
- `public/` - Static assets and configurations (Vite).
- `.agent/` - Subagent workspace and definitions.
- `tests/` / `pytest.ini` - Root level integration tests and test configurations.

## `server/` (Backend & Cognitive Architecture)

### Kernel & Runtime Homes (canonical story still in flux)
- `main.py` - FastAPI entry point (boots `CognitivePipeline` from `server/systems/brain_v2.py`).
- `aariya/` - Aariya kernel v2.0.0-beta. `core/kernel/` (event_bus, runtime, scheduler, lifecycle, state), `memory/` (semantic_memory, knowledge_graph, memory_retriever), plus agents, cognition, conversation, engines, goals, infrastructure.
- `aos/` - Agent Operating System: kernel, governor, memory, worker, event_bus.
- `cognitive_kernel/` - Orchestrator, agents, execution, goals, memory, planning, reflection, llm_router.
- `brain/` - Controller, router, execution_engine, planning, memory, policy, reflex, registry, runtime, agents.
- `core/` - Foundational systems: `executive/` (Attention Manager, Executive Controller, Agent Coordinator, Goal Manager), event_bus, kernel, scheduler, world, safety, runtime, planning, reasoning, memory, learning.

### Subsystems (`systems/` - 63 dirs)
- `systems/cognition/` - Cognitive integration (34 subsystems), critical thinking, attention.
- `systems/rag/` - RAG pipeline, `obsidian_indexer.py` (dual-vault sync), RAG telemetry.
- `systems/voice/` - VAD, faster-whisper ASR, ElevenLabs/XTTS TTS, lip sync, streaming, voice PPO/RL.
- `systems/rl/` - Reinforcement learning (agent, environment, stream manager).
- `systems/emotion/`, `systems/affect*` - Emotion fusion, guard, state machine, emotional replay, expression mask.
- `systems/safety/` - GoalGuardian, ConstraintEngine, ActionValidator.
- `systems/security/` - SecurityService, scanner (SAST/SCA).
- `systems/trust/` - Trust system.
- `systems/conversation/` - ConversationOrchestrator, TopicGraph, NarrativeSelf, CuriosityEngine.
- `systems/creativity/`, `systems/science/`, `systems/social/`, `systems/knowledge/`, `systems/project/` - Tooling subsystems.
- `systems/identity/`, `systems/goals/`, `systems/planning/`, `systems/learning/`, `systems/evolution/`.
- `systems/swarm/`, `systems/agent/` - Multi-agent coordination and discovery.
- `systems/desktop/`, `systems/filesystem/`, `systems/network_search/`, `systems/cyber/`, `systems/recognition/`, `systems/vision/`, `systems/news/`.
- `systems/synoptic/` - Synoptic Engine (aggregator, smoother, telemetry).
- `systems/theory_of_mind_v2.py`, `systems/recorrection_system.py`, `systems/systems_orchestrator.py` (top-level integration).

### Platform & Governance
- `api/` - FastAPI routers (`routes_*`) + WebSocket endpoints (`ws.py`, `ws_osint.py`, `ws_perception.py`).
- `routers/` - Additional routers (agents, analytics, cognition, dashboard, mobile, rl, security, swarm, voice).
- `capabilities/` - Executable skills and adapters (e.g., OSINT, desktop control) adhering to the Capability SDK.
- `sdk/` - The `Capability SDK`: manifests, health monitoring, permissions for tools.
- `world/`, `world_intelligence/` - The World Model (Desktop, Browser, People, OS metrics).
- `llm/` - LLM client, ModelRegistry, health/URL routing.
- `models/` - Model definitions/registries.
- `planner/`, `planning/`, `prediction/` - Planning, risk assessment, prediction.
- `evolution/`, `genome/`, `civilization/`, `economy/`, `capital/` - Genome/civilization/economy simulation layers.
- `swarm/` - Swarm Intelligence (communication, consensus, notifier).
- `identity/`, `perception/`, `intention/`, `autonomous/`, `autonomy/`, `intelligence/` - Perception/autonomy modules.
- `memory/` - Memory layer (semantic, episodic, working).
- `runtime/` - Priority-based async task scheduler.
- `events/`, `bus/`, `signal_bus` - Event bus layers.
- `safety/`, `governance/`, `security/`, `self_heal/`, `self_improvement/`, `recovery/` - Safety/governance layers.
- `gateway/`, `infrastructure/`, `adapters/`, `interface/`, `streaming/`, `websocket/`, `realtime/` - Platform plumbing.
- `config/` - JSON configs (trust, governance, salience, scenarios).
- `data/` - Local datasets and persistent stores.
- `file_memory_db/` - File-backed memory DB.
- `logs/` - Execution logs and observability data.
- `tests/` - Integration and unit testing.
- `scripts/` - Backend utilities.
- `_legacy_archive/` - Archived legacy components (pre-restructure subsystems).

## `src/` (Frontend UI & Avatar Systems)
The frontend uses React 19, Vite, Zustand, and three.js, heavily featuring avatar animation, real-time emotion tracking, and interaction subsystems.
- `main.jsx` / `App.jsx` - React application entry points (React Router).
- `components/` - Reusable UI: BrainScene.jsx, AgentDiscoveryPanel.jsx, AnalyticsDashboard.jsx, GoalPanel.jsx, IdentificationTab.jsx, BrainMonitor.jsx, AutoFunctioningPanel.jsx, MetaPanel.jsx, NarrativePanel.jsx, NewsFeedPanel.jsx, and more.
- `systems/` - Critical React components governing local AI logic: `DialogueSystem.jsx`, `EmotionSystem.jsx`, `VisionSystem.jsx`, `VoiceSystem.jsx`, `TrustSystem.jsx`, `PersonalitySystem.jsx`, `MemorySystem.jsx`, `RuntimeController.jsx`, `SocialIntentSystem.jsx`, `TurnPressureSystem.jsx`.
- `hooks/` - WebSocket hooks (`useAgentRegistry`, `useBrainMetricsWS`, `useVoiceChatWS`, `useOsintWS`, `useCognitionWS`, etc.).
- `store/` - Global state management using Zustand.
- `core/` - Runtime plumbing: EventBus, wsClient, thermalController, tripleLoopRuntime, performance system.
- `brainUI/`, `cognitiveRouter/`, `insightEngine/`, `predictionEngine/`, `learning/`, `memory/`, `rsdk/` - Brain-facing frontend modules.
- `admin/` - Admin app (layout, pages, store, components).
- `pages/`, `pipelines/`, `api/`, `db/`, `utils/`, `assets/` - Supporting modules.
