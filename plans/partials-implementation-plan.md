# Plan — Finish the Partially-Implemented Systems (Aariya / AI Girl)

> **Objective:** Turn the six documented *partially-implemented* subsystems into shipped, tested features.
> **Created:** 2026-10-16
> **Repo:** `/Volumes/Volumn 1/Code Base/AI Girl`
> **Mode:** Direct (edit-in-place). Git is present; no GitHub CLI assumed. Use a feature branch per track.

---

## 0. Scope — what "partially implemented" actually means here

Grounded in the repo's own docs + a code audit (2026-10-16). Only items with **real remaining work** are in scope.

| # | Track | Status | Evidence that work remains |
|---|-------|--------|----------------------------|
| A | **Multi-user identity** | 🟡 Partial | `user_default` hardcoded in ~40 sites: `src/systems/SessionTracker.js:17`, `src/systems/PersonalitySystem.js:13`, `src/systems/MemorySystem.js:7`, `server/main.py:310/558/761`, `server/autonomy/manager.py:39`, `server/autonomy/daemon.py:95`, `server/routers/analytics.py`, `compliance.py`, `sdk_api.py`. DB already has `user_id` columns (`server/migrations/000_base_tables.sql`). |
| B | **Meeting Mode acoustic isolation** | 🟡 Partial | `server/systems/meeting_mode.py` estimates speakers from **single-channel energy variance only** (`SpeakerTracker`). No real VAD/diarization, no per-speaker attribution, no spatial audio output. |
| C | **Personality 3D trajectory** | 🟡 Partial | `PersonalitySpace3DTab` (`src/components/AnalyticsDashboard.jsx:2141`) plots the *current* point; no Core-Identity-vs-Acquired-Traits trajectory across sessions. `personality_snapshots` table already exists. |
| D | **pulse-news → BrainV2 integration** | 🟡 Partial | `pulse-news/backend/services/aigirl_bridge.py` POSTs to `/api/signals/ingest`, but BrainV2 has **zero** news references and `ProactiveAIEngine` has no news trigger. Alerts land in a signal log, not cognition. |
| E | **RL long-horizon reward grounding** | 🟡 Partial | `server/systems/rl/` has PPO + a **per-turn** reward (`reward.py`). No persisted transitions, no multi-step/terminal return, no data-driven retraining cadence. |
| F | **Latency masking polish** | 🟡 Partial | `src/store.js:96` has a bare `thinking` boolean; no min-display duration, no skeleton/streamed "thinking" affordance. |

**Explicitly OUT of scope (already done — do not re-plan):**

- Multi-hop search / research agent — **implemented**: `server/systems/agent/controller.py` `get_research_agent().run_research()` is a real multi-hop RAG+web+vault pipeline, wired into `brain_v2.py:524`, `autonomy/executor.py`, `autonomy/learning.py`, `executor/action_executor.py`.
- RAG visualization (`src/components/rag/*`), security agents (`server/systems/security/agents/*`), person identity (`src/systems/personIdentity.js`, `server/systems/identity.py`), system-wide mute/camera (`kill_switches.py` + `Overlay.jsx`), synoptic/planetary analytics, stress test (`scripts/stress-test.mjs`) — all present.
- `build_err.log` is **stale** (the `isBrowser` export exists at `src/db/init.js:88`); current build succeeds.

---

## 1. Dependency graph

```
A1 (frontend identity) ─┐
A2 (backend user_id plumbing) ─┤
A3 (auth/session resolution) ─┴─► A4 (tests)          [A blocks B4, D3, E3]

B1 (real VAD) ─► B2 (diarization) ─► B3 (gating+attribution) ─► B4 (spatial audio)   [B needs A for per-speaker user_id]

C1 (backend snapshot series) ─► C2 (3D trajectory render) ─► C3 (tests)

D1 (news signal contract) ─► D2 (brain consume+context) ─► D3 (proactive trigger) ─► D4 (UI unify)   [D3 needs A + proactive engine]

E1 (persist transitions) ─► E2 (n-step return) ─► E3 (retrain cadence + corpus) ─► E4 (wire checkpoint) ─► E5 (tests)

F1 (thinking state machine) ─► F2 (UI affordance) ─► F3 (tests)
```

