import logging
from typing import Dict, List, Set
from fastapi import WebSocket

logger = logging.getLogger("aariya.session_manager")


class SessionManager:
    def __init__(self):
        # surface_type -> user_id -> list of sockets
        self.surfaces: Dict[str, Dict[str, List[WebSocket]]] = {
            "main": {},
            "dashboard": {},
            "mobile": {}
        }
        # Dedicated channel registries (one-way streams, not keyed by user).
        self.analytics_clients: Set[WebSocket] = set()
        self.mobile_controls: Set[WebSocket] = set()
        self.dashboard_clients: Set[WebSocket] = set()

    def add_surface(self, stype: str, user_id: str, ws: WebSocket):
        if stype not in self.surfaces:
            self.surfaces[stype] = {}
        if user_id not in self.surfaces[stype]:
            self.surfaces[stype][user_id] = []
        self.surfaces[stype][user_id].append(ws)

    def remove_surface(self, stype: str, user_id: str, ws: WebSocket):
        try:
            if stype in self.surfaces and user_id in self.surfaces[stype]:
                self.surfaces[stype][user_id].remove(ws)
        except ValueError:
            pass  # already removed

    async def broadcast(self, message: dict):
        """
        BUG #4 FIX: wrap each send in try/except so a single disconnected
        socket does not abort the entire broadcast loop for all other clients.
        """
        dead: list[tuple[str, str, WebSocket]] = []
        for stype in self.surfaces:
            for uid in self.surfaces[stype]:
                for ws in list(self.surfaces[stype][uid]):
                    try:
                        await ws.send_json(message)
                    except Exception as e:
                        logger.warning(
                            f"broadcast: removing dead socket [{stype}/{uid}]: {e}"
                        )
                        dead.append((stype, uid, ws))

        for stype, uid, ws in dead:
            self.remove_surface(stype, uid, ws)

    async def broadcast_state(self, user_id: str, state):
        """
        BUG #4 FIX: same exception isolation per-socket.
        BUG #5 FIX: state.dict() was removed in Pydantic v2 — use model_dump().
        mode="json" serializes BrainState.timestamp (datetime) to an ISO string,
        so send_json can't choke on it (was silently dropping/removing sockets).
        """
        payload = {"type": "state.update", "state": state.model_dump(mode="json")}
        dead: list[tuple[str, WebSocket]] = []
        for stype in self.surfaces:
            if user_id in self.surfaces[stype]:
                for ws in list(self.surfaces[stype][user_id]):
                    try:
                        await ws.send_json(payload)
                    except Exception as e:
                        logger.warning(
                            f"broadcast_state: removing dead socket [{stype}/{user_id}]: {e}"
                        )
                        dead.append((stype, ws))

        for stype, ws in dead:
            self.remove_surface(stype, user_id, ws)

    async def broadcast_analytics(self, message: dict):
        """Push a message to all /ws/mobile/analytics clients.

        Used by the agent watcher to push `agent_discovered` alerts to the
        mobile analytics stream. Per-socket exception isolation so a single
        dead socket doesn't abort the loop.
        """
        dead: list[WebSocket] = []
        for ws in list(self.analytics_clients):
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.warning(
                    f"broadcast_analytics: removing dead socket: {e}"
                )
                dead.append(ws)

        for ws in dead:
            self.analytics_clients.discard(ws)


# ── Module-level singleton ────────────────────────────────────────────────────
# Routers and the agent watcher import `manager` from here so they share the
# same socket registries. FastAPI endpoints in main.py use this instance too.
manager = SessionManager()