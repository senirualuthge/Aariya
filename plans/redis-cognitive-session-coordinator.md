# Design — Redis-Backed Distributed Cognitive Session Coordinator

> **Objective:** Let more than one backend worker serve the same personal Aariya
> user without split-brain: one live brain, serialized turns, working reconnect
> and crash recovery, cross-worker broadcast fan-out.
> **Created:** 2026-11-20
> **Repo:** `/Volumes/Volumn 1/Code Base/AI Girl`
> **Status:** Design only. Patch 1 (`server/systems/cognitive_session_coordinator.py`)
> is the in-process implementation this design evolves.

---

## 0. Where we are today (grounded)

| Piece | File | Behaviour today |
|---|---|---|
| Session coordinator | `server/systems/cognitive_session_coordinator.py` | One `BrainV2` per `user_id`, in this process. Per-user `turn_lock`. Idle sweep (default 30 min) started by the app lifespan. |
| Startup guard | same file, `assert_single_worker()` | Aborts boot when `WEB_CONCURRENCY`/`UVICORN_WORKERS`/`--workers`/`-w` request >1 worker. Called first in `lifespan`. |
| Brain | `server/systems/brain_v2.py` | Mutable live object: personality, emotion, narrative, swarm/gateway singletons, LLM clients, conversation log. **Not serializable, not shareable across processes.** |
| Socket fan-out | `server/infrastructure/session_manager.py` | `broadcast` / `broadcast_state` iterate *local* socket registries only. No cross-process reach. |
| Redis helper | `server/infrastructure/redis_manager.py` | Thin JSON `get`/`set` with a silent per-process `_local_cache` fallback. No pub/sub, locks, TTL or CAS. |
| Mobile reliability | `server/main.py` `/ws/mobile` | Protocol v2 `ack` + client `AckOutbox` retries id-bearing messages. |

**The hard constraint:** `BrainV2` cannot be moved or mirrored as an object. So
"one brain per user across workers" must mean **one owner at a time**, never
"same instance on every worker". Any design that tries to serialize the object
graph or rebuild it per turn loses live cognition and is rejected.

---

## 1. Architecture decision

**Owner-affinity sessions + Redis-coordinated leases + state mirror.**

1. Exactly one worker (the **owner**) may hold a live `BrainV2` for a user.
   Ownership is a Redis lease, not an in-process dict.
2. A turn for a user always executes on the owner. A non-owner either forwards
   the turn to the owner (preferred when no L7 stickiness) or, if the owner's
   lease has expired, **claims ownership** and rebuilds the brain.
3. Turns are serialized per user by a Redis turn lock. The in-process
   `turn_lock` stays as the fast path on the owner.
4. Every finished turn writes a small **state mirror** to Redis and publishes
   the same frames the owner would broadcast, so any worker can answer state
   reads and every worker can fan out to its own sockets.
5. Redis is the availability boundary: **fail closed**. If Redis is unreachable
   while `AARIYA_SESSION_BACKEND=redis`, turns are refused with a
   `session.unavailable` frame instead of silently running a second brain.

Rejected alternatives:

| Option | Why rejected |
|---|---|
| Stateless workers, rebuild brain every turn | Loses personality/emotion/narrative continuity, re-runs memory + swarm bootstrap per message. |
| Serialize `BrainV2` to Redis | Object holds sockets, clients, singletons, unpicklable state; snapshot size and staleness are unbounded. |
| Sticky sessions only (L7 hash on `user_id`), no lock | Hairline crack on reschedule: two workers can briefly own the user. Needs the lease anyway. |
| Use `RedisManager._local_cache` fallback for coordination | Per-process cache — the exact split-brain this design prevents. Coordination must never fall back. |

---

## 2. Redis data model

All coordination keys are namespaced `aariya:cog:*`. Values are JSON unless
noted. Times come from Redis `TIME`, never a worker's clock.