**Parallelizable:** after A lands, tracks **B, C, D, E, F** have no shared files — run them as separate branches/worktrees. Within a track, steps are serial.

---

## 2. Steps

Each step is self-contained: a fresh agent can execute it cold.

---

### Track A — Multi-user identity

#### A1 — Frontend identity provider
**Depends on:** none
**Context brief:** Today every frontend system hardcodes `user_default`
(`SessionTracker.js`, `PersonalitySystem.js`, `MemorySystem.js`, `AnalyticsDashboard.jsx`,
`GovernancePanel.jsx`). We introduce a single source of truth for the active user id.

**Tasks**
1. Create `src/systems/userIdentity.js` exporting `getUserId()` / `setUserId(id)` /
   `useUserId()` (Zustand-backed). Persist to `localStorage` key `aariya.user_id`,
   defaulting to a stable generated id (`user_<uuid>`), **not** the literal `user_default`.
2. Replace every literal `'user_default'` in `src/**` with `getUserId()` / the hook.
   (Do not touch test fixtures.)
3. Have `SessionTracker.js` write the resolved id into `users`/`sessions` and expose it
   on the WS handshake query (`?user_id=`).

**Verification**
```bash
grep -rn "user_default" src/ | grep -v test   # expect: 0 hits
npm run lint
npm run test:unit
```

**Exit criteria:** no `user_default` literals in `src/`; app boots and creates a
`user_<uuid>` row; a second launch reuses the same id.
**Rollback:** revert `src/**` (isolated to frontend).
**Model tier:** default.

#### A2 — Backend `user_id` plumbing
**Depends on:** A1
**Context brief:** Backend defaults every request to `user_default`. Thread the
resolved id from the WS/HTTP boundary down through the autonomy + analytics paths.

**Tasks**
1. In `server/main.py` WS handler, read `user_id` from the handshake query; fall back to
   `user_default` only if absent (keep it a *fallback*, not the primary).
2. `server/autonomy/manager.py:39` and `daemon.py:95`: accept `user_id` in the constructor /
   `tick_user()`, stop hardcoding.
3. `server/autonomy/state.py`, `analytics.py`, `compliance.py`, `sdk_api.py`,
   `emotion_predictor_router.py`, `analytics_ws.py`: keep the `user_id` query param but
   ensure it is passed through to stores rather than ignored.
4. Confirm no missing `user_id` columns; add a migration only if a table lacks it
   (base migration already covers `sessions`, `users`, `trust_history`, etc.).

**Verification**
```bash
./run_backend_tests.sh
grep -rn '"user_default"' server/ | grep -v test | grep -v '= "user_default"'  # review remaining
```

**Exit criteria:** tests green; two distinct `user_id`s produce isolated state (add one
integration test asserting isolation).
**Rollback:** revert `server/**`; schema unchanged.
**Model tier:** strongest available (cross-cutting, easy to get subtly wrong).

#### A3 — Session/auth resolution + docs
**Depends on:** A2
**Tasks:** document the identity flow in `Markdown_files/IMPLEMENTATION_STATUS.md`
(move "Single-User Assumptions" out of 🟡); note the fallback contract.
**Exit criteria:** status doc no longer lists multi-user as partial.
**Model tier:** default.

#### A4 — Multi-user test suite
**Depends on:** A3
**Tasks:** add `server/tests/test_multi_user_isolation.py` — two users, disjoint
memory/trust/personality reads. Add a frontend unit test for `userIdentity.js`.
**Exit criteria:** new tests fail before A2 and pass after; no regressions.

---

### Track B — Meeting Mode acoustic isolation

#### B1 — Real VAD
**Depends on:** A2
**Context brief:** `SpeakerTracker` (`server/systems/meeting_mode.py`) infers speaker count
from energy variance of a single channel. Replace the *signal source* with a real VAD
(silero-vad via `torch` — already a dependency path used by `emotion/predictor.py`; or
`webrtcvad` as a lighter fallback) while keeping the class's public API
(`report_audio_frame`, `get_ambient_speaker_count`).

