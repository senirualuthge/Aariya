# Load .env before importing modules that read configuration at import time
# (security/auth.py reads REQUIRE_WS_AUTH then). Skipped under pytest so the
# test suite stays hermetic and legacy-mode tests are not switched to device
# auth by a developer's local .env.
import sys as _sys
if "pytest" not in _sys.modules:
    try:
        from dotenv import load_dotenv as _load_dotenv
        _load_dotenv()
    except Exception:  # python-dotenv is optional
        pass

import asyncio
import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, Set
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from server.protocol import BrainState, MultimodalInput
from server.db import get_db_connection, init_db
from server.systems.cognitive_session_coordinator import (
    assert_single_worker,
    cognitive_sessions,
)
from server.infrastructure.session_manager import SessionManager
from server.infrastructure.signal_bus import SignalBus
from server.systems.signal_bus import bus as admin_signal_bus
from server.autonomy.daemon import get_daemon
from server.autonomy.learning import BackgroundLearner
from server.autonomy.state import AutonomyStore
from server.routers.meeting_control import router as meeting_router
from server.systems.meeting_mode import get_meeting_mode
from server.routers.agents_router import router as agents_router
from server.routers.security_router import router as security_router
from server.routers.news_router import router as news_router
from server.routers.web_search_router import router as web_search_router
from server.routers.self_knowledge_router import router as self_knowledge_router
from server.routers.build_summary_router import router as build_summary_router
from server.routers.obsidian_router import router as obsidian_router
from server.routers.emotion_predictor_router import router as emotion_predictor_router
from server.routers.analytics_ws import router as analytics_ws_router
from server.routers.prediction_router import router as prediction_router
from server.routers.system_health_router import router as system_health_router
from server.routers.compliance import router as compliance_router
from server.routers.events_router import router as events_router
from server.routers.filesystem_router import router as filesystem_router
from server.routers.tools_router import router as tools_router
from server.routers.analytics import router as analytics_router
from server.routers.signals import router as ingest_router, api_signals_router
from server.routers.rl import router as rl_router
from server.routers.swarm_ws import router as swarm_ws_router
from server.routers.gev_router import router as gev_router
from server.infrastructure.agent_watcher import get_watcher
from server.systems.security.mobile_authority import is_mobile_allowed, denied_frame
from server.systems.security.dashboard_authority import execute_authority_command
from server.systems.security.auth import verify_message_signature
from server.systems.security.device_auth import (
    accept_personal_websocket,
    authenticate_personal_websocket,
)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(level=LOG_LEVEL)
logger = logging.getLogger("aariya.main")

# Origins allowed to make credentialed requests to this API.
_DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:4173",
    "http://localhost:8000",
    "http://localhost:8001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:4173",
    "http://127.0.0.1:8000",
    "http://127.0.0.1:8001",
    "app://.",
    "capacitor://localhost",
    # Electron loads the bundled app over file:// in production builds.
    "null",
)


def _cors_origins() -> List[str]:
    """
    Resolve the CORS allowlist from CORS_ORIGINS.

    Comma-separated override for LAN/tailscale mobile clients and any hosted
    front end. A bare "*" is honoured only when the operator explicitly asks
    for it AND credentials are not in play — see the middleware below.
    """
    raw = os.getenv("CORS_ORIGINS", "")
    if not raw.strip():
        return list(_DEFAULT_CORS_ORIGINS)
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    return origins or list(_DEFAULT_CORS_ORIGINS)

# Cap concurrent background gap-detection LLM calls (one in flight at a time)
_gap_detect_lock = asyncio.Lock()

