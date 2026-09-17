# AI Girl — Emotion-Aware AI Companion

> 📘 **[Read the full technical rebuild guide →](./TECHNICAL_ANALYSIS.md)**

A real-time AI companion with a lifelike animated avatar that reads your emotion, adapts its personality over time, and responds with natural voice and synchronized animation.

---

## What It Does

- 🎭 **Detects your emotion** from your face (10 FPS), voice (FFT analysis), and text simultaneously
- 🧠 **Remembers you** — short-term session memory + long-term personality evolution via EMA drift
- 🗣️ **Talks back** — real-time voice pipeline: VAD → Whisper ASR → GPT → TTS + LipSync
- 🤝 **Earns trust** — the more you interact honestly, the more expressive and open it becomes
- 🎮 **Animates naturally** — procedural blink, micro-saccades, breathing, gaze behavior, pre-speech inhale

---

## Two Frontend Options

| | Path A — React + Three.js | Path B — Unity MVP |
|---|---|---|
| **Best for** | Full web/desktop app | Best avatar fidelity |
| **Avatar** | VRM in WebGL | FBX/RPM in Unity |
| **Animation** | Blendshapes + code systems | Blend Trees + Animator |
| **Status** | Feature-complete | In progress |
| **Guide** | §5 in TECHNICAL_ANALYSIS.md | §6 in TECHNICAL_ANALYSIS.md |

Both share the **same Python AI Brain** (`server/`).

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

#### The `npm run dev` launcher

`npm run dev` runs **both** the Python Brain (`:8000`) and the UI (`:5173`) through a single launcher (`scripts/dev.mjs`) so they always start and stop together:

- **Ready message** — while booting it prints which server is still starting:
  ```
  ⏳ Waiting for 🧠 Brain on :8000…
  ⏳ Waiting for 🧠 Brain on :8000 and ⚡ UI on :5173…
  ✅ Both servers are ready!
     → UI:      http://localhost:5173
     → Brain:   http://localhost:8000
  ```
- **No orphans** — closing the terminal, pressing `Ctrl+C`, or a server crash stops **both** servers with a `🛑 Stopping servers…` message. No leftover uvicorn/vite processes.
- **`--clean` flag** — kills any leftover processes still holding ports `8000`/`5173` (e.g. from a crashed session) before starting fresh:
  ```bash
  npm run dev -- --clean      # or npm run dev -- -c
  ```
  Prints what it killed: `🧹 Killed 2 leftover process(es): 61811 61812` (or `🧹 No leftover processes found.`).
- **`--prod` flag** — builds the UI and serves it in production mode instead of the dev server:
  ```bash
  npm run dev -- --prod
  ```
  This runs `vite build` first, then serves the built `dist/` via `vite preview` (same port `5173`) and starts the Brain **without** auto-reload (`--reload` is only for development). On success it prints the `dist/` output path, total bundle size, and build time, and **warns when a single JS chunk exceeds `BUILD_CHUNK_WARN_KB`** (default 500 KB — raise it to silence large-chunk warnings). If the build fails **or times out** (default 5 min, override with `BUILD_TIMEOUT_MS`), no servers are started. Combine freely with `--clean`.
- **Cross-platform** — works on macOS, Linux, and Windows (venv `bin/` vs `Scripts/` and console-close handling are automatic).

#### Tests

```bash
npm test                    # JS tests (node --test)
npm run test:backend        # Python backend tests (pytest)
python -m pytest            # same, directly (server/tests suite)
RUN_LIVE_TESTS=1 python -m pytest   # also run live-LLM tests
npm run test:all            # both
```

`test:backend` wraps `run_backend_tests.sh` (Windows: `run_backend_tests.bat`),
which runs pytest (a declared venv dependency, `server/requirements.txt`). Tests
requiring a live LLM (`test_agent_v2.py`) are skipped unless `RUN_LIVE_TESTS=1`.
Pass filenames to run a subset, e.g. `./run_backend_tests.sh test_autonomy.py`.

### 2B. Connect Unity

1. Open `Unity/Aariya` in Unity Hub
2. Ensure Python Brain is running (`ws://localhost:8000/ws/brain`)
3. Press **Play** — the avatar starts receiving AI emotion data

---

## Architecture at a Glance

```
┌──────────────────────┐       WebSocket        ┌─────────────────────────┐
│  FRONTEND            │  ←──────────────────→  │  PYTHON AI BRAIN        │
│                      │  ws://localhost:8000   │                         │
│  React + Three.js    │                        │  FastAPI + Uvicorn       │
│  OR Unity            │  ClientInput JSON  →   │  ContradictionDetector   │
│                      │  ← ServerOutput JSON   │  TrustSystem             │
│  • Blink (random)    │                        │  PersonalitySystem (EMA) │
│  • Gaze tracking     │  Sends:                │  MemorySystem            │
│  • LipSync           │  text, vision, audio,  │  LLM (GPT-4)            │
│  • Emotion lerp      │  face valence/arousal  │  Whisper ASR             │
│                      │                        │  VAD + TTS               │
│  Reads:              │  Receives:             │                         │
│  MoodValence         │  response_text         │  SQLite (identity)       │
│  Energy              │  emotion_target        │  Redis (sessions)        │
│  IsAngry             │  personality           │  PostgreSQL (analytics)  │
└──────────────────────┘  trust_score           └─────────────────────────┘
```

