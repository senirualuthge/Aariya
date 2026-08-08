"""
Mobile Control WebSocket — /ws/mobile/control

Routes:
  /ws/mobile/control  → accepts remote_input messages and command overrides.

Supported message types:
  { "type": "remote_input", "text": "..." }     → forwards to primary brain WS
  { "type": "command", "action": "wipe_memory" }  → wipes memory hierarchy
  { "type": "command", "action": "override_mode", "mode": "focus|relax|..." }
  { "type": "interrupt" }                         → broadcasts interrupt to primary
"""
import json
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from server.infrastructure.observability import logger
from server.infrastructure.session_manager import manager
from server.systems.agent.mobile_gateway_agent import get_mobile_gateway
from server.systems.security.mobile_authority import is_mobile_allowed, denied_frame

router = APIRouter()


async def _handle_command(action: str, msg: dict) -> dict | None:
    """Execute direct override commands from mobile without round-tripping brain.

    Zero-Interference gate: destructive / identity-mutating actions are
    rejected — mobile is the CONTROL layer, the laptop dashboard is the
    AUTHORITY layer. See server/systems/security/mobile_authority.py.

    Returns a `command_denied` frame when the action is blocked, else None.
    """
    if not is_mobile_allowed(action):
        logger.warning(f"[Mobile Authority] denied {action!r} from mobile control channel")
        return denied_frame(action)

    if action == "wipe_memory":
        try:
            from server.systems.memory_hierarchy import get_memory_hierarchy  # type: ignore
            get_memory_hierarchy().clear_session_memory("user_default")
            logger.info("Mobile commanded: memory wipe executed")
        except Exception as exc:
            logger.error(f"wipe_memory failed: {exc}")

    elif action == "override_mode":
        mode = msg.get("mode", "")
        logger.info(f"Mobile commanded: override_mode \u2192 {mode!r}")
        # Broadcast via /ws/brain_metrics — the channel the GUI actually listens on
        try:
            from server.routers.metrics_ws import broadcast_brain_metrics
            await broadcast_brain_metrics({"type": "override_mode", "mode": mode})
        except Exception as exc:
            logger.error(f"override_mode broadcast failed: {exc}")

    elif action == "ping":
        # Keepalive sent as a command envelope — silently ignore (no pong needed here,
        # the top-level ping handler at the receive loop already handles the proper format)
        pass

    else:
        logger.info(f"Mobile sent unknown command action: {action!r}")


@router.websocket("/ws/mobile/control")
async def mobile_control(websocket: WebSocket) -> None:
    await websocket.accept()
    manager.mobile_controls.add(websocket)
    gateway = get_mobile_gateway()
    gateway.on_client_connected()
    logger.info("Mobile Control client connected")

    try:
        while True:
            t0 = time.monotonic()
            raw = await websocket.receive_text()
            latency_ms = (time.monotonic() - t0) * 1000

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")
            gateway.on_command(msg_type)
            gateway.record_latency(latency_ms)

            # ── ACK if message carries an ID ──────────────────────────────────
            msg_id = msg.get("id")
            if msg_id:
                await websocket.send_text(json.dumps({"type": "ack", "id": msg_id}))

            # ── Ping → Pong (ConnectionMonitor heartbeat) ─────────────────────
            if msg_type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue

            # ── Interrupt ─────────────────────────────────────────────────────
            if msg_type == "interrupt":
                if manager.primary:
                    try:
                        await manager.primary.send_text(json.dumps({"type": "interrupt"}))
                    except Exception as exc:
                        logger.error(f"Interrupt forward failed: {exc}")
                continue

            # ── Remote text input → forward to brain ──────────────────────────
            if msg_type in ("remote_input", "input.multimodal"):
                if manager.primary:
                    try:
                        await manager.primary.send_text(json.dumps({
                            "type": "remote_input",
                            "payload": msg,
                        }))
                    except Exception as exc:
                        logger.error(f"Remote input forward failed: {exc}")
                continue

            # ── Direct command overrides ───────────────────────────────────────
            if msg_type == "command":
                action = msg.get("action", "")
                if action:
                    denied = await _handle_command(action, msg)
                    if denied:
                        await websocket.send_text(json.dumps(denied))
                continue

    except WebSocketDisconnect:
        logger.info("Mobile Control client disconnected")
    except Exception as exc:
        logger.error(f"Mobile Control WebSocket error: {exc}")
    finally:
        manager.mobile_controls.discard(websocket)
        gateway.on_client_disconnected()
