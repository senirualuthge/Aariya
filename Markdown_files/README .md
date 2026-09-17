# Aariya — Emotion-Aware AI Companion

> 📘 **[Read the full technical rebuild guide →](./TECHNICAL_ANALYSIS.md)** (Version 4.0)

A real-time AI companion with a lifelike animated avatar that reads your emotion, adapts its personality over time, and responds with natural voice and synchronized animation — available on **web, desktop, and Android**.

---

- 🧠 **FIXV4 Swarm Intelligence** — Multi-agent cognitive pipeline for parallel reasoning and emotional depth
- 🎭 **Multimodal Fusion** — detects emotion from face (10 FPS), voice (FFT), and text context
- 🗣️ **Conversational Intelligence** — VAD-based sub-150ms interrupt system and low-latency token streaming
- 🤝 **Evolving Relationship** — personality drift and attachment-based trust tiers (Score 0–1)
- 📱 **Mobile App (Aariya)** — Reactive UI with `AvatarOrb` and `EmotionRing` driven by backend state
- ⚡ **Zero-Latency UI** — Live token-by-token streaming for both Web and Mobile
- 🛠️ **Neural Swarm Dashboard** — Real-time 3D observability with interactive node dragging, pinning, and deep zoom/pan physics.
- 📡 **Bi-Directional Control Center** — Instantly push personality traits, memory wipes, and Auto-Adapt overrides from isolated analytical windows back into the cognitive core.
- 🔄 **Automated Agent Discovery** — Backend introspection automatically registers new swarm agents on-the-fly and syncs their lifecycles to the frontend UI via dedicated websockets.
- 🧪 **Identity Kernel** — Immutable core values protected from personality drift corruption
- 🧬 **Deep RL (PPO) Policy** — Self-improving behavioral style selection based on user rapport
- 🔍 **Web Intelligence** — Autonomous research agent for verification and live knowledge retrieval
- 🕒 **Proactive Autonomy** — Background cognitive loop for autonomous check-ins and engagement

---

## Two Frontend Options

| | Path A — React + Three.js | Path B — Unity MVP | Path C — Flutter Mobile |
|---|---|---|---|
| **Best for** | Full web/desktop app | Best avatar fidelity | Mobile (Android/iOS) |
| **Avatar** | VRM in WebGL | FBX/RPM in Unity | Conversational overlay |
| **Animation** | Blendshapes + code systems | Blend Trees + Animator | Pulsing orb + camera |
| **Status** | Feature-complete | In progress | ✅ Feature-complete |
| **Guide** | §5 in TECHNICAL_ANALYSIS.md | §6 in TECHNICAL_ANALYSIS.md | §7 in TECHNICAL_ANALYSIS.md |

All paths share the **same Python AI Brain** (`server/`).

---

## Quick Start

### Prerequisites

- **Python** 3.10+
- **Node.js** 18+ (Path A only)
- **Unity** 2022.3 LTS (Path B only)
- **OpenAI API Key** (for GPT + TTS)

### 1. Start the Python Brain

```bash
cd "/Volumes/Volumn 1/Code Base/AI Girl"
python -m venv venv && source venv/bin/activate

pip install -r server/requirements.txt

cp .env.example .env
# Add your OPENAI_API_KEY to .env

uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
```

Test it:
```bash
python test_client.py   # Should print: [OK] All tests completed successfully!
```

### 2A. Start React Frontend

```bash
npm install
npm run dev          # http://localhost:5173
npm run gui          # Electron desktop app
```

### 2C. Run Mobile App (Android)

```bash
cd "/Volumes/Volumn 1/Code Base/AI Girl/mobile"
flutter pub get
flutter run   # connect Android device via USB
```

> The server must be running on the same Wi-Fi network. Update `WebSocketService` with your machine's LAN IP.

---

## Architecture at a Glance

```
┌───────────────────────┐       WebSocket        ┌───────────────────────────┐
│  FRONTEND             │  ←───────────────────→  │  PYTHON AI BRAIN (FIXV4)  │
│                       │  ws://localhost:8000    │                           │
│  React (VRM)          │                         │  Micro-Agent Swarm (IOM)  │
│  Flutter (Aariya)     │  ClientInput JSON   →   │  EmotionalStateMachine    │
│                       │  ← ServerOutput JSON    │  AttachmentTrustSystem    │
│  • AvatarOrb (Pulse)  │                         │  Deep RL (PPO) Policy     │
│  • EmotionRing (VA)   │  Sends:                 │  Identity Kernel (Values) │
│  • VAD Interrupts     │  text, vision, audio,   │  LLM (GPT-4)              │
│  • LipSync            │  interrupt signal       │  Whisper ASR / TTS        │
│                       │                         │                           │
│  Reads:               │  Receives:              │  SQLite (Identity)        │
│  Valence/Arousal      │  streaming_text         │  Redis (Sessions)         │
│  EmotionalState       │  emotion_target (V/A)   │  ChromaDB (Deep Memory)    │
│  Personality traits   │  personality            │  PostgreSQL (Analytics)   │
└───────────────────────┘  trust_score            └───────────────────────────┘
```

---

## Core Concepts

