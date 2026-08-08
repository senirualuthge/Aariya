# AI Girl: FIXV4 Gap Analysis & Feature Backlog (Pre-April 14th)

This report provides a detailed overview of features that were identified as partially implemented or backlogged during the transition to the **FIXV4 Swarm Architecture**.

> **Update (2026-08-07)**: Sections 1–3 below are now **resolved** (see each section's Resolution notes) — including the **LSTM emotion predictor**, which is now trained on snapshot history and wired into the proactive autonomy loop. Sections 4–6 remain outstanding.

---

## 1. Vision Integration (GPT-4V)
**Status**: ✅ Resolved

### Current State
- **Protocol**: The `VisionData` object is defined in `server/protocol.py`, supporting `face_valence`, `face_arousal`, and `face_confidence`.
- **Inbound Data**: The WebSocket handler can receive `image_b64` strings via `MultimodalInput`.

### Implementation Gaps
- **Cognitive Binding**: ~~The `CognitiveOrchestrator` does not yet route visual frames to a dedicated **Vision Agent**.~~ **Resolved** — `VisionAgent` (`server/systems/swarm/agents/vision.py`) is now a registered swarm member; `brain_v2.py` runs Vision + Emotion + Planner in parallel and feeds `[VISION]` context into the LLM prompt.
- **Contextual Reasoning**: ~~While the system knows "how much" emotion it sees, it cannot currently "see" the user's environment or actions.~~ **Resolved** — with `OPENAI_API_KEY` set the agent performs real GPT-4V scene description; without a key it falls back to structured emotion inference from the `VisionData` fields.

---

## 2. Advanced Personality Visualization
**Status**: ✅ Resolved

### Current State
- **Telemetry**: The backend broadcasts real-time personality drift (Valence, Arousal, Trust) to the Analytics Dashboard.
- **2D Tracking**: Trait vectors are tracked via standard line charts and radar charts in React.
- **3D Personality Space**: The `AnalyticsDashboard` now ships a live 3D personality-space visualizer (`PersonalitySpace3DTab`) tracking Social Drift.

### Implementation Gaps
- **3D Personality Space**: ~~A planned Three.js/Canvas-based visualization representing personality traits as a 3D coordinate system remains in the backlog.~~ **Resolved** — implemented in `src/components/AnalyticsDashboard.jsx`.
- **Vector-Based Evolution**: Visualizing the transition between "Core Identity" and "Acquired Traits" over multi-session timelines is still text/table based only (nice-to-have 3D trait-trajectory overlay remains).

---

## 3. Proactive Autonomy Loop
**Status**: ✅ Resolved

### Current State
- **Architecture**: A dedicated `server/autonomy/` directory is present (`manager.py`, `loop.py`, `daemon.py`, `executor.py`, `planner.py`, `state.py`).
- **Pipeline**: The `AutonomousLoop` (`server/autonomy/loop.py`) is fully wired: rolling brain-state history → prediction → `ProactiveAIEngine.evaluate()` triggers → LLM-generated proactive message → WebSocket broadcast, with template fallbacks when the LLM is unreachable.

### Implementation Gaps
- **Social Awareness Triggers**: ~~Missing the decision-engine to trigger proactive check-ins.~~ **Resolved** — trigger set (distress, escalation, silence) via `server/systems/proactive/engine.py` plus the 24/7 autonomy daemon.
- **Rate Limiting**: ~~Autonomous cadence protection logic is not yet integrated with the main WebSocket state.~~ **Resolved** — cooldown/cadence enforcement is integrated with brain state fed from the main WebSocket loop; covered by `server/tests/test_autonomy.py`.
- **LSTM Emotion Forecasting**: ~~`predict_future_state()` in `server/systems/emotion/predictor.py` was a stub — the PyTorch `EmotionPredictor` was defined but never trained or wired into the cognitive pipeline.~~ **Resolved** — the LSTM now trains on real history (bootstrapped from the `sessions` table's per-session `avg_valence`/`avg_arousal`, then `autonomy_snapshots`; `python -m server.systems.emotion.predictor` writes `data/emotion_predictor.pt`), runs real inference via `predict_future_state()`, and its valence/distress forecasts are blended into the autonomy daemon's prediction dict each tick through `enrich_prediction` (corroboration rule, silent heuristic fallback when no checkpoint exists). The daemon retrains it automatically on a 24h cadence once enough new snapshots accrue, and counts session history toward the first training so a fresh deployment bootstraps early; training status + latest forecast are exposed via `GET /api/emotion/predictor`; covered by `server/tests/test_emotion_predictor.py` and `server/tests/test_emotion_predictor_api.py`.

---

## 4. Advanced Rigged Gesture Library
**Status**: 🔴 Backlog

### Current State
- **Blendshape Logic**: Handled via `GestureManager.js` using standard ARKit blendshape intensities.
- **Syncing**: Animation is procedurally synced to TTS output.

### Implementation Gaps
- **High-Fidelity FBX Integration**: The roadmap for rigged social gestures (hand-waving, shrugging, nodding) using FBX-based animation targets has not yet been implemented in the primary Path A (Web) renderer.

---

## 5. Unreal Engine 5 / Unity Port (Path B)
**Status**: 🔴 Backlog

### Current State
- **Connectivity**: A basic `AIStateReceiver.cs` exists in Unity to listen to the WebSocket brain.
- **Rendering**: Basic VRM/FBX models are loaded into the scene.

### Implementation Gaps
- **Feature Parity**: Path B lacks the multi-modal fusion, advanced lip-sync, and real-time dashboard connectivity found in the React/Path A implementation.
- **Production Status**: UE5 remains a secondary experimental target compared to the high-performance Web/Android target.

---

## 6. Multi-User Gating (Meeting Mode)
**Status**: 🟡 Partially Implemented

### Current State
- **Logic**: `server/systems/meeting_mode.py` implements a "Direct Address" window (base 30s, dynamically scaled by active speaker count). The AI will only respond if its name is mentioned or if it's in an active follow-up loop.
- **Prompting**: Direct LLM prefixing informs the model of its professional/ambient status.
- **Controls**: Toggle/configure endpoints in `server/routers/meeting_control.py` + dashboard integration.

### Implementation Gaps
- **Acoustic Isolation**: Lacks multi-speaker VAD (Voice Activity Detection) to distinguish between the primary user and ambient participants.
- **Spatial Audio**: No differentiation in output direction for multi-user responses.

---

**Report Compiled**: 2026-04-19
**Last Updated**: 2026-08-07
**Context**: FIXV4 Documentation Sync
