"""Coordinates one logical Aariya brain per personal user session.

All connected surfaces for the same user share one BrainV2 instance.
Cognitive turns are serialized per user to prevent concurrent mutation
of personality, emotional state, narrative state and other live cognition.

Scope of this first version (single process only):

  * The registry lives in this Python process. Running multiple Uvicorn
    workers would give each worker its own coordinator and brain, so keep ONE
    backend worker until distributed coordination (e.g. Redis-backed sessions
    with recovery and synchronization) exists.
  * Sessions are in memory. A server restart rebuilds each brain from the
    existing persistent memory / personality stores on the first turn; it does
    not automatically restore every temporary cognitive subsystem.
  * Idle sessions are evicted (default TTL 30 min, see
    AARIYA_SESSION_IDLE_TTL_SECONDS) so a long-lived process does not hold a
    brain per user forever. Eviction uses the same rebuild path as a restart;
    a session with a turn in flight is never evicted.

This module does not remove or replace the existing memory and personality
systems — it only controls how many BrainV2 instances exist per user.
"""

import asyncio
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Optional, Tuple

from server.protocol import BrainState, MultimodalInput, MultimodalOutput
from server.systems.brain_v2 import BrainV2

logger = logging.getLogger("aariya.cognitive_sessions")


class MultiWorkerRuntimeError(RuntimeError):
    """Raised at startup when the process is configured for >1 server worker."""


# uvicorn and gunicorn both honour WEB_CONCURRENCY; UVICORN_WORKERS is accepted
# here as the explicit uvicorn spelling some deployments use.
_WORKER_ENV_VARS = ("WEB_CONCURRENCY", "UVICORN_WORKERS")


def requested_worker_count(
    environ: Optional[dict] = None,
    argv: Optional[List[str]] = None,
) -> Tuple[int, Optional[str]]:
    """Return (requested worker count, source label).

    Detects the worker count a launcher ASKED for, from the environment and the
    command line of this process. Returns ``(1, None)`` when nothing asks for
    more than one worker (the default for ``python server/main.py`` and for
    ``python -m uvicorn server.main:app`` without flags).
    """
    env = os.environ if environ is None else environ
    args = list(sys.argv[1:] if argv is None else argv)

    best = 1
    source: Optional[str] = None

    for var in _WORKER_ENV_VARS:
        raw = env.get(var)
        if not raw:
            continue
        try:
            count = int(str(raw).strip())
        except ValueError:
            continue
        if count > best:
            best, source = count, f"{var}={raw}"

    # Flags: --workers N, --workers=N, -w N, -wN (uvicorn + gunicorn spellings).
    i = 0
    while i < len(args):
        arg = args[i]
        candidate: Optional[str] = None
        if arg == "--workers" or arg == "-w":
            if i + 1 < len(args):
                candidate = args[i + 1]
                i += 1
        elif arg.startswith("--workers="):
            candidate = arg.split("=", 1)[1]
        elif arg.startswith("-w") and len(arg) > 2 and not arg.startswith("--"):
            candidate = arg[2:]
        if candidate is not None:
            try:
                count = int(candidate)
            except ValueError:
                count = 0
            if count > best:
                best, source = count, f"{' '.join(args)}"
        i += 1

    return best, source


def assert_single_worker(
    environ: Optional[dict] = None,
    argv: Optional[List[str]] = None,
) -> None:
    """Refuse to boot when more than one server worker is configured.

    Cognitive sessions live in this process, so each Uvicorn/gunicorn worker
    would silently get its own coordinator and its own brain for the same user
    — the exact split-brain state the coordinator exists to prevent. Until a
    Redis-backed distributed coordinator exists, one worker is the only safe
    configuration, so a multi-worker launch fails loudly at startup instead of
    starting in a subtly wrong mode.

    Call this from the app lifespan; the exception aborts startup and Uvicorn
    exits non-zero.
    """
    workers, source = requested_worker_count(environ=environ, argv=argv)
    if workers > 1:
        raise MultiWorkerRuntimeError(
            f"Aariya's cognitive sessions are single-process, but {source} "
            f"requests {workers} server workers. Each worker would build its "
            f"own coordinator and its own brain for the same user. Run ONE "
            f"worker (omit --workers / set WEB_CONCURRENCY=1) until the "
            f"Redis-backed distributed coordinator is implemented."
        )
    logger.info("Cognitive sessions: single-process mode (one worker) enforced")


@dataclass
class CognitiveSession:
    user_id: str
    brain: BrainV2
    turn_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Monotonic timestamp of the last use; drives idle-session eviction.
    last_used: float = field(default_factory=time.monotonic)
    # Monotonic start of the currently running turn (None when idle); exposed as
    # turn_elapsed_seconds on the System Health endpoint.
    turn_started: Optional[float] = None
    # Turns currently waiting for this user's lock (diagnostic for contention).
    waiting_turns: int = 0


