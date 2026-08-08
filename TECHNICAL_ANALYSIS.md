# AI Girl — Complete Technical Analysis & Rebuild Guide

> **Purpose**: If you read this document cover-to-cover you can rebuild the entire system from scratch. Everything is documented: algorithms, formulas, directory structures, code skeletons, database schema, WebSocket protocol, and C# integration.
>
> **Last Updated**: 2026-02-23 · Version 2.0

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Two Architectures — Choose Your Path](#2-two-architectures)
3. [Core AI Algorithms](#3-core-ai-algorithms)
4. [Python AI Brain (Server)](#4-python-ai-brain-server)
5. [React + Three.js Frontend (Path A)](#5-react--threejs-frontend-path-a)
6. [Unity Frontend (Path B — MVP)](#6-unity-frontend-path-b--mvp)
7. [WebSocket Protocol (Shared)](#7-websocket-protocol-shared)
8. [Database Schema](#8-database-schema)
9. [Voice Pipeline](#9-voice-pipeline)
10. [Step-by-Step Build Order](#10-step-by-step-build-order)
11. [Environment & Configuration](#11-environment--configuration)
12. [Key Design Decisions Explained](#12-key-design-decisions-explained)

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
│          FRONTEND  (Path A: React/Three.js  OR  Path B: Unity)      │
│                                                                      │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐            │
│  │   Sensors    │   │  Animation   │   │  Rendering   │            │
│  │ Face (10Hz)  │   │ Blink/Gaze   │   │ 3D Avatar    │            │
│  │ Audio FFT    │   │ LipSync      │   │ VRM/FBX      │            │
│  │ Webcam       │   │ BodyIdle     │   │ Blendshapes  │            │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘            │
│         └──────────────────┴──────────────────┘                    │
│                             │  WebSocket ws://localhost:8000        │
└─────────────────────────────┼────────────────────────────────────────┘
                              │
┌─────────────────────────────┼────────────────────────────────────────┐
│                 PYTHON AI BRAIN  (FastAPI + Uvicorn)                │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  Fixv2 Engine                                                  │ │
│  │  ContradictionDetector → TrustSystem → NeuralPolicy           │ │
│  │  PolicyRouter → TurnTakingStateMachine → EmotionBehaviorMap   │ │
│  └────────────────────────────────────────────────────────────────┘ │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ PersonalitySystem│ │ MemorySystem │  │   LLM (GPT)  │              │
│  │ (EMA Drift)  │  │ Short/Long   │  │  OpenAI API  │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │   Redis      │  │  PostgreSQL  │  │   SQLite     │              │
│  │  (Sessions)  │  │  (Analytics) │  │  (Identity)  │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
└─────────────────────────────────────────────────────────────────────┘
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

### 3.2 Personality Drift (Exponential Moving Average)

Personality evolves slowly — not instant reactions. The server runs this **once per session end** (or weekly).

**4 Personality Axes**: Warmth (-1 to +1), Energy (0-1), Assertiveness (0-1), Formality (0-1)

```python
# server/systems/personality.py

alpha = 0.01  # Very slow drift

# Calculate targets from session metrics
warmth_target = 0.6 * avg_valence + 0.4 * (1 - volatility)
energy_target = avg_arousal
assertiveness_target = 1 - volatility

# EMA update
warmth_new = (1 - alpha) * personality["warmth"] + alpha * warmth_target
warmth_new = clamp(warmth_new, -0.4, 0.6)
```

### 3.3 Temporal Smoothing (Anti-Snap)

Prevents robotic emotion jumps. Applied every frame on the client/Unity side:

```javascript
// For each emotion dimension
current = lerp(current, target, smoothingFactor * deltaTime);
// where smoothingFactor = 0.05 (5% per frame at 60fps ≈ 3 seconds to reach target)
```

In Unity (C#):
```csharp
currentMoodValence = Mathf.Lerp(currentMoodValence, targetMoodValence, Time.deltaTime * lerpSpeed);
// lerpSpeed = 5.0f (reaches target in ~0.5s)
```

### 3.4 Trust-Based Gating (Fixv2)

Trust determines what the AI is allowed to say and do.

**Formula**:
```
Δtrust = a × V_session   (session valence, rewards positivity)
       + b × (1 - C_history)   (low contradiction = trust boost)
       + c × continuity   (returning user bonus)
       - d × violations   (inappropriate content penalties)
```

**Trust Tiers**:

| Score | Tier | Behavior |
|---|---|---|
| 0.00 – 0.20 | DEFENSIVE | Minimal responses, no personal disclosure |
| 0.20 – 0.40 | GUARDED | Cautious, surface-level |
| 0.40 – 0.60 | NEUTRAL | Normal conversation |
| 0.60 – 0.85 | WARM | Expressive, some personal sharing |
| 0.85 – 1.00 | INTIMATE | Full emotional range, deeper recall |

**Safety Gates enforced by trust level**:
- Trust < 0.4 → `disclosure_level` hard-clamped to 0
- Trust < 0.3 → `emotion_intensity` clamped to 0.5

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
// Gaze changes triggered by AI state and intent
```

---

## 4. Python AI Brain (Server)

### 4.1 Technology Stack

| Technology | Version | Purpose |
|---|---|---|
| FastAPI | ≥0.100.0 | WebSocket + HTTP API framework |
| Uvicorn | ≥0.23.0 | ASGI server |
| Pydantic | ≥2.0.0 | Request/response validation |
| websockets | ≥11.0 | WebSocket protocol |
| openai | ≥1.0.0 | GPT-4/3.5 dialogue + TTS |
| faster-whisper | ≥0.10.0 | Local speech-to-text |
| webrtcvad-wheels | ≥2.0.10 | Voice Activity Detection |
| sounddevice | ≥0.4.6 | Microphone access |
| Redis | — | Session state cache |
| PostgreSQL | — | Analytical logs + trust history |
| SQLite (built-in) | — | Local user identity |

### 4.2 Directory Structure

```
server/
├── main.py                    # FastAPI app + WebSocket endpoint /ws/brain
├── protocol.py                # Pydantic models (ClientInput, ServerOutput)
├── db.py                      # SQLite init, get_or_create_user, create_session
├── requirements.txt
│
├── systems/
│   ├── personality.py         # EMA drift (PersonalitySystem class)
│   ├── memory.py              # Short/long-term memory (MemorySystem class)
│   ├── llm.py                 # GPT API wrapper
│   ├── contradiction_detector.py  # Multimodal mismatch detection
│   ├── trust_system.py        # Trust score + tier calculation
│   ├── state_machine.py       # Conversation state machine
│   ├── neural_policy.py       # Behavioral proposals
│   ├── social_intent.py       # Social intent determination
│   ├── policy_router.py       # Routes to correct intent/memory strategy
│   ├── turn_taking.py         # TurnTakingStateMachine (TTSM)
│   ├── memory_retrieval_policy.py  # Recall quota decisions
│   ├── emotion_behavior.py    # Maps emotion → animation directives
│   ├── interaction_outcome.py  # Tracks session IOM metrics
│   └── voice/
│       ├── asr.py             # faster-whisper ASR
│       ├── tts.py             # OpenAI/ElevenLabs TTS
│       └── vad.py             # Voice Activity Detection
│
├── infrastructure/
│   ├── observability.py       # Logger + LatencyTracker + log_latency()
│   ├── redis_manager.py       # Redis connection pool
│   ├── postgres_manager.py    # PostgreSQL connection + queries
│   └── rich_display.py        # Rich CLI dashboard
│
├── routers/
│   ├── voice.py               # /ws/voice WebSocket endpoint
│   └── compliance.py          # Safety/compliance check routes
│
└── migrations/
    └── __init__.py            # run_migrations() auto-called on startup
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

    personality = PersonalitySystem(user_id)
    memory = MemorySystem(user_id)
    trust = get_trust_system(session_id)
    contradiction = get_contradiction_detector(session_id)
    policy = get_neural_policy()

    while True:
        raw = await websocket.receive_text()
        data = ClientInput.model_validate_json(raw)

        # 1. Contradiction detection (sets safety context)
        c_score = contradiction.update(data.vision)

        # 2. Trust update
        t_score = trust.update(data, c_score)

        # 3. Memory retrieval
        memories = memory.retrieve(data.text, quota=RecallQuota.from_trust(t_score))

        # 4. LLM response
        response = await llm.chat(data.text, memories, personality.get(), t_score)

        # 5. Personality drift (end-of-session or periodic)
        personality.update(data.vision)

        # 6. Send response
        output = ServerOutput(
            brain_state=BrainState(personality=personality.get(), ...),
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
│   ├── Overlay.jsx            # Chat UI overlay
│   ├── BrainMonitor.jsx       # Server brain state visualizer
│   └── AnalyticsDashboard.jsx # Session analytics
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
└── hooks/
    └── useCamera.js           # Webcam access hook
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
                Mathf.Lerp(0, 100, t / half));
            yield return null;
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

## 7. WebSocket Protocol (Shared)

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
      "warmth": 0.6, "energy": 0.5,
      "assertiveness": 0.5, "formality": 0.3
    },
    "emotion_target": {
      "happy": 0.7, "calm": 0.3, "valence": 0.7, "energy": 0.6
    },
    "thought_process": "User seems happy — matching energy",
    "trust_score": 0.72,
    "social_intent": "COMFORTING"
  },
  "response_text": "I'm so glad to hear that!",
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

### Why Unity for MVP?

- Better avatar physics and animation blending than WebGL/Three.js
- Mixamo animations work out-of-the-box with FBX
- Animator State Machine is visual and fast to iterate
- BlendShapes for facial animation are production-quality

---

**Version**: 2.0 · **Date**: 2026-02-23 · **Author**: AI Girl Project
