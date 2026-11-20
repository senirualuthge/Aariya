# Two-process chaos harness

Validates the invariants the shared cognitive session coordinator promises once
more than one backend worker exists:

- **one brain per user** across processes (no split-brain),
- **one turn at a time** per user,
- **ownership survives** a socket moving to another worker,
- **failover** after the owning worker dies mid-turn,
- **fail closed** when the coordination store disappears,
- the **single-worker startup guard** still refuses a multi-worker boot.

Two independent OS processes (not two sockets in one process) are required to
observe any of this, so the harness starts real servers on real ports.

## How it works

```
harness.py (orchestrator)
 ├─ redis-server (throwaway, unless --redis-url)     ← shared coordination store
 ├─ chaos_worker.py --port P1   (worker w1)          ← real coordinator,
 └─ chaos_worker.py --port P2   (worker w2)             deterministic brain
```

`chaos_worker.py` serves a tiny WebSocket protocol through
`cognitive_sessions.process_turn`, with a deterministic `BrainV2` double whose
turn duration is controlled per message (`"sleep": seconds`). Every turn
start/end is appended to Redis (`chaos:{run}:turns`), which is how the harness
proves turns did or did not overlap.

It does **not** use the production `server.main` app: a real turn needs LLM /
swarm / RAG and is neither deterministic nor offline. The harness targets the
coordinator contract, not cognition quality.

## Usage

```bash
# Everything. Distributed scenarios currently SKIP until the Redis backend
# from plans/redis-cognitive-session-coordinator.md is implemented.
server/.venv/bin/python scripts/chaos/harness.py

# The guard works today.
server/.venv/bin/python scripts/chaos/harness.py --scenario guard

# Point at an existing Redis instead of a throwaway instance.
server/.venv/bin/python scripts/chaos/harness.py --redis-url redis://127.0.0.1:6379/0

# Tune waits (per-frame timeout and post-crash failover budget).
server/.venv/bin/python scripts/chaos/harness.py --timeout 20 --failover-budget 60
```

Exit codes: `0` no failures (skips allowed), `1` at least one `FAIL`,
`2` missing dependency / harness cannot start.

## Scenarios

| Scenario | Action | Assertion |
|---|---|---|
| `guard` | Runs `assert_single_worker()` with `WEB_CONCURRENCY=4` and with a clean env. | Multi-worker env aborts non-zero with a "single-process" message; default boots. |
| `concurrent` | Both workers send a turn for the same user at once. | Both replies arrive, exactly two executions, no overlapping turn intervals. |
| `reconnect` | Turn on worker 1, close the socket, reconnect on worker 2, turn again. | Owner key is unchanged, two serialized executions, reply delivered. |
| `crash` | Hold a turn open on the owner, `SIGKILL` that process mid-turn, then turn on the survivor. | Survivor serves within `--failover-budget`; the follow-up turn executes exactly once. |
| `redis-down` | Stop the throwaway coordination store, then send a turn. | No successful reply while coordination is down (fail closed), worker process stays alive. |

`redis-down` is always run last because it kills the store. It refuses to run
against an external `--redis-url` so a real Redis is never touched.

## Current status (2026-11-20)

The distributed coordinator is **designed, not implemented**
(`plans/redis-cognitive-session-coordinator.md`). The harness detects this
honestly: after booting both workers in `AARIYA_SESSION_BACKEND=redis` it sends
a warm turn and probes `aariya:cog:state:{user}` and
`aariya:cog:owner:{user}`. If the contract keys are absent it reports `SKIP`,
never a false `PASS`. Once P1/P2 of the design ships, the same command runs the
distributed scenarios for real.

## Requirements

- `server/.venv` with `websockets`, `redis`, `fastapi`, `uvicorn` (already in
  the backend environment).
- `redis-server` on `PATH` for throwaway instances, or `--redis-url`.
- Local ports: workers bind port `0` (OS-assigned) and report the actual port
  back to the harness, so runs never race on a chosen port.
