import json

"""
Autonomy layer smoke test — verifies Aariya's proactive/autonomous loop.

Exercises the full autonomy stack end-to-end WITHOUT a live LLM (the base URL
is pointed at an unreachable port so every LLM call falls back to template /
keyword paths):

  snapshot recording → self-generated goal → template planning → initiative
  firing (proactive message) → plan approval → executor run + audit trail →
  inner-world payload → gap/insight roundtrip, plus: plan rejection, initiative
  guard blocking, the background learning cycle, and the goal-review cadence
  (generate → plan → await approval / auto-execute).

Isolation: the `offline_llm` and `isolated_db` fixtures (conftest.py) point
the LLM at an unreachable port and redirect server.db to a throwaway SQLite
file, so running this test never touches real brain data (data/brain_v4.db).

Run:  python -m pytest server/tests/test_autonomy.py -v
"""

import asyncio
import time

import pytest

import server.db as server_db  # noqa: E402  (path setup lives in conftest.py)
from server.autonomy.daemon import AutonomyDaemon, set_daemon
from server.protocol import BrainState

# Tables written by the autonomy layer (isolated via the isolated_db fixture).
_AUTONOMY_TABLES = [
    "autonomy_snapshots",
    "autonomy_goals",
    "autonomy_plans",
    "autonomy_actions",
    "autonomy_initiatives",
    "autonomy_gaps",
    "autonomy_insights",
]


@pytest.fixture()
def autonomy_db(isolated_db):
    """Fresh autonomy tables on the isolated temp DB, plus singleton cleanup."""
    _clean_autonomy_tables()
    yield isolated_db
    # Don't leak the test daemon (or its proactive engine / guard singletons)
    # into other tests in the same process.
    set_daemon(None)
    from server.systems.proactive import engine as _engine
    from server.safety import initiative_guard as _guard
    _engine._proactive_engines.clear()
    _guard._initiative_guard = None


def _clean_autonomy_tables() -> None:
    """Start from a clean slate (only autonomy_* tables, only the test DB)."""
    conn = server_db.get_db_connection()
    try:
        for t in _AUTONOMY_TABLES:
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
    finally:
        conn.close()


