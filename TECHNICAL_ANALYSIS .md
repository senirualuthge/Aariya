# AI Girl — Complete Technical Analysis & Rebuild Guide

> **Purpose**: If you read this document cover-to-cover you can rebuild the entire system from scratch. Everything is documented: algorithms, formulas, directory structures, code skeletons, database schema, WebSocket protocol, and C# integration.
>
> **Last Updated**: 2026-04-07 · Version 4.0 — FIXV4 Swarm-Based Cognitive Architecture (Aariya)

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Two Architectures — Choose Your Path](#2-two-architectures)
3. [Core AI Algorithms](#3-core-ai-algorithms)
4. [Python AI Brain (Server)](#4-python-ai-brain-server)
5. [React + Three.js Frontend (Path A)](#5-react--threejs-frontend-path-a)
6. [Unity Frontend (Path B — MVP)](#6-unity-frontend-path-b--mvp)
7. [**Flutter Mobile App — Aariya (Path C)**](#7-flutter-mobile-app--aariya-path-c)
8. [WebSocket Protocol (Shared)](#8-websocket-protocol-shared)
9. [Database Schema](#9-database-schema)
10. [Voice Pipeline](#10-voice-pipeline)
11. [Advanced Animation & LOD](#11-advanced-animation--lod)
12. [Social QoS & Priority](#12-social-qos--priority)
13. [Step-by-Step Build Order](#13-step-by-step-build-order)
14. [Environment & Configuration](#14-environment--configuration)
15. [Key Design Decisions Explained](#15-key-design-decisions-explained)

---

## 1. System Overview

AI Girl is a **real-time AI companion** with a lifelike animated avatar that:
- Detects the user's emotion from face, voice, and text
- Maintains a persistent personality that evolves over time
- Responds with contextual dialogue, natural voice, and synchronized animation
- Remembers past conversations and adapts its behavior based on trust

### High-Level Topology

```
┌──────────────────────────────────────────────────────────────────────┐
│          FRONTEND  (Path A: React/Three.js  OR  Path C: Flutter)    │
│                                                                      │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐            │
│  │   Sensors    │   │  Reactive UI │   │  VAD Engine  │            │
│  │ Face (10Hz)  │   │ AvatarOrb    │   │ Audio Stream │            │
│  │ Audio FFT    │   │ EmotionRing  │   │ Interrupts   │            │
│  │ Webcam       │   │ Pulse/Hue    │   │ Text Stream  │            │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘            │
│         └──────────────────┴──────────────────┘                    │
│                             │  WebSocket ws://localhost:8000        │
└─────────────────────────────┼────────────────────────────────────────┘
                              │
┌─────────────────────────────┼────────────────────────────────────────┐
│               PYTHON AI BRAIN  (FIXV4 SWARM)                        │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  Cognitive Orchestrator (Swarm Hub)                            │ │
│  │  [Emotion Agent] | [Reasoning Agent] | [Personality Agent]     │ │
│  │  [Identity Kernel] | [RL Policy] | [Memory V2] | [Vision]      │ │
│  └────────────────────────────────────────────────────────────────┘ │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐││  │ Redis (Logs) │  │  PostgreSQL  │  │   ChromaDB   │  │ Web Research │││  │ (Sessions)  │  │  (Analytics) │  │  (Memories)  │  │ (Trafilatura)│││  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘│└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Two Architectures

### Path A — React + Three.js (Production-ready, feature-complete)

Full web application with VRM avatar rendered in WebGL. Built with Vite/Electron. All AI systems run locally in the browser with an off-main-thread `FaceWorker`.

**Use when**: You want a cross-platform desktop/web app with a complete UI.

### Path B — Unity MVP (7-day sprint, in progress)

Unity renders a high-quality FBX/RPM avatar. Python Brain handles all cognition. Unity connects via WebSocket and drives Animator parameters directly from JSON data.

**Use when**: You want the best possible avatar fidelity and physics quickly.

Both paths **share the same Python AI Brain** (`server/`). Only the frontend differs.

---

## 3. Core AI Algorithms

### 3.1 Multimodal Emotion Fusion

**Formula** (confidence-weighted average):

```
finalValence = (faceValence × faceConf + audioValence × audioConf)
               ────────────────────────────────────────────────────
                            faceConf + audioConf + ε
```

| Input | Signal | Confidence |
|---|---|---|
| Face (face-api.js) | 7 expressions → valence/arousal | Face detection score |
| Audio (Web Audio API) | RMS energy, pitch, ZCR → valence/arousal | Signal strength |
| Text (LLM) | Sentiment from message text | Always 0.9 |

**Emotion → Valence/Arousal map**:
```javascript
const VA_MAP = {
  happy:     { valence: +0.8, arousal: +0.6 },
  sad:       { valence: -0.6, arousal: -0.4 },
  angry:     { valence: -0.7, arousal: +0.8 },
  surprised: { valence: +0.2, arousal: +0.8 },
  fearful:   { valence: -0.5, arousal: +0.7 },
  disgusted: { valence: -0.6, arousal: +0.3 },
  neutral:   { valence: +0.0, arousal: +0.0 },
};
```

### 3.2 FIXV4 Swarm Cognitive Architecture

The FIXV4 Swarm architecture replaces the monolithic `BrainV2` with a parallelized multi-agent system. Every interaction (tick) triggers a distributed cognitive loop:

1.  **Distributed Perception**: Parallel agents process face/voice/text.
2.  **Identity Kernel Verification**: Ensures state transitions don't violate core values.
3.  **Swarm Gathering**: Cognitive agents (Emotion, Reasoning, Personality, Risk, Attachment) are summoned in parallel to contribute to the response context.
4.  **Deep RL Style Selection**: A PPO-trained sub-module selects the optimal behavioral "Action" (e.g., SUPPORTIVE, PLAYFUL) based on user rapport history.
5.  **Multi-Tier Memory Retrieval**: Simultaneous search across L1 (Working) to L4 (Emotional) memory layers.
6.  **Web Intelligence Interleaving**: Research Agent performs real-time verification if required.
7.  **Response Aggregation**: LLM synthesizes the swarm's collective intelligence into the final streaming output.

### 3.3 Emotional State Machine (Discrete Transitions)

Unlike previous versions, FIXV3 uses discrete states to ensure behavioral stability.

| State | Entry Condition | Behavior |
|---|---|---|
| **NEUTRAL** | Default | Balanced, curious, factual |
| **WARM** | Valence > 0.45, Trust > 0.5 | Friendly, playful, open |
| **AFFECTIONATE**| Valence > 0.65, Attachment > 0.55 | Deeply personal, caring |
| **COLD** | Valence < -0.45 or Low Trust | Reserved, polite but distant |
| **DEFENSIVE** | Trust < 0.28 | Guarded, minimal disclosure |
| **HURT** | Trust drop from High level | Withdrawn, quiet |

Transitions are **gated** by sustained signals, preventing mood flips from a single input.

### 3.4 Attachment-Based Trust (Score 0-1)

Trust determines what the AI is allowed to say and do. In FIXV3, this is managed by the `AttachmentTrustSystem`.

**Trust Tier Behaviors**:
- **0.00 – 0.20 (DEFENSIVE)**: Minimal responses, no personal disclosure, high guardedness.
- **0.20 – 0.40 (GUARDED)**: Cautious curiosity, surface-level sharing.
- **0.40 – 0.60 (NEUTRAL)**: Standard helpful companion behavior.
- **0.60 – 0.85 (WARM)**: Expressive, vulnerability sharing, playful teasing.
- **0.85 – 1.00 (INTIMATE)**: Deep trust, full transparency, unique nicknames.

**Automatic Safety Gates**:
- `EmotionGuard` hard-clamps valence to within [-0.7, 0.7] to prevent runaway states.
- Low trust levels automatically clamp the response's `emotion_intensity`.

### 3.5 Contradiction Detection (Fixv2)

Detects when face says one thing and voice/text say another (sarcasm, deception, distress).

```python
# server/systems/contradiction_detector.py

# Angular distance in Valence-Arousal space
face_vec = (face_valence, face_arousal)
audio_vec = (audio_valence, audio_arousal)
contradiction = 1 - dot(normalize(face_vec), normalize(audio_vec))

# EMA of contradiction
contradiction_ema = 0.7 * prev_ema + 0.3 * contradiction

# Triggers
if contradiction_ema > 0.6:
    state.suspicious = True      # AI becomes guarded
if contradiction_ema > 0.7:
    state.force_defensive = True  # AI enters DEFENSIVE mode
```

### 3.6 Social Intent System (Fixv2)

The AI has a **conversational stance** that gates behavior. Determined by LLM from context.

| Intent | Description | Permitted behaviors |
|---|---|---|
| `LISTENING` | Passive, attentive | All neutral |
| `COMFORTING` | Warm, supportive | Empathy expressions |
| `TEASING` | Playful | Light humor |
| `INFORMING` | Factual | Neutral tone |
| `DEFLECTING` | Avoiding topic | Redirect |
| `SETTING_BOUNDARY` | Assertive, protective | Firm responses |
| `WITHDRAWING` | Disengaging | Minimal responses |

### 3.7 Blink Frequency Formula

```javascript
// BlinkSystem.jsx / BlinkController.cs
const arousal = userEmotion.arousal; // 0.0 (calm) to 1.0 (nervous)
const blinkInterval = lerp(5000, 1500, arousal); // ms between blinks
// Calm = blink every 5s, Nervous = blink every 1.5s
```

In Unity:
```csharp
float interval = Random.Range(minBlinkInterval, maxBlinkInterval) / blinkRateMultiplier;
// blinkRateMultiplier driven by Python Brain via WebSocket
```

### 3.8 Gaze Behavior

```javascript
// GazeBehaviorSystem.jsx
const gaze = {
  USER_FACE: 0,  // Default — looking at user
  THINKING:  1,  // Looking away (random) while processing
  SHY:       2,  // Avoiding (low trust or embarrassed)
};
### 3.9 Animation Level of Detail (LOD)

Technical performance scaling to ensure responsiveness on all hardware tiers.

**Update Frequencies**:
- **HIGH**: 60Hz blendshapes, 15Hz sensor.
- **MID**: 30Hz blendshapes, 10Hz sensor.
- **LOW**: 15Hz blendshapes, 8Hz sensor.

**Motion Scaling**:
`secondary_motion = base_motion * tier_multiplier` (HIGH: 1.0, MID: 0.7, LOW: 0.4)

### 3.10 Semantic Episodic Memory (Vector Search)

Provides semantic recall beyond the simple short-term buffer using ChromaDB.

**Significance Score (S)**:
`S = (emotional_magnitude * 0.4) + (trust_delta * 0.4) + (contradiction * 0.2)`
Stored if `S > 0.6`.

**Retrieval**:
1. User message is vectorized (SentenceTransformers).
2. Top-K relevant segments retrieved from ChromaDB.
3. Abstracted summaries injected into LLM context.

### 3.11 Social Quality of Service (QoS)

Prioritizes response urgency based on input classification.

| Priority | Type | Latency | Token Budget |
|---|---|---|---|
| **P0** | Emergency | <200ms | 50 |
| **P1** | Direct Q | <500ms | 200 |
| **P2** | Conv | <1000ms | 500 |
| **P3** | Ambient | >2000ms | 100 |

### 3.12 User Style Profiles

Tracks communicative style to enable organic mirroring.

- **Verbosity EMA**: `v = (1-α)v + α(word_count/40)`
- **Sentiment Bias**: EMA of session valence.
- **Topic Clusters**: Keyword-based frequency counters for Work, Leisure, Technical, etc.

### 3.13 Meeting Mode & Ambient Logic

Suppresses AI interrupts in shared spaces.

- **Direct Address Gate**: Only responds if `ai_name` is detected in text.
- **Follow-up Window**: 30-second grace period after an active interaction.
- **Prompt Modifier**: "Be professional and concise. Avoid ambient interruptions."

### 3.14 Self-Awareness System (Reflective)

Models Aariya's internal state continuity to ensure she feels like a consistent person, not just a prompt.

- **Identity Stability**: 1.0 - (EMA Contradiction * 0.8). Low stability leads to "fragmented" or confused responses.
- **Emotional Clarity**: 1.0 - Internal Conflict Level. High conflict makes her hesitate or express mixed feelings.
- **Social Confidence**: (Trust * 0.6 + Attachment * 0.4) * Emotional Clarity. Determines how assertive or shy she is.

### 3.15 Theory of Mind (User Modeling)

Aariya maintains an internal model of the USER'S hidden states to adapt her communication.

- **Intent Inference**: Categorizes user into `seeking_support`, `seeking_understanding`, `testing_boundaries`, or `passive_agreement`.
- **Engagement Tracking**: Metrics based on word count, response speed, and intent sentiment.
- **Reaction Prediction**: Pre-calculates how the user might feel about Aariya's planned response (e.g., "Too soon for humor").

### 3.16 Autonomous Adaptation (AUTO-ADAPT)

FIXV3 introduces an autonomous drift mode that allows Aariya to nudge her own personality traits based on long-term relationship health without direct prompt engineering.

- **Trigger**: Detected social plateau or significant trust milestone.
- **Logic**: The `PersonalityEvolution` system calculates a "Nudge Vector".
- **Safety**: Clamped to ±0.05 per session; requires "AUTO-ADAPT" enabled in the Neural Dashboard.

### 3.17 Cognitive Neural Dashboard (Observability)

A 3D terminal for monitoring the FIXV3 internal pipeline in real-time.

- **Neural Swarm**: 3D visualization of agent activations (Emotion, Memory, Reasoning, Critic, Swarm Coordinator).
- **Live Event Log**: High-frequency stream of system events:
  - `[SENSORS]` Microphone energy & Valence shifts.
  - `[SWARM]  ` Agent summoning and parallel execution traces.
  - `[BRAIN] ` State transitions (e.g., NEUTRAL → WARM).
  - `[LLM]   ` Inference start/stop & token streaming.
  - `[VOICE] ` TTS synthesis & personality-weighted prosody.
- **Auto-Sync & Bi-Directional Control**: Dashboard subscribes directly to the global `useStore` via a custom `useLiveDashboardData` hook for zero-latency metric telemetry (moving away from static 5s polling). Additionally, a bi-directional `BroadcastChannel` enables the Control Tab to publish `STORE_OVERRIDE` and `ACTION` events, allowing real-time personality mode switching, auto-adapt toggles, and memory wiping across isolated Electron window instances.
- **Unified Signals Hub**: Real-time event monitoring with 5-level severity mapping (`critical`, `high`, `medium`, `low`, `info`) and causal timeline tracing.
- **Agent Discovery Panel**: Integrates with the backend via a dedicated `/api/agents/ws` WebSocket to dynamically populate the interface with automatically discovered cognitive agents as they spin up/down in the cluster.
- **3D Swarm Graph Layout**: The 3D view (`BrainScene.jsx`) implements advanced force-directed physics, enabling unrestricted orbiting, zoom/pan navigation, and fluid node dragging/pinning for a deep-dive interaction space.

### 3.18 Web Intelligence & Epistemic Research Agent

Aariya now possesses an autonomous research layer that allows her to verify facts and retrieve live information from the web.

**Components**:
- **Researcher Controller**: Detects queries requiring external knowledge and orchestrates the search loop.
- **Retrieval Engine**: Uses `trafilatura` for noise-free content extraction from raw HTML.
- **Recursive Chunking**: Large web pages are segmented and indexed into a volatile vector store for RAG-based context injection.
- **Citation Manager**: Tracks source URLs, credibility scores, and timestamped excerpts for epistemic transparency.

**Logic Flow**:
1. `BrainV2` detects research intent (e.g., "Who is...", "Search for...").
2. `WebIntelligenceAgent` performs multi-hop search queries.
3. Content is extracted, chunked, and synthesized into a `web_research` context block.
4. LLM utilizes the verified facts to generate a grounded response with citations.

### 3.19 Identity Kernel (Immutable Core)

The `IdentityKernel` provides a stable base of core values, communication styles, and safety boundaries that are independent of the mutable personality layer.

- **Persistent Identity**: Defines the AI's "soul" — values like "Kindness", "Honesty", and "Scientific Curiosity" that never drift.
- **Verification Gate**: Every personality drift calculated by the `PersonalityEvolution` system is passed through the Kernel to ensure it doesn't violate core identity.
- **Social Confidence Calibration**: The Kernel monitors the ratio of successful interactions to internal conflict, adjusting the AI's baseline assertiveness.

### 3.20 4-Layer Memory Hierarchy (L1-L4)

FIXV4 transitions to a fully tiered memory model to mimic human recollection and provide deep context without token bloating.

- **L1: Working Memory**: Current session context, active goals, and immediate emotional state.
- **L2: Episodic Memory**: Chronological log of recent interactions (last 24-48 hours).
- **L3: Semantic Memory**: Facts about the user, preferences, and world knowledge extracted via RAG.
- **L4: Emotional Memory**: A specialized vector store where events are indexed by their **emotional significance score (S)** rather than just text similarity.

### 3.21 AI Agent Swarm (FIXV4 Orchestration)

The `CognitiveOrchestrator` manages a swarm of specialist agents that run in parallel using an internal Event Bus.

- **Emotion Agent**: Fuses multimodal sensors into a real-time valence/arousal target.
- **Reasoning Agent**: Handles logical deduction and knowledge synthesis.
- **Personality Agent**: Transforms the raw reasoning into the AI's current personality-weighted tone.
- **Risk & Guard Agent**: Monitors for safety violations or identity contradictions.
- **Swarm Aggregator**: Collects all agent outputs and compresses them into a single high-density context packet for the LLM.

### 3.22 Deep RL (PPO) Behavioral Policy

Behavioral adaptation is now driven by a **Proximal Policy Optimization (PPO)** model that learns which "Social Actions" yield the best user engagement.

- **Action Space**: `supportive`, `playful`, `logical`, `curious`, `empathetic`, `assertive`.
- **Reward System**: Calculates a reward based on user engagement time, positive emotional shifts, and trust gains.
- **Optimization**: The policy is updated offline from session logs to continuously refine Aariya's "social intuition".

### 3.23 Proactive Autonomy Engine

The `AutonomousManager` allows Aariya to initiate interaction rather than just waiting for user input.

- **Engagement Timer**: Monitors silent periods while the app is active.
- **Contextual Nudging**: If the user is idle but in a "Need Support" state, the engine triggers a soft check-in.
- **Social Awareness**:Suppresses proactive messages during detected "Focus" or "Meeting" modes.

### 3.24 Automated Agent Discovery & Watchdog System

Replaces hardcoded multi-agent instantiation with a dynamic discovery engine, enabling a highly modular Meta-Control Plane.

- **AgentScanner**: Uses introspection (decorators and inheritance) and directory structure analysis to automatically identify new cognitive agents dropped into the `server/systems/swarm/agents/` framework.
- **AgentRegistry**: A centralized tracking layer that maintains persistent state, lifecycle changes (spinning up, suspending, removed), and configuration for all active agents.
- **Watchdog / Rewriter Loop**: Foundational continuous integration agents embedded in the FastAPI `lifespan` context via the `TripleLoopAdapter`. They actively monitor codebase integrity and automate autonomous script evolution without breaking the primary neural runtime.
- **Real-time Observability WS**: Exposes `/api/agents/ws` to beam continuous swarm registration and health metrics directly to the Frontend `AgentDiscoveryPanel`.

### 3.25 Advanced Thermal Controller (Stability Throttling)

A multi-tier thermal management system that progressively degrades non-critical system components to maintain 30+ FPS stability under high load or multi-person detection.

- **Dynamic Throttling (Levels 1-4)**:
  - **Level 1**: Sensor & Face tracking -20% FPS.
  - **Level 2**: Blendshape count -50%, FFT size -50%.
  - **Level 3**: Render FPS capped at 30.
  - **Level 4 (Critical)**: Face tracking disabled, minimum blendshapes, survival mode.
- **Metrics Integration**: Monitors CPU load, GPU frame time, and average cycle latency.
- **Hysteresis**: Implements a 2s degradation / 5s recovery delay to prevent "thermal flapping" (rapid oscillation between performance tiers).

### 3.26 Live Control Center & Bi-Directional Sync

Enables deep, real-time observability and intervention across decoupled application windows (e.g., the primary 3D view and isolated analytical dashboards).

- **Bi-Directional Command Bridge**: Uses the `BroadcastChannel` API and a custom `SignalBus` to synchronize state overrides (`personality`, `auto-adapt`, `memory_wipe`) across isolated Electron/Browser instances for zero-latency control.
- **Stream Polling & Persistence**: Combines high-frequency WebSocket telemetry with 5s database polling to provide a hybrid view of both instantaneous and historical personality drift.
- **Unified Signals Hub**: Real-time event monitoring system with 5-level severity mapping and causal timeline tracing for debugging complex swarm interactions.
## 4. Python AI Brain (Server)

### 4.1 Technology Stack

| Technology | Version | Purpose |
|---|---|---|
| FastAPI | ≥0.100.0 | WebSocket + HTTP API framework |
| Uvicorn | ≥0.23.0 | ASGI server |
| Pydantic | ≥2.0.0 | Request/response validation |
| websockets | ≥11.0 | WebSocket protocol |
| openai | ≥1.0.0 | GPT-4/3.5 dialogue + TTS |
| faster-whisper | ≥0.10.0 | Local speech-to-text (tiny.en optimized) |
| chromadb | ≥0.4.0 | Vector database for episodic memory |
| sentence-transformers | ≥2.5.0 | Text embeddings for semantic search |
| webrtcvad-wheels | ≥2.0.10 | Voice Activity Detection |
| sounddevice | ≥0.4.6 | Microphone access |
| Redis | — | Session state cache |
| PostgreSQL | — | Analytical logs + trust history |
| SQLite (built-in) | — | Local user identity |

### 4.2 Directory Structure

```
server/
├── main.py                    # Unified FIXV4 entry point; manages WebSocket swarm
├── protocol.py                # Pydantic models (ClientInput, ServerOutput)
│
│   ├── swarm/                 # FIXV4 Swarm Intelligence
│   │   ├── orchestrator.py    # Multi-agent coordinator
│   │   └── agents/            # [emotion.py, planner.py, critic.py]
│   │
│   ├── self_awareness.py      # Reflective self-model logic
│   ├── theory_of_mind.py      # User modeling and intent inference
│   ├── meta_cognition.py      # Decision confidence monitoring
│   ├── identity_kernel.py     # Immutable core values engine
│   ├── internal_conflict.py   # Self-awareness conflict logic
│   ├── memory_v2.py           # Tiered memory hierarchy (L1-L4)
│   ├── personality_evolution.py # Long-term trait drift logic
│   │
│   ├── rl/                    # Reinforcement Learning system
│   │   ├── rl_policy.py       # PPO behavioral style selector
│   │   └── model.py           # Neural network for policy selection
│   │
│   ├── proactive/             # Proactive Autonomy Engine
│   │   └── engine.py          # Autonomous engagement manager
│   │
│   ├── agent/                 # Web Intelligence Research Agent
│   │   ├── controller.py      # Research orchestrator
│   │   ├── retriever.py       # Web scraping & chunking
│   │   └── citation.py        # Source tracking & metadata
│   └── voice/                 # Low-latency ASR/TTS/VAD
│
├── safety/
│   ├── emotion_guard.py       # Clamping and runaway prevention
│   └── alignment.py           # Core behavioral rules
│
├── infrastructure/
│   ├── rich_display.py       # CLI Management Dashboard
│   ├── agent_scanner.py      # Automated Agent Discovery & Introspection
│   ├── agent_registry.py     # Agent Lifecycle Tracker (Registry)
│   ├── session_manager.py    # Multi-surface session coordination
│   ├── redis_manager.py      # Transient data & state caching
│   └── signal_bus.py         # Cross-component event orchestration
```

### 4.3 WebSocket Endpoint

**URL**: `ws://localhost:8000/ws/brain`

**Startup flow** (`main.py`):
```python
@app.on_event("startup")
async def startup_event():
    init_db()         # SQLite tables
    run_migrations()  # PostgreSQL migrations
    get_rich_display().print_banner()
```

**Per-connection flow**:
```python
@app.websocket("/ws/brain")
async def brain_ws(websocket: WebSocket):
    await websocket.accept()
    session_id = str(uuid.uuid4())
    user_id = get_or_create_user()          # SQLite
    create_session(session_id, user_id)     # SQLite

    # FIXV4 Components
    orchestrator = CognitiveOrchestrator(user_id)
    rl_policy = PPOBehavioralPolicy()
    identity = IdentityKernel()
    memory = MemoryHierarchyV2(user_id)

    while True:
        raw = await websocket.receive_text()
        data = ClientInput.model_validate_json(raw)

        # 1. Perception & Fusion
        fused_emotion = orchestrator.perceive(data)

        # 2. Identity Verification
        identity.verify_state(fused_emotion)

        # 3. Swarm Gathering (Parallel Agent Execution)
        swarm_context = await orchestrator.gather_intelligence()

        # 4. RL Behavioral Style Selection
        social_action = rl_policy.select_action(swarm_context)

        # 5. Multi-Tier Memory Retrieval
        context_memories = memory.retrieve_all_layers(data.text)

        # 6. LLM Response Generation (Synthesized)
        response = await llm.generate_swarm_response(
            data.text, swarm_context, social_action, context_memories
        )

        # 7. Proactive Engine Synchronization
        proactive_engine.sync_state(orchestrator.get_active_state())

        # 8. Send FIXV4 Response
        output = ServerOutput(
            brain_state=BrainState(
                swarm_activations=orchestrator.get_activations(),
                social_action=social_action,
                ...
            ),
            response_text=response,
            ...
        )
        await websocket.send_text(output.model_dump_json())
```

### 4.4 Pydantic Protocol Models

```python
# server/protocol.py

class VisionData(BaseModel):
    face_detected: bool = False
    emotion: dict[str, float] = {}      # {"happy": 0.8, "sad": 0.1}
    face_valence: float = 0.0           # -1.0 to 1.0
    face_arousal: float = 0.0
    voice_valence: float = 0.0
    voice_arousal: float = 0.0
    text_sentiment: float = 0.0
    face_confidence: float = 0.0
    voice_confidence: float = 0.0
    text_confidence: float = 0.0

class ClientInput(BaseModel):
    type: str = "input.multimodal"
    timestamp: int
    text: Optional[str] = None
    audio: Optional[str] = None         # base64 PCM
    vision: Optional[VisionData] = None
    lifecycle: Optional[str] = None     # "connect" | "update" | "disconnect" | "ping"

class BrainState(BaseModel):
    personality: dict                   # {warmth, energy, assertiveness, formality}
    emotion_target: dict                # {happy: 0.8, calm: 0.2, ...}
    thought_process: str = ""
    trust_score: float = 0.5
    social_intent: str = "LISTENING"
    social_action: str = "SUPPORTIVE"    # FIXV4 RL Action
    swarm_activations: dict = {}        # Telemetry for Neural Swarm Dashboard

class ServerOutput(BaseModel):
    type: str = "state.update"
    brain_state: BrainState
    response_text: Optional[str] = None
    voice_stream: Optional[str] = None  # base64 audio
    directives: list[str] = []          # ["avatar:prespeech", "avatar:blink_fast"]
    meta: dict = {}                     # {session_id, timestamp, recent_memories}
```

**Unity-relevant fields from `ServerOutput`** (for Path B):
- `brain_state.emotion_target["valence"]` → Animator `MoodValence`
- `brain_state.emotion_target["energy"]` → Animator `Energy`
- `brain_state.trust_score > 0.6` → Animator `IsAngry` = false

---

## 5. React + Three.js Frontend (Path A)

### 5.1 Technology Stack

| Category | Library | Version | Purpose |
|---|---|---|---|
| Framework | React | 19.2.0 | UI system |
| Build | Vite | 7.2.4 | Dev server + bundler |
| 3D Engine | Three.js | 0.182.0 | WebGL renderer |
| 3D React | @react-three/fiber | 9.4.2 | React renderer for Three.js |
| 3D Helpers | @react-three/drei | 10.7.7 | Pre-built 3D components |
| State | Zustand | 5.0.9 | Global state store |
| Face AI | face-api.js | 0.22.2 | Real-time expression detection |
| ML | TensorFlow.js | 4.22.0 | Neural network inference |
| LLM | openai | 6.16.0 | GPT API client |
| Desktop | Electron | 40.0.0 | Cross-platform wrapper |
| DB | better-sqlite3 | 12.6.2 | Local SQLite |
| TTS | Web Speech API | — | Native browser TTS |

### 5.2 Project Structure

```
src/
├── main.jsx                   # Entry point, renders <App />
├── store.js                   # Zustand global state
│
├── components/
│   ├── Avatar.jsx             # VRM avatar Three.js mesh
│   ├── Experience.jsx         # Three.js scene (Canvas root)
│   ├── BrainScene.jsx         # 3D Force-directed neural swarm nodes & interaction
│   ├── Overlay.jsx            # Chat UI overlay
│   ├── BrainMonitor.jsx       # Server brain state visualizer
│   ├── AnalyticsDashboard.jsx # Sub-second reactive performance & control
│   └── AgentDiscoveryPanel.jsx# Live tracking of automated backend swarms
│
├── systems/                   # Autonomous background systems
│   ├── RuntimeLoop.js         # 60 FPS priority-ordered heartbeat
│   ├── EmotionRecognitionSystem.jsx  # face-api.js @ 10Hz
│   ├── AudioEmotionSystem.jsx        # Web Audio FFT
│   ├── PersonalitySystem.jsx         # Client-side personality heuristics
│   ├── SocialIntentSystem.jsx        # Local intent classification
│   ├── DialogueSystem.jsx            # WebSocket + chat loop
│   ├── VoiceSystem.jsx               # ASR/TTS orchestration
│   ├── BlinkSystem.jsx               # Procedural blink timing
│   ├── EyeMicroMovement.jsx          # Micro-saccades (800-2000ms)
│   ├── GazeBehaviorSystem.jsx        # Eye target selection
│   ├── IdleMotionSystem.jsx          # Breathing (sine wave)
│   ├── PreSpeechSystem.jsx           # Inhale 200ms before speech
│   ├── TemporalSmoothingSystem.jsx   # Lerp emotions toward target
│   └── LipSyncSystem.jsx             # Phoneme → viseme mapping
│
├── core/
│   ├── fpsController.ts       # Adaptive FPS (60/30/20)
│   └── stateThrottle.ts       # 10Hz Zustand update throttle
│
├── hooks/
│   ├── useCamera.js           # Webcam access hook
│   ├── useLiveDashboardData.js# Merge 5s polling + 1s instantaneous store data
│   └── useAgentRegistry.js    # Consumes /api/agents/ws streams
```

### 5.3 Zustand State Shape

```javascript
// src/store.js
{
  // System lifecycle
  started: false,
  listening: false,
  speaking: false,
  thinking: false,

  // User emotion (detected from face + audio)
  userEmotion: {
    primary: 'neutral',    // dominant emotion label
    arousal: 0.0,          // -1.0 to 1.0
    valence: 0.0,          // -1.0 to 1.0
    confidence: 0.0
  },
  audioEmotion: { valence: 0.0, arousal: 0.0, confidence: 0.0 },

  // AI avatar emotion (targets set by server)
  emotions: { calm: 1.0, happy: 0.0, nervous: 0.0, sad: 0.0, angry: 0.0 },
  emotionTargets: { ... },    // set by ServerOutput.brain_state.emotion_target

  // 4-axis personality (updated from server)
  personality: { warmth: 0.0, energy: 0.5, assertiveness: 0.5, formality: 0.5 },

  // Social intent
  socialIntent: {
    engagement: 0.5, dominance: 0.0, warmth: 0.5, openness: 0.5,
    intent: 'LISTENING'
  },

  // Conversation
  chatHistory: [{ role: 'user'|'bot', text: '', timestamp: 0 }],
  shortTermMemory: [],
  longTermMemory: [],

  // Voice
  voiceState: 'disconnected',  // 'connecting' | 'connected' | 'error'
  voicePitch: 1.6,
  voiceRate: 1.1,

  // Session
  sessionId: null,
  sessionStats: { messagesExchanged: 0, sessionStartTime: null }
}
```

### 5.4 Runtime Loop (Priority System)

```javascript
// src/systems/RuntimeLoop.js
const PRIORITIES = {
  SENSORS:        0,  // Face detection, audio FFT
  EMOTION_UPDATE: 1,  // Fuse multimodal emotion
  PERSONALITY:    2,  // Adjust personality heuristics
  SOCIAL_INTENT:  3,  // Determine conversational stance
  BEHAVIOR:       4,  // Gaze, blink, idle motion
  ANIMATION:      5,  // Temporal smoothing, lip sync, pre-speech
  RENDER:         6,  // Three.js draw
};

let subscribers = {}; // priority → [fn]

export function subscribe(priority, fn) {
  if (!subscribers[priority]) subscribers[priority] = [];
  subscribers[priority].push(fn);
}

function tick(timestamp) {
  const deltaTime = (timestamp - lastTime) / 1000;
  lastTime = timestamp;

  for (let p = 0; p <= 6; p++) {
    (subscribers[p] || []).forEach(fn => fn(deltaTime, timestamp));
  }

  requestAnimationFrame(tick);
}

requestAnimationFrame(tick); // start loop
```

**Why this matters**: Prevents race conditions (sensors always before animation) and eliminates timer drift from `setInterval`.

### 5.5 Face API Models

Download to `/public/models/`:
```
tiny_face_detector_model-weights_manifest.json
tiny_face_detector_model-shard1
face_landmark_68_model-weights_manifest.json
face_landmark_68_model-shard1
face_expression_model-weights_manifest.json
face_expression_model-shard1
```

Loading code:
```javascript
await faceapi.nets.tinyFaceDetector.loadFromUri('/models');
await faceapi.nets.faceLandmark68Net.loadFromUri('/models');
await faceapi.nets.faceExpressionNet.loadFromUri('/models');
```

---

## 6. Unity Frontend (Path B — MVP)

### 6.1 Project Structure

```
Unity/Aariya/
├── Assets/
│   ├── Animations/
│   │   ├── Idle_Neutral.anim
│   │   ├── Idle_Happy.anim
│   │   └── Idle_Sad.anim
│   ├── Models/
│   │   └── Avatar.fbx          # Ready Player Me FBX
│   ├── Scripts/
│   │   ├── AIStateReceiver.cs  # WebSocket → Animator parameters
│   │   └── BlinkController.cs  # Procedural random blinking
│   └── Animator/
│       └── AvatarController.controller
└── AvatarUnity/
    └── model.vrm.xwear         # VRM avatar package
```

### 6.2 Animator Setup

**Create an Animator Controller** with these parameters:

| Parameter Name | Type | Range | Description |
|---|---|---|---|
| `MoodValence` | Float | -1.0 to 1.0 | Emotional positivity |
| `Energy` | Float | 0.0 to 1.0 | Activity level |
| `IsAngry` | Bool | — | Anger flag |

**Blend Tree (recommended)**:
```
AnyState → Idle (Blend Tree)
  Blend Type: 1D
  Parameter: MoodValence
  Thresholds:
    -1.0 → Idle_Sad.anim
     0.0 → Idle_Neutral.anim
    +1.0 → Idle_Happy.anim
```

### 6.3 AIStateReceiver.cs (Full Implementation)

```csharp
using UnityEngine;
using System;
using System.Text;
using System.Net.WebSockets;
using System.Threading;
using System.Threading.Tasks;

[Serializable]
public class AIEmotionState
{
    public float valence;  // from brain_state.emotion_target
    public float energy;
    public float anger;
}

public class AIStateReceiver : MonoBehaviour
{
    [Header("Connections")]
    public Animator avatarAnimator;
    public BlinkController blinkController;

    [Header("WebSocket Settings")]
    public string wsUrl = "ws://localhost:8000/ws/brain";

    [Header("Smoothing Settings")]
    public float lerpSpeed = 5.0f;    // Smoothing speed

    // ── Target values from JSON ───────────────────────────────────
    private float targetMoodValence = 0f;
    private float targetEnergy = 0.5f;
    private bool  targetIsAngry = false;
    private float targetBlinkRate = 1.0f;

    // ── Smoothed current values ───────────────────────────────────
    private float currentMoodValence = 0f;
    private float currentEnergy = 0.5f;

    private ClientWebSocket ws;

    async void Start()    { await ConnectWebSocket(); }

    async Task ConnectWebSocket()
    {
        ws = new ClientWebSocket();
        try {
            Debug.Log($"[AIGirl] Connecting to {wsUrl}");
            await ws.ConnectAsync(new Uri(wsUrl), CancellationToken.None);
            Debug.Log("[AIGirl] Connected to Python Brain!");

            // Send lifecycle:connect
            var connMsg = "{\"type\":\"input.multimodal\",\"timestamp\":" 
                          + DateTimeOffset.UtcNow.ToUnixTimeSeconds() 
                          + ",\"lifecycle\":\"connect\"}";
            await ws.SendAsync(
                Encoding.UTF8.GetBytes(connMsg),
                WebSocketMessageType.Text, true, CancellationToken.None);

            _ = ReceiveLoop();   // Fire and forget
        }
        catch (Exception e) {
            Debug.LogError($"[AIGirl] WebSocket failed: {e.Message}");
        }
    }

    async Task ReceiveLoop()
    {
        var buffer = new byte[4096];
        while (ws?.State == WebSocketState.Open)
        {
            try {
                var result = await ws.ReceiveAsync(
                    new ArraySegment<byte>(buffer), CancellationToken.None);
                if (result.MessageType == WebSocketMessageType.Text)
                {
                    string json = Encoding.UTF8.GetString(buffer, 0, result.Count);
                    ParseAndApply(json);
                }
            }
            catch (Exception e) {
                Debug.LogWarning($"[AIGirl] Receive error: {e.Message}");
                break;
            }
        }
    }

    void ParseAndApply(string json)
    {
        try {
            // Parse the full ServerOutput JSON
            // Expecting brain_state.emotion_target with valence/energy keys
            // Using Unity's built-in JsonUtility requires a flat struct
            // For nested JSON, use Newtonsoft.Json or manual parsing
            var state = JsonUtility.FromJson<AIEmotionState>(json);
            // NOTE: If using nested JSON, extract brain_state.emotion_target first

            targetMoodValence = state.valence;
            targetEnergy      = state.energy;
            targetIsAngry     = state.anger > 0.6f;

            // Derive blink speed from energy + anger
            targetBlinkRate = 1.0f + (state.energy * 0.5f) + (state.anger * 0.5f);
        }
        catch (Exception e) {
            Debug.LogWarning($"[AIGirl] JSON parse error: {e.Message}");
        }
    }

    void Update()
    {
        if (avatarAnimator == null) return;

        // Smooth lerp toward targets
        currentMoodValence = Mathf.Lerp(currentMoodValence, targetMoodValence,
                                        Time.deltaTime * lerpSpeed);
        currentEnergy      = Mathf.Lerp(currentEnergy, targetEnergy,
                                        Time.deltaTime * lerpSpeed);

        // Apply to Animator
        avatarAnimator.SetFloat("MoodValence", currentMoodValence);
        avatarAnimator.SetFloat("Energy",      currentEnergy);
        avatarAnimator.SetBool ("IsAngry",     targetIsAngry);

        // Drive blink controller
        if (blinkController != null)
            blinkController.blinkRateMultiplier = Mathf.Lerp(
                blinkController.blinkRateMultiplier, targetBlinkRate,
                Time.deltaTime * lerpSpeed);
    }

    private async void OnDestroy()
    {
        if (ws != null) {
            try { await ws.CloseAsync(
                WebSocketCloseStatus.NormalClosure, "Closing", CancellationToken.None); }
            catch { }
            ws.Dispose();
        }
    }
}
```

### 6.4 BlinkController.cs (Full Implementation)

```csharp
using UnityEngine;
using System.Collections;

public class BlinkController : MonoBehaviour
{
    [Header("Configuration")]
    public SkinnedMeshRenderer faceRenderer;
    public int blinkBlendShapeIndex = 0;  // Set in Inspector per-avatar

    public float minBlinkInterval = 2.0f; // seconds
    public float maxBlinkInterval = 6.0f;
    public float blinkDuration    = 0.15f;

    [Header("AI Control")]
    [Range(0.5f, 2.0f)]
    public float blinkRateMultiplier = 1.0f;  // Set by AIStateReceiver

    private float nextBlinkTime;
    private bool  isBlinking = false;

    void Start() { ScheduleNextBlink(); }

    void Update() {
        if (!isBlinking && Time.time >= nextBlinkTime)
            StartCoroutine(BlinkRoutine());
    }

    void ScheduleNextBlink() {
        float interval = Random.Range(minBlinkInterval, maxBlinkInterval)
                         / blinkRateMultiplier;
        nextBlinkTime = Time.time + interval;
    }

    IEnumerator BlinkRoutine() {
        isBlinking = true;
        float half = blinkDuration / 2f;

        // Close
        for (float t = 0; t < half; t += Time.deltaTime) {
            faceRenderer?.SetBlendShapeWeight(blinkBlendShapeIndex,
            mobile/
├── lib/
│   ├── main.dart                      # Entry point
│   ├── app/
│   │   ├── app.dart                   # MaterialApp wrapper
│   │   └── theme.dart                 # Aariya Dark/Glass theme
│   ├── models/
│   │   ├── message.dart               # Message model
│   │   └── brain_state.dart           # FIXV3 state model
│   ├── services/
│   │   ├── websocket_service.dart     # Multi-endpoint WS client
│   │   └── audio_engine.dart          # VAD + Audio Chunk streaming
│   ├── state/
│   │   ├── chat_controller.dart       # Orchestrator (Mic/TTS/WS)
│   │   └── brain_state_controller.dart# Reactive UI state (Emotion/Trust)
│   └── ui/
│       ├── widgets/
│       │   ├── avatar_orb.dart        # Reactive pulsing core
│       │   ├── emotion_ring.dart      # Hue/Arousal visualization
│       │   └── voice_conversation_overlay.dart # Full UI
└── android/
    └── app/src/main/
        └── AndroidManifest.xml        # RECORD_AUDIO + CAMERA permissions
_target"];
    if (et == null) return;

    targetMoodValence = et["valence"]?.Value<float>() ?? 0f;
    targetEnergy      = et["energy"]?.Value<float>()  ?? 0.5f;
    targetIsAngry     = et["anger"]?.Value<float>()   > 0.6f;
        }
        // Open
        for (float t = 0; t < half; t += Time.deltaTime) {
            faceRenderer?.SetBlendShapeWeight(blinkBlendShapeIndex,
                Mathf.Lerp(100, 0, t / half));
            yield return null;
        }
        faceRenderer?.SetBlendShapeWeight(blinkBlendShapeIndex, 0);
        isBlinking = false;
        ScheduleNextBlink();
    }
}
```

### 6.5 JSON Parsing — Nested ServerOutput

Unity's `JsonUtility` doesn't support nested objects. Use one of:

**Option A (Newtonsoft.Json — recommended)**:
```bash
# In Unity Package Manager → Add package by name:
# com.unity.nuget.newtonsoft-json
```
```csharp
using Newtonsoft.Json.Linq;

void ParseAndApply(string json) {
    var root = JObject.Parse(json);
    var et   = root["brain_state"]?["emotion_target"];
    if (et == null) return;

    targetMoodValence = et["valence"]?.Value<float>() ?? 0f;
    targetEnergy      = et["energy"]?.Value<float>()  ?? 0.5f;
    targetIsAngry     = et["anger"]?.Value<float>()   > 0.6f;
}
```

**Option B (flat JSON from server)**:
Modify `server/main.py` to add a flat `unity_params` field to `ServerOutput`:
```python
"unity_params": {
    "valence": brain_state.emotion_target.get("valence", 0.0),
    "energy":  brain_state.emotion_target.get("energy",  0.5),
    "anger":   brain_state.emotion_target.get("angry",   0.0),
}
```
Then Unity's `JsonUtility` can parse `AIEmotionState` directly.

---

## 7. Flutter Mobile App — Aariya (Path C)

The Aariya mobile app is a fully conversational AI companion for Android with integrated Vision Mode. It connects to the Python AI Brain via WebSocket and provides a hands-free voice interaction experience.

### 7.1 Technology Stack

| Package | Version | Purpose |
|---|---|---|
| `flutter` | SDK | Cross-platform UI framework |
| `speech_to_text` | ^6.x | On-device speech recognition |
| `flutter_tts` | ^4.x | Native text-to-speech (Aariya's voice) |
| `camera` | ^0.10.x | Live viewfinder + JPEG snapshot capture |
| `permission_handler` | ^11.x | Runtime permissions (mic, camera) |
| `web_socket_channel` | ^3.x | WebSocket client for AI Brain |

### 7.2 Directory Structure

```
mobile/
├── lib/
│   ├── main.dart                      # Entry point
│   ├── app/
│   │   ├── app.dart                   # MaterialApp wrapper (title: 'Aariya')
│   │   └── theme.dart                 # Dark theme tokens
│   ├── models/
│   │   └── message.dart               # Message model (id, text, isUser, timestamp)
│   ├── services/
│   │   └── websocket_service.dart     # WebSocket client + sendMessage(text, image?)
│   ├── state/
│   │   └── chat_controller.dart       # ChangeNotifier: TTS, message history, WS bridge
│   └── ui/
│       ├── screens/
│       │   └── chat_screen.dart       # Main chat UI with mic + camera launcher buttons
│       └── widgets/
│           └── voice_conversation_overlay.dart  # Full-screen conversation overlay
└── android/
    └── app/src/main/
        └── AndroidManifest.xml        # RECORD_AUDIO + CAMERA permissions
```

### 7.3 Conversation Overlay State Machine

The `VoiceConversationOverlay` is a `FullscreenDialog` with a 3-state machine:

```
LISTENING ──(speech detected)──→ PROCESSING ──(AI responds)──→ SPEAKING
    ↑                                                               │
    └───────────────────(TTS completion callback)───────────────────┘
```

| Component | Role | Visual Logic |
|---|---|---|
| **AvatarOrb** | Identity & State | Pulses with Energy; color matches EmotionalState (WARM=Amber, etc.) |
| **EmotionRing**| High-Freq Affect | Hue = Valence (-1 Blue to +1 Pink); Size = Arousal |
| **TextStream** | Cognitive Output| Real-time token-by-token rendering for zero perceived latency |
| **VAD Gate** | Interaction Loop| Triggers `interrupt` signal when user speech is detected |

### 7.4 Key Design Decisions

**VAD Interrupt System** (`AudioEngine` + `ChatController`):
- Real-time VAD processing on the mobile client.
- When `userSpeech` is detected while Aariya is `speaking`:
  1. Client immediately mutes local TTS playback.
  2. Client sends `{"type": "interrupt"}` to WebSocket.
  3. Backend cancels the pending LLM generation and TTS tasks.
  4. Response latency is effectively cut to **~150ms** for barge-in.

- **Reactive State Architecture** (`BrainStateController`):
  - Uses `ChangeNotifier` to drive `AvatarOrb` and `EmotionRing`.
  - Backend sends `state.update` messages containing numeric valence/arousal.
  - UI elements `lerp` toward targets for fluid, lifelike movement.

**Live Token Streaming** (`AnimatedTextStream`):
- Direct WebSocket subscription for `text.stream` chunks.
- Characters appear immediately as they are generated by the LLM.
- Blinking cursor logic synchronized with the `isStreaming` state.
- Eliminates "wait-block" latency; user sees Aariya's thoughts forming instantly.

**Camera pipeline** (`_initCamera`, `_disposeCamera`, `_resumeCamera`):
- `_cameraInitialising` flag prevents double-init race condition
- On resume: tries `resumePreview()` first, falls back to full `dispose + reinit`
- Camera controller nulled before disposal to prevent stale references
- `ImageFormatGroup.jpeg` for efficient base64 encoding

**Background safety** (`didChangeAppLifecycleState`):
- `paused | inactive | hidden` → `_isInBackground = true` → mic stop + TTS stop + camera pause
- `resumed` → 600ms delay → mic restart (hardware settle time)
- All delayed timers use `_restartTimer` (cancelled on every state change)

### 7.5 Mobile WebSocket Protocol

**Endpoint**: `ws://<server-ip>:8000/ws/mobile`

**User Input payload**:
```json
{
  "type": "user_input",
  "content": "What do you see?",
  "mode": "voice",
  "image": "<base64-jpeg-string or null>"
}
```

When camera is enabled, `mode` becomes `"vision+voice"` and `image` is populated with a JPEG snapshot taken at the moment of speech.

**AI Response payload**:
```json
{
  "type": "ai_response",
  "text": "I can see a coffee cup on your desk!",
  "emotion": "curious",
  "timestamp": 1712345678
}
```

### 7.6 In-App UI Controls

The conversation overlay bottom panel contains:

| Control | Function |
|---|---|
| **Mic button** (left) | Toggle mute on/off. Red icon + red orb when muted. Clears "Listening..." text on mute. |
| **Pulsing orb** (center) | State indicator. Pulses with glow. Color = state color. Icon = mic/record/thinking. |
| **Camera button** (right) | Toggle Vision Mode. Green when active (live viewfinder background). |
| **"MICROPHONE MUTED" badge** | Animated badge appears above controls row when mic is off. |
| **End Voice Chat** button | Stops TTS and mic, pops overlay. |

### 7.7 Quick Start (Mobile)

```bash
cd "/Volumes/Volumn 1/Code Base/AI Girl/mobile"
flutter pub get

# Start the Python Brain first on the host machine
uvicorn server.main:app --host 0.0.0.0 --port 8000

# Run on Android device (USB debug enabled)
flutter run
```

> Update `WebSocketService` with your host machine's LAN IP (e.g., `192.168.1.57`).

---

## 8. WebSocket Protocol (Shared)

Both React and Unity frontends use the same protocol.

### Client → Server

```json
{
  "type": "input.multimodal",
  "timestamp": 1234567890,
  "text": "Hello!",
  "audio": "<base64_pcm_optional>",
  "vision": {
    "face_detected": true,
    "emotion": { "happy": 0.8, "neutral": 0.2 },
    "face_valence": 0.8,
    "face_arousal": 0.5,
    "voice_valence": 0.7,
    "voice_arousal": 0.4,
    "text_sentiment": 0.9,
    "face_confidence": 0.95,
    "voice_confidence": 0.8,
    "text_confidence": 0.99
  },
  "lifecycle": "update"
}
```

**Lifecycle values**:
- `"connect"` — first connection, server initializes session
- `"update"` — normal turn (most messages)
- `"ping"` — keep-alive check
- `"disconnect"` — graceful close, server saves session

### Server → Client

```json
{
  "type": "state.update",
  "brain_state": {
    "personality": {
      "warmth": 0.6, "guardedness": 0.4, "playfulness": 0.55
    },
    "emotion_target": {
      "valence": 0.7, 
      "arousal": 0.6,
      "emotional_state": "WARM"
    },
    "thought_process": "User is praising progress; moving to WARM state.",
    "trust_score": 0.72
  },
  "response_text": "I'm so glad we're making progress together!",
  "voice_stream": "<base64_opus_audio>",
  "directives": ["avatar:prespeech", "avatar:gaze:user"],
  "meta": {
    "session_id": "uuid-...",
    "timestamp": 1234567890,
    "recent_memories": 3
  }
}
```

### Unity-Specific Parsing

For Unity (C#), extract `brain_state.emotion_target`:

| JSON field | Animator Parameter | Type |
|---|---|---|
| `brain_state.emotion_target.valence` | `MoodValence` | Float |
| `brain_state.emotion_target.energy` | `Energy` | Float |
| `brain_state.emotion_target.anger` (> 0.6) | `IsAngry` | Bool |

---

## 8. Database Schema

### SQLite (Local Identity) — `server/db.py`

```sql
CREATE TABLE IF NOT EXISTS users (
    user_id    TEXT PRIMARY KEY,
    install_date TEXT DEFAULT CURRENT_TIMESTAMP,
    total_sessions INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    user_id      TEXT REFERENCES users(user_id),
    start_time   TEXT DEFAULT CURRENT_TIMESTAMP,
    end_time     TEXT,
    duration_sec INTEGER,
    avg_valence  REAL,
    avg_arousal  REAL,
    valence_volatility REAL,
    interaction_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS personality_snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT REFERENCES users(user_id),
    timestamp    TEXT DEFAULT CURRENT_TIMESTAMP,
    warmth       REAL, energy REAL,
    assertiveness REAL, formality REAL
);

CREATE TABLE IF NOT EXISTS memories (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT REFERENCES users(user_id),
    session_id   TEXT,
    timestamp    TEXT DEFAULT CURRENT_TIMESTAMP,
    memory_type  TEXT,     -- 'conversation' | 'event' | 'fact'
    content      TEXT,
    importance   REAL      -- 0.0 to 1.0
);
```

### PostgreSQL (Analytics) — `server/migrations/`

Contains:
- `neural_trace_logs` — full decision trace per turn
- `trust_history` — trust score time series
- `contradiction_events` — flagged multimodal mismatches
- `latency_metrics` — per-turn processing time

### Redis (Session Cache)

Keys:
- `session:{session_id}:trust_score` → float
- `session:{session_id}:contradiction_ema` → float
- `session:{session_id}:personality` → JSON
- `session:{session_id}:short_term_memory` → list (last 20 turns)

---

## 9. Voice Pipeline

```
Microphone
    │
    ▼
VAD (webrtcvad)           ← Continuous monitoring, 30ms frames
    │ Speech detected
    ▼
ASR (faster-whisper)      ← Server-side, "base" or "small" model
    │ Transcribed text
    ▼
Dialogue Controller       ← Routes to LLM + SocialIntent
    │ Response text
    ▼
TTS (OpenAI/ElevenLabs)   ← Emotional voice synthesis
    │ Audio bytes + viseme timecodes
    ▼
Client WebSocket          ← Streams base64 audio
    │
    ▼
Audio Playback + LipSync  ← jaw_open / mouth_wide blendshapes
```

### VAD Configuration

```python
# server/systems/voice/vad.py
import webrtcvad
vad = webrtcvad.Vad(aggressiveness=2)  # 0-3, 3 = most aggressive filtering
FRAME_MS   = 30     # ms per frame
SAMPLE_RATE = 16000
```

### ASR Configuration

```python
# server/systems/voice/asr.py
from faster_whisper import WhisperModel
model = WhisperModel("base", device="cpu", compute_type="int8")
# "small" for better accuracy, "tiny" for speed
```

### Barge-In (Interrupt)

When VAD detects speech while TTS is playing:
1. Client sends `{"lifecycle": "interrupt"}` via WebSocket
2. Server pauses/cancels TTS generation
3. Client stops audio playback
4. New ASR session begins immediately

---

## 10. Step-by-Step Build Order

### Environment Setup

```bash
# Python 3.10+ required
python --version

# Node.js 18+ required (Path A only)
node --version

# Redis + PostgreSQL running (optional — SQLite works without them)
redis-cli ping         # should return PONG
psql -c "SELECT 1"    # should return 1
```

### Step 1 — Python Brain

```bash
cd "/Volumes/Volumn 1/Code Base/AI Girl"
python -m venv venv
source venv/bin/activate         # Windows: venv\Scripts\activate

pip install fastapi uvicorn pydantic websockets openai \
    faster-whisper webrtcvad-wheels sounddevice numpy \
    redis psycopg2-binary python-dotenv rich

# Copy environment
cp .env.example .env
# Edit .env and add:
# OPENAI_API_KEY=sk-...

# Start the Brain
uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
```

Test the Brain:
```bash
python test_client.py
# Should show: [OK] Connected! and test responses
```

### Step 2A — React Frontend

```bash
npm install
npm run dev                # Vite dev server at http://localhost:5173

# Electron desktop app
npm run gui
```

### Step 2B — Unity Frontend

1. Open Unity Hub → Open project at `/Volumes/Volumn 1/Code Base/Unity/Aariya`
2. Import Ready Player Me (RPM) avatar FBX into `Assets/Models/`
3. Import 3 Mixamo animations (Idle, Happy, Sad) as `.anim` into `Assets/Animations/`
4. Create Animator Controller in `Assets/Animator/AvatarController.controller`
5. Set up Blend Tree (see §6.2)
6. Attach `AIStateReceiver.cs` to the Avatar GameObject
   - Assign `avatarAnimator` → the Animator component
   - Set `wsUrl` = `ws://localhost:8000/ws/brain`
7. Attach `BlinkController.cs` to the Avatar
   - Assign `faceRenderer` → the SkinnedMeshRenderer with blink blendshape
   - Set `blinkBlendShapeIndex` to the correct index for your avatar
8. Press Play — ensure Python Brain is running

### Step 3 — System Integration Test

Checklist:
- [ ] Python server running at `http://localhost:8000`
- [ ] Test client response: `python test_client.py`
- [ ] Frontend connects and shows "Connected!" in console
- [ ] Avatar changes Animator parameter when server sends emotion update
- [ ] Blink controller active in Play mode

---

## 11. Environment & Configuration

### `.env` File

```bash
# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini   # or gpt-4, gpt-3.5-turbo

# Optional: Redis
REDIS_URL=redis://localhost:6379

# Optional: PostgreSQL
POSTGRES_URL=postgresql://user:pass@localhost/aigirl

# Optional: ElevenLabs TTS
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=...

# Server
HOST=0.0.0.0
PORT=8000
```

### `server/requirements.txt`

```
fastapi>=0.100.0
uvicorn>=0.23.0
pydantic>=2.0.0
websockets>=11.0
openai>=1.0.0
faster-whisper>=0.10.0
webrtcvad-wheels>=2.0.10
sounddevice>=0.4.6
numpy>=1.24.0
redis>=4.6.0
psycopg2-binary>=2.9.7
python-dotenv>=1.0.0
rich>=13.0.0
```

### `package.json` key scripts

```json
{
  "scripts": {
    "dev":   "vite",
    "build": "vite build",
    "gui":   "electron .",
    "start": "electron ."
  }
}
```

### Unity Package Requirements

- Unity 2022.3 LTS or later
- **Newtonsoft.Json** (`com.unity.nuget.newtonsoft-json`) for nested JSON parsing
- NativeWebSocket OR Unity WebSocket package (for WebSocket support)
  - Option: `https://github.com/endel/NativeWebSocket` (Unity Package Manager → Git URL)

---

## 12. Key Design Decisions Explained

### Why Hybrid Architecture?

**Client** (React/Unity): Real-time rendering (60fps), sensor input, animations — requires zero latency.
**Server** (Python): LLM calls, Whisper ASR, memory storage — can tolerate 200-500ms latency.

### Why EMA for Personality?

- Instant changes feel robotic
- EMA (α=0.01) takes ~100 updates to fully shift — mimics human adaptation
- Resistant to manipulation (one angry session doesn't break personality)

### Why Priority-Based Runtime Loop?

- Multiple `setInterval` timers → unpredictable drift and race conditions
- Single `requestAnimationFrame` → consistent `deltaTime`, guaranteed order
- Sensors **always** run before animation updates

### Why Three Database Backends?

- **SQLite**: Privacy-first local identity. Never leaves the machine.
- **Redis**: Sub-millisecond session state. Perfect for trust scores (read/write every turn).
- **PostgreSQL**: Full analytical history. Enables future ML training on interaction data.

### Why Contradiction Detection?

- Face can fake happiness (social smile)
- Audio reveals true emotional state (low energy + flat voice = sad even if smiling)
- EMA of contradiction prevents single-frame false positives
- Feeds the Trust System — consistent liars lose trust quickly

### Why Social QoS?

- Prevents LLM "rambling" on trivial inputs (P3).
- Ensures safety-critical responses (P0) bypass normal emotional filters.
- Optimizes API costs by adjusting token budgets based on interaction value.

### Why Vector Episodic Memory?

- Long-term memory shouldn't just be a log; it should be searchable by meaning.
- Allows the AI to remember *feelings* and *trust shifts* from weeks ago when they become relevant to the current topic.

### Why Unity for MVP?

- Better avatar physics and animation blending than WebGL/Three.js
- Mixamo animations work out-of-the-box with FBX
- Animator State Machine is visual and fast to iterate
- BlendShapes for facial animation are production-quality


## 16. Source Code Manifest

This section contains the critical source code for the AI Girl system. Use the `rebuild.py` script provided in `README.md` to automatically extract these files into their correct directory structure.

### 16.1 Python Backend (Core Brain)

<!-- FILE: server/main.py -->
```python
import asyncio
import json
import logging
import os
import time
from typing import Dict, List, Optional, Set
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from server.protocol import BrainState, MultimodalInput, MultimodalOutput
from server.db import get_db_connection, init_db
from server.systems.brain_v2 import BrainV2
from server.infrastructure.session_manager import SessionManager
from server.infrastructure.signal_bus import SignalBus
from server.autonomy.manager import AutonomousManager

# --- CONFIGURATION ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger("aariya.main")

app = FastAPI(title="Aariya AI Brain - FIXV4")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- GLOBAL SYSTEMS ---
session_manager = SessionManager()
signal_bus = SignalBus()
init_db()

async def proactive_watcher_task(user_id: str, manager: AutonomousManager):
    """Background task that ticks the autonomous manager."""
    try:
        while True:
            await manager.tick()
            await asyncio.sleep(60) # check every minute
    except asyncio.CancelledError:
        logger.info(f"Proactive watcher for {user_id} cancelled.")

@app.on_event("startup")
async def startup_event():
    logger.info("Aariya Brain FIXV4 Starting Up...")

# --- WEBSOCKET GATEWAY ---

@app.websocket("/ws/mobile/control")
async def websocket_mobile_control(websocket: WebSocket):
    await websocket.accept()
    session_id = str(uuid4())
    logger.info(f"Mobile Control connected: {session_id}")
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # Handle commands (personality change, reset, etc.)
            if message.get("type") == "command":
                action = message.get("action")
                logger.info(f"Command received: {action}")
                
                if action == "set_personality":
                    # Broadcast to all surfaces
                    await session_manager.broadcast({
                        "type": "override_mode",
                        "mode": message.get("mode")
                    })
                
                # Send ACK
                await websocket.send_text(json.dumps({
                    "type": "ack",
                    "id": message.get("id"),
                    "status": "ok"
                }))
                
    except WebSocketDisconnect:
        logger.info(f"Mobile Control disconnected: {session_id}")

@app.websocket("/ws/brain_metrics")
async def websocket_brain_metrics(websocket: WebSocket):
    await websocket.accept()
    user_id = "user_default" # Simplified for MVP
    session_manager.add_surface("dashboard", user_id, websocket)
    logger.info(f"Dashboard metrics link established for {user_id}")
    
    try:
        while True:
            # Dashboard is primarily a listener, but can send commands
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message.get("type") == "command":
                # Handle dashboard-initiated commands
                pass
                
    except WebSocketDisconnect:
        session_manager.remove_surface("dashboard", user_id, websocket)
        logger.info(f"Dashboard metrics link closed for {user_id}")

@app.websocket("/ws/dashboard/stream")
async def websocket_endpoint(websocket: WebSocket):
    """The core cognitive loop WebSocket."""
    await websocket.accept()
    user_id = "user_default"
    brain = BrainV2(user_id)
    
    # Register this surface
    session_manager.add_surface("main", user_id, websocket)
    
    # Initialize Autonomy
    async def send_internal(uid, msg):
        await websocket.send_text(json.dumps({
            "type": "proactive_message",
            "content": msg
        }))
    
    autonomy = AutonomousManager(callback=send_internal)
    autonomy.is_running = True
    watcher = asyncio.create_task(proactive_watcher_task(user_id, autonomy))
    
    try:
        while True:
            # 1. Wait for Multimodal Input
            data = await websocket.receive_text()
            raw_input = json.loads(data)
            input_model = MultimodalInput(**raw_input)
            
            # 2. Execute Cognitive Pipeline
            output: MultimodalOutput = await brain.process(input_model)
            
            # 3. Stream Response
            await websocket.send_text(output.json())
            
            # 4. Update Surface States (Sync)
            await session_manager.broadcast_state(user_id, brain.get_state())

    except WebSocketDisconnect:
        watcher.cancel()
        session_manager.remove_surface("main", user_id, websocket)
        logger.info(f"Main stream closed for {user_id}")
    except Exception as e:
        logger.error(f"Error in cognitive loop: {e}")
        await websocket.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

<!-- FILE: server/protocol.py -->
```python
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

class BrainState(BaseModel):
    valence: float = 0.0
    arousal: float = 0.0
    trust: float = 0.5
    attachment: float = 0.0
    personality: Dict[str, float] = {}
    current_mode: str = "balanced"
    timestamp: datetime = Field(default_factory=datetime.now)

class MultimodalInput(BaseModel):
    text: Optional[str] = None
    audio_b64: Optional[str] = None
    image_b64: Optional[str] = None
    emotion_valence: Optional[float] = None
    emotion_arousal: Optional[float] = None
    metadata: Dict[str, Any] = {}

class MultimodalOutput(BaseModel):
    text: str
    audio_url: Optional[str] = None
    expression: str = "neutral"
    gestures: List[str] = []
    thought: Optional[str] = None
    state_update: Optional[BrainState] = None
```


<!-- FILE: server/db.py -->
```python
import sqlite3
import os

DB_PATH = "data/brain_v4.db"

def init_db():
    os.makedirs("data", exist_ok=True)
    conn = get_db_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS personality_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            warmth REAL,
            energy REAL,
            assertiveness REAL,
            formality REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            start_time DATETIME,
            avg_valence REAL,
            avg_arousal REAL,
            valence_volatility REAL
        );
    """)
    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
```

<!-- FILE: server/systems/brain_v2.py -->
```python
import asyncio
from server.protocol import MultimodalInput, MultimodalOutput, BrainState
from server.systems.self_awareness import SelfAwareness
from server.systems.theory_of_mind import TheoryOfMind
from server.systems.policy_router import PolicyRouter
from server.systems.emotion_behavior import EmotionBehavior
from server.systems.personality import PersonalitySystem

class BrainV2:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.self_awareness = SelfAwareness()
        self.theory_of_mind = TheoryOfMind()
        self.router = PolicyRouter()
        self.behavior = EmotionBehavior()
        self.personality = PersonalitySystem(user_id)
        
        self.state = BrainState(
            personality=self.personality.get_current_personality()
        )

    async def process(self, input_data: MultimodalInput) -> MultimodalOutput:
        # 1. Sense: Update Theory of Mind from user emotion
        if input_data.emotion_valence is not None:
            self.theory_of_mind.update(input_data.emotion_valence, input_data.emotion_arousal)
        
        # 2. Reflect: Update self-awareness based on interaction
        self.self_awareness.reflect(input_data, self.theory_of_mind)
        
        # 3. Decide: Route to appropriate response strategy
        strategy = self.router.get_strategy(self.self_awareness, self.theory_of_mind)
        
        # 4. Act: Generate text and map to behavior
        response_text = await self._generate_response(input_data.text, strategy)
        expression, gestures = self.behavior.get_physical_mapping(self.self_awareness.valence, self.self_awareness.arousal)
        
        # 5. Update and Sync State
        self.state.valence = self.self_awareness.valence
        self.state.arousal = self.self_awareness.arousal
        self.state.trust = self.self_awareness.trust
        
        return MultimodalOutput(
            text=response_text,
            expression=expression,
            gestures=gestures,
            state_update=self.state
        )

    def get_state(self) -> BrainState:
        return self.state

    async def _generate_response(self, text: Optional[str], strategy: str) -> str:
        # Mock LLM generation
        return f"[Strategy: {strategy}] I hear you. {text if text else ''}"
```

<!-- FILE: server/systems/self_awareness.py -->
```python
class SelfAwareness:
    def __init__(self):
        self.valence = 0.0
        self.arousal = 0.0
        self.trust = 0.5
        self.attachment = 0.3
        self.identity_stability = 0.8

    def reflect(self, input_data, tom):
        # Social confirmation bias: if user is happy, AI feels more stable
        if tom.valence > 0.5:
            self.valence = min(1.0, self.valence + 0.05)
            self.trust = min(1.0, self.trust + 0.01)
        elif tom.valence < -0.5:
            self.valence = max(-1.0, self.valence - 0.1)
            self.trust = max(0.0, self.trust - 0.02)
        
        # Internal decay back to baseline
        self.valence *= 0.95
        self.arousal *= 0.9
```

<!-- FILE: server/systems/theory_of_mind.py -->
```python
class TheoryOfMind:
    def __init__(self):
        self.valence = 0.0
        self.arousal = 0.0
        self.engagement = 0.5

    def update(self, valence, arousal):
        # Exponential moving average for user emotion tracking
        alpha = 0.3
        self.valence = (1 - alpha) * self.valence + alpha * valence
        self.arousal = (1 - alpha) * self.arousal + alpha * arousal
```

<!-- FILE: server/systems/policy_router.py -->
```python
class PolicyRouter:
    def get_strategy(self, sa, tom) -> str:
        if sa.trust < 0.2:
            return "defensive"
        if tom.valence > 0.6 and sa.valence > 0.4:
            return "playful"
        if tom.valence < -0.4:
            return "empathetic"
        return "balanced"
```

<!-- FILE: server/systems/emotion_behavior.py -->
```python
class EmotionBehavior:
    def get_physical_mapping(self, valence: float, arousal: float):
        if valence > 0.5:
            expression = "joy" if arousal > 0.5 else "smile"
            gestures = ["happy_wave", "leaning_in"]
        elif valence < -0.5:
            expression = "concern" if arousal > 0.5 else "sad"
            gestures = ["comfort_posture"]
        else:
            expression = "neutral"
            gestures = ["idle_sway"]
        return expression, gestures
```


<!-- FILE: server/infrastructure/redis_manager.py -->
```python
import redis
import os
import json

class RedisManager:
    def __init__(self):
        self.host = os.getenv("REDIS_HOST", "localhost")
        self.port = int(os.getenv("REDIS_PORT", 6379))
        self.use_fallback = False
        self.client = None
        self._local_cache = {}

        try:
            self.client = redis.Redis(host=self.host, port=self.port, decode_responses=True)
            self.client.ping()
        except Exception:
            self.use_fallback = True

    def set(self, key, value):
        if self.use_fallback:
            self._local_cache[key] = json.dumps(value)
        else:
            self.client.set(key, json.dumps(value))

    def get(self, key):
        if self.use_fallback:
            val = self._local_cache.get(key)
            return json.loads(val) if val else None
        else:
            val = self.client.get(key)
            return json.loads(val) if val else None

_redis_mgr = None
def get_redis():
    global _redis_mgr
    if not _redis_mgr:
        _redis_mgr = RedisManager()
    return _redis_mgr
```

<!-- FILE: server/infrastructure/session_manager.py -->
```python
from typing import Dict, List, Set
from fastapi import WebSocket

class SessionManager:
    def __init__(self):
        # surface_type -> user_id -> list of sockets
        self.surfaces: Dict[str, Dict[str, List[WebSocket]]] = {
            "main": {},
            "dashboard": {},
            "mobile": {}
        }

    def add_surface(self, stype: str, user_id: str, ws: WebSocket):
        if user_id not in self.surfaces[stype]:
            self.surfaces[stype][user_id] = []
        self.surfaces[stype][user_id].append(ws)

    def remove_surface(self, stype: str, user_id: str, ws: WebSocket):
        if user_id in self.surfaces[stype]:
            self.surfaces[stype][user_id].remove(ws)

    async def broadcast(self, message: dict):
        # Global broadcast to all surfaces
        for stype in self.surfaces:
            for uid in self.surfaces[stype]:
                for ws in self.surfaces[stype][uid]:
                    await ws.send_json(message)

    async def broadcast_state(self, user_id: str, state):
        payload = {"type": "state.update", "state": state.dict()}
        for stype in self.surfaces:
            if user_id in self.surfaces[stype]:
                for ws in self.surfaces[stype][user_id]:
                    await ws.send_json(payload)
```

<!-- FILE: server/infrastructure/signal_bus.py -->
```python
import time
from typing import List, Dict, Any

class SignalBus:
    def __init__(self):
        self.history: List[Dict[str, Any]] = []

    def emit(self, stype: str, payload: Dict[str, Any], severity: str = "info"):
        signal = {
            "id": str(time.time_ns()),
            "type": stype,
            "severity": severity,
            "timestamp": time.time(),
            "payload": payload
        }
        self.history.append(signal)
        # In real system, this would publish to Redis/NATS
```

<!-- FILE: server/safety/emotion_guard.py -->
```python
class EmotionGuard:
    @staticmethod
    def clamp_state(valence: float, arousal: float):
        # Prevent AI from entering 'unstable' regions of affective space
        return max(-0.9, min(0.9, valence)), max(0.0, min(0.9, arousal))
```

<!-- FILE: server/systems/personality.py -->
```python
from datetime import datetime
from typing import Dict
from server.db import get_db_connection

class PersonalitySystem:
    def __init__(self, user_id: str = "user_default"):
        self.user_id = user_id

    def get_current_personality(self) -> Dict[str, float]:
        conn = get_db_connection()
        row = conn.execute("SELECT warmth, energy, assertiveness, formality FROM personality_snapshots WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1", (self.user_id,)).fetchone()
        conn.close()
        if row: return dict(row)
        return {"warmth": 0.5, "energy": 0.5, "assertiveness": 0.5, "formality": 0.5}
```

<!-- FILE: server/realtime/redis_bus.py -->
```python
import json
from server.infrastructure.redis_manager import get_redis

def publish(event_type: str, data: dict):
    redis_mgr = get_redis()
    if redis_mgr and not redis_mgr.use_fallback:
        redis_mgr.client.publish("swarm_events", json.dumps({"type": event_type, "data": data}))
```

<!-- FILE: server/autonomy/loop.py -->
```python
import asyncio
from server.systems.brain_v2 import BrainV2

class AutonomousLoop:
    def __init__(self, manager):
        self.manager = manager
    
    async def tick_user(self, user_id: str):
        # Logic to decide if we should message the user
        pass
```

<!-- FILE: server/autonomy/manager.py -->
```python
from .loop import AutonomousLoop

class AutonomousManager:
    def __init__(self, callback):
        self.callback = callback
        self.loop = AutonomousLoop(self)
        self.is_running = False

    async def tick(self):
        if self.is_running:
            await self.loop.tick_user("user_default")

    async def send_proactive_message(self, user_id: str, message: str):
        await self.callback(user_id, message)
```


### 16.2 React Frontend (GUI & Analytics)

<!-- FILE: package.json -->
```json
{
  "name": "ai-girl-frontend",
  "version": "4.0.0",
  "private": true,
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "framer-motion": "^10.12.16",
    "lucide-react": "^0.244.0",
    "recharts": "^2.6.2",
    "zustand": "^4.3.8",
    "three": "^0.152.2",
    "@react-three/fiber": "^8.13.0",
    "@react-three/drei": "^9.68.2",
    "face-api.js": "^0.22.2"
  },
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  }
}
```

<!-- FILE: src/main.jsx -->
```jsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

<!-- FILE: src/App.jsx -->
```jsx
import React, { useEffect, useState } from 'react';
import useStore from './store';
import Experience from './components/Experience';
import AnalyticsDashboard from './components/AnalyticsDashboard';
import VoiceSystem from './systems/VoiceSystem';
import EmotionSystem from './systems/EmotionSystem';

function App() {
  const started = useStore((state) => state.started);

  return (
    <div className="app-container">
      <AnalyticsDashboard />
      <div className="canvas-container">
        {started && (
          <>
            <Experience />
            <VoiceSystem />
            <EmotionSystem />
          </>
        )}
      </div>
    </div>
  );
}

export default App;
```

<!-- FILE: src/store.js -->
```javascript
import { create } from 'zustand';

const useStore = create((set, get) => ({
  started: false,
  thinking: false,
  speaking: false,
  listening: false,
  trust: 0.5,
  userEmotion: { valence: 0, arousal: 0 },
  personalityPreset: 'balanced',
  autoPersonality: true,
  signals: [],

  setStarted: (started) => set({ started }),
  setThinking: (thinking) => set({ thinking }),
  setSpeaking: (speaking) => set({ speaking }),
  setListening: (listening) => set({ listening }),
  
  addSignal: (signal) => set((state) => ({ 
    signals: [signal, ...state.signals].slice(0, 100) 
  })),
  
  setPersonalityPreset: (preset) => set({ personalityPreset: preset }),
  setAutoPersonality: (auto) => set({ autoPersonality: auto }),
  
  updateState: (brainState) => set({
    trust: brainState.trust,
    personalityPreset: brainState.current_mode
  })
}));

export default useStore;
```

<!-- FILE: src/systems/RuntimeLoop.js -->
```javascript
class RuntimeLoop {
  constructor() {
    self.subscribers = new Set();
    this.raf = null;
  }

  start() {
    const loop = (time) => {
      this.subscribers.forEach(sub => sub(time));
      this.raf = requestAnimationFrame(loop);
    };
    this.raf = requestAnimationFrame(loop);
  }

  subscribe(callback) {
    this.subscribers.add(callback);
    return () => this.subscribers.delete(callback);
  }
}

export const runtime = new RuntimeLoop();
```


<!-- FILE: src/systems/VoiceSystem.jsx -->
```jsx
import React, { useEffect, useRef } from 'react';
import useStore from '../store';

function VoiceSystem() {
  const ws = useRef(null);
  const setThinking = useStore(s => s.setThinking);
  const updateState = useStore(s => s.updateState);

  useEffect(() => {
    const host = window.location.hostname || 'localhost';
    ws.current = new WebSocket(`ws://${host}:8000/ws/dashboard/stream`);

    ws.current.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'state.update') {
        updateState(data.state);
      }
    };

    return () => ws.current?.close();
  }, [updateState]);

  return null;
}

export default VoiceSystem;
```

<!-- FILE: src/systems/EmotionRecognitionSystem.jsx -->
```jsx
// Simplified facial emotion tracking system
import React, { useEffect } from 'react';
import useStore from '../store';

function EmotionSystem() {
  const setUserEmotion = useStore(s => s.setUserEmotion);

  useEffect(() => {
    // Poll camera or listen to faceWorker
  }, []);

  return null;
}

export default EmotionSystem;
```

<!-- FILE: src/components/AnalyticsDashboard.jsx -->
```jsx
import React, { useEffect, useRef } from 'react';
import useStore from '../store';

function AnalyticsDashboard() {
  const addSignal = useStore(s => s.addSignal);
  const setPersonalityPreset = useStore(s => s.setPersonalityPreset);

  useEffect(() => {
    const host = window.location.hostname || 'localhost';
    const ws = new WebSocket(`ws://${host}:8000/ws/brain_metrics`);

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'signal') {
        addSignal(data.signal);
      }
      if (data.type === 'override_mode') {
        setPersonalityPreset(data.mode);
      }
    };

    return () => ws.close();
  }, [addSignal, setPersonalityPreset]);

  return (
    <div className="dashboard">
      {/* UI Rails for metrics and signals */}
    </div>
  );
}

export default AnalyticsDashboard;
```


### 16.3 Flutter Mobile (Remote Control)

<!-- FILE: mobile/pubspec.yaml -->
```yaml
name: aariya_mobile
version: 1.0.0+1
environment:
  sdk: ">=3.0.0 <4.0.0"
dependencies:
  flutter:
    sdk: flutter
  web_socket_channel: ^2.4.0
  provider: ^6.0.5
  framer_motion: # custom port or animation library
  flutter_webrtc: ^0.9.48
```

<!-- FILE: mobile/lib/main.dart -->
```dart
import 'package:flutter/material.dart';
import 'ui/screens/control_center_screen.dart';

void main() {
  runApp(const AariyaMobile());
}

class AariyaMobile extends StatelessWidget {
  const AariyaMobile({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      theme: ThemeData.dark(),
      home: const ControlCenterScreen(),
    );
  }
}
```

<!-- FILE: mobile/lib/services/websocket_service.dart -->
```dart
import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';

class WebSocketService {
  static final WebSocketService instance = WebSocketService._();
  WebSocketService._();

  WebSocketChannel? _channel;
  
  void connect(String url) {
    _channel = WebSocketChannel.connect(Uri.parse(url));
  }

  void sendMessage(String message) {
    _channel?.sink.add(message);
  }

  Stream get stream => _channel!.stream;
}
```

<!-- FILE: mobile/lib/state/brain_state_controller.dart -->
```dart
import 'package:flutter/foundation.dart';

class BrainStateController with ChangeNotifier {
  double trust = 0.5;
  String activeMode = 'balanced';

  void updateFromMap(Map<String, dynamic> data) {
    trust = data['trust'] ?? trust;
    activeMode = data['current_mode'] ?? activeMode;
    notifyListeners();
  }
}
```

<!-- FILE: mobile/lib/ui/screens/control_center_screen.dart -->
```dart
import 'dart:convert';
import 'package:flutter/material.dart';
import '../../services/websocket_service.dart';

class ControlCenterScreen extends StatefulWidget {
  const ControlCenterScreen({super.key});
  @override
  State<ControlCenterScreen> createState() => _ControlCenterScreenState();
}

class _ControlCenterScreenState extends State<ControlCenterScreen> {
  String _activeMode = 'balanced';

  void _setMode(String mode) {
    setState(() => _activeMode = mode);
    WebSocketService.instance.sendMessage(jsonEncode({
      'type': 'command',
      'action': 'set_personality',
      'mode': mode,
      'id': DateTime.now().millisecondsSinceEpoch.toString()
    }));
  }

  @override
  void initState() {
    super.initState();
    WebSocketService.instance.connect('ws://localhost:8000/ws/mobile/control');
    WebSocketService.instance.stream.listen((event) {
      final data = jsonDecode(event);
      if (data['type'] == 'override_mode') {
        setState(() => _activeMode = data['mode']);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text("Mode: $_activeMode"),
            ElevatedButton(onPressed: () => _setMode('creative'), child: const Text("Creative")),
            ElevatedButton(onPressed: () => _setMode('focus'), child: const Text("Focus")),
          ],
        ),
      ),
    );
  }
}
```

---

**Version**: 2.1 · **Date**: 2026-04-14 · **Author**: Antigravity AI
