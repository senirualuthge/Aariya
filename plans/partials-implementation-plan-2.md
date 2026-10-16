# AI Girl — Partials Plan (Wave 2)

Second audit pass, run **after** the Wave‑1 tracks A–F (multi‑user identity,
latency masking, personality trajectory, pulse‑news, RL long‑horizon, meeting‑mode
acoustic isolation) were implemented and verified.

Scope rule (unchanged): **no mock / synthetic / hardcoded data**. If a real signal
doesn't exist, the correct answer is an honest empty state — not a fabrication.

---

## 1. Audit method

- Grep for `TODO / FIXME / placeholder / not implemented / for now / stub` across
  `server/` and `src/` (excluding `node_modules`, `.venv`, `__pycache__`, tests).
- Cross‑referenced the docs backlog (`Markdown_files/Missing\Partially implemented .md`,
  `IMPLEMENTATION_STATUS.md`, `AI_Girl_Improvements.md`) against the **real code**.
- Mount/call analysis: for every `src/systems/*.jsx|tsx` and `src/core/*.ts`, checked
  whether it is imported/mounted, and whether the function it depends on is ever called.
- `codegraph`/grep caller analysis for suspicious backend methods.

---

## 2. Findings

### 2.1 Real partials on the **live path** (implement — Wave G)

