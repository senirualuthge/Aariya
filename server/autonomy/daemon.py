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
        self.enabled = True
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        self._engine = get_proactive_engine(self.user_id)
        self._history: List[Dict[str, float]] = []   # rolling brain snapshots
        self._latest_snapshot: Optional[Dict[str, Any]] = None
        self._last_user_message: float = time.time()  # real user activity tracker
        # First learning/goal passes run after their full cadence, not at boot,
        # so a freshly started server doesn't kick off heavy research immediately.
        self._last_learning: float = time.time()
        self._last_goal_review: float = time.time()
        self._learning_task: Optional[asyncio.Task] = None  # non-blocking research
        # LSTM emotion predictor self-retraining (non-blocking worker thread).
        self._last_emotion_retrain_check: float = time.time()
        self._emotion_train_task: Optional[asyncio.Task] = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self.is_running:
            return
        self.is_running = True
        self._task = asyncio.create_task(self._run())
        logger.info("[AutonomyDaemon] 🧠 Started — Aariya is now always awake.")

    async def stop(self) -> None:
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
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
        self.store.update_plan(plan_id, status="running")
        logger.info("[AutonomyDaemon] ✅ User approved plan %s", plan_id)
        result = await self.executor.execute_plan(plan, goal)
        await self._broadcast_autonomy_state()
        return {"ok": True, **result}

    async def reject_plan(self, plan_id: str) -> Dict[str, Any]:
        plan = self.store.get_plan(plan_id)
        if not plan:
            return {"ok": False, "error": "plan not found"}
        self.store.update_plan(plan_id, status="rejected")
        self.store.update_goal(plan["goal_id"], status="suspended")
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

    # ── 1. Initiative evaluation (proactive moments) ─────────────────────────

    async def _initiative_tick(self) -> None:
        if self._latest_snapshot is None:
            return  # no real brain state yet — wait

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
            },
        )
        if trigger is None:
            # No proactive message warranted right now — but if she's been
            # idle a while, let her inner life surface instead.
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
        logger.info("[AutonomyDaemon] 💬 Proactive (%s): %s", trigger["type"], message[:60])

    async def _maybe_stream_consciousness(self) -> None:
        """
        Visible inner life while idle: when no proactive trigger fires and the
        user has been quiet for a while, occasionally broadcast a brief inner
        musing so Aariya still reads as "thinking" between conversations.
        Rate-limited (default ~25 min) and fully template-driven — never blocks
        or spends an LLM call. Her musings are persisted as idle thoughts.
        """
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
        """
        if self._learning_task and not self._learning_task.done():
            return  # a research pass is already running — don't stack

        async def _run_learning():
            try:
                result = await self.learner.run_cycle(max_gaps=2)
                if result["processed"]:
                    logger.info("[AutonomyDaemon] 📚 Learned %d topic(s), %d left",
                                result["processed"], result["gaps_left"])
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

        if plan_dict["requires_approval"]:
            await self._broadcast_async({
                "type": "plan.approval_requested",
                "plan": self._plan_payload(plan, goal),
                "timestamp": time.time(),
            })
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
        return self.store.get_goal(goal_id)

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


# ── Singleton ─────────────────────────────────────────────────────────────────
_daemon: Optional[AutonomyDaemon] = None

def get_daemon(broadcast: Optional[Callable[[dict], Any]] = None) -> AutonomyDaemon:
    global _daemon
    if _daemon is None:
        _daemon = AutonomyDaemon(broadcast=broadcast)
    return _daemon

def set_daemon(daemon: Optional[AutonomyDaemon]) -> None:
    """Override the singleton (used for tests)."""
    global _daemon
    _daemon = daemon