async def _run_smoke_checks() -> list:
    """Run the whole flow; returns the list of failed check names."""
    passed = []
    failed = []

    def check(name, cond, detail=""):
        if cond:
            passed.append(name)
            print(f"  \u2714 {name}")
        else:
            failed.append(name)
            print(f"  \u2718 {name}  {detail}")

    received = []
    daemon = await _new_daemon(received)
    store = daemon.store

    # 1. Snapshot recording
    state = BrainState(valence=-0.5, arousal=0.4, trust=0.6, attachment=0.2)
    daemon.record_snapshot(state)
    snap = store.get_latest_snapshot("user_default")
    check("snapshot persisted", snap and abs(snap["valence"] - (-0.5)) < 0.001, str(snap))

    # 2. Goal generation from valence signal (distress → support_user).
    #    _generate_goal persists the goal itself via _create_goal.
    goal = daemon._generate_goal()
    check("goal generated from real signal",
          goal is not None and goal["goal_type"] == "support_user", str(goal))

    # 3. Planning (template fallback — no LLM)
    active = daemon._get_active_goal()
    check("active goal present", active is not None)
    if not active:
        return failed  # goal generation failed — report and stop cleanly
    plan_dict = await daemon.planner.plan_goal(
        active, {"gaps": [], "insights": [], "trust": 0.6}
    )
    steps = plan_dict["steps"]
    check("plan has whitelisted steps",
          len(steps) >= 1 and all(
              s["type"] in {"research", "surface_insight", "check_in", "monitor", "review_vault"}
              for s in steps), str(steps))
    check("plan requires approval (has check_in)", plan_dict["requires_approval"] is True,
          str(plan_dict))

    plan_id = store.add_plan(
        active["id"], steps, plan_dict["risk_level"],
        plan_dict["requires_approval"], status="awaiting_approval",
    )

    # 4. Initiative evaluation → distress trigger + fallback message
    daemon._latest_snapshot = {
        "valence": -0.55, "arousal": 0.3, "trust": 0.6, "attachment": 0.2,
    }
    daemon._history = [
        {"valence": -0.1, "arousal": 0.2, "trust": 0.6, "ts": time.time() - 180},
        {"valence": -0.3, "arousal": 0.25, "trust": 0.6, "ts": time.time() - 120},
        {"valence": -0.55, "arousal": 0.3, "trust": 0.6, "ts": time.time() - 60},
    ]
    await daemon._initiative_tick()
    fired = store.list_initiatives(limit=5)
    check("initiative fired (distress)",
          len(fired) >= 1 and fired[0]["trigger_type"] == "distress",
          str([i["trigger_type"] for i in fired]))
    proactive_msgs = [m for m in received if m.get("type") == "proactive_message"]
    check("proactive message broadcast",
          len(proactive_msgs) >= 1 and proactive_msgs[0].get("content"),
          str(proactive_msgs[:1]))
    check("initiative guard respected", len(fired) == 1, str(len(fired)))

    # 5. Plan approval → executor runs + audit log (research fails w/o LLM,
    #    proving graceful failure handling + audit coverage)
    result = await daemon.approve_plan(plan_id)
    actions = store.list_actions(limit=10)
    check("plan executed",
          result.get("ok") is True and result.get("status") in ("completed", "failed"),
          str(result))
    check("audit log written",
          len(actions) >= 1 and all(a["status"] in ("completed", "failed") for a in actions),
          str([(a["action_type"], a["status"]) for a in actions]))
    check("plan no longer awaiting approval",
          store.get_plan(plan_id)["status"] in ("completed", "failed"),  # type: ignore
          store.get_plan(plan_id)["status"])  # type: ignore

    # 6. Inner world payload
    world = daemon.get_inner_world()
    check("inner world payload complete",
          all(k in world for k in ("enabled", "active_goal", "plans", "initiatives",
                                   "insights", "actions")),
          str(list(world.keys())))

    # 7. Gap + insight roundtrip
    store.add_gap("quantum computing", "user asked and I hedged", priority=8)
    check("gap queued", len(store.get_pending_gaps()) == 1)
    store.add_insight("quantum computing", "Qubits are fragile; error correction matters",
                      source="test", confidence=0.7)
    unsurfaced = store.get_unsurfaced_insights()
    check("insight stored & unsurfaced", len(unsurfaced) == 1)
    store.mark_insight_surfaced(unsurfaced[0]["id"])
    check("insight surfaced flag", len(store.get_unsurfaced_insights()) == 0)

    print(f"\n{'='*44}\nPASS: {len(passed)}  FAIL: {len(failed)}")
    return failed


def test_autonomy_smoke(autonomy_db, offline_autonomy_stack):
    """Full autonomy flow against isolated state (no live LLM, no dev data)."""
    failed = asyncio.run(_run_smoke_checks())
    assert not failed, f"Autonomy smoke test failed: {failed}"


# ── Additional flows ─────────────────────────────────────────────────────────

class _DownResearchAgent:
    """Research agent stub that deterministically fails (like an offline LLM)."""
    async def run_research(self, question):
        return {"error": "LLM unreachable", "status": "failed"}


@pytest.fixture()
def offline_autonomy_stack(monkeypatch):
    """Stub every LLM/network path the autonomy layer can touch.

    The real endpoints are captured at import time (not reachable via the
    offline_llm env fixture) and can hang for minutes against a slow-but-up
    Ollama — the tests only need the graceful-failure paths, so stub all four
    call sites to make the suite deterministic and network-free.
    """
    from server.systems.agent import controller as agent_controller
    from server.autonomy import planner, learning, loop as loop_module

    monkeypatch.setattr(agent_controller, "get_research_agent", lambda: _DownResearchAgent())
    monkeypatch.setattr(planner, "_get_llm", lambda: _DownLLM())
    monkeypatch.setattr(learning, "_get_llm", lambda: _DownLLM())
    monkeypatch.setattr(loop_module, "_get_llm", lambda: _DownLLM())


async def _new_daemon(received: list) -> AutonomyDaemon:
    """Fresh daemon broadcasting into `received`, installed as the singleton."""
    async def broadcast(msg):
        received.append(msg)

    daemon = AutonomyDaemon(broadcast=broadcast)
    set_daemon(daemon)
    return daemon