**Tasks**
1. Add a `server/systems/voice/vad.py` wrapper accepting PCM frames → speech probability.
2. Extend `report_audio_frame(energy, vad_user, pcm=None)` to use the real VAD when PCM is
   present; keep the variance heuristic as the no-PCM fallback.
3. Feed PCM from the WS handler (currently only `energy` is sent — extend the frame schema
   in `server/protocol.py` + `src` sender).

**Verification:** unit tests with synthetic single/multi-speaker PCM; assert the VAD path
is used when PCM is supplied and the heuristic path otherwise.
**Rollback:** feature-flag via `AARIYA_MEETING_VAD` env; heuristic remains default until B3.
**Model tier:** strongest available.

#### B2 — Speaker diarization / attribution
**Depends on:** B1
**Tasks:** add lightweight online diarization (embedding clustering) turning VAD segments
into `speaker_id`s; expose `get_speakers() -> [{id, last_active, energy}]`.
**Exit criteria:** ≥2 synthetic voices separate into 2 ids with >90% segment accuracy on the
fixture set.
**Model tier:** strongest available.

#### B3 — Diarized gating + per-speaker memory
**Depends on:** B2, A2
**Tasks:** `should_respond()` uses diarized direct-address (the *named* speaker addressed the
AI); tag transcripts with `speaker_id`; route memory writes per speaker under the same
`user_id` tenant.
**Exit criteria:** in meeting mode, ambient B talking about Aariya does not trigger a reply
unless the direct-address window for the *primary* speaker is open.
**Rollback:** disable diarization flag → falls back to B1 single-VAD behavior.

#### B4 — Spatial audio output
**Depends on:** B3
**Context brief:** today all TTS output is mono. Multi-user needs directional/attributed
output. Keep it pragmatic: pan by speaker slot via WebAudio `StereoPannerNode` in the
frontend; backend just labels which speaker a response targets.
**Tasks:** backend adds `target_speaker_id` to the outbound turn; frontend pans.
**Exit criteria:** two-speaker fixture produces panned output; single-speaker unchanged.
**Model tier:** default.
**Note:** true room-accurate spatialization (HRTF) is explicitly a later nice-to-have.

---

### Track C — Personality 3D trajectory

#### C1 — Backend snapshot series (Core vs Acquired)
**Depends on:** none (can run in parallel with A)
**Tasks:** add `GET /api/personality/trajectory?user_id=&limit=` returning per-session
`{ts, core:{...}, acquired:{...}, trust}` built from `personality_snapshots`
(`src/db/schema.sql` / `server/migrations`). "Core" = identity-kernel traits
(`server/systems/identity_kernel.py`); "Acquired" = drifted traits (`personality.py`).
**Verification:** `server/tests/test_personality_trajectory.py` with seeded snapshots.
**Exit criteria:** endpoint returns ≥2 points per seeded session; empty user → `[]`.
**Model tier:** default.

#### C2 — 3D trajectory render
**Depends on:** C1
**Context brief:** `PersonalitySpace3DTab` (`AnalyticsDashboard.jsx:2141`) renders one point.
Extend it to draw a **trail** of session points (fading older→newer) plus a
Core-vs-Acquired delta vector.
**Tasks:** consume C1, add trail geometry + legend; keep the existing single-point view as a
mode toggle.
**Verification:** `npm run dev` + visual check against a seeded user; add a lightweight
render unit test if the suite supports it.
**Exit criteria:** trail renders ≥2 sessions; no regression in the existing tab.
**Model tier:** default (visual work — pair with a screenshot check).

#### C3 — Tests + docs
**Tasks:** document the new endpoint in `ANALYTICS_DASHBOARD.md`; add the trajectory test to CI.

---

### Track D — pulse-news → BrainV2 integration

