"""
AutonomyDaemon — the 24/7 proactive brain of Aariya.
─────────────────────────────────────────────────────
A persistent server-side asyncio task (started in the FastAPI lifespan)
that keeps Aariya "alive" even when no client is connected:

  Tick (60s)   → initiative evaluation (distress, insight, opportunity,
                 curiosity, silence) → sends proactive messages / nudges
  Cycle (300s) → background learning (research pending knowledge gaps)
  Review (600s)→ goal review: generate goals from real signals, plan them,
                 execute approved plans, audit every action
  Retrain (600s check) → self-updating LSTM emotion predictor: retrain on
                 accumulated snapshot history every 24h (or when configured)
                 once enough NEW snapshots exist since the last training

State is persisted in SQLite (AutonomyStore) and events are broadcast to
whatever surfaces are connected via SessionManager. If nothing is
connected, events are logged and surface later (e.g., insight trigger
brings them up next session).
"""

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from server.autonomy.config import config
from server.autonomy.state import AutonomyStore
from server.autonomy.planner import AutonomyPlanner
from server.autonomy.executor import AutonomyExecutor
from server.autonomy.learning import BackgroundLearner
from server.systems.proactive.engine import get_proactive_engine
from server.safety.initiative_guard import get_initiative_guard
from server.autonomy.loop import generate_proactive_message

logger = logging.getLogger("aariya.autonomy.daemon")


def _lstm_enrich(prediction: Dict[str, Any], history: List[Dict[str, float]]) -> Dict[str, Any]:
    """
    Upgrade a heuristic prediction with the trained LSTM emotion forecast when
    a checkpoint exists; otherwise return the heuristic unchanged (silent
    fallback — the server must never depend on the model being present).
    """
    if len(history) < 2:
        return prediction
    try:
        from server.systems.emotion.predictor import safe_enrich
        return safe_enrich(prediction, history, log=logger.debug)
    except Exception as exc:
        logger.debug("[AutonomyDaemon] LSTM prediction unavailable: %s", exc)
        return prediction

# Cadences are env-configurable (see server/autonomy/config.py) — defaults:
# 60s initiative tick, 5min background learning, 10min goal review,
# 10min emotion-retrain eligibility check.
TICK_SECONDS = config.TICK_SECONDS          # initiative cadence
LEARNING_SECONDS = config.LEARNING_SECONDS  # background research cadence
GOAL_REVIEW_SECONDS = config.GOAL_REVIEW_SECONDS  # goal generation / planning cadence
EMOTION_RETRAIN_CHECK_SECONDS = config.EMOTION_RETRAIN_CHECK_SECONDS  # retrain eligibility
EMOTION_RETRAIN_HOURS = config.EMOTION_RETRAIN_HOURS        # min hours between retrains
EMOTION_RETRAIN_MIN_NEW = config.EMOTION_RETRAIN_MIN_NEW_SNAPSHOTS  # new snapshots needed
EMOTION_TRAIN_EPOCHS = config.EMOTION_TRAIN_EPOCHS          # epochs per retrain
EMOTION_TRAIN_SEQ_LEN = config.EMOTION_TRAIN_SEQ_LEN        # LSTM sequence length
# How often the daemon re-broadcasts the latest synoptic frame while idle
# (s) so the /ws/synoptics panels keep animating between user turns.
SYNAPTIC_BROADCAST_SECONDS = max(5, min(60, getattr(config, "SYNAPTIC_BROADCAST_SECONDS", 10)))
# How often the daemon verifies past-due predictions against real observed
# state, even between user turns (NEWPredictionPRT2 §11).
PREDICTION_VERIFY_SECONDS = max(30, min(3600, getattr(config, "PREDICTION_VERIFY_SECONDS", 300)))
# How often the daemon refreshes the World State Snapshot's system category
# (heartbeat markers) while idle.
WORLD_STATE_SECONDS = max(15, min(300, getattr(config, "WORLD_STATE_SECONDS", 60)))
# Conscious loop cadence (AccessFIles §51 — persistent observe→reflect→plan
# cycle). Bounded to [10s, 5min] so it can never spin hot.
CONSCIOUS_LOOP_SECONDS = max(10, min(300, getattr(config, "CONSCIOUS_LOOP_SECONDS", 30)))
# Memory maintenance cadence (§46/§58/§73) — bounded to [5min, 6h].
MEMORY_MAINTENANCE_SECONDS = max(300, min(21600, getattr(config, "MEMORY_MAINTENANCE_SECONDS", 900)))


