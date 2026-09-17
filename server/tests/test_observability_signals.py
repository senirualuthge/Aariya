"""
Observability ↔ signal-bus integration:

  * StructuredLogger WARN/ERROR must emit a REAL Signal — persisted to the
    signals table and mirrored onto the admin bus (dashboard Event Log).
    (This path was dead-on-arrival before: it imported SignalSource /
    SignalPayload / SignalContext, which never existed.)
  * Every structured log line feeds the dashboard brain-log ring so mobile
    analytics brain_logs show real server activity.
  * dashboard_ws.py defines NO routes — /ws/dashboard/stream is owned solely
    by main.py (regression guard against the shadowing bug it once caused).
"""

import pytest


@pytest.fixture()
def isolated_ingest_bus():
    """Fresh IngestBus singleton per test (it caches table-ready state)."""
    import server.infrastructure.signal_bus as isb
    old = isb._ingest_bus
    isb._ingest_bus = None
    yield
    isb._ingest_bus = old


def test_error_log_persists_real_signal(isolated_db, isolated_ingest_bus):
    from server.infrastructure.observability import StructuredLogger

    log = StructuredLogger("aariya-test")
    log.error("turn failed", error="boom", session_id="s-42")

    from server.db import get_db_connection
    conn = get_db_connection()
    row = conn.execute(
        "SELECT type, severity, source, payload FROM signals "
        "ORDER BY timestamp DESC LIMIT 1").fetchone()
    conn.close()

    assert row is not None, "ERROR log must persist a signal"
    assert row["type"] == "bug" and row["severity"] == "critical"
    assert row["source"] == "aariya-test"
    payload = __import__("json").loads(row["payload"])
    assert payload["title"] == "turn failed"
    assert payload["description"] == "boom"


def test_warn_log_mirrors_onto_admin_bus(isolated_db, isolated_ingest_bus):
    from server.infrastructure.observability import StructuredLogger
    from server.systems.signal_bus import bus as admin_bus

    before = len(admin_bus.active_signals)
    StructuredLogger("aariya-test").warn("cache miss rate high")

    titles = [s.get("payload", {}).get("title", "")
              for s in admin_bus.active_signals[before:]]
    assert any("cache miss rate high" in t for t in titles)


def test_info_line_feeds_brain_log_ring(isolated_db):
    from server.infrastructure.observability import StructuredLogger
    from server.routers.dashboard_ws import _brain_log_ring, push_brain_log

    push_brain_log("[BOOT] ring online")
    n = len(_brain_log_ring)
    StructuredLogger("aariya-test").info("cognitive turn complete")

    assert len(_brain_log_ring) == n + 1
    assert "cognitive turn complete" in _brain_log_ring[0]


def test_dashboard_ws_defines_no_routes():
    """/ws/dashboard/stream must be registered ONLY in main.py — a second
    definition shadowed web chat once already."""
    import server.routers.dashboard_ws as dw
    assert not hasattr(dw, "router"), (
        "dashboard_ws must not define an APIRouter; the live endpoint lives "
        "in main.py")