| Key | Type | TTL | Writer | Meaning |
|---|---|---|---|---|
| `aariya:cog:owner:{user_id}` | string `worker_id` | lease TTL (15 s), renewed every 5 s | owner only (renew via Lua CAS) | Who may hold the brain. |
| `aariya:cog:turn:{user_id}` | string `{token,worker_id,started_at}` | 2× p99 turn (300 s), renewed during a turn | turn holder | Serializes turns; heartbeat-extended while `BrainV2.process` runs. |
| `aariya:cog:state:{user_id}` | hash: `state` (BrainState JSON), `version`, `last_used`, `owner` | `AARIYA_SESSION_IDLE_TTL_SECONDS` (1800) | owner after every turn | State mirror for reads, reconnects, failover seed. |
| `aariya:cog:seen:{user_id}` | set of `msg_id` | 10 min | owner | Idempotency for mobile v2 retries across failover. |
| `aariya:workers:{worker_id}` | hash: `addr`, `started`, `users` | heartbeat 15 s | each worker | Liveness + forwarding address. |
| `aariya:workers` | set | — | each worker on boot/shutdown | Worker discovery. |
| `aariya:events` | pub/sub channel | — | any worker | Fan-out frames: `state.update`, `inner_thought`, `avatar.update`, kill-switches, `ai_response` copies for mirrored surfaces. |
| `aariya:cog:req:{worker_id}` | pub/sub channel | — | any worker | Forwarded turn requests/responses (or use HTTP; see §4). |

Idle eviction maps directly onto the `aariya:cog:state` TTL; the in-process
sweeper remains as a local safety net.

---

## 3. Ownership protocol

**Acquire (turn start):**

```
owner = GET aariya:cog:owner:{uid}
if owner == me:                       # fast path
    renew lease (Lua: value == me -> PEXPIRE)
elif owner is None or owner not live in aariya:workers:
    SET aariya:cog:owner:{uid} me NX PX lease_ttl   # claim
    if claim won: adopt_state(uid)                   # §5
else:
    forward turn to owner.addr                       # §4
```

**Turn lock (owner only, but Redis-authoritative):**

```
token = uuid4()
SET aariya:cog:turn:{uid} {token,me} NX PX turn_ttl
if not acquired: wait/retry bounded (return busy frame after N s)
... run BrainV2.process with a renewer task ...
Lua release: if value.token == token then DEL
```

**Renewal:** a background task on the owner renews both the lease and the turn
key every 5 s while a turn runs. A process pause (GC, debugger, suspend)
therefore expires the lock rather than deadlocking the user forever.

**Release:** lease is *not* deleted after a turn — the owner keeps the warm
brain. Shutdown deletes `aariya:cog:owner:{uid}` and the worker heartbeat;
the next turn anywhere claims it.

**Why both lease and turn lock:** the lease answers "who owns cognition"; the
turn lock answers "who is executing right now". Failover uses the lease; the
lock prevents a forwarded request and a just-claimed request from overlapping.

---

## 4. Request routing

Two deployment modes; pick per environment, keep the same coordinator interface.

**Mode A — forward to owner (default, no proxy work).**
Any worker accepts the WebSocket. For a turn, if it is not the owner it
publishes `{type:"turn.request", user_id, msg_id, payload, reply_to}` on
`aariya:cog:req:{owner}` and awaits `turn.result` (correlation id, 30 s
timeout). The owner runs the turn and replies with output + state version. The
accepting worker writes only socket frames; it never builds a second brain.

**Mode B — sticky L7 routing.**
The load balancer hashes `user_id` (or the auth subject) to a worker. Forwarding
becomes rare; the coordinator still runs the acquire/lease path so reschedules
and rolling deploys are safe.

Both modes preserve the client contract: `/ws/mobile` and `/ws/brain` keep
their current input frames and replies; only the coordinator's internals change.

---

## 5. State mirror and recovery

**Write (owner, end of every turn):**