# --- BUG #18 FIX: use lifespan context manager instead of deprecated @app.on_event ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast on a misconfigured production launch: a deployment that
    # requires device auth must never silently fall back to legacy trust.
    from server.systems.security.device_auth import validate_device_auth_configuration
    validate_device_auth_configuration()

    # Fail fast on a multi-worker launch: each worker would hold its own
    # coordinator + brain per user. One worker is required until distributed
    # (Redis-backed) coordination exists.
    assert_single_worker()

    logger.info("Aariya Brain FIXV4 Starting Up...")
    init_db()

    # ── IDLE COGNITIVE SESSION EVICTION ──────────────────────────────────────
    # A long-lived process must not keep one BrainV2 per user that ever
    # connected. Sessions idle past the TTL are dropped by a background sweep;
    # the next turn rebuilds that brain from the persistent memory/personality
    # stores (the same recovery path as a restart).
    session_sweeper = asyncio.create_task(
        cognitive_sessions.eviction_loop(
            idle_seconds=float(os.getenv("AARIYA_SESSION_IDLE_TTL_SECONDS", "1800")),
            interval_seconds=float(os.getenv("AARIYA_SESSION_SWEEP_INTERVAL_SECONDS", "60")),
        )
    )

    # Apply SQL migrations (trust/contradiction/episodic/pattern/audit tables
    # etc.) to the analytics store. Never ran before — every module querying
    # those tables hit "no such table" until this startup hook existed.
    try:
        from server.migrations import MigrationRunner
        applied = MigrationRunner().run_pending_migrations()
        if applied:
            logger.info("Applied %d DB migration(s)", applied)
    except Exception as exc:
        logger.warning("DB migrations skipped: %s", exc)


    # Kick off a non-blocking sync of the Obsidian dual vaults into RAG memory.
    # Runs in a background thread so server startup is never blocked by indexing.
    try:
        obsidian_indexer = get_obsidian_indexer()
        threading.Thread(target=obsidian_indexer.sync_all, daemon=True, name="obsidian-vault-sync").start()
    except Exception as exc:
        logger.warning("Obsidian vault sync skipped: %s", exc)

    # Runtime telemetry -> runtime Obsidian vault: appends live system metrics
    # (uptime, memory, CPU, active agents) on an interval so Aariya's running
    # details accumulate as retrievable obsidian_runtime context.
    try:
        from server.systems.rag.runtime_telemetry import start_runtime_telemetry, seed_runtime_vault
        # Seed the runtime vault with a starter log template + today's log file
        # first so future entries are formatted consistently (idempotent).
        seed_runtime_vault()
        start_runtime_telemetry()
    except Exception as exc:
        logger.warning("Runtime telemetry logger skipped: %s", exc)

    # Start agent auto-discovery watcher — runs startup scan immediately,
    # then watches for .py file changes and broadcasts diffs to all
    # connected /api/agents/ws clients in real-time.
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    watcher = get_watcher(root=project_root)
    loop = asyncio.get_event_loop()
    watcher.start(loop)
    logger.info("[AgentWatcher] Started — initial registry scan complete.")

    # ── AUTONOMY DAEMON ──────────────────────────────────────────────────────
    # The 24/7 proactive brain. Runs independent of any client connection:
    # initiative evaluation, background research/learning, goal → plan →
    # execute → audit. Events broadcast to connected surfaces when present.
    daemon = get_daemon(broadcast=session_manager.broadcast)
    daemon.start()

    # ── SYSTEM HEALTH MONITOR ────────────────────────────────────────────────
    # Broadcasts a full health snapshot (server perf + subsystem checks +
    # auto-discovered functions + mobile telemetry) to /ws/brain_metrics every
    # 2 s so the dashboard's System Health tab stays live with zero extra
    # connections. Also serves GET /api/system/health as a fetch fallback.
    try:
        from server.systems.system_health import get_system_health
        get_system_health().start()
    except Exception as exc:
        logger.warning("System health monitor start skipped: %s", exc)

    # ── MOBILE TELEMETRY AGENTS ─────────────────────────────────────────────
    # The gateway / analytics / dashboard agents maintain live mobile health
    # (connected clients, command throughput, latency, payload rates) and
    # broadcast mobile_*_health pings over /ws/brain_metrics. Start them here
    # so their 1 s tick loops run from boot (they were defined but never
    # started, so the dashboard never received their health pings).
    try:
        from server.systems.agent.mobile_gateway_agent import get_mobile_gateway
        from server.systems.agent.mobile_analytics_agent import get_mobile_analytics
        from server.systems.agent.mobile_dashboard_agent import get_mobile_dashboard
        get_mobile_gateway().start()
        get_mobile_analytics().start()
        get_mobile_dashboard().start()
        logger.info("[MobileTelemetry] gateway + analytics + dashboard agents started")
    except Exception as exc:
        logger.warning("Mobile telemetry agents start skipped: %s", exc)

    # ── GEV GEOSPATIAL INTELLIGENCE AGENT ───────────────────────────────────
    # ⚡ On-demand mode: no background polling.  The agent is only registered
    # here so the dashboard's Agent Registry tab shows it.  Data is fetched
    # when the brain, daemon, or a REST consumer explicitly requests it.
    try:
        from server.systems.gev.gev_agent import get_gev_agent, GEVAgent
        _gev_agent = get_gev_agent()
        # Self-register in the persistent agent registry so the dashboard's
        # Agent Registry tab shows GEVAgent without waiting for a file scan.
        from server.infrastructure.agent_registry import get_registry
        reg = get_registry()
        rec = _gev_agent.registry_record()
        reg.register_static_agent(rec)
        logger.info("[GEVAgent] Registered (kind=geospatial, on-demand mode)")
    except Exception as exc:
        logger.warning("GEV agent registration skipped: %s", exc)

    # Surface any pending startup brief (things learned while away) after a
    # short delay so clients connecting right at boot receive it.
    async def _brief_broadcaster():
        try:
            await asyncio.sleep(3)
            brief = BackgroundLearner(AutonomyStore()).get_startup_brief()
            if brief:
                await session_manager.broadcast({
                    "type": "proactive_message",
                    "content": brief,
                    "trigger": "startup_brief",
                    "urgency": "info",
                    "timestamp": time.time(),
                })
        except Exception as exc:
            logger.warning("Startup brief skipped: %s", exc)

    asyncio.create_task(_brief_broadcaster())

    yield

    # Stop idle-session eviction before tearing the rest down.
    session_sweeper.cancel()
    try:
        await session_sweeper
    except asyncio.CancelledError:
        pass

    await daemon.stop()
    watcher.stop()
    try:
        from server.systems.system_health import get_system_health
        await get_system_health().stop()
    except Exception:
        pass
    # Stop the mobile telemetry agents' tick loops (started above).
    try:
        from server.systems.agent.mobile_gateway_agent import get_mobile_gateway
        from server.systems.agent.mobile_analytics_agent import get_mobile_analytics
        from server.systems.agent.mobile_dashboard_agent import get_mobile_dashboard
        get_mobile_gateway().stop()
        get_mobile_analytics().stop()
        get_mobile_dashboard().stop()
    except Exception:
        pass
    # Stop GEV polling loop.
    try:
        from server.systems.gev.gev_agent import get_gev_agent
        get_gev_agent().stop()
    except Exception:
        pass
    # Close any live WebRTC peer connections so aiortc's ICE/DTLS transports
    # do not outlive the app.
    try:
        from server.realtime.webrtc_server import close_all_peer_connections
        await close_all_peer_connections()
    except Exception:
        pass
    logger.info("Aariya Brain shutting down.")

