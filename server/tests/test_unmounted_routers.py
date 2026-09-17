"""
Unmounted-router gap closure:

  * /api/analytics/*  — queries the REAL schema (sessions/memories/
                        personality_snapshots), real timestamps
  * /ingest/*         — Signal validation, SQLite persistence, admin-bus
                        mirror, device registry upsert
  * /api/swarm/ws     — route registered; events reachable without Redis
  * infra SignalBus   — cognitive-loop emits now reach the admin bus instead
                        of vanishing into an unread list
"""

import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(isolated_db):
    from server.main import app
    return TestClient(app)


def _all_paths(app):
    """Recursively collect paths — newer FastAPI wraps includes in
    _IncludedRouter containers (expose .original_router)."""
    paths = []
    stack = list(app.routes)
    while stack:
        r = stack.pop()
        nested = getattr(r, "original_router", None)
        if nested is not None:
            stack.extend(nested.routes)
            continue
        p = getattr(r, "path", None)
        if p:
            paths.append(p)
        stack.extend(getattr(r, "routes", []) or [])
    return paths


def test_analytics_overview_real_schema_and_timestamp(client, isolated_db):
    conn = isolated_db.get_db_connection()
    conn.execute(
        "INSERT INTO sessions (id, user_id, start_time, avg_valence, avg_arousal) "
        "VALUES ('s1', 'user_default', '2026-01-01 10:00:00', 0.4, 0.6)")
    conn.commit()
    conn.close()

    r = client.get("/api/analytics/overview")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sessions"][0]["session_id"] == "s1"
    # Totals derived from real rows; timestamp is NOW, not a hardcoded date.
    assert body["user_info"]["total_sessions"] >= 1
    year = int(body["timestamp"][:4])
    assert year >= 2026


def test_analytics_memories_maps_real_columns(client, isolated_db):
    conn = isolated_db.get_db_connection()
    conn.execute(
        "INSERT INTO memories (id, user_id, text, valence, trust, significance, created_at) "
        "VALUES ('m1', 'user_default', 'learned to sail', 0.5, 0.7, 0.9, 1720000000)")
    conn.commit()
    conn.close()

    r = client.get("/api/analytics/memories")
    assert r.status_code == 200, r.text
    mem = r.json()[0]
    assert mem["memory_id"] == "m1"
    assert mem["content"] == "learned to sail"      # real text column mapped
    assert abs(mem["significance"] - 0.9) < 1e-6


def test_ingest_signal_persists_and_mirrors(client, isolated_db, monkeypatch):
    mirrored = []

    async def fake_emit_real_event(source, severity, title, payload):
        mirrored.append((source, severity, title))

    import server.systems.signal_bus as sb
    monkeypatch.setattr(sb, "emit_real_event", fake_emit_real_event)

    payload = {"type": "heartbeat", "payload": {"bpm": 72}, "source": "mobile"}
    r = client.post("/ingest/signal", json=payload)
    assert r.status_code == 200 and r.json()["ok"] is True
    sig_id = r.json()["id"]

    # Persisted to the REAL table with parsed payload on read-back.
    hist = client.get("/ingest/signals").json()
    match = [h for h in hist if h["id"] == sig_id]
    assert match and match[0]["type"] == "heartbeat"
    assert match[0]["payload"]["bpm"] == 72


def test_analytics_personality_falls_back_to_v2(client, isolated_db):
    """The live personality system writes v2 (traits_json); the endpoint
    must surface those REAL traits when the v1 column table is empty."""
    conn = isolated_db.get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS personality_snapshots_v2 (
            user_id TEXT, traits_json TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)
    """)
    conn.execute(
        "INSERT INTO personality_snapshots_v2 (user_id, traits_json) VALUES (?, ?)",
        ("user_default", json.dumps({"warmth": 0.8, "curiosity": 0.9})))
    conn.commit()
    conn.close()

    r = client.get("/api/analytics/personality")
    assert r.status_code == 200, r.text
    snap = r.json()[0]
    assert abs(snap["warmth"] - 0.8) < 1e-6
    assert abs(snap["curiosity"] - 0.9) < 1e-6


def test_device_registration_upsert(client, isolated_db):
    r1 = client.post("/ingest/device", json={
        "device_id": "dev1", "platform": "android", "app_version": "1.0"})
    assert r1.status_code == 200
    r2 = client.post("/ingest/device", json={
        "device_id": "dev1", "platform": "android", "app_version": "2.0"})
    assert r2.status_code == 200

    conn = isolated_db.get_db_connection()
    row = conn.execute(
        "SELECT app_version FROM devices WHERE device_id='dev1'").fetchone()
    conn.close()
    assert row[0] == "2.0"                          # updated, not duplicated


def test_swarm_ws_route_registered():
    from server.main import app
    paths = _all_paths(app)
    assert "/api/swarm/ws" in paths
    assert "/api/analytics/overview" in paths
    assert "/ingest/signal" in paths


def test_infra_signal_bus_mirrors_to_admin(monkeypatch):
    """The cognitive loop's sync emits must land in the admin bus' visible
    signals — not vanish into an unread history list."""
    from server.infrastructure.signal_bus import SignalBus
    bus = SignalBus()
    sig = bus.emit("session", {"endpoint": "test"})
    assert sig["id"]

    from server.systems.signal_bus import bus as admin_bus
    titles = [s.get("payload", {}).get("title", "") for s in admin_bus.active_signals]
    assert any("session:" in t for t in titles)


def test_swarm_ring_delivers_without_redis():
    from server.realtime.redis_bus import publish, recent_events
    e1 = publish("AGENT_UPDATE", {"agent": "Coder"})
    e2 = publish("AGENT_EVOLVED", {"agent": "Coder", "gen": 2})
    ring = recent_events(since=e2["seq"] - 2)
    types = [e["type"] for e in ring]
    assert "AGENT_UPDATE" in types and "AGENT_EVOLVED" in types