#### D1 — Stable news signal contract
**Depends on:** none
**Context brief:** `aigirl_bridge.py` posts arbitrary signal payloads to
`/api/signals/ingest`. Formalize a `news.alert` signal schema
(`{headline, summary, importance, category, topics, url, ts}`) on both sides.
**Tasks:** define schema in `server/routers/signals.py` (validation) and mirror in
`pulse-news/backend/services/aigirl_bridge.py`; keep backwards compat with existing
`system`-type signals.
**Exit criteria:** malformed alert → 422; valid alert → 200 + stored.
**Model tier:** default.

#### D2 — Brain consumes alerts into context
**Depends on:** D1
**Tasks:** in `brain_v2.py`, subscribe to `news.alert` (existing `SignalBus`
`server/systems/signal_bus.py`); when importance ≥ threshold, inject a `[NEWS]` context
block into the next prompt (mirror the existing `[VISION]` injection pattern in
`brain_v2.py:524`).
**Verification:** unit test asserts `[NEWS]` appears in the system prompt after an ingested
alert; absent below threshold.
**Exit criteria:** high-importance alert demonstrably changes the prompt; low-importance
does not.
**Model tier:** strongest available.

#### D3 — Proactive news trigger
**Depends on:** D2, A2
**Context brief:** `ProactiveAIEngine.evaluate()` (`server/systems/proactive/engine.py`) has
triggers: distress, silence, escalation, insight, opportunity, curiosity. Add a **news**
trigger with its own cooldown, gated by the user's favorite topics.
**Tasks:** add trigger #7 (favorite-topic/importance match) using `UserStyleProfile.fav_topics`
(`user_profile_system.py`); add `NEWS_COOLDOWN_SECONDS` to `server/autonomy/config.py`.
**Verification:** extend `server/tests/test_autonomy.py` — injected alert fires exactly one
proactive message, respects cooldown, and stays silent for non-favorite topics.
**Exit criteria:** tests green; no double-fire within cooldown.
**Model tier:** strongest available.

#### D4 — UI unify
**Depends on:** D3
**Tasks:** surface proactive news headsup through the existing `NewsPanel.jsx` alert path +
`PresenceChip`/toast; do not build a second notification system.
**Exit criteria:** a fired news trigger shows exactly one user-visible headsup.
**Model tier:** default.

---

### Track E — RL long-horizon reward grounding

#### E1 — Persist transitions
**Depends on:** none
**Context brief:** `RolloutBuffer` (`server/systems/rl/rl_policy.py`) is in-memory only;
`compute_reward` (`reward.py`) scores a single turn. Add durable, replayable transitions.

**Tasks:** add table `rl_transitions(session_id, user_id, ts, state_json, action, reward,
next_state_json, done)` (new migration); write from `rl_policy` on every `push`.
**Verification:** after N turns, N rows exist; a read-back replays identical states.
**Exit criteria:** migration applies cleanly; no PPO-path regression.
**Model tier:** default.

#### E2 — N-step / terminal return
**Depends on:** E1
**Tasks:** replace the 1-step reward with an n-step or per-session terminal return computed
from the transition log; blend short-term (`reward.py`) with long-horizon signal.
**Verification:** synthetic trajectory with a delayed reward assigns credit to earlier
actions (unit test).
**Exit criteria:** delayed-reward fixture yields higher return on the credited action.
**Model tier:** strongest available.

#### E3 — Retrain cadence + corpus
**Depends on:** E2
**Context brief:** mirror the existing self-updating LSTM pattern
(`server/systems/emotion/predictor.py`, `AARIYA_EMOTION_RETRAIN_HOURS`) for PPO.
**Tasks:** background retrain when ≥ `AARIYA_RL_RETRAIN_MIN_TRANSITIONS` new rows accrue;
checkpoint to `server/systems/rl/ppo_checkpoint.pt`; run in a worker thread (never block the tick).
**Exit criteria:** fresh DB + 0 transitions → no retrain; threshold crossed → checkpoint written.
**Model tier:** default.

#### E4 — Wire checkpoint into policy routing + status API
**Depends on:** E3
**Tasks:** ensure `policy_router.py` loads the trained checkpoint; expose
`GET /api/rl/status` (trained, transitions, last train, latest action distribution).
**Exit criteria:** status endpoint reflects train/untrained correctly; fallback path intact.
**Model tier:** default.