app = FastAPI(title="Aariya AI Brain - FIXV4", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    # Explicit allowlist — see _cors_origins(). Credentials are still enabled
    # (the desktop app authenticates with cookies), which is exactly why a
    # wildcard origin is unsafe here.
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
async def health_liveness() -> dict:
    """Cheap liveness probe for uptime checks, containers and curl.

    Deliberately does NOT build the System Health snapshot: that walks psutil,
    probes every subsystem and can take tens of milliseconds, which is wrong for
    a probe. Full metrics live at ``GET /api/system/health``.
    """
    return {"status": "ok", "service": "aariya-brain", "ts": time.time()}

# --- GLOBAL SYSTEMS ---
session_manager = SessionManager()
# BUG #20 FIX: signal_bus is now wired into the cognitive loop
signal_bus = SignalBus()

# Include routers
app.include_router(meeting_router)
app.include_router(agents_router)    # Provides /api/agents + /api/agents/ws
app.include_router(security_router)  # Provides /api/security/scan + /api/security/last-scan
app.include_router(news_router)      # Provides /api/news + /api/news/article + /api/news/alerts
app.include_router(web_search_router) # Provides /api/web-search (Bing > SerpAPI > Serper > DDG > Wikipedia — keyless tail)
app.include_router(self_knowledge_router)  # Provides /api/self-knowledge (data-location inventory)
app.include_router(build_summary_router)   # Provides /api/build/summary (production build stats)
app.include_router(obsidian_router)        # Provides /api/obsidian/search + /api/obsidian/runtime/latest
app.include_router(emotion_predictor_router)  # Provides /api/emotion/predictor (LSTM training status + forecast)
app.include_router(analytics_ws_router)       # Provides /ws/mobile/analytics (mobile telemetry stream)
app.include_router(prediction_router)         # Provides /api/prediction/* (unified prediction engine)
app.include_router(system_health_router)      # Provides /api/system/health (System Health tab snapshot)
from server.routers.device_auth_router import router as device_auth_router
app.include_router(device_auth_router)        # Provides /api/auth/* (device pairing + WS tickets)
app.include_router(compliance_router)         # Provides /api/compliance/* (consent matrix + governance + GDPR)
app.include_router(events_router)              # Provides /api/events/latest (real event-log ring for mobile)
from server.routers.synoptics_ws import router as synoptics_router
app.include_router(synoptics_router)          # Provides /ws/synoptics (synoptics v2 frame stream)

from server.routers.autonomy_router import router as autonomy_router
app.include_router(autonomy_router)        # Provides /api/autonomy/* (inner world, approvals, gaps)

# AccessFIles §1-§17: guarded local filesystem access (browse/read/search/
# semantic recall/confirmation-gated mutations/audit/rollback/sandbox/vision).
app.include_router(filesystem_router)      # Provides /api/fs/* + /api/sandbox/run + /api/vision/screen*

# AccessFIles §33: MCP tool ecosystem + knowledge-graph query/ingest surface.
app.include_router(tools_router)           # Provides /api/tools/* + /api/knowledge/*
app.include_router(analytics_router)       # Provides /api/analytics/overview|personality|memories (real schema)
app.include_router(ingest_router)          # Provides /ingest/signal|signals|device (external telemetry)
app.include_router(api_signals_router)     # Provides /api/signals/ingest (pulse-news news.alert contract)
app.include_router(rl_router)              # Provides /api/rl/status (PPO policy status)
app.include_router(swarm_ws_router)        # Provides /api/swarm/ws (AGENT_UPDATE / AGENT_EVOLVED pulses)
app.include_router(gev_router)             # Provides /api/gev/* (geospatial intelligence + /api/gev/stream WS)

# HumanAI SDK: trust, emotion, memory, audit, kill-switch REST API.
from server.routers.sdk_api import router as sdk_router
app.include_router(sdk_router)             # Provides /api/sdk/* (SDK public contract)

# AccessFIles §61/§76: distributed-memory sync + real-hardware embodiment probe.
from server.routers.sync_router import router as sync_router
app.include_router(sync_router)            # Provides /api/memory/* + /api/embodiment/status

# AccessFIles §75: real-time collaboration (shared workspace memory + live rooms).
from server.routers.collab_router import router as collab_router, ws_router as collab_ws_router
app.include_router(collab_router)          # Provides /api/collab/*
app.include_router(collab_ws_router)       # Provides /ws/collab/{name} rooms

# WebRTC microphone capture for the paired phone: POST /offer + /interrupt.
# Capture-only — audio is VAD-cut and handed to the utterance sink; there is no
# ASR/LLM/TTS pipeline in this tree yet, so the reply track carries silence.
from server.realtime.webrtc_server import router as webrtc_router
app.include_router(webrtc_router)          # Provides /offer + /interrupt (paired mobile only)


# --- SHARED COGNITIVE LOOP HANDLER ---

async def _run_cognitive_loop(websocket: WebSocket, endpoint_name: str):
    """
    Shared handler for any endpoint that runs the full AI cognitive loop.
    BUG #7 FIX: both /ws/brain and /ws/dashboard/stream resolve here so
    the Unity client (which targets /ws/brain) and the React dashboard
    (which targets /ws/dashboard/stream) both work without change.
    """
    principal = await authenticate_personal_websocket(websocket)
    if principal is None:
        return
    if not await accept_personal_websocket(websocket, principal):
        return
    # Device-auth mode: the owner comes from the server-side device record, not
    # from ?user_id=. The legacy path keeps the historical fallback until
    # devices are paired (see device_auth.device_auth_enabled).
    user_id = principal.owner_id

    session_manager.add_surface("main", user_id, websocket)
    signal_bus.emit("session", {"endpoint": endpoint_name, "user_id": user_id}, "info")

    # The 24/7 autonomy daemon is the single proactive brain — this connection
    # only feeds it real brain state and handles control commands from the UI.
    daemon = get_daemon()

    try:
        while True:
            data = await websocket.receive_text()
            raw_input = json.loads(data)

            # ── Control commands from the client ─────────────────────────────
            if raw_input.get("type") == "command":
                await _handle_control_command(raw_input, daemon, websocket)
                continue

            # ── User-activity heartbeat (local chat pings the daemon) ────────
            if raw_input.get("type") == "user_activity":
                daemon.on_user_message(user_id)
                continue

            input_model = MultimodalInput(**raw_input)

            # Feed the real audio frame to Meeting Mode. When the client ships
            # 16-bit PCM (meeting_pcm_b64) the REAL webrtcvad + diarization path
            # runs; otherwise the energy heuristic is used (nothing fabricated).
            meeting = get_meeting_mode()
            audio_energy = raw_input.get("audio_energy", 0.0)
            vad_active   = raw_input.get("vad_active", False)
            meeting.report_audio_frame(
                audio_energy,
                vad_active,
                pcm_b64=raw_input.get("meeting_pcm_b64"),
                sample_rate=int(raw_input.get("meeting_sample_rate") or 16000),
            )

            # User spoke → reset proactive silence timers in the daemon
            daemon.on_user_message(user_id)

            # Meeting Mode gate (Track B): in a shared space only the primary
            # speaker's direct address (or their follow-up window) earns a reply;
            # ambient chatter is observed, never answered.
            if not meeting.should_respond(
                input_model.text or "",
                priority_level=1,
                speaker_id=meeting.current_speaker_id,
            ):
                await websocket.send_text(json.dumps({
                    "type": "ambient.suppressed",
                    "reason": "meeting_mode",
                    "speaker_id": meeting.current_speaker_id,
                    "timestamp": time.time(),
                }))
                continue

            # Stream tokens as they're generated so she "speaks" in real time.
            async def _stream_token(token: str) -> None:
                await websocket.send_text(json.dumps({
                    "type": "text.stream",
                    "chunk": token,
                    "timestamp": time.time(),
                }))

            # One brain per user for the whole process: a concurrent phone turn
            # and this dashboard turn share the same cognitive session (turns
            # are serialized by the coordinator), instead of racing two brains.
            output, brain_state = await cognitive_sessions.process_turn(
                user_id,
                input_model,
                on_token=_stream_token,
            )

            # B4: label the reply with the REAL diarized speaker it is addressed
            # to (None when Meeting Mode is off / nothing has been diarized) so
            # the client can attribute — and spatially render — the reply.
            target = meeting.get_reply_target()

            # Final complete reply — the chat surfaces consume this.
            await websocket.send_text(json.dumps({
                "type": "ai_response",
                "text": output.text,
                "expression": output.expression,
                "gestures": output.gestures,
                "thought": output.thought,
                "meta": output.meta,
                "target_speaker_id": target["speaker_id"],
                "target_speaker_slot": target["slot"],
                "speaker_count": target["count"],
                "timestamp": time.time(),
            }))

            # Visible inner life: broadcast her private thought so surfaces can
            # show she's thinking (thought ticker / brain monitor).
            if output.thought:
                await session_manager.broadcast({
                    "type": "inner_thought",
                    "thought": output.thought,
                    "timestamp": time.time(),
                })

            await session_manager.broadcast_state(user_id, brain_state)
            signal_bus.emit("response", {"user_id": user_id}, "info")

            # Avatar motion bridge (AI Girl 2 §"AVATAR RENDERER"): broadcast the
            # real trait-engine avatar floats (Smile, HeadTilt, EyeFocus,
            # Posture, BlinkRate, MicroMovement) after every turn so the Unity
            # avatar + any web embodiment consume the same live motion state.
            # These are measured values from this turn — never synthetic.
            try:
                _te = (brain_state.synoptic or {}).get("trait_engine") or {}
                if _te.get("avatar"):
                    await session_manager.broadcast({
                        "type": "avatar.update",
                        "avatar": _te["avatar"],
                        "mode": _te.get("mode"),
                        "traits": [t["id"] for t in (_te.get("active_traits") or [])],
                        "voice": _te.get("voice"),
                        "ui": _te.get("ui"),
                        "timestamp": time.time(),
                    })
            except Exception:
                pass

            # Real event log: emit a REAL telemetry signal carrying the actual
            # brain state + turn measurements (no synthetic data). The
            # dashboard's Event Log renders these as live events — trust /
            # emotion / reply length are measured this turn, never fabricated.
            try:
                _bs = brain_state
                await admin_signal_bus.emit_signal(
                    "telemetry", "info", "BRAIN",
                    {
                        "title": f"Turn complete — trust {_bs.trust:.2f} · {_bs.emotion}",
                        "trust": round(_bs.trust, 2),
                        "valence": round(_bs.valence, 2),
                        "emotion": _bs.emotion,
                        "reply_chars": len(output.text),
                    },
                )
            except Exception:
                pass

            # Synoptics v2 frame (Agents Swarm Visualize §238): predictive
            # ghost layer + anomaly overlay streamed to /ws/synoptics clients.
            try:
                from server.routers.synoptics_ws import (
                    build_synoptics_frame,
                    broadcast_synoptics_frame,
                )
                frame = build_synoptics_frame(brain_state.synoptic)
                await broadcast_synoptics_frame(frame)
            except Exception:
                pass

            # Feed the real brain state to the 24/7 autonomy daemon
            daemon.record_snapshot(brain_state)

            # Non-blocking knowledge-gap detection after each real response
            if input_model.text and output.text:
                try:
                    if not _gap_detect_lock.locked():
                        learner = BackgroundLearner(AutonomyStore())
                        asyncio.create_task(
                            _run_gap_detection(learner, input_model.text, output.text)
                        )
                except Exception as exc:
                    logger.debug(f"Gap detection skip: {exc}")

    except WebSocketDisconnect:
        session_manager.remove_surface("main", user_id, websocket)
        logger.info(f"[{endpoint_name}] stream closed for {user_id}")
    except Exception as e:
        session_manager.remove_surface("main", user_id, websocket)
        logger.error(f"[{endpoint_name}] error in cognitive loop: {e}")
        try:
            await websocket.close()
        except Exception:
            pass


async def _run_gap_detection(learner, user_text: str, response_text: str):
    """Background gap detection, serialized so rapid messages don't stack LLM calls."""
    async with _gap_detect_lock:
        try:
            await learner.detect_and_queue_gaps(user_text, response_text)
        except Exception as exc:
            logger.debug(f"Gap detection task error: {exc}")


async def _handle_control_command(raw_input: dict, daemon, websocket: WebSocket):
    """Route UI control commands to the autonomy daemon."""
    action: str = raw_input.get("action") or ""
    plan_id = raw_input.get("plan_id", "")
    try:
        if action == "approve_plan":
            result = await daemon.approve_plan(plan_id)
        elif action == "reject_plan":
            result = await daemon.reject_plan(plan_id)
        elif action == "autonomy_enabled":
            result = daemon.set_enabled(bool(raw_input.get("enabled", True)))
        else:
            result = {"ok": False, "error": f"unknown action: {action}"}
        # build_control_ack echoes plan_id into plan.ack frames so the frontend's
        # live plan-status chip can update after approve/reject (the executor
        # result doesn't carry it). Pure helper — testable without server.main.
        from server.autonomy.daemon import build_control_ack
        await websocket.send_text(json.dumps(build_control_ack(action, plan_id, result)))
    except Exception as exc:
        logger.warning(f"Control command {action} failed: {exc}")


# --- WEBSOCKET ENDPOINTS ---

@app.websocket("/ws/dashboard/stream")
async def websocket_dashboard_stream(websocket: WebSocket):
    """React frontend cognitive loop.

    This is the ONLY registration for /ws/dashboard/stream. It previously
    duplicated the route mounted by server.routers.dashboard_ws (a 10 Hz swarm
    snapshot that never read incoming frames); Starlette matched that router
    first, so the full chat pipeline here was shadowed and web chat inputs were
    silently dropped. The swarm helpers still live in dashboard_ws.py (used by
    /ws/mobile/analytics) — only the duplicate mount was removed.
    """
    await _run_cognitive_loop(websocket, "dashboard/stream")


from server.systems.swarm.orchestrator import get_swarm_system
from server.systems.rag.obsidian_indexer import get_obsidian_indexer

@app.websocket("/api/security/stream")
async def security_stream_ws(websocket: WebSocket):
    """
    Dedicated endpoint for the Security Command Center.
    Continuously runs the security swarm in the background (every 2s)
    so the dashboard receives live telemetry regardless of user chat input.
    """
    principal = await authenticate_personal_websocket(websocket, "/api/security/stream")
    if principal is None:
        return
    if not await accept_personal_websocket(websocket, principal):
        return
    swarm = get_swarm_system()
    
    try:
        while True:
            # Poll security agents with empty input to scan background state
            security_context = await swarm.run_security_agents({"text": "", "metadata": {}})
            
            await websocket.send_json({
                "state_update": {
                    "security": security_context
                }
            })
            await asyncio.sleep(2.0)  # Realtime 2-second polling tick
    except WebSocketDisconnect:
        logger.info("Security dashboard stream disconnected")
    except Exception as e:
        logger.error(f"Security stream error: {e}")
        try:
            await websocket.close()
        except Exception:
            pass

# BUG #7 FIX: add /ws/brain alias so Unity client connects correctly
@app.websocket("/ws/brain")
async def websocket_brain(websocket: WebSocket):
    """Unity frontend cognitive loop (alias for /ws/dashboard/stream)."""
    await _run_cognitive_loop(websocket, "brain")


# BUG #2 FIX: add /ws/mobile endpoint for Flutter conversation chat
@app.websocket("/ws/mobile")
async def websocket_mobile_chat(websocket: WebSocket):
    """
    Flutter mobile chat endpoint.
    Accepts the mobile-specific protocol (§7.5):
      Input:  { type, content, mode, image? }
      Output: { type: 'ai_response', text, emotion, timestamp }
               { type: 'text.stream', chunk }
               { type: 'state.update', state }
    """
    principal = await authenticate_personal_websocket(websocket, "/ws/mobile")
    if principal is None:
        return
    if not await accept_personal_websocket(websocket, principal):
        return
    # The phone's owner is resolved server-side once it is paired.
    user_id = principal.owner_id
    session_manager.add_surface("mobile", user_id, websocket)
    signal_bus.emit("session", {"endpoint": "mobile", "user_id": user_id}, "info")

    # Mobile gateway telemetry: this chat socket counts as a connected client.
    # Group channels by the AUTHENTICATED device id once paired, so a client
    # cannot claim another phone's telemetry by inventing a client_id.
    _mobile_client_key = None
    try:
        from server.systems.agent.mobile_gateway_agent import get_mobile_gateway
        _mobile_gateway = get_mobile_gateway()
        _mobile_client_key = _mobile_gateway.on_client_connected(
            principal.device_id or None
        )
    except Exception:
        _mobile_gateway = None

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)

            # Protocol v2 ACK: the mobile client retries reliable messages
            # (id + requires_ack) until we echo the id back. ACK before
            # processing so a slow turn never looks like a lost message.
            msg_id = message.get("id")
            if msg_id:
                await websocket.send_text(json.dumps({"type": "ack", "id": msg_id}))

            if message.get("type") == "interrupt":
                # Client-side barge-in: acknowledge and reset
                await websocket.send_text(json.dumps({"type": "interrupt_ack"}))
                if _mobile_gateway:
                    _mobile_gateway.on_command("interrupt")
                continue

            # Map mobile protocol → MultimodalInput
            input_model = MultimodalInput(
                text=message.get("content"),
                image_b64=message.get("image"),
                metadata={"mode": message.get("mode", "voice")}
            )

            # Same per-user cognitive session as /ws/brain — a phone turn and a
            # computer turn for the same person never run two brains.
            output, brain_state = await cognitive_sessions.process_turn(
                user_id,
                input_model,
            )

            # Feed the 24/7 autonomy daemon (silence reset + brain snapshot)
            get_daemon().on_user_message(user_id)
            get_daemon().record_snapshot(brain_state)

            # Reply in mobile protocol format
            await websocket.send_text(json.dumps({
                "type": "ai_response",
                "text": output.text,
                "emotion": output.expression,
                "timestamp": int(time.time())
            }))

            # Push brain state to EVERY connected surface (all mobile phones,
            # the React dashboard, Unity) through the shared session manager,
            # so every client's orb/ring reacts to state frames produced from
            # ANY surface — not just this phone's own replies. The requesting
            # socket still receives its own frame (it's registered under the
            # "mobile" surface). broadcast_state uses model_dump(mode="json")
            # (BUG #5 FIX) so the datetime timestamp serializes to an ISO string.
            await session_manager.broadcast_state(user_id, brain_state)

            # Broadcast kill-switch / feature-flag state so mobile stays in sync.
            try:
                from server.systems.kill_switches import get_kill_switches
                await session_manager.broadcast(get_kill_switches().to_broadcast_frame())
            except Exception:
                pass

            # Real event log: real mobile turn telemetry (no synthetic data).
            try:
                _bs = brain_state
                await admin_signal_bus.emit_signal(
                    "telemetry", "info", "MOBILE",
                    {
                        "title": f"Mobile turn — trust {_bs.trust:.2f} · {_bs.emotion}",
                        "trust": round(_bs.trust, 2),
                        "emotion": _bs.emotion,
                        "reply_chars": len(output.text),
                    },
                )
            except Exception:
                pass

            # Visible inner life: broadcast her private thought so ALL surfaces
            # (phones, dashboard, Unity) see she's thinking — matches the shared
            # cognitive loop, so thoughts flow from any surface, not just the
            # requesting socket. The requesting phone still receives its own
            # (it's registered under the "mobile" surface).
            if output.thought:
                await session_manager.broadcast({
                    "type": "inner_thought",
                    "thought": output.thought,
                    "timestamp": time.time(),
                })

    except WebSocketDisconnect:
        session_manager.remove_surface("mobile", user_id, websocket)
        if _mobile_gateway:
            _mobile_gateway.on_client_disconnected(_mobile_client_key)
        logger.info(f"Mobile chat disconnected for {user_id}")
    except Exception as e:
        session_manager.remove_surface("mobile", user_id, websocket)
        if _mobile_gateway:
            _mobile_gateway.on_client_disconnected(_mobile_client_key)
        logger.error(f"Mobile chat error: {e}")
        try:
            await websocket.close()
        except Exception:
            pass