class CognitiveSessionCoordinator:
    def __init__(self):
        self._sessions: dict[str, CognitiveSession] = {}
        self._registry_lock = asyncio.Lock()
        # Counters exposed through the System Health endpoint.
        self._idle_evictions = 0
        self._lock_waits = 0
        self._lock_wait_seconds = 0.0

    async def get_session(self, user_id: str) -> CognitiveSession:
        if not user_id:
            raise ValueError("Authenticated user_id is required")
        session = self._sessions.get(user_id)
        if session is not None:
            return session
        async with self._registry_lock:
            session = self._sessions.get(user_id)
            if session is None:
                logger.info("Creating cognitive session for user %s", user_id)
                session = CognitiveSession(
                    user_id=user_id,
                    brain=BrainV2(user_id),
                )
                self._sessions[user_id] = session
            return session

    async def process_turn(
        self,
        user_id: str,
        input_data: MultimodalInput,
        on_token: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> tuple[MultimodalOutput, BrainState]:
        session = await self.get_session(user_id)
        # Touch before queueing for the lock so a waiting turn cannot be
        # evicted while it is about to run.
        session.last_used = time.monotonic()

        # BrainV2 mutates live state during processing.
        # Serialize turns belonging to the same personal session.
        queued = session.turn_lock.locked()
        queued_at = time.monotonic()
        if queued:
            session.waiting_turns += 1
        try:
            async with session.turn_lock:
                session.turn_started = time.monotonic()
                if queued:
                    self._lock_waits += 1
                    self._lock_wait_seconds += time.monotonic() - queued_at
                try:
                    output = await session.brain.process(
                        input_data,
                        on_token=on_token,
                    )
                    # Snapshot BEFORE releasing the lock. The caller broadcasts
                    # this state after the lock is free, and the next queued
                    # turn (often another surface) mutates the live BrainState
                    # in place — returning the live object would let that turn
                    # overwrite the frame this handler is still preparing.
                    state = session.brain.get_state().model_copy(deep=True)
                    return output, state
                finally:
                    session.turn_started = None
                    session.last_used = time.monotonic()
        finally:
            if queued:
                session.waiting_turns -= 1

    async def get_state(self, user_id: str) -> BrainState:
        session = await self.get_session(user_id)
        session.last_used = time.monotonic()
        queued = session.turn_lock.locked()
        queued_at = time.monotonic()
        if queued:
            session.waiting_turns += 1
        try:
            async with session.turn_lock:
                if queued:
                    self._lock_waits += 1
                    self._lock_wait_seconds += time.monotonic() - queued_at
                # Same reasoning as process_turn: never hand out the live state.
                return session.brain.get_state().model_copy(deep=True)
        finally:
            if queued:
                session.waiting_turns -= 1

    async def has_session(self, user_id: str) -> bool:
        return user_id in self._sessions

    async def evict_idle_sessions(self, idle_seconds: float) -> List[str]:
        """Drop sessions unused for ``idle_seconds``; return the evicted ids.

        A session mid-turn is never evicted (its lock is held): killing live
        cognition would lose state the turn is still mutating. Evicted brains
        are rebuilt from the persistent memory / personality stores on the
        user's next turn — the same recovery path a restart takes.
        """
        if idle_seconds <= 0:
            return []
        cutoff = time.monotonic() - idle_seconds
        evicted: List[str] = []
        async with self._registry_lock:
            for user_id, session in list(self._sessions.items()):
                if session.turn_lock.locked():
                    continue
                if session.last_used <= cutoff:
                    del self._sessions[user_id]
                    evicted.append(user_id)
            self._idle_evictions += len(evicted)
        if evicted:
            logger.info(
                "Evicted %d idle cognitive session(s): %s",
                len(evicted),
                ", ".join(evicted),
            )
        return evicted

    def stats(self) -> dict:
        """Live coordination counters for the System Health endpoint.

        ``users`` carries one row per in-memory session so an operator can see
        WHICH user's brain is busy or idle, not just the aggregate counts:
        idle age, whether the turn lock is held, how long the current turn has
        been running, and how many turns are queued behind it.
        """
        now = time.monotonic()
        users = []
        for user_id, session in list(self._sessions.items()):
            in_flight = session.turn_lock.locked()
            users.append({
                "user_id": user_id,
                "idle_seconds": round(max(0.0, now - session.last_used), 1),
                "turn_in_flight": in_flight,
                "turn_elapsed_seconds": (
                    round(max(0.0, now - session.turn_started), 1)
                    if in_flight and session.turn_started is not None
                    else None
                ),
                "waiting_turns": int(session.waiting_turns),
            })
        # Most recently used first: the rows an operator usually wants.
        users.sort(key=lambda row: row["idle_seconds"])
        return {
            "sessions": len(self._sessions),
            "idle_evictions": self._idle_evictions,
            "lock_waits": self._lock_waits,
            "lock_wait_seconds_total": round(self._lock_wait_seconds, 3),
            "users": users,
        }

    async def eviction_loop(
        self,
        idle_seconds: float,
        interval_seconds: float,
    ) -> None:
        """Periodically evict idle sessions until cancelled.

        Long-lived processes would otherwise hold one BrainV2 per user that
        ever connected. Started by the app lifespan; cancelling the task stops
        the sweep.
        """
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                await self.evict_idle_sessions(idle_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — a sweep must never kill the loop
                logger.exception("Idle-session sweep failed")


# One coordinator per Python process.
cognitive_sessions = CognitiveSessionCoordinator()