| # | Item | Evidence | Notes |
|---|------|----------|-------|
| G1 | `AdvancedMemoryManager` MTM never maintained or searched | `src/systems/memory/AdvancedMemoryManager.js:134-136` `TODO: Expand MTM to hold full session logs`; live caller `aiEngine.js:85,130,146` | STM works; MTM `topics`/`emotionTrend` are declared but never updated, and `retrieveContext` searches STM only. Fix: session log + topics + emotion trend + MTM retrieval. |
| G2 | `StabilityGuardrails` feedback‑loop protection is a TODO and the component is unwired | `src/systems/StabilityGuardrails.jsx:51` `TODO: Detect oscillating emotions`; not mounted anywhere | Also **wrong subscribe signature** (`runtime.subscribe(fn, priority, name)` vs `RuntimeLoop.subscribe(priority, fn)`). Fix: extract a pure guardrail module, implement oscillation damping, apply it on the live emotion path (`DialogueSystem` heartbeat), and correct the subscribe call. |
| G3 | `contradiction_detector.process_turn` passes a fabricated trust | `server/systems/contradiction_detector.py:335` `calculate_trust_decay(1.0, contradiction_ema)  # Placeholder trust` | Fix: accept a real `trust` argument (default `1.0` = current behaviour for callers that don't have it yet) and use it. |
| G4 | `gap_detector.scan_for_gaps` claims agents self‑report capabilities but only name‑matches | `server/meta/gap_detector.py:76-97` (`Simple name-based capability mapping for now`) | Fix: consume a real `capabilities` self‑report when present, keep name matching as fallback. |

### 2.2 Dormant subsystem — built but never started (Wave H, needs a decision)

The entire **Phase‑1 performance / runtime layer** exists but is never initialized:

- `initializePerformanceSystem()` (`src/core/initializePerformanceSystem.ts`) — **no callers anywhere**.
- Therefore dormant: `performanceSystem` (`performanceIntegration.ts`), `bootProfiler`,
  `runtimeConfig`, `fpsController`, `thermalController`, `stateThrottle`,
  `wsClient` (msgpack batcher), and `tripleLoopRuntime`.
- `ThermalMonitor.tsx` — not mounted (reads the never‑updated `thermalController`).
- Two competing loops: legacy `RuntimeLoop`/`RuntimeController` (unmounted) vs
  `tripleLoopRuntime` (uninitialized). `StabilityGuardrails`/`SocialIntentSystem`
  and `AudioFFTSystem` were written against the **new** `tripleLoopRuntime`
  signature but never migrated off the old import.
- `SocialIntentSystem` — unmounted; `socialIntent` is not even a store field, so it is orphaned.
- Niche backend gap: `SwarmSynergyBridge.execute_dispatch` (`server/systems/gev/swarm_synergy.py:203`)
  has **no callers** and returns the dispatch request as a stub; nothing subscribes
  to `on_dispatch`, so GEV triggers never reach the swarm.

> **Why this is a decision, not an automatic fix:** activating it starts extra
> RAF/interval loops, an FPS/thermal governor, and (if configured) a second msgpack
> WebSocket plus the face worker — each of which can interact with the already‑live
> avatar render loop and camera pipeline. It needs an explicit choice of how far to wire.

### 2.3 Explicitly out of scope (cannot be done honestly, or by design)

- UE5/MetaHuman port and the rigged gesture library — no real assets/engine here.
- Meeting‑mode spatial pan / DoA — no real multi‑channel/SRP‑PHAT source (deferred in Wave 1).
- `meta_reasoner` heuristic router and `thermalController.estimateCPUUsage` frame‑time
  estimate — documented "swap later" heuristics, not broken gaps.
- Legacy dead modules (`src/systems/EmotionSystem.jsx`, `PersonalitySystem.jsx`,
  `SessionTracker.js`, `MemorySystem.js`) — superseded/referenced only in a comment.

---

## 3. Wave G — implemented in this pass

Live‑path, self‑contained, no fabricated data, each with tests.

1. **G1** `AdvancedMemoryManager`: bounded MTM session log, real topic extraction
   (stop‑word‑filtered term counts), emotion trend (rolling valence + volatility)
   from the metadata already passed by `aiEngine`, and `retrieveContext` now ranks
   STM **and** MTM hits. Persist interval is `unref()`'d so it can't hang tests.
2. **G2** new pure module `src/systems/emotionGuardrails.js`:
   `clampEmotions` (replaces the inline clamps) + stateful oscillation detection
   (sign‑flip count within a time window, with damping toward baseline). Wired into
   the live `DialogueSystem` 10 Hz heartbeat before `setAllEmotions`; `StabilityGuardrails`
   refactored to use it and its `subscribe` call corrected.
3. **G3** `contradiction_detector.process_turn(..., trust=1.0)` uses the real trust.
4. **G4** `gap_detector.scan_for_gaps` honours a real `capabilities` self‑report
   (list/set/str) per agent, unioned with the name‑match fallback.

### Verification

- Backend: `venv/bin/python -m pytest server/tests/test_gap_detector.py server/tests/test_contradiction_trust.py`
- Frontend: `npm run test:unit` (new files added to the script), `npm run build`, `npx eslint`.

---

## 4. Wave H — dormant runtime/performance layer (option (b) chosen — implemented)

Options: (a) leave dormant and document; (b) initialize the runtime guarded
(no second WS, no duplicate face worker) and mount `ThermalMonitor`, migrating
`StabilityGuardrails`/`SocialIntentSystem` to `tripleLoopRuntime`; (c) retire the
legacy `RuntimeLoop`/`RuntimeController` and delete the superseded modules.

**Chosen: (b).** Implemented as a self-contained `PerformanceBootstrap` rather than
via `initializePerformanceSystem()`:

* `initializePerformanceSystem()` pulls in `performanceIntegration → wsClient`, which
  `import '@msgpack/msgpack'` — an **undeclared** dependency (and `npm install` is
  blocked by a pre-existing React 19 / framer-motion peer conflict). It would also open
  a second WebSocket and start a second face worker. The bootstrap therefore wires only
  boot-profiler → runtime-config → `tripleLoopRuntime` → `fpsController`/`thermalController`,
  governed from real render-loop frame timing.
* `ThermalMonitor` mounted (renders only while throttled / Ctrl+Shift+T).
* `StabilityGuardrails` and `SocialIntentSystem` moved to `tripleLoopRuntime.subscribeCognition`
  (priorities 10 / 30); `socialIntent` + `setSocialIntent` added to the store (SocialIntentSystem
  would otherwise call an undefined setter); `NeuralEngine.resolveSocialIntent` arousal-source
  bug fixed (`emotions.arousal` → `state.arousal`).
* Option (c) NOT done — legacy `RuntimeLoop`/`RuntimeController` are now unreferenced but left
  in place.

---

## 5. Progress log

- 2026‑10‑16 — Wave‑2 audit complete; plan written.
- 2026‑10‑16 — **Wave G implemented.**
  - G1 `AdvancedMemoryManager` (MTM session log + topics + emotion trend + MTM retrieval);
    new `src/systems/memory/AdvancedMemoryManager.test.mjs`.
  - G2 `src/systems/emotionGuardrails.js` (clamp + oscillation damping) wired into the live
    `DialogueSystem` heartbeat; `StabilityGuardrails` refactored onto it (subscribe bug fixed);
    new `src/systems/emotionGuardrails.test.mjs`.
  - G3 `ContradictionDetector.process_turn(trust=...)` + zero-floor in `calculate_trust_decay`;
    new `server/tests/test_contradiction_trust.py`.
  - G4 `gap_detector.scan_for_gaps` self-reported capabilities; new cases in `test_gap_detector.py`.
  - Verify: `npm run test:unit` **74 passed**; full backend suite `pytest server/tests`
    **631 passed, 3 skipped** (+6 vs. the pre-Wave‑2 baseline); `npx eslint` clean;
    `npm run build` ✓.
- 2026‑10‑16 — **Wave G committed** (`3881ffb`).
- 2026‑10‑17 — **Wave H (b) implemented.**
  - H1 new `src/systems/PerformanceBootstrap.jsx` (guarded, idempotent) mounted in `App.jsx`.
  - H2 `ThermalMonitor` mounted.
  - H3 `StabilityGuardrails` → `tripleLoopRuntime.subscribeCognition(…, 10, …)`.
  - H4 `SocialIntentSystem` → cognition loop; store `socialIntent`/`setSocialIntent` added;
    `resolveSocialIntent` arousal bug fixed; new `src/systems/ai/SocialIntent.test.mjs`.
  - Verify: `npm run test:unit` **78 passed**; `npx eslint` clean; `npm run build` ✓
    (new chunks `PerformanceBootstrap`/`StabilityGuardrails`/`SocialIntentSystem`/`ThermalMonitor`,
    no `msgpack` in the bundle).