@app.websocket("/ws/mobile/control")
async def websocket_mobile_control(websocket: WebSocket):
    principal = await authenticate_personal_websocket(websocket, "/ws/mobile/control")
    if principal is None:
        return
    if not await accept_personal_websocket(websocket, principal):
        return
    session_id = str(uuid4())
    logger.info(f"Mobile Control connected: {session_id}")

    # Mobile gateway telemetry: control sockets count as connected clients.
    # The authenticated device id keeps one phone counted as one device.
    _control_client_key = None
    try:
        from server.systems.agent.mobile_gateway_agent import get_mobile_gateway
        _control_gateway = get_mobile_gateway()
        _control_client_key = _control_gateway.on_client_connected(
            principal.device_id or None
        )
    except Exception:
        _control_gateway = None

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            msg_type = message.get("type")

            # ── Protocol v2 ACK: any message carrying an id is acknowledged ──
            # so the mobile AckOutbox stops retrying it. Pings (no id) get
            # the dedicated pong below instead.
            msg_id = message.get("id")
            if msg_id:
                await websocket.send_text(json.dumps({
                    "type": "ack",
                    "id": msg_id,
                    "status": "ok",
                }))

            # ── Ping → Pong (ConnectionMonitor heartbeat) ────────────────────
            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue

            # ── Phone-reported device metrics ───────────────────────────────
            # The mobile app pushes battery / CPU / memory / model every few
            # seconds. This is telemetry, not a command — it bypasses the
            # authority gate and is stored on the gateway agent so the System
            # Health tab's Mobile App panel can show the phone's own perf.
            if msg_type == "device_metrics":
                if _control_gateway:
                    _control_gateway.record_device_metrics(
                        message.get("device") or {},
                        message.get("ts") or 0.0,
                        _control_client_key,
                    )
                continue

            if msg_type == "command":
                action = message.get("action") or ""

                # ── Zero-Interference gate (see mobile_authority.py) ─────────
                # Mobile is the CONTROL layer, not the authority layer: it may
                # send interrupts / chat / pings, but never wipe memory or
                # rewrite the persona. Rejected commands get a command_denied
                # frame so the phone UI can explain the refusal.
                if not is_mobile_allowed(action):
                    logger.warning(
                        f"[Mobile Authority] denied {action!r} from mobile control channel"
                    )
                    await websocket.send_text(json.dumps(denied_frame(action)))
                    continue

                logger.info(f"Command received (allowed): {action}")
                if _control_gateway:
                    _control_gateway.on_command(action)

    except WebSocketDisconnect:
        if _control_gateway:
            _control_gateway.on_client_disconnected(_control_client_key)
        logger.info(f"Mobile Control disconnected: {session_id}")