```python
state = session.brain.get_state()
HSET aariya:cog:state:{uid} state=state.model_dump_json() version=++v \
     last_used=now owner=me
PUBLISH aariya:events {"type":"state.update","user_id":uid,"state":..., "version":v}
```

**Read (any worker):** `HGETALL` the mirror for `get_state`, reconnects, and
dashboard state reads. Reject stale reads newer than `version` seen locally
(`version` is monotonic per user).

**Failover (new owner):**

1. Claim the lease (§3). The old owner is dead only when its heartbeat key is
   gone *and* the turn key has expired; until then, wait/queue rather than steal.
2. Build `BrainV2(user_id)` — it already restores trust/valence/arousal/attachment
   from `ConversationLog` (existing behaviour on restart).
3. Apply the mirrored `BrainState` fields over the fresh brain (synoptic,
   security, mode) when `version` is newer than the local default.
4. Log `recovered_from=worker_id`, `version`, `gap_seconds`; emit a real
   telemetry signal (`BRAIN`, title `Session recovered (owner failover)`).
5. Run the queued turn. If the turn's `msg_id` is in `aariya:cog:seen:{uid}`,
   replay the stored reply instead of running it twice.

**What recovery cannot restore:** temporary subsystems not in `BrainState`
(in-flight LLM generation, live diarization windows, unsaved swarm scratch).
The client-visible contract is: no duplicate turn, no lost acknowledged reply,
personality/relationship state from persistent stores, mirrored brain state.

---

## 6. Broadcast fan-out

The owner publishes every frame it would have sent locally:

```
aariya:events -> {"type":"state.update", user_id, state, version, origin}
aariya:events -> {"type":"inner_thought"|"avatar.update"|"kill_switches"|"proactive_message", ...}
```

Each worker runs one subscriber task (started in `lifespan`, cancelled on
shutdown) that calls the existing local `session_manager.broadcast*` for sockets
attached to it. Deduplicate by `(origin, frame_id)` so the publishing worker
does not double-send its own local sockets. Ordering is per user: publish under
the turn lock, include `version`, and drop frames with `version` older than the
last one seen for that user.

---

## 7. Failure modes and policy