| Concept | What it does |
|---|---|
| **FIXV4 Swarm** | Multi-agent parallel cognitive loop (Emotion, Reasoning, Personality, Risk) |
| **Deep RL Policy** | PPO-based behavioral adaptation that learns from user engagement signals |
| **Identity Kernel** | Immutable core value system that ensures long-term personality consistency |
| **4-Layer Memory** | Tiered hierarchy: L1 (Working), L2 (Episodic), L3 (Semantic), L4 (Emotional) |
| **VAD Interrupt** | Sub-150ms cancellation of AI generation when user starts speaking |
| **Self-Awareness** | Internal self-model tracking identity stability and social confidence |
| **Theory of Mind** | Modeling user intent and emotional state to predict reactions |
| **Emotion Ring** | Real-time visualization of Valence (Hue) and Arousal (Expansion) on mobile |
| **Personality Evolution**| Long-term trait drift (Warmth, Guardedness, Playfulness) based on rapport |
| **Attachment Trust** | Multi-tiered relationship modeling that gates AI disclosure and expressivity |
| **Neural Swarm Dashboard**| 3D visual terminal for live monitoring of cognitive agent activations, physics-based dragging, and node pinning |
| **Agent Discovery** | Automated Introspection that detects, registers, and syncs cognitive plugin modules dynamically |
| **Live Token Stream** | Real-time character-by-character rendering for zero-latency interactions |
| **Proactive Autonomy**| Background cognitive loop for autonomous check-ins and engagement |
| **Web Intelligence** | Autonomous research layer for live fact verification and deep knowledge retrieval |
| **Bi-Directional Sync** | Real-time command bridging across decoupled React windows using Custom Broadcaster Channels |

---

## Key Files

| File | Purpose |
|---|---|
| `server/main.py` | Unified FIXV4 entry point; handles WebSocket session & Swarm |
| `server/systems/swarm/orchestrator.py` | Central cognitive orchestrator for the FIXV4 swarm |
| `server/systems/identity_kernel.py` | Immutable core values engine |
| `server/systems/agent/web_intelligence.py` | Web Intelligence Research Agent orchestration layer |
| `server/infrastructure/agent_scanner.py` | Automated agent discovery & discovery introspection |

---

## Monitoring

The server includes a **Rich CLI dashboard** (`server/infrastructure/rich_display.py`):
- Live trust meter
- Self-awareness confidence indicator
- Full decision trace per turn

---

## Roadmap

| ✅ Done | **FIXV3 Unified Brain (BrainV2, Trust, Personality, State Machine)** |
| ✅ Done | **Reflective AI Integration (Self-Awareness + Theory of Mind)** |
| ✅ Done | **VAD-based Interrupt System (Sub-150ms response cancellation)** |
| ✅ Done | **Reactive Mobile UI (AvatarOrb + EmotionRing + BrainStateController)** |
| ✅ Done | Semantic memory search (ChromaDB + vector embeddings) |
| ✅ Done | **Flutter Mobile App — Aariya integration** |
| ✅ Done | **Live Token Streaming (Zero-Latency token rendering logic)** |
| ✅ Done | **Web Intelligence Research Agent (Aariya Search)** |
| ✅ Done | **Agent Auto-Discovery (Dynamic Meta-Control Plane & Watchdogs)** |
| ✅ Done | **Bi-Directional Analytics Control Center** |
| 🔧 In Progress | Real AI vision response (GPT-4V integration) |
| 🔧 In Progress | **Proactive Autonomy loop (AutonomousManager)** |


## 🛠️ System Rebuilder

The entire AI Girl system can be recreated from the documentation in this repository. Ensure you have `TECHNICAL_ANALYSIS.md` in the current directory, then run the reconstruction script:

### rebuild.py
```python
import os
import re

def rebuild():
    """
    Parses TECHNICAL_ANALYSIS.md to extract and reconstruct the source code.
    """
    if not os.path.exists('TECHNICAL_ANALYSIS.md'):
        print("Error: TECHNICAL_ANALYSIS.md not found in current directory.")
        return

    with open('TECHNICAL_ANALYSIS.md', 'r', encoding='utf-8') as f:
        content = f.read()

    # Pattern to match: <!-- FILE: path -->\n```language\ncode\n```
    pattern = r'<!-- FILE: (.*?) -->\s*?\n```.*?\n([\s\S]*?)\n```'
    matches = re.finditer(pattern, content)

    extracted_count = 0
    for match in matches:
        path = match.group(1).strip()
        code = match.group(2)
        
        print(f"Reconstructing: {path}")
        
        # Create directory structure
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        # Write file
        with open(path, 'w', encoding='utf-8') as f:
            f.write(code)
        
        extracted_count += 1

    print(f"\n✅ Rebuild complete. {extracted_count} files reconstructed.")
    print("Next steps:")
    print("1. cd server && pip install -r requirements.txt && python main.py")
    print("2. npm install && npm run dev")
    print("3. cd mobile && flutter pub get && flutter run")

if __name__ == "__main__":
    rebuild()
```

---

> For complete implementation details, algorithms, and code skeletons → **[TECHNICAL_ANALYSIS.md](./TECHNICAL_ANALYSIS.md)**

**Version**: 3.0 · **Date**: 2026-04-19 · **Author**: Antigravity AI
