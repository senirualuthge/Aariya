"""
agent_watcher.py
────────────────
Three-trigger orchestrator for the Agent Auto-Discovery system:

  TRIGGER 1  Startup         — runs on FastAPI lifespan startup
  TRIGGER 2  File watch      — watchdog monitors .py files, debounced 1.5s
  TRIGGER 3  Manual scan     — call trigger_manual_scan() from CLI or API

On every trigger:
  scanner.scan() → registry.update_from_scan() → broadcast diff to all WebSocket clients

Install watchdog:
  pip install watchdog
"""

from __future__ import annotations
import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional, Any, Union

from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent
from watchdog.observers import Observer

from .agent_scanner import AgentScanner
from .agent_registry import get_registry

logger = logging.getLogger("aariya.agent_watcher")

# Debounce window — prevent rapid re-scans while you're actively coding
DEBOUNCE_SECONDS = 1.5


# ── Broadcaster ──────────────────────────────────────────────────────────────

class AgentBroadcaster:
    """
    Holds a set of async WebSocket send-callbacks.
    The FastAPI router registers/deregisters clients here.
    """

    def __init__(self):
        self._clients: set[Callable] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def register(self, send_fn: Callable):
        self._clients.add(send_fn)
        logger.debug(f"[Broadcaster] Client registered. Total: {len(self._clients)}")

    def unregister(self, send_fn: Callable):
        self._clients.discard(send_fn)
        logger.debug(f"[Broadcaster] Client removed. Total: {len(self._clients)}")

    def broadcast(self, message: dict):
        """Thread-safe broadcast — safe to call from watchdog threads."""
        if not self._clients or not self._loop:
            return
        payload = json.dumps(message)
        for send_fn in list(self._clients):
            try:
                asyncio.run_coroutine_threadsafe(send_fn(payload), self._loop)
            except Exception as e:
                logger.warning(f"[Broadcaster] Failed to send to client: {e}")
                self._clients.discard(send_fn)


# ── File event handler ────────────────────────────────────────────────────────

class _PythonFileHandler(FileSystemEventHandler):
    def __init__(self, on_change: Callable):
        super().__init__()
        self._on_change = on_change
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    def _debounced_trigger(self, path: str):
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(DEBOUNCE_SECONDS, self._on_change, args=[path])
            self._timer.daemon = True
            self._timer.start()

    def on_modified(self, event):
        if not event.is_directory and str(event.src_path).endswith(".py"):
            self._debounced_trigger(str(event.src_path))

    def on_created(self, event):
        if not event.is_directory and str(event.src_path).endswith(".py"):
            self._debounced_trigger(str(event.src_path))


# ── Main watcher ──────────────────────────────────────────────────────────────

class AgentWatcher:
    """
    Central coordinator. One instance lives for the lifetime of the server.

    Usage (in FastAPI lifespan):

        watcher = AgentWatcher(root=".")
        broadcaster = watcher.broadcaster

        @asynccontextmanager
        async def lifespan(app):
            watcher.start(asyncio.get_event_loop())
            yield
            watcher.stop()
    """

    def __init__(self, root: Union[str, Path] = "."):
        self.root = Path(root).resolve()
        self.scanner = AgentScanner(root=self.root)
        self.registry = get_registry()
        self.broadcaster = AgentBroadcaster()
        self._observer: Optional[Any] = None
        self._running = False

    # ── Public ───────────────────────────────────────────────────────────────

    def start(self, loop: asyncio.AbstractEventLoop):
        """Call from FastAPI lifespan startup."""
        self.broadcaster.set_loop(loop)
        self._running = True

        # Trigger 1: Startup scan
        logger.info("[AgentWatcher] Running startup scan...")
        self._run_scan(trigger="startup")

        # Trigger 2: File watcher
        handler = _PythonFileHandler(
            on_change=lambda path: self._run_scan(trigger="file_watch", changed_file=path)
        )
        self._observer = Observer()
        self._observer.schedule(handler, str(self.root), recursive=True)
        self._observer.start()
        logger.info(f"[AgentWatcher] Watching {self.root} for .py changes")

    def stop(self):
        self._running = False
        if self._observer:
            self._observer.stop()
            self._observer.join()
        logger.info("[AgentWatcher] Stopped")

    def trigger_manual_scan(self) -> dict:
        """Trigger 3: Manual scan. Returns diff synchronously."""
        return self._run_scan(trigger="manual")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run_scan(self, trigger: str, changed_file: Optional[str] = None) -> dict:
        start = time.monotonic()
        try:
            results = self.scanner.scan()
            diff = self.registry.update_from_scan(results)
            elapsed = round((time.monotonic() - start) * 1000)

            has_changes = any(diff[k] for k in ("new", "updated", "removed"))

            payload = {
                "type": "agent_registry_update",
                "trigger": trigger,
                "changed_file": changed_file,
                "elapsed_ms": elapsed,
                "diff": diff,
                "stats": self.registry.stats(),
                "all_agents": self.registry.get_active_agents(),
            }

            if has_changes or trigger == "startup":
                self.broadcaster.broadcast(payload)
                n_new = len(diff["new"])
                n_upd = len(diff["updated"])
                n_rem = len(diff["removed"])
                logger.info(
                    f"[AgentWatcher] scan={trigger} +{n_new}new ~{n_upd}updated -{n_rem}removed ({elapsed}ms)"
                )

                # ── Push new agents instantly to mobile analytics clients ──
                if diff["new"] or diff["updated"]:
                    try:
                        from server.infrastructure.session_manager import manager  # noqa
                        alert = {
                            "type": "agent_discovered",
                            "agents": [
                                {
                                    "name":       a.get("name", "Unknown"),
                                    "kind":       a.get("kind", "unknown"),
                                    "status":     a.get("status", "new"),
                                    "detection":  a.get("detection", ""),
                                    "first_seen": a.get("first_seen", ""),
                                }
                                for a in (diff["new"] + diff["updated"])
                            ],
                            "agents_active": len(self.registry.get_active_agents()),
                        }
                        if self.broadcaster._loop:
                            asyncio.run_coroutine_threadsafe(
                                manager.broadcast_analytics(alert), self.broadcaster._loop
                            )
                    except Exception as _push_err:
                        logger.debug(f"[AgentWatcher] mobile push skipped: {_push_err}")

            return diff
        except Exception as e:
            logger.error(f"[AgentWatcher] Scan failed ({trigger}): {e}", exc_info=True)
            return {"new": [], "updated": [], "removed": [], "error": str(e)}


# ── Singleton ─────────────────────────────────────────────────────────────────

_watcher: Optional[AgentWatcher] = None

def get_watcher(root: Union[str, Path] = ".") -> AgentWatcher:
    global _watcher
    if _watcher is None:
        _watcher = AgentWatcher(root=root)
    return _watcher