#### E5 — Tests + docs
**Tasks:** `server/tests/test_rl_longhorizon.py`; update `IMPLEMENTATION_STATUS.md` RL row.

---

### Track F — Latency-masking polish

#### F1 — Thinking state machine
**Depends on:** none
**Context brief:** `src/store.js:96` has a bare `thinking` boolean toggled by
`setThinking`. Add a min-display duration so the indicator doesn't flicker on fast replies,
and a `thinkingSince` timestamp.
**Tasks:** add `thinkingSince` + `setThinking` min-hold logic (e.g. 450ms floor);
expose `isThinkingVisible` selector.
**Verification:** unit test — set→clear in 50ms still reports visible for the floor duration.
**Exit criteria:** no flicker in the test; existing consumers unaffected.
**Model tier:** default.

#### F2 — UI affordance
**Depends on:** F1
**Tasks:** consume `isThinkingVisible` in the existing message UI for a skeleton/streamed
"thinking" state; match current design tokens.
**Exit criteria:** visible skeleton appears once, no layout shift when the real message arrives.
**Model tier:** default (screenshot check).

#### F3 — Tests
**Tasks:** add store unit test + a render assertion; run `npm run test:unit`.

---

## 3. Invariants (verify after every step)

1. `./run_backend_tests.sh` passes.
2. `npm run test:unit` + `npm run test:gev` pass.
3. `npm run lint` clean.
4. No new `user_default` literal introduced (Track A invariant).
5. No second notification/event system — reuse `SignalBus` / `ProactiveAIEngine` / `NewsPanel`.
6. Every new backend default is a *fallback*, never the primary path.

## 4. Anti-patterns to avoid

- **Re-plumbing identity with a big-bang rename** — do it file-by-file with the invariant grep.
- **Adding a parallel news pipeline** instead of extending `SignalBus` + `ProactiveAIEngine`.
- **Blocking the autonomy tick** with RL/LSTM training (worker threads only).
- **Over-engineering spatial audio** (HRTF/room sim) in B4 — pan-by-slot is the target.
- **Deleting the heuristic** in `meeting_mode.py` — keep it as the no-PCM fallback.
- **Editing tests to make gaps disappear** — tests must fail before, pass after.

## 5. Rollback strategy

- A: frontend revert is isolated; backend falls back to `user_default` (safe).
- B: env flags (`AARIYA_MEETING_VAD`, diarization) gate it; disable → prior behavior.
- C: additive endpoint + additive render mode; no delete.
- D: additive trigger + cooldown; disable trigger → prior behavior.
- E: new table + optional checkpoint; absent checkpoint → existing untrained path.
- F: additive store fields; `thinking` boolean kept for back-compat.

## 6. Plan mutation protocol

- **Split** a step if it exceeds one PR (>~400 LOC or >1 reviewable concern).
- **Insert** a step when a dependency surfaces; update the graph in §1.
- **Skip** a step only with a written reason here (e.g. B4 deferred if time-boxed).
- **Reorder** only within a track; cross-track reorder requires re-checking the graph.
- Every mutation appends a dated note to this file.

---

## 7. Build order (recommended)

| Phase | Steps | Rationale |
|-------|-------|-----------|
| 1 | **A1→A4** | Identity is load-bearing for B3, D3, E1 |
| 2 | **C1→C3**, **F1→F3**, **D1→D2** | Independent, low-risk, parallelizable |
| 3 | **D3→D4**, **B1→B2** | Need A + the D2 contract |
| 4 | **E1→E5**, **B3→B4** | Heaviest; need A and B1/B2 |

**Estimate:** A ≈ 1 session · B ≈ 2–3 · C ≈ 1 · D ≈ 1–2 · E ≈ 2 · F ≈ 1 → **~9–11 focused sessions**, parallelizable to fewer wall-clock days.

---

*Plan generated from a code + doc audit on 2026-10-16. Superseded items (multi-hop search, RAG viz, security agents, mute/camera, person identity) are listed as out-of-scope in §0.*
