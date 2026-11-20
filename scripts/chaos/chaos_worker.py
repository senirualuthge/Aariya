#!/usr/bin/env python3
"""Chaos target worker: a minimal ASGI app driven by the REAL coordinator.

`scripts/chaos/harness.py` starts two of these as separate OS processes on
different ports, so chaos experiments exercise genuine cross-process behaviour.

Why not the real ``server.main`` app?  A real turn builds a full ``BrainV2``
(LLM, swarm, RAG, vault) whose latency is neither deterministic nor offline.
Chaos needs deterministic timing, so this worker installs a deterministic
brain double on the coordinator module — the same public hook the pytest suite
uses — and serves a tiny WebSocket protocol on top of
``cognitive_sessions.process_turn``.

Observability:
  * every turn start/end is appended to Redis (``chaos:{RUN_ID}:turns``) when
    ``CHAOS_REDIS_URL`` is set, otherwise kept in-process and served at
    ``GET /chaos/turns``;
  * records carry worker id, pid, timestamp, user, message id, and text, which
    is what the harness uses to prove turns did or did not overlap.

This file is a test fixture for the coordinator contract, not a product API.
"""

import argparse
import asyncio
import itertools
import json
import logging
import os
import pathlib
import time
import uuid

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from server.protocol import BrainState, MultimodalInput, MultimodalOutput
from server.systems import cognitive_session_coordinator as coordinator_module
from server.systems.cognitive_session_coordinator import cognitive_sessions

WORKER_ID = os.getenv("CHAOS_WORKER_ID") or f"w-{uuid.uuid4().hex[:6]}"
RUN_ID = os.getenv("CHAOS_RUN_ID", "local")
REDIS_URL = os.getenv("CHAOS_REDIS_URL") or ""
TURNLOG_KEY = f"chaos:{RUN_ID}:turns"

logger = logging.getLogger("aariya.chaos_worker")
_LOCAL_TURNS: list = []
_SEQ = itertools.count(1)
_redis_client = None
_redis_warned = False


def _redis():
    """Lazy Redis client; None when unconfigured or unreachable."""
    global _redis_client, _redis_warned
    if not REDIS_URL:
        return None
    if _redis_client is None:
        try:
            import redis as redis_lib

            _redis_client = redis_lib.Redis.from_url(
                REDIS_URL, decode_responses=True,
                socket_connect_timeout=0.5, socket_timeout=0.5,
            )
            _redis_client.ping()
        except Exception as exc:  # noqa: BLE001 — fall back to local log
            if not _redis_warned:
                logger.warning("chaos turn log falling back to local memory: %s", exc)
                _redis_warned = True
            _redis_client = None
    return _redis_client


def _record(event: str, **fields) -> None:
    record = {
        "event": event,
        "worker": WORKER_ID,
        "pid": os.getpid(),
        "seq": next(_SEQ),
        "ts": time.time(),
        "run": RUN_ID,
        **fields,
    }
    client = _redis()
    if client is not None:
        try:
            client.rpush(TURNLOG_KEY, json.dumps(record))
            return
        except Exception as exc:  # noqa: BLE001 — Redis outage is a scenario
            logger.warning("chaos turn log write failed: %s", exc)
    _LOCAL_TURNS.append(record)


class _ChaosBrain:
    """Deterministic BrainV2 double with controllable turn duration."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.serial = uuid.uuid4().hex[:8]
        self.state = BrainState(valence=0.1, arousal=0.4, emotion="calm")

    async def process(self, input_model, on_token=None):
        text = input_model.text or ""
        meta = input_model.metadata or {}
        msg_id = meta.get("chaos_msg_id")
        try:
            sleep_for = float(meta.get("chaos_sleep") or 0.05)
        except (TypeError, ValueError):
            sleep_for = 0.05
        _record("start", user=self.user_id, text=text, msg_id=msg_id, sleep=sleep_for)
        try:
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
            if on_token is not None:
                await on_token(text)
            return MultimodalOutput(
                text=f"echo:{text}",
                expression="calm",
                gestures=[],
                thought=None,
                state_update=self.state,
            )
        finally:
            _record("end", user=self.user_id, text=text, msg_id=msg_id)

    def get_state(self) -> BrainState:
        return self.state


# The coordinator resolves BrainV2 lazily at session creation, so installing
# the double before the first turn is enough.
coordinator_module.BrainV2 = _ChaosBrain

app = FastAPI(title="Aariya chaos worker")


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "worker": WORKER_ID,
        "pid": os.getpid(),
        "backend": os.getenv("AARIYA_SESSION_BACKEND", "memory"),
    }


@app.get("/chaos/info")
async def chaos_info() -> dict:
    return {
        "worker": WORKER_ID,
        "pid": os.getpid(),
        "backend": os.getenv("AARIYA_SESSION_BACKEND", "memory"),
        "run": RUN_ID,
        "sessions": len(cognitive_sessions._sessions),
        "turnlog": "redis" if _redis() is not None else "local",
    }


@app.get("/chaos/turns")
async def chaos_turns() -> dict:
    return {"worker": WORKER_ID, "records": list(_LOCAL_TURNS)}


@app.get("/chaos/state")
async def chaos_state(user_id: str) -> dict:
    state = await cognitive_sessions.get_state(user_id)
    return {"worker": WORKER_ID, "state": state.model_dump(mode="json")}


@app.websocket("/ws/chat")
async def chat(websocket: WebSocket):
    await websocket.accept()
    user_id = websocket.query_params.get("user_id") or "chaos_user"

    async def _stream(token: str) -> None:
        await websocket.send_text(json.dumps({"type": "text.stream", "chunk": token}))

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            if msg.get("type") == "interrupt":
                continue
            input_model = MultimodalInput(
                text=msg.get("text"),
                metadata={
                    "chaos_sleep": msg.get("sleep"),
                    "chaos_msg_id": msg.get("id"),
                },
            )
            output, state = await cognitive_sessions.process_turn(
                user_id, input_model, on_token=_stream
            )
            await websocket.send_text(json.dumps({
                "type": "ai_response",
                "text": output.text,
                "worker": WORKER_ID,
                "state": state.model_dump(mode="json"),
                "timestamp": time.time(),
            }))
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001 — surface, then drop the socket
        logger.exception("chaos chat error: %s", exc)


async def _serve(server: uvicorn.Server, port_file: str | None) -> None:
    """Run Uvicorn, then report the actually-bound port to the harness.

    Binding port 0 lets the OS assign a free port, which removes the
    check-then-bind race that made two-process runs flaky.
    """
    task = asyncio.create_task(server.serve())
    while not server.started and not task.done():
        await asyncio.sleep(0.02)
    if server.started and port_file:
        sockets = server.servers[0].sockets if server.servers else []
        if sockets:
            port = sockets[0].getsockname()[1]
            pathlib.Path(port_file).write_text(str(port), encoding="utf-8")
    await task


def main() -> None:
    parser = argparse.ArgumentParser(description="Aariya chaos worker")
    parser.add_argument("--port", type=int, default=0,
                        help="0 = let the OS assign a free port")
    parser.add_argument("--port-file", default=None,
                        help="write the actually bound port here")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--log-level", default="warning")
    args = parser.parse_args()
    logging.basicConfig(level=args.log_level.upper())
    config = uvicorn.Config(app, host=args.host, port=args.port,
                            log_level=args.log_level)
    asyncio.run(_serve(uvicorn.Server(config), args.port_file))


if __name__ == "__main__":
    main()