@app.websocket("/ws/brain_metrics")
async def websocket_brain_metrics(websocket: WebSocket):
    principal = await authenticate_personal_websocket(websocket, "/ws/brain_metrics")
    if principal is None:
        return
    if not await accept_personal_websocket(websocket, principal):
        return
    user_id = principal.owner_id
    session_manager.add_surface("dashboard", user_id, websocket)
    logger.info(f"Dashboard metrics link established for {user_id}")
    
    # Register socket with Admin Signal Bus. Only REAL signals from the
    # cognitive loop / observability layer are broadcast — no synthetic
    # test signals are injected on connect (the dashboard shows live data only).
    if websocket not in admin_signal_bus._connected_sockets:
        admin_signal_bus._connected_sockets.append(websocket)

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            # ── AUTHORITY LAYER (laptop dashboard only) ────────────────────
            # The zero-interference contract (resolved in mobile_authority.py)
            # says mobile = control layer, laptop = authority layer. This is
            # the laptop's channel: destructive / identity-mutating commands
            # are EXECUTED here (and denied on /ws/mobile/control), then
            # broadcast so every surface syncs to the new mode.
            if message.get("type") == "command":
                action = str(message.get("action") or "")
                ack, broadcast_frame = await execute_authority_command(action, message)
                await websocket.send_text(json.dumps(ack))
                if broadcast_frame:
                    await session_manager.broadcast(broadcast_frame)
                continue

    except WebSocketDisconnect:
        session_manager.remove_surface("dashboard", user_id, websocket)
        if websocket in admin_signal_bus._connected_sockets:
            admin_signal_bus._connected_sockets.remove(websocket)
        logger.info(f"Dashboard metrics link closed for {user_id}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)