| Failure | Detection | Policy |
|---|---|---|
| Owner crash mid-turn | heartbeat gone, turn key expires | New owner claims after expiry (≤ 300 s p99); queued message retried by client `AckOutbox`; `msg_id` dedupe prevents double reply. |
| Owner hang / GC pause | lease expires but process alive | It must **self-demote**: renewal fails → abort local turn, drop the brain, and forward/refuse further turns. Never keep writing after losing the lease. |
| Two workers claim simultaneously | `SET NX` | Exactly one wins; loser forwards or retries. |
| Redis unavailable | ping/command error | `AARIYA_SESSION_BACKEND=redis` → fail closed: `{"type":"session.unavailable"}`, log, HTTP 503 on REST state reads. Never fall back to `_local_cache`. |
| Split view after partition | lease loss | Only the lease holder may mutate; the other side demotes. |
| Clock skew | — | All TTLs computed server-side by Redis; no worker wall-clock comparisons. |
| Stale mirror overwrite | `version` | Writes are compare-and-set on `version` (Lua); loser re-reads and retries once, then logs. |
| Idle user | `last_used` | Mirror TTL expires; owner drops the brain in the same sweep; next turn rebuilds (identical to today's eviction). |

---

## 8. Phased delivery

| Phase | Scope | Guard state |
|---|---|---|
| **P0 (shipped)** | In-process coordinator, single-worker startup guard, idle eviction, reconnection/concurrency tests. | Refuses >1 worker. |
| **P1 — Mirror + fan-out** | Owner writes `aariya:cog:state`; subscriber task re-broadcasts `aariya:events` through local `session_manager`. Still one worker, but exercises every cross-process code path. | Still refuses >1 worker. |
| **P2 — Lease + turn lock** | Lease, heartbeat, turn lock, self-demotion, failover claim, recovery telemetry. Run a second process manually in tests for chaos coverage. | Still refuses >1 worker by default. |
| **P3 — Forwarding / sticky** | Mode A forwarder or Mode B stickiness; lift the guard when `AARIYA_SESSION_BACKEND=redis` (guard becomes `assert_single_worker()` unless the Redis backend is explicitly selected and healthy). | Allows >1 worker only in redis mode. |
| **P4 — Hardening** | Metrics (lease claims, failovers, lock waits, mirror size), TTL tuning, operator runbook, Redis HA (Sentinel/managed). | — |

Each phase is independently shippable and testable; P1/P2 change no client
contract.

---

## 9. Test plan

**Harness:** `scripts/chaos/harness.py` already starts two real worker
processes on OS-assigned ports plus a throwaway Redis, with deterministic
brain doubles injected via the same hook Patch 1 uses
(`cognitive_session_coordinator.BrainV2`). It currently reports the Redis
dependent scenarios as SKIP until the contract keys below exist, and covers
`concurrent`, `reconnect`, `crash`, `redis-down`, and `guard`.
See `scripts/chaos/README.md`.

| Test | Assertion |
|---|---|
| Concurrent phone + laptop, different workers | One brain instance total, turns do not overlap (Redis marker around `process`), both replies delivered. |
| Reconnect to the *other* worker | Same `version` continuity, no rebuild (`recovered_from` absent), no duplicate reply. |
| Owner killed mid-turn | Next turn served within lease+lock TTL; one `recovered` telemetry event; acknowledged `msg_id` not executed twice. |
| Owner hang, renewal fails | Old owner demotes, stops mutating, new owner serves. |
| Redis down | Turns refused with `session.unavailable`; no second brain built; existing local sockets stay connected. |
| Idle parity | Mirror TTL and local sweep both drop the session; next turn rebuilds from persistent stores. |
| Guard | `AARIYA_SESSION_BACKEND=redis` allows >1 worker; `memory` still refuses (existing tests stay green). |

Existing suites that must keep passing unchanged: `test_cognitive_session_coordinator.py`,
`test_mobile_ws_broadcast.py`, `test_dashboard_stream_route.py`,
`test_session_broadcast.py`, `test_mobile_device_count.py`,
`test_mobile_authority.py`, `test_dashboard_authority.py`.

---

## 10. Config additions

| Variable | Default | Meaning |
|---|---|---|
| `AARIYA_SESSION_BACKEND` | `memory` | `memory` (current, single worker) or `redis` (distributed). |
| `AARIYA_SESSION_IDLE_TTL_SECONDS` | `1800` | Idle eviction / mirror TTL. (Already used by P0.) |
| `AARIYA_SESSION_SWEEP_INTERVAL_SECONDS` | `60` | Local sweep cadence. (Already used by P0.) |
| `AARIYA_OWNER_LEASE_SECONDS` | `15` | Ownership lease TTL. |
| `REDIS_HOST` / `REDIS_PORT` | `localhost` / `6379` | Reuse `redis_manager`; coordination must use a real client, not its fallback cache. |

---

## 11. Open questions

1. Forwarding transport: Redis pub/sub request-reply (Mode A) vs an internal
   HTTP hop. Pub/sub is broker-free but has no backpressure; HTTP gives
   timeouts and retries for free but needs worker address registration.
2. Which `BrainState` fields are safe to seed on failover (synoptic/security
   are snapshots; `personality` is authoritative from the personality store —
   do not overwrite it from the mirror).
3. Whether ownership should be per user or per (user, surface group): a user
   with many devices still resolves to one brain, so per-user is expected.
4. Mirror size guardrails: `BrainState` currently includes `synoptic` and
   `planetary` payloads; cap/trim before writing if they grow.
5. Redis HA topology for a personal deployment (single node + persistence vs
   Sentinel) and whether fail-closed is acceptable during a broker restart.