async def _seed_awaiting_plan(daemon, goal_type: str = "support_user") -> tuple:
    """Seed a real goal + awaiting-approval plan; returns (goal, plan_id)."""
    daemon.record_snapshot(BrainState(valence=-0.5, arousal=0.3, trust=0.6, attachment=0.2))
    goal = daemon._generate_goal()
    assert goal is not None and goal["goal_type"] == goal_type
    plan_dict = await daemon.planner.plan_goal(
        goal, {"gaps": [], "insights": [], "trust": 0.6}
    )
    plan_id = daemon.store.add_plan(
        goal["id"], plan_dict["steps"], plan_dict["risk_level"],
        plan_dict["requires_approval"], status="awaiting_approval",
    )
    return goal, plan_id


async def _reject_plan_flow() -> None:
    received = []
    daemon = await _new_daemon(received)
    store = daemon.store
    sock = _FakeLogSocket()
    goal, plan_id = await _seed_awaiting_plan(daemon)

    # Reject → plan rejected, goal suspended, state broadcast
    await _collect_daemon_events(daemon, sock, daemon.reject_plan, plan_id)
    assert store.get_plan(plan_id)["status"] == "rejected"  # type: ignore
    assert store.get_goal(goal["id"])["status"] == "suspended"  # type: ignore
    assert any(m.get("type") == "autonomy.state" for m in received)
    # The rejection produced a REAL PLANNER event in the log.
    planner_sigs = [s for s in _signal_events(sock) if s["source"]["system"] == "PLANNER"]
    assert len(planner_sigs) == 1
    assert "rejected" in planner_sigs[0]["payload"]["title"].lower()
    assert planner_sigs[0]["payload"]["plan_id"] == plan_id

    # A rejected plan can no longer be approved
    sock.frames.clear()
    res2 = await daemon.approve_plan(plan_id)
    assert res2["ok"] is False
    assert _signal_events(sock) == []  # nothing fabricated for a failed approve

    # Rejecting a missing plan fails gracefully
    res3 = await daemon.reject_plan("does_not_exist")
    assert res3["ok"] is False


def test_reject_plan(autonomy_db, offline_autonomy_stack):
    asyncio.run(_reject_plan_flow())


async def _guard_blocking_integration_flow() -> None:
    received = []
    daemon = await _new_daemon(received)
    store = daemon.store

    # A distress signal WOULD fire an initiative — but dangerously high
    # attachment makes the guard veto it, so nothing is initiated.
    daemon._latest_snapshot = {
        "valence": -0.6, "arousal": 0.4, "trust": 0.7, "attachment": 0.95,
    }
    daemon._history = [
        {"valence": -0.2, "arousal": 0.2, "trust": 0.7, "ts": time.time() - 120},
        {"valence": -0.6, "arousal": 0.4, "trust": 0.7, "ts": time.time() - 60},
    ]
    await daemon._initiative_tick()
    assert len(store.list_initiatives(limit=10)) == 0


def test_daemon_respects_initiative_guard(autonomy_db, offline_autonomy_stack):
    asyncio.run(_guard_blocking_integration_flow())


def test_initiative_guard_unit_rules(autonomy_db, offline_autonomy_stack):
    from server.safety.initiative_guard import get_initiative_guard

    guard = get_initiative_guard()  # fresh (autonomy_db resets the singleton)

    # Attachment too high → blocked (prevents clingy behavior)
    assert guard.allow("u1", trust=0.8, attachment=0.9) is False
    # Trust too low → blocked
    assert guard.allow("u2", trust=0.1, attachment=0.0) is False
    # Happy path → allowed
    assert guard.allow("u3", trust=0.8, attachment=0.1) is True
    # Cooldown blocks an immediate re-fire
    assert guard.allow("u3", trust=0.8, attachment=0.1) is False

    # Hourly cap: seed a full hour-log (default 3/hour) with cooldown elapsed
    guard._last_initiation["u4"] = time.time() - 400
    guard._hourly_log["u4"] = [
        time.time() - 3500, time.time() - 1800, time.time() - 60,
    ]
    assert guard.allow("u4", trust=0.8, attachment=0.1) is False


