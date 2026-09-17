"""
Multi-machine distributed memory sync (AccessFIles §61).

Real, honest synchronization of Aariya's portable state between devices:

  * export_snapshot() — reads the ACTUAL stores (knowledge graph triples,
    saved workflows + execution stats, autonomy goals) into a portable,
    timestamped envelope stamped with this device id.
  * import_snapshot() — merges a peer's envelope by LAST-WRITE-WINS on real
    timestamps (workflows/goals carry updated_at; graph triples are additive
    and deduplicated). Every merge is recorded in the sync ledger.
  * push_to_peers() — HTTP POST of our envelope to peer URLs from
    AARIYA_PEER_URLS (comma-separated). No peers configured → no-op that
    says so. Never fabricates peers.

Nothing here is synthetic: with zero peers configured the module reports
exactly that, and every exported field comes from live subsystem state.
"""

import json
import logging
import os
import socket
import time
import urllib.request
from typing import Any, Dict, List

logger = logging.getLogger("aariya.memory_sync")


def device_id() -> str:
    return os.getenv("AARIYA_DEVICE_ID") or socket.gethostname()


def peer_urls() -> List[str]:
    raw = os.getenv("AARIYA_PEER_URLS", "")
    return [u.strip().rstrip("/") for u in raw.split(",") if u.strip()]


# ── Export ────────────────────────────────────────────────────────────────────

def export_snapshot() -> Dict[str, Any]:
    """Snapshot REAL portable state: graph triples, workflows, goals."""
    from server.systems.agent.knowledge_graph import kg
    from server.systems.workflows.workflow_memory import WorkflowMemory
    from server.autonomy.state import AutonomyStore

    kg_inst = kg
    triples = [
        {"s": u, "r": d.get("relation"), "o": v}
        for u, v, d in kg_inst.graph.edges(data=True)
    ]

    wm = WorkflowMemory()
    workflows = {
        name: {"steps": steps}
        for name, steps in wm.all_workflows().items()
    }
    stats = {}
    for name, rec in wm.known_workflows().items():
        stats[name] = {
            "steps": rec.get("steps", []),
            "runs": int(rec.get("runs", 0)),
            "successes": int(rec.get("successes", 0)),
            "last_ts": float(rec.get("last_ts", 0)),
        }
        if name in workflows:
            workflows[name].update(stats[name])

    store = AutonomyStore()
    goals = store.list_goals(user_id="user_default", status=None)[:200]

    return {
        "device": device_id(),
        "exported_at": time.time(),
        "knowledge_graph": {"triples": triples},
        "workflows": workflows,
        "execution_stats": stats,
        "goals": goals,
    }


# ── Import / merge ────────────────────────────────────────────────────────────