---

## Core Concepts

| Concept | What it does |
|---|---|
| **Emotion Fusion** | Confidence-weighted average of face + audio + text emotion signals |
| **Temporal Smoothing** | `lerp(current, target, speed × dt)` prevents snap transitions |
| **Personality Drift** | EMA (α=0.01) slowly shifts warmth/energy/assertiveness over sessions |
| **Trust System** | Score 0–1 gates how expressive and disclosing the AI becomes |
| **Contradiction Detection** | Angular distance between face/voice valence — detects sarcasm/deception |
| **Social Intent** | AI maintains a conversational stance (LISTENING, COMFORTING, DEFLECTING…) |

---

## Key Files

| File | Purpose |
|---|---|
| `server/main.py` | FastAPI app, WebSocket `/ws/brain`, session initialization |
| `server/protocol.py` | Pydantic models: `ClientInput`, `ServerOutput`, `BrainState` |
| `server/systems/personality.py` | EMA-based personality drift |
| `server/systems/trust_system.py` | Trust score calculation + tier gates |
| `server/systems/contradiction_detector.py` | Multimodal mismatch detection |
| `src/systems/RuntimeLoop.js` | 60 FPS priority-based heartbeat (Path A) |
| `src/store.js` | Zustand global state (Path A) |
| `Unity/…/AIStateReceiver.cs` | WebSocket → Animator parameters (Path B) |
| `Unity/…/BlinkController.cs` | Procedural random blinking (Path B) |
| `test_client.py` | Full integration test for the Python Brain |
| `TECHNICAL_ANALYSIS.md` | **Complete rebuild guide — read this to recreate the system** |

---

## Monitoring

The server includes a **Rich CLI dashboard** (`server/infrastructure/rich_display.py`):

- Live trust meter
- Contradiction warning (blinks red when EMA > 0.6)
- Full decision trace per turn

```bash
# Access via interactive client
python interactive_client.py
```

Debug overlays (Path A, Electron):
- `Ctrl+Shift+T` — Thermal Overlay
- `Ctrl+Shift+D` — Debug Dashboard

The **Analytics Dashboard** (open via `?route=analytics`) has a **Build** tab that shows the last production build summary (total bundle size, per-type JS/CSS/HTML/Other breakdown, largest files, build time, and oversized-chunk warnings) — written by `npm run dev -- --prod` and served from `GET /api/build/summary`.

The **Electron GUI** (`run_gui.sh` / `run_gui.bat` / `npm run gui`) also surfaces oversized-chunk warnings as a dismissible amber banner in the main Aariya window — no need to read the terminal. The Electron main process reads `.build-summary.json` over IPC (`window.electronAPI.getBuildSummary()`); in a plain browser the app falls back to `GET /api/build/summary`. The banner shows the offending chunk(s) and sizes, links to the dashboard's **Build** tab, and remembers its dismissal per build (a fresh `--prod` build re-shows it). It only appears when the summary is **fresh** (see the dashboard's Build tab, which shows a muted `OUTDATED` badge instead when the summary is older than the window) — so running in dev mode won't surface stale warnings from an old production build. The freshness window defaults to **24h** and is configurable via `BUILD_WARN_MAX_AGE_HOURS` — set it in the shell when starting the dev server (e.g. `BUILD_WARN_MAX_AGE_HOURS=48 npm run dev`) or in a `.env` file; the `VITE_BUILD_WARN_MAX_AGE_HOURS` name works too. It's exposed to the renderer through vite's `envPrefix` (see `vite.config.js`), so it applies in both dev and production builds.

---

## Roadmap

| Status | Item |
|---|---|
| ✅ Done | Python AI Brain (FastAPI + all Fixv2 systems) |
| ✅ Done | React + Three.js full frontend |
| ✅ Done | Voice pipeline (VAD + Whisper + TTS) |
| ✅ Done | Unity C# WebSocket scripts |
| 🔧 In Progress | Unity avatar import (RPM FBX + Mixamo animations) |
| 🔧 In Progress | Unity Animator Blend Tree setup |
| ⬜ Planned | Semantic memory search (vector embeddings) |
| ⬜ Planned | Mobile port (React Native / Flutter) |
| ⬜ Planned | Cloud deployment option |

---

> For complete implementation details, algorithms, and code skeletons → **[TECHNICAL_ANALYSIS.md](./TECHNICAL_ANALYSIS.md)**