class _DownLLM:
    """Learner LLM stub that raises (like an offline endpoint)."""
    def chat_completion(self, *args, **kwargs):
        raise ConnectionError("offline")


async def _inner_world_predictor_flow() -> None:
    received = []
    daemon = await _new_daemon(received)
    daemon.record_snapshot(BrainState(valence=0.2, arousal=0.3, trust=0.6, attachment=0.1))

    world = daemon.get_inner_world()
    pred = world["predictor"]
    # Telemetry entry is always present and shaped for the dashboard.
    assert pred["status"] in ("trained", "untrained")
    assert "checkpoint_age_hours" in pred
    assert "count" in pred and "seed_count" in pred
    assert pred["corpus"] == {"snapshots": 1, "sessions": 0}
    assert "forecast" in pred


def test_inner_world_includes_predictor_telemetry(autonomy_db, offline_autonomy_stack):
    asyncio.run(_inner_world_predictor_flow())


async def _learning_cycle_flow() -> None:
    received = []
    daemon = await _new_daemon(received)
    store = daemon.store
    learner = daemon.learner

    # No pending gaps → no-op
    assert await learner.run_cycle(max_gaps=2) == {"processed": 0, "gaps_left": 0}

    # With a pending gap, research yields nothing → the gap is marked failed
    # and NO insight is fabricated. The cycle must never raise.
    store.add_gap("quantum computing", "asked and hedged", priority=8)
    result = await learner.run_cycle(max_gaps=2)
    assert result["processed"] == 0
    assert result["gaps_left"] == 0

    gaps = store.list_gaps(limit=5)
    assert gaps and gaps[0]["status"] == "failed"
    assert len(store.get_unsurfaced_insights()) == 0

    # Gap detection with the LLM down → gracefully returns nothing
    queued = await learner.detect_and_queue_gaps(
        "explain quantum error correction", "Qubits are fragile...",
    )
    assert queued == []


def test_learning_cycle_degrades_gracefully(autonomy_db, offline_autonomy_stack):
    asyncio.run(_learning_cycle_flow())


async def _goal_review_generate_flow() -> None:
    received = []
    daemon = await _new_daemon(received)
    store = daemon.store

    # Distress signal → the review cycle must self-generate a support_user
    # goal, plan it, and gate it on approval.
    daemon._latest_snapshot = {
        "valence": -0.5, "arousal": 0.3, "trust": 0.6, "attachment": 0.2,
    }
    await daemon._goal_review_tick()

    goal = daemon._get_active_goal()
    assert goal is not None and goal["goal_type"] == "support_user"
    plans = store.list_plans(goal_id=goal["id"])
    assert len(plans) == 1
    assert plans[0]["status"] == "awaiting_approval"
    step_types = [s["type"] for s in plans[0]["steps"]]
    assert "check_in" in step_types  # user-facing → needs approval

    # The approval card was broadcast
    assert any(m.get("type") == "plan.approval_requested" for m in received)

    # A second review must NOT create a duplicate plan (idempotent)
    await daemon._goal_review_tick()
    assert len(store.list_plans(goal_id=goal["id"])) == 1


def test_goal_review_generates_and_waits_for_approval(autonomy_db, offline_autonomy_stack):
    asyncio.run(_goal_review_generate_flow())


async def _goal_review_autoexecute_flow() -> None:
    received = []
    daemon = await _new_daemon(received)
    store = daemon.store

    # A pre-existing safe (approval-free) plan must auto-execute on review.
    goal_id = store.add_goal("Test goal", "learn_topic", "test", priority=0.5)
    plan_id = store.add_plan(
        goal_id,
        steps=[{"type": "review_vault", "params": {"topic": "wellbeing"},
                "requires_approval": False}],
        risk_level="low",
        requires_approval=False,
        status="proposed",
    )
    await daemon._goal_review_tick()

    plan = store.get_plan(plan_id)
    assert plan["status"] in ("completed", "failed")  # type: ignore
    assert store.get_goal(goal_id)["status"] in ("completed", "failed")  # type: ignore
    # The run was audited
    actions = store.list_actions(plan_id=plan_id, limit=5)
    assert len(actions) >= 1


def test_goal_review_auto_executes_proposed_plan(autonomy_db, offline_autonomy_stack):
    asyncio.run(_goal_review_autoexecute_flow())


