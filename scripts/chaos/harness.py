#!/usr/bin/env python3
"""Two-process chaos harness for the Aariya cognitive session coordinator.

Runs TWO independent OS processes of ``scripts/chaos/chaos_worker.py`` on
different ports against one shared coordination store, then applies chaos and
checks the single-brain / single-turn invariants:

  guard       startup refuses a multi-worker boot (works today)
  concurrent  both workers serve the SAME user at the same time; turns must
              not overlap and both replies must arrive
  reconnect   a socket reconnects on the other worker; same owner, no rebuild
  crash       SIGKILL the owning worker mid-turn; another worker must take over
              within the lease/failover budget and serve the next turn
  redis-down  the coordination store disappears mid-run; the worker must fail
              closed (refuse the turn) instead of building a second brain

The distributed scenarios depend on the Redis-backed coordinator designed in
``plans/redis-cognitive-session-coordinator.md``. That backend is not
implemented yet, so the harness probes its contract keys
(``aariya:cog:state:{user}`` and ``aariya:cog:owner:{user}``) after a warm turn
and reports SKIP — never a false PASS — until they appear.

The harness starts its own throwaway ``redis-server`` by default and refuses to
kill an external Redis in the redis-down scenario.

Exit codes: 0 = no failures (skips allowed), 1 = at least one FAIL,
2 = environment/usage error (missing dependency or harness cannot start).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote
from urllib.request import urlopen

try:
    import redis as redis_lib
except Exception:  # noqa: BLE001
    redis_lib = None

try:
    from websockets.sync.client import connect as ws_connect
except Exception:  # noqa: BLE001
    ws_connect = None

ROOT = Path(__file__).resolve().parents[2]
WORKER_SCRIPT = Path(__file__).resolve().with_name("chaos_worker.py")
_VENV_PY = ROOT / "server" / ".venv" / "bin" / "python"
PY = _VENV_PY if _VENV_PY.exists() else Path(sys.executable)
REDIS_SERVER = shutil.which("redis-server")

SCENARIOS = ("guard", "concurrent", "reconnect", "crash", "redis-down")


class HarnessError(RuntimeError):
    """A scenario assertion failed."""


class SkipScenario(RuntimeError):
    """A scenario cannot run in this environment / implementation state."""


@dataclass
class Result:
    name: str
    status: str  # PASS / FAIL / SKIP
    detail: str = ""


@dataclass
class Worker:
    index: int
    port: int  # filled in once the worker reports its bound port
    worker_id: str
    proc: subprocess.Popen
    log_path: Path
    port_file: Path

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def ws_url(self, user_id: str) -> str:
        return f"ws://127.0.0.1:{self.port}/ws/chat?user_id={quote(user_id)}"

    def alive(self) -> bool:
        return self.proc.poll() is None

    def info(self) -> dict:
        return _http_json(f"{self.base_url}/chaos/info")

    def stop(self, sig: int = signal.SIGTERM) -> None:
        if self.proc.poll() is None:
            with contextlib.suppress(Exception):
                self.proc.send_signal(sig)
        with contextlib.suppress(Exception):
            self.proc.wait(timeout=10)
        if self.proc.poll() is None:
            with contextlib.suppress(Exception):
                self.proc.kill()


class RedisCtl:
    """Harness-managed throwaway Redis, or an explicit external URL."""

    def __init__(self, url: Optional[str]):
        self.external = bool(url)
        self.url = url
        self.proc: Optional[subprocess.Popen] = None
        self.tmpdir: Optional[str] = None
        self.port: Optional[int] = None

    @property
    def available(self) -> bool:
        return self.external or REDIS_SERVER is not None

    def start(self) -> None:
        if self.external:
            if not self._ping():
                raise HarnessError(f"Redis at {self.url} is not reachable")
            return
        if REDIS_SERVER is None:
            raise HarnessError("no redis-server binary found")
        # A port chosen as "free" can lose a race before redis-server binds it,
        # so retry on a fresh port a few times.
        last_error = ""
        for _ in range(3):
            self.port = _free_port()
            self.tmpdir = tempfile.mkdtemp(prefix="aariya-chaos-redis-")
            self.proc = subprocess.Popen(
                [
                    REDIS_SERVER,
                    "--port", str(self.port),
                    "--bind", "127.0.0.1",
                    "--save", "",
                    "--appendonly", "no",
                    "--dir", self.tmpdir,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.url = f"redis://127.0.0.1:{self.port}/0"
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if self._ping():
                    return
                if self.proc.poll() is not None:
                    last_error = f"redis-server exited (port {self.port})"
                    break
                time.sleep(0.1)
            self.stop()
            if self.tmpdir:
                shutil.rmtree(self.tmpdir, ignore_errors=True)
        raise HarnessError(
            f"throwaway redis-server did not become ready: {last_error or 'timeout'}"
        )

    def _ping(self) -> bool:
        if redis_lib is None or not self.url:
            return False
        try:
            client = redis_lib.Redis.from_url(
                self.url, socket_connect_timeout=0.5, socket_timeout=0.5
            )
            return bool(client.ping())
        except Exception:  # noqa: BLE001
            return False

    def client(self):
        if redis_lib is None:
            raise HarnessError("python redis package is not installed")
        if not self.url:
            raise HarnessError("no Redis URL configured")
        return redis_lib.Redis.from_url(
            self.url, decode_responses=True,
            socket_connect_timeout=1, socket_timeout=1,
        )

    def stop(self) -> None:
        if self.external or self.proc is None:
            return
        if self.proc.poll() is None:
            with contextlib.suppress(Exception):
                self.proc.terminate()
            with contextlib.suppress(Exception):
                self.proc.wait(timeout=5)
        if self.proc.poll() is None:
            with contextlib.suppress(Exception):
                self.proc.kill()

    def cleanup(self) -> None:
        self.stop()
        if self.tmpdir:
            shutil.rmtree(self.tmpdir, ignore_errors=True)


@dataclass
class Context:
    run_id: str
    artifacts: Path
    redis: RedisCtl
    workers: List[Worker] = field(default_factory=list)
    timeout: float = 15.0
    failover_budget: float = 45.0

    @property
    def turnlog_key(self) -> str:
        return f"chaos:{self.run_id}:turns"


# ── small helpers ────────────────────────────────────────────────────────────

def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _http_json(url: str, timeout: float = 2.0) -> dict:
    with urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _wait_port_file(worker: Worker, timeout: float = 30.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            raw = worker.port_file.read_text(encoding="utf-8").strip()
            if raw:
                return int(raw)
        except Exception:  # noqa: BLE001 — not written yet
            pass
        if not worker.alive():
            break
        time.sleep(0.05)
    tail = ""
    with contextlib.suppress(Exception):
        tail = worker.log_path.read_text()[-800:]
    raise HarnessError(
        f"worker w{worker.index} did not report a bound port. log tail:\n{tail}"
    )


def _wait_health(worker: Worker, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if _http_json(f"{worker.base_url}/health").get("status") == "ok":
                return
        except Exception:  # noqa: BLE001
            pass
        if not worker.alive():
            break
        time.sleep(0.1)
    tail = ""
    with contextlib.suppress(Exception):
        tail = worker.log_path.read_text()[-800:]
    raise HarnessError(
        f"worker w{worker.index} (port {worker.port}) did not become healthy. "
        f"log tail:\n{tail}"
    )


def _start_workers(ctx: Context, count: int) -> List[Worker]:
    env = os.environ.copy()
    for var in ("WEB_CONCURRENCY", "UVICORN_WORKERS"):
        env.pop(var, None)
    env.update({
        "PYTHONPATH": str(ROOT),
        "AARIYA_SESSION_BACKEND": "redis",
        "AARIYA_SESSION_IDLE_TTL_SECONDS": "600",
        "CHAOS_REDIS_URL": ctx.redis.url or "",
        "CHAOS_RUN_ID": ctx.run_id,
    })
    workers: List[Worker] = []
    try:
        for i in range(count):
            worker_id = f"w{i + 1}-{ctx.run_id}"
            log_path = ctx.artifacts / f"worker-{i + 1}.log"
            port_file = ctx.artifacts / f"worker-{i + 1}.port"
            with contextlib.suppress(FileNotFoundError):
                port_file.unlink()
            log_file = open(log_path, "w", encoding="utf-8")
            proc = subprocess.Popen(
                [
                    str(PY), str(WORKER_SCRIPT),
                    "--port", "0",
                    "--port-file", str(port_file),
                ],
                cwd=ROOT,
                env={**env, "CHAOS_WORKER_ID": worker_id},
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
            workers.append(
                Worker(i + 1, 0, worker_id, proc, log_path, port_file)
            )
            log_file.close()
        for worker in workers:
            worker.port = _wait_port_file(worker)
            _wait_health(worker)
        return workers
    except Exception:
        for worker in workers:
            worker.stop()
        raise


def _open(worker: Worker, user_id: str):
    if ws_connect is None:
        raise HarnessError("websockets is not installed")
    return ws_connect(worker.ws_url(user_id), open_timeout=10, close_timeout=2)


def _send(ws, text: str, msg_id: str, sleep: float = 0.05) -> None:
    ws.send(json.dumps({"text": text, "id": msg_id, "sleep": sleep}))


def _await_frame(ws, want: set, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise HarnessError(f"no {sorted(want)} frame within {timeout}s")
        try:
            raw = ws.recv(timeout=remaining)
        except TimeoutError:
            raise HarnessError(f"no {sorted(want)} frame within {timeout}s")
        except Exception as exc:  # noqa: BLE001 — closed socket is a harness outcome
            raise HarnessError(
                f"socket closed while waiting for {sorted(want)}: {exc}"
            )
        msg = json.loads(raw)
        if msg.get("type") in want:
            return msg


def _records(ctx: Context, user_id: str) -> List[dict]:
    raw = ctx.redis.client().lrange(ctx.turnlog_key, 0, -1)
    out = []
    for item in raw:
        with contextlib.suppress(Exception):
            rec = json.loads(item)
            if rec.get("user") == user_id:
                out.append(rec)
    return out


def _events(recs: List[dict], event: str) -> List[dict]:
    return sorted((r for r in recs if r.get("event") == event), key=lambda r: r["ts"])


def _turns_overlap(recs: List[dict]) -> bool:
    starts = _events(recs, "start")
    ends = _events(recs, "end")
    intervals = []
    for start in starts:
        end = next(
            (e for e in ends
             if e.get("msg_id") == start.get("msg_id") and e["ts"] >= start["ts"]),
            None,
        )
        if end is not None:
            intervals.append((start["ts"], end["ts"]))
    intervals.sort()
    return any(intervals[i + 1][0] < intervals[i][1] for i in range(len(intervals) - 1))


def _wait_for_record(ctx: Context, user_id: str, msg_id: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(r.get("msg_id") == msg_id for r in _records(ctx, user_id)):
            return
        time.sleep(0.1)
    raise HarnessError(f"turn {msg_id} never started on any worker")


def _owner(ctx: Context, user_id: str) -> Optional[str]:
    try:
        return ctx.redis.client().get(f"aariya:cog:owner:{user_id}")
    except Exception:  # noqa: BLE001
        return None


def _state_exists(ctx: Context, user_id: str) -> bool:
    try:
        return bool(ctx.redis.client().exists(f"aariya:cog:state:{user_id}"))
    except Exception:  # noqa: BLE001
        return False


def _probe_redis_backend(ctx: Context) -> bool:
    """Warm turn + contract-key probe. False while the redis backend is absent."""
    user = f"{ctx.run_id}-probe"
    with _open(ctx.workers[0], user) as ws:
        _send(ws, "probe", "m-probe")
        _await_frame(ws, {"ai_response"}, ctx.timeout)
    return _owner(ctx, user) is not None and _state_exists(ctx, user)


# ── scenarios ────────────────────────────────────────────────────────────────

def scenario_guard(ctx: Context) -> str:
    code = (
        "from server.systems.cognitive_session_coordinator import assert_single_worker; "
        "assert_single_worker()"
    )
    base_env = {k: v for k, v in os.environ.items()
                if k not in ("WEB_CONCURRENCY", "UVICORN_WORKERS")}

    ok = subprocess.run(
        [str(PY), "-c", code], cwd=ROOT, env=base_env,
        capture_output=True, text=True, timeout=60,
    )
    if ok.returncode != 0:
        raise HarnessError(
            f"single-worker configuration failed to boot:\n{ok.stderr[-500:]}"
        )

    bad = subprocess.run(
        [str(PY), "-c", code], cwd=ROOT,
        env={**base_env, "WEB_CONCURRENCY": "4"},
        capture_output=True, text=True, timeout=60,
    )
    if bad.returncode == 0:
        raise HarnessError("WEB_CONCURRENCY=4 was accepted — guard did not refuse")
    output = bad.stderr + bad.stdout
    if "single-process" not in output:
        raise HarnessError(f"refusal message missing 'single-process':\n{output[-500:]}")
    return "refused WEB_CONCURRENCY=4; allowed single-worker default"


def scenario_concurrent(ctx: Context) -> str:
    user = f"{ctx.run_id}-concurrent"
    first, second = ctx.workers[0], ctx.workers[1]
    with _open(first, user) as a, _open(second, user) as b:
        _send(a, "chaos-a", "m-a")
        _send(b, "chaos-b", "m-b")
        reply_a = _await_frame(a, {"ai_response"}, ctx.timeout)
        reply_b = _await_frame(b, {"ai_response"}, ctx.timeout)

    if reply_a.get("text") != "echo:chaos-a" or reply_b.get("text") != "echo:chaos-b":
        raise HarnessError(
            f"unexpected replies: {reply_a.get('text')!r} / {reply_b.get('text')!r}"
        )

    recs = _records(ctx, user)
    starts = _events(recs, "start")
    if len(starts) != 2:
        raise HarnessError(f"expected 2 executed turns, saw {len(starts)}: {starts}")
    if _turns_overlap(recs):
        raise HarnessError("two turns for one user overlapped across workers")
    if len({s.get("worker") for s in starts}) < 1:
        raise HarnessError("turn records carry no worker id")
    return f"2 turns serialized across {len({s.get('worker') for s in starts})} executing worker(s)"


def scenario_reconnect(ctx: Context) -> str:
    user = f"{ctx.run_id}-reconnect"
    first, second = ctx.workers[0], ctx.workers[1]

    with _open(first, user) as a:
        _send(a, "first", "m-first")
        _await_frame(a, {"ai_response"}, ctx.timeout)
    owner_before = _owner(ctx, user)

    with _open(second, user) as b:
        _send(b, "second", "m-second")
        reply = _await_frame(b, {"ai_response"}, ctx.timeout)

    if reply.get("text") != "echo:second":
        raise HarnessError(f"reconnected turn got {reply.get('text')!r}")
    owner_after = _owner(ctx, user)
    if not owner_before:
        raise HarnessError("no ownership key after the first turn")
    if owner_before != owner_after:
        raise HarnessError(
            f"reconnect moved ownership {owner_before!r} -> {owner_after!r}"
        )
    recs = _records(ctx, user)
    if len(_events(recs, "start")) != 2:
        raise HarnessError("expected 2 turns after reconnect")
    if _turns_overlap(recs):
        raise HarnessError("reconnect turn overlapped an in-flight turn")
    return f"reconnected to the other worker; owner stayed {owner_after}"


def scenario_crash(ctx: Context) -> str:
    user = f"{ctx.run_id}-crash"
    owner_seed = ctx.workers[0]
    with _open(owner_seed, user) as ws:
        _send(ws, "warmup", "m-warm")
        _await_frame(ws, {"ai_response"}, ctx.timeout)

    owner = _owner(ctx, user)
    victim = next((w for w in ctx.workers if w.worker_id == owner), None)
    if victim is None:
        raise HarnessError(f"owner {owner!r} is not one of the harness workers")
    survivor = next(w for w in ctx.workers if w is not victim)

    conn = _open(victim, user)
    try:
        _send(conn, "in-flight", "m-inflight", sleep=5.0)
        _wait_for_record(ctx, user, "m-inflight", timeout=5)
        started = time.monotonic()
        victim.proc.kill()
        with contextlib.suppress(Exception):
            victim.proc.wait(timeout=10)
    finally:
        with contextlib.suppress(Exception):
            conn.close()

    deadline = started + ctx.failover_budget
    while time.monotonic() < deadline:
        current = _owner(ctx, user)
        if current is None or current != victim.worker_id:
            break
        time.sleep(0.25)

    with _open(survivor, user) as ws:
        _send(ws, "after-crash", "m-after")
        reply = _await_frame(ws, {"ai_response"}, ctx.timeout)
    elapsed = time.monotonic() - started

    if reply.get("text") != "echo:after-crash":
        raise HarnessError(f"post-crash turn got {reply.get('text')!r}")
    if elapsed > ctx.failover_budget:
        raise HarnessError(
            f"failover took {elapsed:.1f}s, budget {ctx.failover_budget:.0f}s"
        )
    recs = _records(ctx, user)
    after = [r for r in recs if r.get("msg_id") == "m-after" and r["event"] == "start"]
    if len(after) != 1:
        raise HarnessError(f"post-crash turn executed {len(after)} times, expected 1")
    return (
        f"owner {victim.worker_id} killed mid-turn; "
        f"{after[0].get('worker')} served next turn in {elapsed:.1f}s"
    )


def scenario_redis_down(ctx: Context) -> str:
    if ctx.redis.external:
        raise SkipScenario(
            "redis-down only stops a harness-managed redis-server; "
            "refusing to kill the external store"
        )
    user = f"{ctx.run_id}-redis-down"
    ctx.redis.stop()

    msg: Optional[dict] = None
    with _open(ctx.workers[0], user) as ws:
        _send(ws, "during-outage", "m-outage")
        try:
            msg = _await_frame(ws, {"ai_response", "session.unavailable", "error"}, 8.0)
        except HarnessError:
            msg = None

    if msg and msg.get("type") == "ai_response":
        raise HarnessError(
            "worker served a successful turn while coordination was down "
            "(split-brain risk) — must fail closed"
        )
    if not ctx.workers[0].alive():
        raise HarnessError("worker crashed when Redis disappeared; expected fail-closed")
    refusal = msg.get("type") if msg else "no reply"
    return f"failed closed ({refusal}); worker stayed alive"


SCENARIO_FUNCS = {
    "guard": scenario_guard,
    "concurrent": scenario_concurrent,
    "reconnect": scenario_reconnect,
    "crash": scenario_crash,
    "redis-down": scenario_redis_down,
}


# ── orchestration ────────────────────────────────────────────────────────────

def _run(name: str, ctx: Context) -> Result:
    print(f"  ▶ {name} ...", flush=True)
    try:
        detail = SCENARIO_FUNCS[name](ctx)
        return Result(name, "PASS", detail)
    except SkipScenario as exc:
        return Result(name, "SKIP", str(exc))
    except HarnessError as exc:
        return Result(name, "FAIL", str(exc))
    except Exception as exc:  # noqa: BLE001 — harness should report, not traceback
        return Result(name, "FAIL", f"{type(exc).__name__}: {exc}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--scenario", action="append", choices=(*SCENARIOS, "all"),
        help="scenario to run (repeatable); default: all",
    )
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--redis-url", default=None,
                        help="use an existing Redis instead of a throwaway one")
    parser.add_argument("--timeout", type=float, default=15.0,
                        help="per-frame wait (seconds)")
    parser.add_argument("--failover-budget", type=float, default=45.0,
                        help="max seconds for a new owner to serve after a crash")
    parser.add_argument("--no-artifacts", action="store_true",
                        help="delete worker logs after the run")
    args = parser.parse_args(argv)

    if ws_connect is None or redis_lib is None:
        print("ERROR: needs the venv with websockets + redis installed", file=sys.stderr)
        return 2

    selected = args.scenario or ["all"]
    if "all" in selected:
        selected = list(SCENARIOS)
    # redis-down kills the coordination store, so it must run last.
    selected = sorted(dict.fromkeys(selected),
                      key=lambda s: (s == "redis-down", SCENARIOS.index(s)))

    artifacts = Path(tempfile.mkdtemp(prefix="aariya-chaos-"))
    ctx = Context(
        run_id=uuid.uuid4().hex[:8],
        artifacts=artifacts,
        redis=RedisCtl(args.redis_url),
        timeout=args.timeout,
        failover_budget=args.failover_budget,
    )

    results: List[Result] = []
    exit_code = 0
    print(f"two-process chaos harness — run {ctx.run_id}")
    print(f"python: {PY}")
    print(f"artifacts: {artifacts}")

    distributed = [s for s in selected if s != "guard"]
    try:
        if "guard" in selected:
            results.append(_run("guard", ctx))

        if distributed:
            if not ctx.redis.available:
                reason = "no redis-server binary and no --redis-url"
                for name in distributed:
                    results.append(Result(name, "SKIP", reason))
            else:
                try:
                    ctx.redis.start()
                    ctx.workers = _start_workers(ctx, args.workers)
                except HarnessError as exc:
                    for name in distributed:
                        results.append(Result(name, "FAIL", f"setup: {exc}"))
                else:
                    ready = _probe_redis_backend(ctx)
                    if not ready:
                        reason = (
                            "Redis-backed coordinator not implemented yet "
                            "(aariya:cog:state/* and aariya:cog:owner/* absent)"
                        )
                        for name in distributed:
                            results.append(Result(name, "SKIP", reason))
                    else:
                        for name in distributed:
                            results.append(_run(name, ctx))
    finally:
        for worker in ctx.workers:
            worker.stop()
        ctx.redis.cleanup()

    print("\nresults")
    print("-" * 72)
    for result in results:
        line = f"{result.status:<4} {result.name:<11} {result.detail}"
        print(line)
        if result.status == "FAIL":
            exit_code = 1
    print("-" * 72)
    passed = sum(r.status == "PASS" for r in results)
    skipped = sum(r.status == "SKIP" for r in results)
    failed = sum(r.status == "FAIL" for r in results)
    print(f"{passed} passed, {failed} failed, {skipped} skipped")

    if exit_code:
        print(f"worker logs kept at {artifacts}")
    elif args.no_artifacts:
        shutil.rmtree(artifacts, ignore_errors=True)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