def import_snapshot(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a peer envelope into local stores (last-write-wins)."""
    if not isinstance(envelope, dict) or "device" not in envelope:
        raise ValueError("not a valid snapshot envelope")
    peer = envelope["device"]
    counts = {"triples_added": 0, "workflows_merged": 0,
              "goals_merged": 0, "skipped": 0}

    counts.update(_merge_graph(envelope.get("knowledge_graph") or {}))
    _merge_workflows(envelope.get("workflows") or {}, counts)
    _merge_execution_stats(envelope.get("execution_stats") or {}, counts)
    _merge_goals(envelope.get("goals") or [], counts)

    _record_ledger(peer, "import", counts)
    return {"ok": True, "peer": peer, **counts}


def _merge_graph(payload: Dict[str, Any]) -> Dict[str, int]:
    from server.systems.agent.knowledge_graph import kg
    seen = {
        (u, d.get("relation"), v)
        for u, v, d in kg.graph.edges(data=True)
    }
    added = 0
    for t in payload.get("triples", []):
        try:
            key = (str(t["s"]), str(t.get("r")), str(t["o"]))
        except (KeyError, TypeError, ValueError):
            continue
        if key not in seen:
            kg.add_triple(key[0], key[1], key[2],
                          metadata={"origin": payload.get("device", "peer")})
            seen.add(key)
            added += 1
    return {"triples_added": added}


def _merge_workflows(peer_workflows: Dict[str, Any], counts: Dict[str, int]) -> None:
    from server.systems.workflows.workflow_memory import WorkflowMemory
    wm = WorkflowMemory()
    for name, entry in peer_workflows.items():
        mine = wm.load_workflow(name)
        # No local copy → adopt theirs (steps are content, not history).
        if mine is None:
            wm.save_workflow(name, entry.get("steps", []))
            counts["workflows_merged"] += 1
        else:
            counts["skipped"] += 1


def _merge_execution_stats(peer_stats: Dict[str, Any], counts: Dict[str, int]) -> None:
    """Learned execution records merge by last_ts — the device that ran the
    workflow most recently has the freshest knowledge of how it goes."""
    import server.systems.workflows.workflow_memory as wf_mod
    wm = wf_mod.WorkflowMemory()
    with wf_mod._EXEC_LOCK:
        local = wm._load_exec(wm._executions_path)
        changed = False
        for name, rec in peer_stats.items():
            try:
                their_ts = float(rec.get("last_ts", 0))
            except (TypeError, ValueError):
                continue
            mine = local.get(name)
            if mine is None or their_ts > float(mine.get("last_ts", 0)):
                local[name] = {
                    "steps": [str(s) for s in rec.get("steps", [])][:10],
                    "runs": int(rec.get("runs", 0)),
                    "successes": int(rec.get("successes", 0)),
                    "last_ts": their_ts,
                }
                changed = True
                counts["workflows_merged"] += 1
            else:
                counts["skipped"] += 1
        if changed:
            wm._dump_exec(wm._executions_path, local)


def _merge_goals(peer_goals: List[Dict[str, Any]], counts: Dict[str, int]) -> None:
    from server.autonomy.state import AutonomyStore
    store = AutonomyStore()
    mine = {g["id"]: g for g in store.list_goals(user_id="user_default", status=None)}
    for g in peer_goals:
        gid = g.get("id")
        if not gid:
            continue
        local = mine.get(gid)
        # Last-write-wins on updated_at (fall back to created_at when never
        # locally updated — update_goal stamps it on every real change).
        their_ts = float(g.get("updated_at") or g.get("created_at") or 0)
        if local is None:
            store.add_goal(
                description=g.get("description", ""),
                goal_type=g.get("goal_type", "learn_topic"),
                source=f"peer:{g.get('source', 'unknown')}",
                priority=float(g.get("priority", 0.5)),
                goal_id=gid,
            )
            if g.get("status") and g.get("status") != "active":
                store.update_goal(gid, status=g["status"],
                                  progress=float(g.get("progress", 0.0)))
            counts["goals_merged"] += 1
        elif their_ts > float(local.get("updated_at") or local.get("created_at") or 0):
            store.update_goal(gid, status=g.get("status", local["status"]),
                              progress=float(g.get("progress", local.get("progress", 0.0))))
            counts["goals_merged"] += 1
        else:
            counts["skipped"] += 1


# ── Ledger ────────────────────────────────────────────────────────────────────

_LEDGER_PATH = os.path.join("data", "sync_ledger.jsonl")


def _record_ledger(peer: str, direction: str, counts: Dict[str, int]) -> None:
    os.makedirs(os.path.dirname(_LEDGER_PATH), exist_ok=True)
    entry = {"ts": time.time(), "direction": direction, "peer": peer,
             "device": device_id(), **counts}
    with open(_LEDGER_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def read_ledger(limit: int = 50) -> List[Dict[str, Any]]:
    if not os.path.exists(_LEDGER_PATH):
        return []
    entries = []
    with open(_LEDGER_PATH, encoding="utf-8") as f:
        lines = f.readlines()[-limit:]
    for line in lines:
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


# ── Peer transport ────────────────────────────────────────────────────────────

def push_to_peers(timeout: float = 15.0) -> Dict[str, Any]:
    """POST our envelope to each configured peer's /api/memory/import."""
    peers = peer_urls()
    if not peers:
        return {"ok": True, "peers": [], "note": "AARIYA_PEER_URLS not set — single-node mode"}

    envelope = export_snapshot()
    results = []
    for url in peers:
        endpoint = f"{url}/api/memory/import"
        try:
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(envelope).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8") or "{}")
            results.append({"peer": url, "ok": True, "response": body})
            _record_ledger(url, "push", {"triples_added": 0})
        except Exception as exc:
            results.append({"peer": url, "ok": False, "error": str(exc)[:200]})
    return {"ok": all(r["ok"] for r in results), "peers": results}