# ── Real Event Log feed (no synthetic events) ────────────────────────────────

class _FakeLogSocket:
    """Captures frames pushed by admin_signal_bus.emit_signal."""

    def __init__(self):
        self.frames = []

    async def send_json(self, obj):
        self.frames.append(obj)


async def _collect_daemon_events(daemon, sock, fn, *args):
    """Run an async daemon action while a fake log socket is attached."""
    from server.systems.signal_bus import bus as admin_signal_bus
    admin_signal_bus._connected_sockets.append(sock)
    try:
        await fn(*args)
    finally:
        if sock in admin_signal_bus._connected_sockets:
            admin_signal_bus._connected_sockets.remove(sock)


def _signal_events(sock):
    """Extract the emitted signal frames (skip non-signal frames if any)."""
    return [f["signal"] for f in sock.frames if f.get("type") == "signal"]


async def _daemon_event_log_flow() -> None:
    received = []
    daemon = await _new_daemon(received)
    sock = _FakeLogSocket()

    # No action yet → nothing emitted (nothing fabricated at boot).
    assert sock.frames == []

    # 1. Proactive initiative → DAEMON signal with real trigger + message.
    daemon._latest_snapshot = {
        "valence": -0.55, "arousal": 0.3, "trust": 0.6, "attachment": 0.2,
    }
    daemon._history = [
        {"valence": -0.1, "arousal": 0.2, "trust": 0.6, "ts": time.time() - 180},
        {"valence": -0.3, "arousal": 0.25, "trust": 0.6, "ts": time.time() - 120},
        {"valence": -0.55, "arousal": 0.3, "trust": 0.6, "ts": time.time() - 60},
    ]
    await _collect_daemon_events(daemon, sock, daemon._initiative_tick)
    signals = _signal_events(sock)
    daemon_sigs = [s for s in signals if s["source"]["system"] == "DAEMON"]
    assert len(daemon_sigs) == 1
    sig = daemon_sigs[0]
    assert sig["severity"] == "info"
    assert sig["timestamp"] > 0
    assert sig["payload"]["trigger"] == "distress"
    assert "Proactive (distress)" in sig["payload"]["title"]
    assert sig["payload"]["urgency"]

    # Steady re-fire of the same tick (guard cooldown) → no new signals.
    sock.frames.clear()
    await _collect_daemon_events(daemon, sock, daemon._initiative_tick)
    assert _signal_events(sock) == []

    # 2. Goal review → PLANNER signal for the new goal + approval request.
    daemon._last_user_message = time.time() - 3600  # reset silence for a fresh pass
    sock.frames.clear()
    await _collect_daemon_events(daemon, sock, daemon._goal_review_tick)
    signals = _signal_events(sock)
    planner_sigs = [s for s in signals if s["source"]["system"] == "PLANNER"]
    titles = [s["payload"].get("title", "") for s in planner_sigs]
    assert any("New goal" in t for t in titles), titles
    assert any("awaits approval" in t for t in titles), titles
    # The approval signal carries real plan metadata.
    approval = next(s for s in planner_sigs if "awaits approval" in s["payload"]["title"])
    assert approval["severity"] == "warn"
    assert approval["payload"]["risk_level"] in ("low", "medium", "high")
    assert approval["payload"]["goal_type"]

    # 3. Learning cycle completion → LEARNING signal (when research succeeded).
    #    The cycle runs in a background task, so keep the socket attached until
    #    the task finishes before detaching it (or the emit is dropped).
    async def _fake_run_cycle(**kwargs):
        return {"processed": 2, "gaps_left": 1}

    daemon.learner.run_cycle = _fake_run_cycle  # type: ignore[method-assign]
    from server.systems.signal_bus import bus as admin_signal_bus
    sock.frames.clear()
    admin_signal_bus._connected_sockets.append(sock)
    try:
        await daemon._learning_tick()
        if daemon._learning_task:  # learning runs in its own task — wait for it
            await daemon._learning_task
    finally:
        if sock in admin_signal_bus._connected_sockets:
            admin_signal_bus._connected_sockets.remove(sock)
    signals = _signal_events(sock)
    learn_sigs = [s for s in signals if s["source"]["system"] == "LEARNING"]
    assert len(learn_sigs) == 1
    assert "Researched 2 topic(s)" in learn_sigs[0]["payload"]["title"]
    assert learn_sigs[0]["payload"]["processed"] == 2
    assert learn_sigs[0]["payload"]["gaps_left"] == 1