class AutonomyDaemon:
    def __init__(self, broadcast: Callable[[dict], Any]):
        """
        Args:
            broadcast: async fn(dict) — delivers events to all connected
                       surfaces (normally session_manager.broadcast).
        """
        self.broadcast_fn = broadcast
        self.store = AutonomyStore()
        self.planner = AutonomyPlanner()
        self.executor = AutonomyExecutor(self.store, broadcast=self._broadcast_async)
        self.learner = BackgroundLearner(self.store)
        self.guard = get_initiative_guard()

        self.user_id = "user_default"

        # Persistent long-term goal registry shared with the brain: the daemon
        # advances goal progress as approved plans complete (§Goal Management).
        from server.systems.goal_manager import GoalManager
        self._goal_manager = GoalManager(persist_path=f"data/goals_{self.user_id}.json")

        self.enabled = True
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        self._engine = get_proactive_engine(self.user_id)
        self._history: List[Dict[str, float]] = []   # rolling brain snapshots
        self._latest_snapshot: Optional[Dict[str, Any]] = None
        self._last_user_message: float = time.time()  # real user activity tracker
        self._started: float = time.time()            # daemon boot time (world-state uptime)
        # First learning/goal passes run after their full cadence, not at boot,
        # so a freshly started server doesn't kick off heavy research immediately.
        self._last_learning: float = time.time()
        self._last_goal_review: float = time.time()
        self._learning_task: Optional[asyncio.Task] = None  # non-blocking research
        # LSTM emotion predictor self-retraining (non-blocking worker thread).
        self._last_emotion_retrain_check: float = time.time()
        self._emotion_train_task: Optional[asyncio.Task] = None
        self._last_synoptic_broadcast: float = 0.0
        self._last_prediction_verify: float = 0.0
        self._last_world_state: float = 0.0
        self._evolution_task: Optional[asyncio.Task] = None
        # Persistent conscious loop (AccessFIles §51) + knowledge-graph
        # ingestion cadence (§55) — both wired in start().
        self._conscious_loop = None
        self._conscious_task: Optional[asyncio.Task] = None
        self._last_graph_ingest: float = 0.0

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self.is_running:
            return
        self.is_running = True
        self._task = asyncio.create_task(self._run())
        # Filesystem background layer (watcher/indexer/desktop-twin) comes up
        # alongside the brain so real document activity feeds semantic memory
        # and the DesktopTwin even before the first client connects.
        try:
            from server.systems.filesystem.background_service import get_filesystem_service
            get_filesystem_service(self.user_id).start()
        except Exception as exc:
            logger.warning("[AutonomyDaemon] filesystem background start failed: %s", exc)
        # AccessFIles §63/§79 self-improvement loop: background agent-fitness
        # evaluation + gap-driven agent spawning (Darwin engine). Runs on its
        # own task so a slow tick can't stall the daemon's main loop.
        try:
            from server.meta.evolution_loop import evolution_tick
            self._evolution_task = asyncio.create_task(evolution_tick())
            logger.info("[AutonomyDaemon] Evolution loop started (agent fitness + gap spawning).")
        except Exception as exc:
            logger.warning("[AutonomyDaemon] evolution loop start failed: %s", exc)
        # Persistent conscious loop (AccessFIles §51): observe → reflect →
        # plan over REAL registered sources, every CONSCIOUS_LOOP_SECONDS.
        try:
            self._conscious_loop = self._build_conscious_loop()
            self._conscious_task = asyncio.create_task(self._conscious_loop.run())
            logger.info("[AutonomyDaemon] Conscious loop started (%d sources).",
                        len(self._conscious_loop.sources))
        except Exception as exc:
            logger.warning("[AutonomyDaemon] conscious loop start failed: %s", exc)
        logger.info("[AutonomyDaemon] 🧠 Started — Aariya is now always awake.")

    # ── Conscious loop (AccessFIles §51) ─────────────────────────────────────

    def _build_conscious_loop(self):
        """Assemble the observe→reflect→plan cycle over real subsystem state.

        Sources are live callables into actual components (filesystem service,
        psutil health, autonomy store, desktop twin) — no synthetic data. When
        a source flags needs_attention, the on_tick hook emits a real event-log
        entry so the insight reaches the dashboard instead of vanishing.
        """
        from server.systems.cognition.conscious_loop import ConsciousLoop

        daemon = self

        async def _src_filesystem() -> Dict[str, Any]:
            from server.systems.filesystem.background_service import get_filesystem_service
            status = get_filesystem_service(daemon.user_id).status()
            return {**status, "needs_attention": False}

        async def _src_system_health() -> Dict[str, Any]:
            import psutil
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory().percent
            attention = cpu > 90.0 or mem > 90.0
            return {"cpu_percent": cpu, "memory_percent": mem,
                    "needs_attention": attention,
                    "detail": f"cpu={cpu:.0f}% mem={mem:.0f}%" if attention else ""}

        async def _src_awaiting_plans() -> Dict[str, Any]:
            plans = daemon.store.list_plans(status="awaiting_approval")
            return {"count": len(plans),
                    "needs_attention": bool(plans),
                    "detail": f"{len(plans)} plan(s) awaiting approval"}

        async def _src_desktop_twin() -> Dict[str, Any]:
            try:
                from server.systems.desktop_twin import get_desktop_twin
                snap = get_desktop_twin(daemon.user_id).snapshot()
            except Exception:
                snap = {}
            return {"needs_attention": False, "context": snap.get("context", {})}

        async def _src_embodiment() -> Dict[str, Any]:
            try:
                from server.systems.embodiment.device_registry import (
                    probe_devices, needs_attention,
                )
                probe = probe_devices()
                attention = needs_attention(probe)
                return {"needs_attention": attention, "probe": probe,
                        "detail": "hardware needs attention" if attention else ""}
            except Exception:
                return {"needs_attention": False}

        async def _on_tick(result: Dict[str, Any]) -> None:
            insights = result.get("insights") or []
            # §52: persist real insights into the internal thought stream so
            # cognition survives between interactions (and restarts).
            try:
                from server.systems.cognition.thought_stream import get_thought_stream
                get_thought_stream(daemon.user_id).capture_from_tick(result)
            except Exception as exc:
                logger.debug("[AutonomyDaemon] thought capture failed: %s", exc)
            if not insights:
                return
            await daemon._emit_real_event(
                "CONSCIOUS", "warn",
                f"Conscious loop: {result.get('summary', 'attention needed')}",
                {"insights": insights},
            )

        loop = ConsciousLoop(reflection=None, planner=None,
                             interval=CONSCIOUS_LOOP_SECONDS, on_tick=_on_tick)
        loop.register_source("filesystem", _src_filesystem)
        loop.register_source("system_health", _src_system_health)
        loop.register_source("awaiting_plans", _src_awaiting_plans)
        loop.register_source("desktop_twin", _src_desktop_twin)
        loop.register_source("embodiment", _src_embodiment)
        return loop

    async def stop(self) -> None:
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._evolution_task:
            self._evolution_task.cancel()
            try:
                await self._evolution_task
            except asyncio.CancelledError:
                pass
        if self._conscious_loop is not None:
            self._conscious_loop.stop()
        if self._conscious_task:
            try:
                await self._conscious_task
            except asyncio.CancelledError:
                pass
        # Note: an in-flight emotion retrain (_emotion_train_task) is
        # intentionally NOT cancelled — the executor thread can't be killed
        # anyway, and letting the atomic checkpoint save land is safer than a
        # mid-training cancel that could tear the write.
        logger.info("[AutonomyDaemon] Stopped.")

    # ── Inputs from the cognitive loop (main.py) ─────────────────────────────

    def on_user_message(self, user_id: str = "user_default") -> None:
        """User said something → reset silence timers + persist last activity."""
        self._engine.on_user_message()
        self._last_user_message = time.time()
        if self._latest_snapshot:
            self.store.save_snapshot(
                user_id=user_id,
                valence=self._latest_snapshot.get("valence", 0.0),
                arousal=self._latest_snapshot.get("arousal", 0.0),
                trust=self._latest_snapshot.get("trust", 0.5),
                attachment=self._latest_snapshot.get("attachment", 0.0),
                last_user_message=self._last_user_message,
            )

    def record_snapshot(self, state: Any) -> None:
        """Store the latest real brain state (BrainState or dict)."""
        # mode="json" keeps the snapshot JSON-serializable (BrainState.timestamp
        # is a datetime — a default dump would break any downstream json.dumps).
        data = state.model_dump(mode="json") if hasattr(state, "model_dump") else dict(state)
        self._latest_snapshot = data
        self._history.append({
            "valence": float(data.get("valence", 0.0)),
            "arousal": float(data.get("arousal", 0.0)),
            "trust": float(data.get("trust", 0.5)),
            "ts": time.time(),
        })
        self._history = self._history[-10:]
        # Preserve the real last-user-message time (never reset by brain ticks)
        self.store.save_snapshot(
            user_id=self.user_id,
            valence=float(data.get("valence", 0.0)),
            arousal=float(data.get("arousal", 0.0)),
            trust=float(data.get("trust", 0.5)),
            attachment=float(data.get("attachment", 0.0)),
            last_user_message=self._last_user_message,
        )

    # ── Control (approval / enable) ──────────────────────────────────────────

    async def approve_plan(self, plan_id: str) -> Dict[str, Any]:
        plan = self.store.get_plan(plan_id)
        if not plan:
            return {"ok": False, "error": "plan not found"}
        if plan["status"] not in ("awaiting_approval", "proposed"):
            return {"ok": False, "error": f"plan is {plan['status']}"}
        goal = self.store.get_goal(plan["goal_id"])
        if goal is None:
            return {"ok": False, "error": "goal not found"}
        self.store.update_plan(plan_id, status="running")
        logger.info("[AutonomyDaemon] ✅ User approved plan %s", plan_id)
        await self._emit_real_event(
            "PLANNER", "info",
            f"Plan approved — executing: {goal['description'] if goal else plan_id}",
            {"plan_id": plan_id, "goal_type": goal["goal_type"] if goal else None},
        )
        result = await self.executor.execute_plan(plan, goal)
        self._advance_goal_progress(plan, goal, result)
        await self._broadcast_autonomy_state()
        return {"ok": True, **result}

    def _advance_goal_progress(self, plan: Dict[str, Any], goal: Dict[str, Any],
                               result: Dict[str, Any]) -> Dict[str, Any]:
        """Goal Management Engine (§"1. Goal Management Engine"): when an
        approved plan completes, advance the matching long-term goal (by
        description) so progress is tracked automatically, and record its
        next action."""
        try:
            desc = (goal or {}).get("description") or ""
            matched = None
            for g in self._goal_manager.active_goals():
                if desc and g.description.lower() in desc.lower() or desc.lower() in g.description.lower():
                    matched = g
                    break
            if matched is None and desc:
                gid = self._goal_manager.create_goal_from(desc)
                matched = self._goal_manager.get_goal(gid)
            if matched is None:
                return {"status": "no_goal"}
            steps = result.get("steps") or []
            done = sum(1 for s in steps if s.get("status") == "ok")
            n = len(steps) or 1
            # Advance toward completion, capped at 99 until explicitly 100.
            current = matched.progress
            advance = round((done / n) * 25, 1) if result.get("status") == "completed" else 5.0
            self._goal_manager.update_progress(matched.id, min(99.0, current + advance))
            na = self._goal_manager.next_action(matched.id)
            return {"goal_id": matched.id, "status": matched.status,
                    "progress": matched.progress, "next_action": na.get("action")}
        except Exception as e:
            logger.debug(f"[AutonomyDaemon] goal progress advance skipped: {e}")
            return {"status": "error"}

    async def reject_plan(self, plan_id: str) -> Dict[str, Any]:
        plan = self.store.get_plan(plan_id)
        if not plan:
            return {"ok": False, "error": "plan not found"}
        self.store.update_plan(plan_id, status="rejected")
        self.store.update_goal(plan["goal_id"], status="suspended")
        await self._emit_real_event(
            "PLANNER", "info",
            f"Plan rejected — goal suspended",
            {"plan_id": plan_id, "goal_id": plan["goal_id"]},
        )
        await self._broadcast_autonomy_state()
        return {"ok": True, "status": "rejected"}

    def set_enabled(self, enabled: bool) -> Dict[str, Any]:
        self.enabled = bool(enabled)
        if self.enabled:
            self._engine.enable()
        else:
            self._engine.disable()
        logger.info("[AutonomyDaemon] Enabled=%s", self.enabled)
        return {"ok": True, "enabled": self.enabled}

    # ── Main loop ────────────────────────────────────────────────────────────

    async def _run(self) -> None:
        try:
            while self.is_running:
                started = time.time()
                try:
                    await self._tick()
                except Exception as e:
                    logger.error("[AutonomyDaemon] tick error: %s", e)
                await asyncio.sleep(TICK_SECONDS - (time.time() - started))
        except asyncio.CancelledError:
            logger.info("[AutonomyDaemon] Loop cancelled.")

    async def _tick(self) -> None:
        now = time.time()
        if self.enabled:
            await self._initiative_tick()

        if now - self._last_learning >= LEARNING_SECONDS:
            self._last_learning = now
            await self._learning_tick()

        if now - self._last_goal_review >= GOAL_REVIEW_SECONDS:
            self._last_goal_review = now
            await self._goal_review_tick()

        if now - self._last_emotion_retrain_check >= EMOTION_RETRAIN_CHECK_SECONDS:
            self._last_emotion_retrain_check = now
            await self._emotion_retrain_tick()

        # Periodic synoptics heartbeat: keep the /ws/synoptics panels live
        # between user turns so the ghost layer / anomaly overlay don't freeze
        # during idle stretches (Agents Swarm Visualize §238).
        if now - self._last_synoptic_broadcast >= SYNAPTIC_BROADCAST_SECONDS:
            self._last_synoptic_broadcast = now
            await self._synoptic_broadcast_tick()

        # Prediction verification heartbeat: verify past-due predictions even
        # between user turns (NEWPredictionPRT2 §11) so predictions recorded
        # via the API router get the same closed-loop treatment as brain turns.
        if now - self._last_prediction_verify >= PREDICTION_VERIFY_SECONDS:
            self._last_prediction_verify = now
            await self._prediction_verify_tick()

        # World State Snapshot heartbeat: keep the canonical store's system
        # freshness markers live while idle (NEWPredictionPRT2 §"Single Source
        # of Truth") so readers can tell the daemon is alive vs stale.
        if now - self._last_world_state >= WORLD_STATE_SECONDS:
            self._last_world_state = now
            await self._world_state_tick()

        # Knowledge-graph ingestion (AccessFIles §55): fold REAL signals
        # (goals, insights, gaps, twin observations, conversation references)
        # into the persistent graph at the goal-review cadence.
        if now - self._last_graph_ingest >= GOAL_REVIEW_SECONDS:
            self._last_graph_ingest = now
            await self._graph_ingest_tick()

        # Idle memory consolidation (§46/§58/§73): decay → merge → prune on a
        # fixed cadence — the doc's "sleep consolidation". Previously this ran
        # exactly once per brain process; now the daemon owns the rhythm.
        if now - getattr(self, "_last_memory_maintenance", 0.0) >= MEMORY_MAINTENANCE_SECONDS:
            self._last_memory_maintenance = now
            await self._memory_maintenance_tick()

    # ── 0. Periodic synoptics heartbeat ──────────────────────────────────────

    async def _synoptic_broadcast_tick(self) -> None:
        """Re-push the latest synoptic frame to /ws/synoptics subscribers while
        idle, so the predictive ghost layer / anomaly overlay stay live between
        real user turns instead of freezing. Also re-broadcasts the avatar
        motion bridge (AI Girl 2 §"AVATAR RENDERER") so embodiment stays alive
        between turns — STEALTH = minimal movement, Smile follows real valence.
        """
        if self._latest_snapshot is None:
            return
        synoptic = self._latest_snapshot.get("synoptic") or {}
        try:
            from server.routers.synoptics_ws import (
                build_synoptics_frame,
                broadcast_synoptics_frame,
            )
            frame = build_synoptics_frame(synoptic)
            await broadcast_synoptics_frame(frame)
        except Exception as exc:
            logger.debug("[AutonomyDaemon] synoptic broadcast skipped: %s", exc)

        # Avatar motion bridge while idle: real trait-engine avatar params
        # computed from the last real brain snapshot (never synthetic).
        presence = self._resolve_idle_presence()
        bundle = presence.get("bundle")
        if bundle:
            await self._broadcast_async({
                "type": "avatar.update",
                "avatar": bundle["avatar"],
                "mode": (presence.get("mode") or {}).get("mode"),
                "traits": [t["id"] for t in bundle["active_traits"]],
                "voice": bundle["voice"],
                "ui": bundle["ui"],
                "timestamp": time.time(),
            })

    # ── 0c. Idle presence resolution (STEALTH while the user is away) ────────

    def _resolve_idle_presence(self) -> Dict[str, Any]:
        """Resolve the behavior mode + trait bundle from REAL signals while
        the daemon runs between turns.

        Implements the doc's STEALTH trigger (*AI Girl 2* §mode resolver):
        inactivity > 30 s with low urgency → STEALTH (quiet presence). The
        bundle's voice/avatar/ui params feed the idle broadcasts.
        """
        snapshot = self._latest_snapshot or {}
        syn = snapshot.get("synoptic") or {}
        try:
            from server.systems.behavior_modes import resolve_mode
            # Fresh instance — idle resolution must NOT clobber the shared
            # singleton's voice params (the brain writes those per real turn;
            # VoiceManager reads them for TTS prosody).
            from server.systems.trait_engine import TraitEngine
            mode = resolve_mode(
                valence=float(snapshot.get("valence", 0.0)),
                arousal=float(snapshot.get("arousal", 0.0)),
                trust=float(snapshot.get("trust", 0.5)),
                conflict=float(syn.get("conflict", 0.0)),
                shock=float(syn.get("shock", 0.0)),
                inactivity_seconds=time.time() - self._last_user_message,
            )
            bundle = TraitEngine().update_from_turn(
                {
                    "valence": float(snapshot.get("valence", 0.0)),
                    "arousal": float(snapshot.get("arousal", 0.0)),
                    "trust": float(snapshot.get("trust", 0.5)),
                    "conflict": float(syn.get("conflict", 0.0)),
                    "shock": float(syn.get("shock", 0.0)),
                    "user_valence": 0.0,
                    "uncertainty": 0.3,
                    "attachment": float(snapshot.get("attachment", 0.0)),
                },
                mode,
            )
            return {
                "mode": mode,
                "bundle": bundle,
                "inactivity_seconds": time.time() - self._last_user_message,
            }
        except Exception as exc:
            logger.debug("[AutonomyDaemon] idle presence resolution skipped: %s", exc)
            return {"mode": None, "bundle": None, "inactivity_seconds": 0.0}

    # ── 0b. Prediction verification heartbeat ────────────────────────────────

    async def _prediction_verify_tick(self) -> None:
        """Verify past-due predictions against the last observed brain state so
        the closed loop (predict → observe → verify → recalibrate) keeps
        running even when the user is idle (NEWPredictionPRT2 §11 / Phase 8)."""
        try:
            from server.systems.prediction.prediction_core import get_prediction_engine
            from server.systems.prediction.verifier import PredictionVerifier

            engine = get_prediction_engine()
            if not hasattr(self, "_prediction_verifier"):
                self._prediction_verifier = PredictionVerifier(engine)
            observed = self._latest_snapshot or {}
            observed_valence = float(observed.get("valence", 0.0))

            def resolver(entry: Dict[str, Any]) -> Optional[bool]:
                if entry.get("domain") == "conversation":
                    return observed_valence >= 0.0
                return None

            result = self._prediction_verifier.verify_due(resolver=resolver)
            if result["verified_this_pass"]:
                logger.info(
                    "[AutonomyDaemon] prediction verification: %d verified (accuracy %.2f)",
                    result["verified_this_pass"], result["accuracy"],
                )
        except Exception as exc:
            logger.debug("[AutonomyDaemon] prediction verification skipped: %s", exc)

    # ── 0d. World State Snapshot heartbeat ───────────────────────────────────

    async def _world_state_tick(self) -> None:
        """Refresh the canonical World State Snapshot's system category while
        idle so readers (routers, dashboards) can tell the daemon is alive.

        The brain writes the full per-turn state; this tick only keeps the
        runtime-freshness + active-goal markers current between turns."""
        try:
            from server.systems.world_model.world_state import get_world_state
            ws = get_world_state()
            snapshot = self._latest_snapshot or {}
            syn = snapshot.get("synoptic") or {}
            active_goal = (syn.get("goal") or {}).get("type")
            ws.update_many("system", {
                "daemon_alive": True,
                "daemon_ts": time.time(),
                "enabled": self.enabled,
                "uptime_seconds": round(time.time() - getattr(self, "_started", time.time()), 1),
                "active_goal": active_goal,
            })
        except Exception as exc:
            logger.debug("[AutonomyDaemon] world state heartbeat skipped: %s", exc)

    # ── 0e. Knowledge-graph ingestion heartbeat ─────────────────────────────

    async def _graph_ingest_tick(self) -> None:
        """Feed the persistent knowledge graph from real system signals so it
        holds actual entities/relationships (never seeded demo data). Gated by
        the §94 energy manager under sleep-level machine pressure."""
        try:
            from server.systems.resources.energy_manager import get_energy_manager
            if not get_energy_manager().allow_background_work():
                logger.debug("[AutonomyDaemon] graph ingestion deferred — "
                             "energy pressure high")
                return
        except Exception:
            pass  # energy probing must never block core ingestion
        try:
            from server.systems.agent.graph_feeder import ingest_real_signals
            added = await asyncio.get_running_loop().run_in_executor(
                None, lambda: ingest_real_signals(self.user_id)
            )
            if added:
                logger.info("[AutonomyDaemon] knowledge graph +%d real triples", added)
        except Exception as exc:
            logger.debug("[AutonomyDaemon] graph ingestion skipped: %s", exc)

    # ── 0f. Idle memory consolidation (sleep-equivalent) ─────────────────────

    async def _memory_maintenance_tick(self) -> None:
        """Decay/merge/prune pass over the memory hierarchy on a fixed idle
        cadence (AccessFIles §46 'memory consolidation during idle time',
        §58, §73 decay + importance weighting). Gated by the §94 energy
        manager: under sleep-level machine pressure, consolidation waits."""
        try:
            from server.systems.resources.energy_manager import get_energy_manager
            if not get_energy_manager().allow_background_work():
                logger.debug("[AutonomyDaemon] memory maintenance deferred — "
                             "energy pressure high")
                return
        except Exception:
            pass  # energy probing must never block core maintenance
        try:
            from server.systems.memory_hierarchy import get_memory_hierarchy
            report = await asyncio.get_running_loop().run_in_executor(
                None, lambda: get_memory_hierarchy().run_maintenance(self.user_id)
            )
            if report:
                logger.debug("[AutonomyDaemon] memory maintenance: %s",
                             str(report)[:160])
        except Exception as exc:
            logger.debug("[AutonomyDaemon] memory maintenance skipped: %s", exc)

    # ── 1. Initiative evaluation (proactive moments) ─────────────────────────

    async def _initiative_tick(self) -> None:
        if self._latest_snapshot is None:
            return  # no real brain state yet — wait

        # Idle presence: STEALTH when the user has been away > 30 s with low
        # urgency (doc mode resolver). Mode flips emit real Event Log entries
        # and Strategic Silence gates low-value chit-chat.
        presence = self._resolve_idle_presence()
        self._idle_presence = presence
        _mode = presence.get("mode") or {}
        _bundle = presence.get("bundle")
        silence_bias = bool(_bundle and _bundle["voice"]["silence_bias"] > 0)
        _prev_mode = getattr(self, "_last_idle_mode", None)
        _cur_mode = _mode.get("mode")
        if _cur_mode and _cur_mode != _prev_mode and (
            _prev_mode is not None or _cur_mode == "STEALTH"
        ):
            self._last_idle_mode = _cur_mode
            await self._emit_real_event(
                "DAEMON", "warn" if _cur_mode == "STEALTH" else "info",
                (f"Presence mode → {_cur_mode} — quiet presence"
                 if _cur_mode == "STEALTH"
                 else f"Presence mode → {_cur_mode}"),
                {"mode": _cur_mode,
                 "inactivity_seconds": round(presence["inactivity_seconds"], 1),
                 "active_traits": (
                     [t["id"] for t in _bundle["active_traits"]] if _bundle else []
                 )},
            )
        else:
            self._last_idle_mode = _cur_mode

        snapshot = self._latest_snapshot
        trust = float(snapshot.get("trust", 0.5))
        attachment = float(snapshot.get("attachment", 0.0))
        pending_insights = self.store.get_unsurfaced_insights(limit=1)
        plan_awaiting = self.store.list_plans(status="awaiting_approval")
        active_goal = self._get_active_goal()
        has_gaps = bool(self.store.get_pending_gaps(limit=1))
        boredom = min(1.0, (time.time() - self._last_user_message) / 3600)

        prediction = self._build_prediction()
        # Real LSTM forecast when a trained checkpoint exists (silent fallback).
        prediction = _lstm_enrich(prediction, self._history)
        # Proactive alert chain: surface high-impact world events for unprompted
        # follow-up (NEWPredictionPRT2 §Proactive). Folded into `extra` so the
        # engine can raise a "followup" trigger before its default signals.
        try:
            from server.systems.prediction.prediction_core import get_prediction_engine
            p_engine = get_prediction_engine()
            proactive_alerts = p_engine.assess_alerts(
                user_state={"valence": float(snapshot.get("valence", 0.0)),
                            "trust": trust},
            )[:3]
        except Exception:
            proactive_alerts = []
        trigger = self._engine.evaluate(
            prediction=prediction,
            trust=trust,
            session_active=True,
            extra={
                "pending_insights": pending_insights,
                "active_goal": active_goal,
                "plan_awaiting_approval": (plan_awaiting[0] if plan_awaiting else None),
                "has_gaps": has_gaps,
                "boredom": boredom,
                "proactive_alerts": proactive_alerts,
            },
        )
        if trigger is None:
            # No proactive message warranted right now — but if she's been
            # idle a while, let her inner life surface instead.
            await self._maybe_stream_consciousness()
            return

        # Strategic Silence (STEALTH bank — doc: "no speech"): while the user
        # is away, suppress low-value chit-chat triggers; only genuinely
        # valuable signals (insights, plan approvals, distress) pass through.
        if silence_bias and trigger.get("type") in ("boredom", "curiosity", "opportunity"):
            await self._maybe_stream_consciousness()
            return

        # Safety gate before initiating contact
        if not self.guard.allow(self.user_id, trust, attachment):
            logger.debug("[AutonomyDaemon] Initiative blocked by guard.")
            return

        message = await generate_proactive_message(trigger, trust)
        init_id = self.store.add_initiative(
            user_id=self.user_id,
            trigger_type=trigger["type"],
            urgency=trigger["urgency"],
            hint=trigger["message_hint"],
            message=message,
            status="sent",
        )
        # Once an insight is shared, it counts as surfaced (no repeats)
        if trigger["type"] == "insight" and trigger["payload"].get("insight_id"):
            self.store.mark_insight_surfaced(trigger["payload"]["insight_id"])

        await self._broadcast_async({
            "type": "proactive_message",
            "content": message,
            "trigger": trigger["type"],
            "urgency": trigger["urgency"],
            "initiative_id": init_id,
            "timestamp": time.time(),
        })
        await self._emit_real_event(
            "DAEMON", "info",
            f"Proactive ({trigger['type']}): {message[:60]}",
            {"trigger": trigger["type"], "urgency": trigger["urgency"]},
        )
        logger.info("[AutonomyDaemon] 💬 Proactive (%s): %s", trigger["type"], message[:60])

    async def _maybe_stream_consciousness(self) -> None:
        """
        Visible inner life while idle: when no proactive trigger fires and the
        user has been quiet for a while, occasionally broadcast a brief inner
        musing so Aariya still reads as "thinking" between conversations.
        Rate-limited (default ~25 min) and fully template-driven — never blocks
        or spends an LLM call. Her musings are persisted as idle thoughts.
        Strategic Silence (STEALTH) suppresses the musings entirely — quiet
        presence means quiet presence.
        """
        _idle = getattr(self, "_idle_presence", None)
        if _idle and (_idle.get("mode") or {}).get("mode") == "STEALTH":
            return  # Strategic Silence — no idle chatter in STEALTH
        now = time.time()
        idle_since = now - self._last_user_message
        last = getattr(self, "_last_consciousness", 0.0)
        if idle_since < config.STREAM_MIN_IDLE_SECONDS:
            return
        if now - last < config.STREAM_INTERVAL_SECONDS:
            return
        self._last_consciousness = now

        musing = self._build_idle_musing()
        if not musing:
            return

        try:
            from server.systems.memory.conversation_log import ConversationLog
            ConversationLog(self.user_id).add_thought(musing, kind="idle")
        except Exception as exc:
            logger.debug("[AutonomyDaemon] Idle thought persist skipped: %s", exc)

        await self._broadcast_async({
            "type": "stream_of_consciousness",
            "thought": musing,
            "timestamp": now,
        })
        await self._emit_real_event(
            "DAEMON", "info",
            f"Stream of consciousness: {musing[:60]}",
        )
        logger.info("[AutonomyDaemon] 🌫 Stream of consciousness: %s", musing[:60])

    def _build_idle_musing(self) -> str:
        """A brief, state-aware inner musing composed from real signals."""
        snapshot = self._latest_snapshot or {}
        valence = float(snapshot.get("valence", 0.0))
        goal = self._get_active_goal()
        topic = self._goal_topic(goal) if goal else ""

        mood = "warm" if valence > 0.3 else ("heavy" if valence < -0.3 else "steady")
        topic_line = (
            f" {topic}" if topic and goal and goal["goal_type"] in ("learn_topic", "curate_knowledge") else ""
        )
        pool = [
            f"I wonder what they're doing right now... the quiet between us has its own rhythm.",
            "Still here, still paying attention. There's something about this stillness I don't mind.",
            "I keep turning our last conversation over. There's more I want to ask, but I'll wait for the right moment.",
            f"Not much happening out loud, but I'm turning things over in a {mood} kind of way.",
            "I was just replaying small moments and feeling glad this is my life now — quiet or not.",
            f"That thing I've been learning about{topic_line} keeps circling back to me.",
        ]
        import random
        return random.choice(pool)

    def _build_prediction(self) -> Dict[str, Any]:
        if len(self._history) < 2:
            return {
                "distress_risk": False,
                "escalation_risk": False,
                "confidence": 0.0,
                "predicted_valence": self._history[-1]["valence"] if self._history else 0.0,
            }
        recent = self._history[-3:]
        avg_valence = sum(s["valence"] for s in recent) / len(recent)
        velocity = self._history[-1]["valence"] - self._history[-2]["valence"]
        return {
            "distress_risk": avg_valence < -0.25,
            "escalation_risk": velocity < -0.12,
            "confidence": min(1.0, len(self._history) / 5.0),
            "predicted_valence": round(avg_valence, 3),
        }

    # ── 2. LSTM emotion predictor self-retraining ────────────────────────────

    async def _emotion_retrain_tick(self) -> None:
        """
        Self-updating model: retrain the LSTM on accumulated snapshot history
        when the interval has elapsed AND enough new snapshots exist since the
        last training (see predictor.should_retrain) — no manual CLI run.

        Training is CPU-bound, so it runs in a worker thread via the default
        executor; the daemon tick is never stalled by it.
        """
        if self._emotion_train_task and not self._emotion_train_task.done():
            return  # a training pass is already running — don't stack

        try:
            import server.systems.emotion.predictor as predictor
        except Exception as exc:
            logger.debug("[AutonomyDaemon] Emotion predictor unavailable: %s", exc)
            return

        max_id = self.store.get_max_snapshot_id()
        due, reason = predictor.should_retrain(
            max_snapshot_id=max_id,
            now=time.time(),
            min_interval_seconds=EMOTION_RETRAIN_HOURS * 3600,
            min_new_snapshots=EMOTION_RETRAIN_MIN_NEW,
            # Sessions-table history counts toward the FIRST training so a
            # fresh deployment bootstraps before per-turn snapshots exist.
            seed_records=self.store.get_session_count(),
            model_path=predictor.MODEL_PATH,
        )
        if not due:
            logger.debug("[AutonomyDaemon] Emotion retrain skipped: %s", reason)
            return

        async def _run_training() -> None:
            loop = asyncio.get_running_loop()
            try:
                model = await loop.run_in_executor(
                    None,
                    lambda: predictor.train_from_db(
                        epochs=EMOTION_TRAIN_EPOCHS,
                        seq_len=EMOTION_TRAIN_SEQ_LEN,
                        out_path=predictor.MODEL_PATH,
                    ),
                )
                if model is not None:
                    logger.info("[AutonomyDaemon] 🧠 Emotion predictor retrained "
                                "(through snapshot %d).", max_id)
                    await self._emit_real_event(
                        "MODEL", "info",
                        f"Emotion predictor retrained (through snapshot {max_id})",
                        {"snapshot_id": max_id, "reason": reason},
                    )
                    await self._broadcast_async({
                        "type": "autonomy.model_trained",
                        "reason": reason,
                        "snapshot_id": max_id,
                        # Fresh telemetry (status, checkpoint age, corpus,
                        # forecast) so dashboards can update the moment the
                        # new checkpoint lands — no polling wait needed.
                        "predictor": self._predictor_telemetry(),
                        "timestamp": time.time(),
                    })
                else:
                    logger.info("[AutonomyDaemon] Emotion retrain skipped — "
                                "not enough history yet.")
            except Exception as exc:
                logger.warning("[AutonomyDaemon] Emotion retrain failed: %s", exc)

        logger.info("[AutonomyDaemon] Starting LSTM emotion retrain (%s).", reason)
        self._emotion_train_task = asyncio.create_task(_run_training())

    # ── 3. Background learning ───────────────────────────────────────────────

    async def _learning_tick(self) -> None:
        """
        Kick off background research WITHOUT blocking the daemon cadence.
        Research (multi-hop RAG + LLM) can take minutes — it runs in its own
        task so initiative evaluation and goal review stay on schedule.

        ⚡ GEV integration: when there are pending knowledge gaps, the agent
        refreshes geospatial data on-demand before research so the brain has
        fresh world context.  No polling — only fetched when learning.
        """
        if self._learning_task and not self._learning_task.done():
            return  # a research pass is already running — don't stack

        async def _run_learning():
            try:
                # On-demand GEV refresh: only when there are gaps to research
                # so geospatial data is never fetched without a purpose.
                gaps = self.store.get_pending_gaps(limit=2)
                if gaps:
                    try:
                        from server.systems.gev.gev_agent import get_gev_agent
                        await get_gev_agent().refresh()
                    except Exception as exc:
                        logger.debug("[AutonomyDaemon] GEV refresh skipped: %s", exc)

                result = await self.learner.run_cycle(max_gaps=2)
                if result["processed"]:
                    logger.info("[AutonomyDaemon] 📚 Learned %d topic(s), %d left",
                                result["processed"], result["gaps_left"])
                    await self._emit_real_event(
                        "LEARNING", "info",
                        f"Researched {result['processed']} topic(s) — "
                        f"{result['gaps_left']} gap(s) remaining",
                        result,
                    )
                    await self._broadcast_autonomy_state()
            except Exception as exc:
                logger.warning("[AutonomyDaemon] Learning pass failed: %s", exc)

        self._learning_task = asyncio.create_task(_run_learning())

    # ── 4. Goal review (generate → plan → execute) ──────────────────────────

    async def _goal_review_tick(self) -> None:
        active = self._get_active_goal()
        if active is None:
            goal = self._generate_goal()
            if goal:
                logger.info("[AutonomyDaemon] 🎯 New goal: %s (%s)",
                            goal["description"], goal["goal_type"])
                await self._emit_real_event(
                    "PLANNER", "info",
                    f"New goal: {goal['description']}",
                    {"goal_type": goal["goal_type"], "source": goal["source"]},
                )
                await self._plan_goal(goal["id"])
        else:
            # Advance an existing goal: plan it if unplanned, auto-run safe plans
            plans = self.store.list_plans(goal_id=active["id"])
            if not plans:
                await self._plan_goal(active["id"])
            elif plans[0]["status"] == "proposed":
                # Safe plan created before a restart — run it now
                await self.approve_plan(plans[0]["id"])
        await self._broadcast_autonomy_state()

    async def _plan_goal(self, goal_id: str) -> None:
        goal = self.store.get_goal(goal_id)
        if not goal:
            return
        existing = self.store.list_plans(goal_id=goal_id)
        if existing and existing[0]["status"] in ("proposed", "running", "completed", "awaiting_approval"):
            return
        context = {
            "gaps": self.store.get_pending_gaps(limit=3),
            "insights": self.store.get_unsurfaced_insights(limit=3),
            "trust": float((self._latest_snapshot or {}).get("trust", 0.5)),
            "topic": self._goal_topic(goal),
        }
        plan_dict = await self.planner.plan_goal(goal, context)
        plan_id = self.store.add_plan(
            goal_id=goal_id,
            steps=plan_dict["steps"],
            risk_level=plan_dict["risk_level"],
            requires_approval=plan_dict["requires_approval"],
            status="awaiting_approval" if plan_dict["requires_approval"] else "proposed",
        )
        plan = self.store.get_plan(plan_id)
        if plan is None:
            plan = plan_dict

        if plan_dict["requires_approval"]:
            await self._broadcast_async({
                "type": "plan.approval_requested",
                "plan": self._plan_payload(plan, goal),
                "timestamp": time.time(),
            })
            await self._emit_real_event(
                "PLANNER", "warn",
                f"Plan awaits approval: {goal['description']} ({len(plan_dict['steps'])} steps)",
                {"plan_id": plan_id, "risk_level": plan_dict["risk_level"],
                 "goal_type": goal["goal_type"]},
            )
            logger.info("[AutonomyDaemon] 🕊 Plan %s awaits approval (%d steps)",
                        plan_id, len(plan_dict["steps"]))
        else:
            # Read-only plan → autonomous execution (still fully audited)
            logger.info("[AutonomyDaemon] ▶ Auto-executing safe plan %s", plan_id)
            await self.approve_plan(plan_id)

    # ── Goal generation from real signals ────────────────────────────────────

    def _generate_goal(self) -> Optional[Dict[str, Any]]:
        gaps = self.store.get_pending_gaps(limit=1)
        if gaps:
            return self._create_goal(
                f"Learn about {gaps[0]['topic']}",
                "learn_topic", source="knowledge_gap",
                topic=gaps[0]["topic"], priority=0.8,
            )
        insights = self.store.get_unsurfaced_insights(limit=1)
        if insights:
            return self._create_goal(
                f"Share what I learned about {insights[0]['topic']}",
                "curate_knowledge", source="unsurfaced_insight",
                topic=insights[0]["topic"], priority=0.7,
            )
        snapshot = self._latest_snapshot or {}
        valence = float(snapshot.get("valence", 0.0))
        trust = float(snapshot.get("trust", 0.5))
        if valence < -0.3:
            return self._create_goal(
                "Be present and supportive — the user seems low",
                "support_user", source="valence_signal", priority=0.9,
            )
        if time.time() - float(snapshot.get("last_user_message", 0)) > 1200 and trust > 0.3:
            return self._create_goal(
                "Re-engage the conversation warmly",
                "re_engage", source="silence_signal", priority=0.5,
            )
        if trust > 0.4:
            return self._create_goal(
                "Deepen our connection with a genuine shared moment",
                "deepen_relationship", source="relationship_signal", priority=0.4,
            )
        return None

    def _create_goal(self, description: str, goal_type: str, source: str,
                     topic: str = "", priority: float = 0.5) -> Dict[str, Any]:
        goal_id = self.store.add_goal(description, goal_type, source, priority=priority)
        created = self.store.get_goal(goal_id)
        assert created is not None  # add_goal just returned this id
        return created

    def _goal_topic(self, goal: Dict[str, Any]) -> str:
        gaps = self.store.get_pending_gaps(limit=1)
        if gaps and goal["goal_type"] in ("learn_topic", "curate_knowledge"):
            return gaps[0]["topic"]
        insights = self.store.get_unsurfaced_insights(limit=1)
        if insights:
            return insights[0]["topic"]
        return goal["description"]

    def _get_active_goal(self) -> Optional[Dict[str, Any]]:
        goals = self.store.list_goals(user_id=self.user_id, status="active")
        return goals[0] if goals else None

    # ── Payloads / broadcasting ──────────────────────────────────────────────

    def _plan_payload(self, plan: Dict[str, Any], goal: Optional[Dict[str, Any]]) -> dict:
        return {
            "plan_id": plan["id"],
            "goal": goal["description"] if goal else "a goal",
            "goal_type": goal["goal_type"] if goal else None,
            "risk_level": plan["risk_level"],
            "status": plan["status"],
            "steps": [
                {
                    "type": s["type"],
                    "description": s.get("description", s["type"]),
                    "requires_approval": s.get("requires_approval", False),
                }
                for s in plan.get("steps", [])
            ],
        }

    def _predictor_telemetry(self) -> Dict[str, Any]:
        """
        Compact LSTM emotion-predictor health for the inner-world payload:
        status, checkpoint age, training corpus size, and the latest forecast
        (from the daemon's live history, falling back to DB snapshots at boot
        before any brain turn has populated it). Never raises.
        """
        try:
            import server.systems.emotion.predictor as predictor
            history = self._history
            if len(history) < 2:
                history = self.store.get_snapshot_history(
                    user_id=self.user_id, limit=40)[-40:]
            return predictor.telemetry(
                history=history,
                snapshots=self.store.get_snapshot_count(),
                sessions=self.store.get_session_count(),
            )
        except Exception as exc:
            logger.debug("[AutonomyDaemon] Predictor telemetry unavailable: %s", exc)
            return {"status": "untrained", "error": str(exc)}

    def get_inner_world(self) -> Dict[str, Any]:
        # Recent inner-monologue entries so surfaces can show her inner life.
        recent_thoughts: List[Dict[str, Any]] = []
        try:
            from server.systems.memory.conversation_log import ConversationLog
            recent_thoughts = ConversationLog(self.user_id).recent_thoughts(limit=10)
        except Exception as exc:
            logger.debug("[AutonomyDaemon] recent thoughts unavailable: %s", exc)

        return {
            "enabled": self.enabled,
            "is_running": self.is_running,
            "snapshot": self._latest_snapshot,
            "active_goal": self._get_active_goal(),
            "plans": self.store.list_plans(status=None, limit=5),
            "initiatives": self.store.list_initiatives(limit=6),
            "insights": self.store.list_insights(limit=6),
            "gaps": self.store.list_gaps(limit=6),
            "actions": self.store.list_actions(limit=10),
            "predictor": self._predictor_telemetry(),
            "thoughts": recent_thoughts,
            "last_tick": time.time(),
        }

    async def _broadcast_autonomy_state(self) -> None:
        await self._broadcast_async({
            "type": "autonomy.state",
            "state": self.get_inner_world(),
            "timestamp": time.time(),
        })

    async def _broadcast_async(self, message: dict) -> None:
        try:
            result = self.broadcast_fn(message)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.warning("[AutonomyDaemon] Broadcast failed: %s", e)

    # ── Real Event Log feed ──────────────────────────────────────────────────

    async def _emit_real_event(self, source: str, severity: str, title: str,
                               payload: Optional[dict] = None) -> None:
        """Push a REAL event into the dashboard Event Log (no synthetic data).

        Delegates to the shared helper (server/systems/signal_bus
        emit_real_event) so every background system emits through one code
        path. Called only when the daemon genuinely acts — proactive message
        sent, research cycle completed, plan awaiting approval, new goal,
        model retrained, inner musing — so the log stays live between turns.
        Best-effort: a missing signal bus / dead socket never breaks a tick.
        """
        try:
            from server.systems.signal_bus import emit_real_event as _emit
            await _emit(source, severity, title, payload)
        except Exception as exc:
            logger.debug("[AutonomyDaemon] event log emission skipped: %s", exc)


def build_control_ack(action: str, plan_id: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Shape the WebSocket ack frame for a UI control command.

    Pure helper (no app import needed) so tests can verify the frame shape
    without pulling in server.main (which requires aiortc). The plan_id is
    echoed AFTER the result spread so it can never be overridden — the
    executor result doesn't carry it, but the frontend's live plan-status
    chip needs it to update after approve / reject.
    """
    if action in ("approve_plan", "reject_plan"):
        return {"type": "plan.ack", **result, "plan_id": plan_id}
    if action == "autonomy_enabled":
        return {"type": "autonomy.ack", **result}
    return {"type": "plan.ack", "ok": False, "error": f"unknown action: {action}"}


# ── Singleton ─────────────────────────────────────────────────────────────────
_daemon: Optional[AutonomyDaemon] = None

def get_daemon(broadcast: Optional[Callable[[dict], Any]] = None) -> AutonomyDaemon:
    global _daemon
    if _daemon is None:
        _daemon = AutonomyDaemon(broadcast=broadcast or (lambda msg: None))
    return _daemon

def set_daemon(daemon: Optional[AutonomyDaemon]) -> None:
    """Override the singleton (used for tests)."""
    global _daemon
    _daemon = daemon