def test_daemon_emits_real_events_to_log(autonomy_db, offline_autonomy_stack):
    asyncio.run(_daemon_event_log_flow())


async def _daemon_event_helper_flow() -> None:
    """The helper is best-effort: never raises with no bus / dead sockets."""
    daemon = await _new_daemon([])

    # No connected sockets → emit is a cheap no-op, no crash.
    from server.systems.signal_bus import bus as admin_signal_bus
    admin_signal_bus._connected_sockets.clear()
    await daemon._emit_real_event("MODEL", "info", "Retrained", {"id": 7})
    # A bad payload shape still can't crash the daemon tick.
    await daemon._emit_real_event("MODEL", "info", None, None)  # type: ignore[arg-type]

    # With a live socket, the frame arrives shaped for the frontend.
    sock = _FakeLogSocket()
    admin_signal_bus._connected_sockets.append(sock)
    try:
        await daemon._emit_real_event(
            "MODEL", "info", "Emotion predictor retrained (through snapshot 42)",
            {"snapshot_id": 42, "reason": "enough new snapshots"},
        )
        sig = _signal_events(sock)[0]
        assert sig["source"]["system"] == "MODEL"
        assert sig["severity"] == "info"
        assert sig["payload"]["snapshot_id"] == 42
        assert "retrained" in sig["payload"]["title"].lower()
    finally:
        if sock in admin_signal_bus._connected_sockets:
            admin_signal_bus._connected_sockets.remove(sock)


def test_daemon_event_helper_is_best_effort(autonomy_db, offline_autonomy_stack):
    asyncio.run(_daemon_event_helper_flow())


# ── plan.ack carries plan_id (live strip contract) ───────────────────────────

async def _control_command_ack_flow() -> None:
    """The /ws/dashboard/stream control handler must echo plan_id in plan.ack
    so the frontend's live plan-status chip can update after approve/reject.

    Uses the pure build_control_ack helper (server.autonomy.daemon) rather than
    importing server.main, which requires aiortc (missing in this venv) and
    would fail collection for the whole file.
    """
    from server.autonomy.daemon import (
        AutonomyDaemon,
        build_control_ack,
        set_daemon as _set_daemon,
    )

    async def _broadcast(_msg):
        pass

    daemon = AutonomyDaemon(broadcast=_broadcast)
    _set_daemon(daemon)
    goal, plan_id = await _seed_awaiting_plan(daemon)

    # Approve via the real daemon → ack (built by the pure helper) carries plan_id.
    result = await daemon.approve_plan(plan_id)
    ack = build_control_ack("approve_plan", plan_id, result)
    assert ack["type"] == "plan.ack"
    assert ack["plan_id"] == plan_id
    assert ack["ok"] is True
    assert ack["status"] in ("completed", "failed")

    # plan_id is echoed AFTER the result spread — a result containing plan_id
    # can never override the echoed one.
    ack_override = build_control_ack("approve_plan", "real_id", {"ok": True, "plan_id": "spoofed"})
    assert ack_override["plan_id"] == "real_id"

    # Reject a fresh plan → ack carries plan_id + status rejected.
    goal2, plan2 = await _seed_awaiting_plan(daemon)
    result2 = await daemon.reject_plan(plan2)
    ack2 = build_control_ack("reject_plan", plan2, result2)
    assert ack2["plan_id"] == plan2
    assert ack2["ok"] is True
    assert ack2["status"] == "rejected"

    # autonomy_enabled → autonomy.ack (never a plan frame), unknown → plan.ack err.
    en = build_control_ack("autonomy_enabled", "", {"ok": True, "enabled": True})
    assert en["type"] == "autonomy.ack"
    assert "plan_id" not in en
    unknown = build_control_ack("nope", "", {})
    assert unknown["type"] == "plan.ack" and unknown["ok"] is False


def test_control_command_ack_carries_plan_id(autonomy_db, offline_autonomy_stack):
    asyncio.run(_control_command_ack_flow())
