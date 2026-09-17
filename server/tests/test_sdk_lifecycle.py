"""
Integration tests for SDK Init, Session Lifecycle, and REST endpoints.

Covers:
- POST /api/sdk/init — session creation, feature resolution, API key validation
- POST /api/sdk/shutdown — session teardown, audit logging
- POST /api/sdk/conversation/input — text submission
- GET /api/sdk/conversation/response — response retrieval
- GET /api/sdk/trust/state — trust query with real trend
- POST /api/sdk/trust/update — trust modification
- POST /api/sdk/memory/write — trust-gated TTL memory write
- GET /api/sdk/memory/read — memory retrieval
- DELETE /api/sdk/memory/delete — memory deletion
- Full lifecycle: init → conversation → trust → memory → shutdown

All tests use isolated subsystem instances (no real Redis/DB).
"""

import asyncio
import os
import sys
import time
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.systems.kill_switches import KillSwitchSystem, FeatureFlag
from server.systems.audit_logger import AuditLogger, AuditEventType
from server.systems.trust_system import TrustSystem


# ── Helpers ──────────────────────────────────────────────────────────────────

class FakeRedis:
    """In-memory Redis mock for trust/memory store."""
    def __init__(self):
        self._store = {}
        self._ts = {}

    def get_trust_score(self, uid):
        return self._store.get(uid)

    def set_trust_score(self, uid, score):
        self._store[uid] = score

    def get(self, key):
        return self._ts.get(key)

    def set(self, key, val):
        self._ts[key] = val

    def delete(self, key):
        self._ts.pop(key, None)


def _patch_singletons():
    """Patch global singletons with isolated test instances. Returns context manager."""
    import server.systems.kill_switches as ks_mod
    import server.systems.audit_logger as audit_mod
    import server.systems.trust_system as trust_mod

    ks = KillSwitchSystem()
    ks._emotion_cap = 0.8
    for flag in FeatureFlag:
        ks._flags[flag.value] = True

    audit = AuditLogger(max_buffer=1000)
    ts = TrustSystem()
    fake_redis = FakeRedis()
    ts.redis = fake_redis
    ts.redis.set_trust_score("user_default", 0.5)

    old_ks = ks_mod._kill_switches
    old_audit = audit_mod._audit_logger
    old_trust = trust_mod._trust_system

    ks_mod._kill_switches = ks
    audit_mod._audit_logger = audit
    trust_mod._trust_system = ts

    return ks, audit, ts, old_ks, old_audit, old_trust


def _restore_singletons(old_ks, old_audit, old_trust):
    """Restore original singletons."""
    import server.systems.kill_switches as ks_mod
    import server.systems.audit_logger as audit_mod
    import server.systems.trust_system as trust_mod

    ks_mod._kill_switches = old_ks
    audit_mod._audit_logger = old_audit
    trust_mod._trust_system = old_trust


def _clear_sdk_sessions():
    """Clear the in-memory session store."""
    from server.routers.sdk_api import _sdk_sessions
    _sdk_sessions.clear()


def _make_client():
    """Create a FastAPI TestClient with isolated singletons."""
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    from server.routers.sdk_api import router as sdk_router

    app = FastAPI()
    app.include_router(sdk_router)
    return TestClient(app)


# ═══════════════════════════════════════════════════════════════════════════════
# SDK Init
# ═══════════════════════════════════════════════════════════════════════════════

class TestSDKInit:

    def setup_method(self):
        _clear_sdk_sessions()
        self.patches = _patch_singletons()
        self.ks, self.audit, self.ts, self.old_ks, self.old_audit, self.old_trust = self.patches
        self.client = _make_client()

    def teardown_method(self):
        _restore_singletons(self.old_ks, self.old_audit, self.old_trust)
        _clear_sdk_sessions()

    def test_init_returns_session_id_and_features(self):
        resp = self.client.post("/api/sdk/init", json={
            "sdk_key": "test_key_123",
            "device_id": "device_abc",
            "capabilities": {"voice": True, "avatar": True, "memory": True},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "session_id" in data
        assert isinstance(data["session_id"], str)
        assert len(data["session_id"]) > 0
        assert "features" in data
        assert isinstance(data["features"], dict)
        # All features should be True (all kill switches enabled)
        for key in ["emotion", "trust", "audit", "memory", "micro_expressions", "multi_language"]:
            assert key in data["features"]
            assert data["features"][key] is True

    def test_init_session_persisted(self):
        resp = self.client.post("/api/sdk/init", json={
            "sdk_key": "key", "device_id": "dev1",
        })
        session_id = resp.json()["session_id"]
        # Session should be accessible via shutdown
        resp2 = self.client.post(f"/api/sdk/shutdown?session_id={session_id}")
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "shutdown"

    def test_init_reflects_disabled_flags(self):
        self.ks.set_flag(FeatureFlag.EMOTION_TRACKING, False, reason="test")
        self.ks.set_flag(FeatureFlag.MEMORY_WRITE, False, reason="test")
        resp = self.client.post("/api/sdk/init", json={
            "sdk_key": "key", "device_id": "dev1",
        })
        features = resp.json()["features"]
        assert features["emotion"] is False
        assert features["memory"] is False
        assert features["trust"] is True  # still enabled

    def test_init_logs_session_start(self):
        resp = self.client.post("/api/sdk/init", json={
            "sdk_key": "key", "device_id": "dev_xyz",
        })
        session_id = resp.json()["session_id"]
        events = self.audit.get_events(event_type="session.start", session_id=session_id)
        assert len(events) >= 1
        # user_id is stored in the AuditEvent's user_id field, not in data
        assert events[-1]["user_id"] == "dev_xyz"

    def test_init_custom_capabilities(self):
        resp = self.client.post("/api/sdk/init", json={
            "sdk_key": "key", "device_id": "dev1",
            "capabilities": {"voice": False, "avatar": True, "memory": False},
        })
        assert resp.status_code == 200
        from server.routers.sdk_api import _sdk_sessions
        session_id = resp.json()["session_id"]
        stored = _sdk_sessions[session_id]
        assert stored["capabilities"]["voice"] is False
        assert stored["capabilities"]["memory"] is False

    def test_init_default_capabilities(self):
        resp = self.client.post("/api/sdk/init", json={
            "sdk_key": "key", "device_id": "dev1",
        })
        from server.routers.sdk_api import _sdk_sessions
        session_id = resp.json()["session_id"]
        stored = _sdk_sessions[session_id]
        assert stored["capabilities"]["voice"] is True
        assert stored["capabilities"]["avatar"] is True
        assert stored["capabilities"]["memory"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# SDK API Key Validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestSDKKeyValidation:

    def setup_method(self):
        _clear_sdk_sessions()
        self.patches = _patch_singletons()
        self.ks, self.audit, self.ts, self.old_ks, self.old_audit, self.old_trust = self.patches
        self.client = _make_client()

    def teardown_method(self):
        _restore_singletons(self.old_ks, self.old_audit, self.old_trust)
        _clear_sdk_sessions()

    def test_valid_key_accepted(self):
        os.environ["SDK_API_KEY"] = "my_secret_key"
        try:
            resp = self.client.post("/api/sdk/init", json={
                "sdk_key": "my_secret_key", "device_id": "dev1",
            })
            assert resp.status_code == 200
        finally:
            del os.environ["SDK_API_KEY"]

    def test_invalid_key_rejected(self):
        os.environ["SDK_API_KEY"] = "my_secret_key"
        try:
            resp = self.client.post("/api/sdk/init", json={
                "sdk_key": "wrong_key", "device_id": "dev1",
            })
            assert resp.status_code == 401
            assert "Invalid SDK API key" in resp.json()["detail"]
        finally:
            del os.environ["SDK_API_KEY"]

    def test_no_env_key_skips_validation(self):
        os.environ.pop("SDK_API_KEY", None)
        resp = self.client.post("/api/sdk/init", json={
            "sdk_key": "anything", "device_id": "dev1",
        })
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# SDK Shutdown
# ═══════════════════════════════════════════════════════════════════════════════

class TestSDKShutdown:

    def setup_method(self):
        _clear_sdk_sessions()
        self.patches = _patch_singletons()
        self.ks, self.audit, self.ts, self.old_ks, self.old_audit, self.old_trust = self.patches
        self.client = _make_client()

    def teardown_method(self):
        _restore_singletons(self.old_ks, self.old_audit, self.old_trust)
        _clear_sdk_sessions()

    def test_shutdown_removes_session(self):
        resp = self.client.post("/api/sdk/init", json={
            "sdk_key": "key", "device_id": "dev1",
        })
        session_id = resp.json()["session_id"]
        from server.routers.sdk_api import _sdk_sessions
        assert session_id in _sdk_sessions

        resp2 = self.client.post(f"/api/sdk/shutdown?session_id={session_id}")
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "shutdown"
        assert session_id not in _sdk_sessions

    def test_shutdown_logs_session_end(self):
        resp = self.client.post("/api/sdk/init", json={
            "sdk_key": "key", "device_id": "dev1",
        })
        session_id = resp.json()["session_id"]
        self.client.post(f"/api/sdk/shutdown?session_id={session_id}")
        events = self.audit.get_events(event_type="session.end", session_id=session_id)
        assert len(events) >= 1
        assert events[-1]["data"]["reason"] == "sdk_shutdown"

    def test_shutdown_nonexistent_session_ok(self):
        resp = self.client.post("/api/sdk/shutdown?session_id=nonexistent")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# Conversation API
# ═══════════════════════════════════════════════════════════════════════════════

class TestConversationAPI:

    def setup_method(self):
        _clear_sdk_sessions()
        self.patches = _patch_singletons()
        self.ks, self.audit, self.ts, self.old_ks, self.old_audit, self.old_trust = self.patches
        self.client = _make_client()

    def teardown_method(self):
        _restore_singletons(self.old_ks, self.old_audit, self.old_trust)
        _clear_sdk_sessions()

    def test_conversation_input_accepted(self):
        resp = self.client.post("/api/sdk/conversation/input", json={
            "text": "Hello, how are you?",
            "language": "en",
            "session_id": "sess1",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["text"] == "Hello, how are you?"
        assert data["language"] == "en"
        assert isinstance(data["trust"], float)

    def test_conversation_input_logs_asr(self):
        self.client.post("/api/sdk/conversation/input", json={
            "text": "test", "language": "es", "session_id": "sess2",
        })
        events = self.audit.get_events(event_type="voice.asr_result")
        assert len(events) >= 1
        assert events[-1]["data"]["language"] == "es"
        assert events[-1]["data"]["source"] == "rest"

    def test_conversation_response_empty_when_no_events(self):
        resp = self.client.get("/api/sdk/conversation/response?session_id=empty_session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == ""
        assert data["emotion"] == "neutral"


# ═══════════════════════════════════════════════════════════════════════════════
# Trust API
# ═══════════════════════════════════════════════════════════════════════════════

class TestTrustAPI:

    def setup_method(self):
        _clear_sdk_sessions()
        self.patches = _patch_singletons()
        self.ks, self.audit, self.ts, self.old_ks, self.old_audit, self.old_trust = self.patches
        self.client = _make_client()

    def teardown_method(self):
        _restore_singletons(self.old_ks, self.old_audit, self.old_trust)
        _clear_sdk_sessions()

    def test_trust_state_returns_full_payload(self):
        resp = self.client.get("/api/sdk/trust/state?user_id=test_u")
        assert resp.status_code == 200
        data = resp.json()
        assert "trust" in data
        assert "effective_trust" in data
        assert "tier" in data
        assert "gates" in data
        assert "trend" in data
        assert data["tier"] in ["DEFENSIVE", "GUARDED", "NEUTRAL", "WARM", "INTIMATE"]
        assert data["trend"] in ["rising", "falling", "stable"]

    def test_trust_trend_stable_by_default(self):
        resp = self.client.get("/api/sdk/trust/state")
        assert resp.json()["trend"] == "stable"

    def test_trust_update_modifies_score(self):
        # Start from neutral trust so the update has room to move
        self.ts.redis.set_trust_score("test_u", 0.5)
        resp = self.client.post("/api/sdk/trust/update?user_id=test_u", json={
            "delta": 0.15,
            "reason": "good conversation",
            "trigger_event": "test",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["trust_after"] >= data["trust_before"]

    def test_trust_update_disabled_by_killswitch(self):
        self.ks.set_flag(FeatureFlag.TRUST_GATING, False, reason="test")
        resp = self.client.post("/api/sdk/trust/update?user_id=test_u", json={
            "delta": 0.1, "reason": "test",
        })
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# Memory API (TTL-Enforced)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMemoryAPI:
    """Memory endpoints are trust-gated REST surface area kept for SDK
    compatibility; the voice-session backend was removed with the voice
    pipeline, so they respond 501 until a non-voice backend is wired."""

    def setup_method(self):
        _clear_sdk_sessions()
        self.patches = _patch_singletons()
        self.ks, self.audit, self.ts, self.old_ks, self.old_audit, self.old_trust = self.patches
        self.client = _make_client()

    def teardown_method(self):
        _restore_singletons(self.old_ks, self.old_audit, self.old_trust)
        _clear_sdk_sessions()

    def test_memory_write_returns_501(self):
        resp = self.client.post("/api/sdk/memory/write?user_id=mem_u", json={
            "content": "prefers short answers",
            "memory_type": "preference",
            "ttl_days": 30,
        })
        assert resp.status_code == 501
        assert "memory" in resp.json()["detail"].lower()

    def test_memory_read_returns_501(self):
        resp = self.client.get("/api/sdk/memory/read?user_id=read_u")
        assert resp.status_code == 501

    def test_memory_delete_returns_501(self):
        resp = self.client.request(
            "DELETE", "/api/sdk/memory/delete?user_id=del_u",
            json={"memory_id": None},
        )
        assert resp.status_code == 501


# ═══════════════════════════════════════════════════════════════════════════════
# Kill Switch API
# ═══════════════════════════════════════════════════════════════════════════════

class TestKillSwitchAPI:

    def setup_method(self):
        _clear_sdk_sessions()
        self.patches = _patch_singletons()
        self.ks, self.audit, self.ts, self.old_ks, self.old_audit, self.old_trust = self.patches
        self.client = _make_client()

    def teardown_method(self):
        _restore_singletons(self.old_ks, self.old_audit, self.old_trust)
        _clear_sdk_sessions()

    def test_get_killswitch_state(self):
        resp = self.client.get("/api/sdk/killswitches/state")
        assert resp.status_code == 200
        data = resp.json()
        assert "flags" in data
        assert "emotion_cap" in data
        assert data["flags"]["tts_enabled"] is True

    def test_toggle_killswitch(self):
        resp = self.client.post("/api/sdk/killswitches/toggle", json={
            "flag": "tts_enabled",
            "enabled": False,
            "reason": "testing",
        })
        assert resp.status_code == 200
        assert resp.json()["old_value"] is True
        assert resp.json()["new_value"] is False

    def test_toggle_invalid_flag(self):
        resp = self.client.post("/api/sdk/killswitches/toggle", json={
            "flag": "nonexistent_flag",
            "enabled": False,
        })
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# Full Lifecycle
# ═══════════════════════════════════════════════════════════════════════════════

class TestFullSDKLifecycle:

    def setup_method(self):
        _clear_sdk_sessions()
        self.patches = _patch_singletons()
        self.ks, self.audit, self.ts, self.old_ks, self.old_audit, self.old_trust = self.patches
        self.client = _make_client()

    def teardown_method(self):
        _restore_singletons(self.old_ks, self.old_audit, self.old_trust)
        _clear_sdk_sessions()

    def test_full_lifecycle(self):
        """Test init → conversation → trust query → trust update → memory write → read → shutdown."""
        # 1. Init
        resp = self.client.post("/api/sdk/init", json={
            "sdk_key": "lifecycle_key",
            "device_id": "device_lifecycle",
            "capabilities": {"voice": True, "avatar": True, "memory": True},
        })
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]
        features = resp.json()["features"]
        assert features["trust"] is True
        assert features["memory"] is True

        # 2. Conversation input
        resp = self.client.post("/api/sdk/conversation/input", json={
            "text": "What's the weather?",
            "language": "en",
            "session_id": session_id,
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

        # 3. Trust state
        resp = self.client.get("/api/sdk/trust/state?user_id=lifecycle_user")
        assert resp.status_code == 200
        initial_trust = resp.json()["trust"]
        assert 0.0 <= initial_trust <= 1.0

        # 4. Trust update
        resp = self.client.post("/api/sdk/trust/update?user_id=lifecycle_user", json={
            "delta": 0.1,
            "reason": "positive interaction",
        })
        assert resp.status_code == 200
        assert "trust_after" in resp.json()

        # 5. Verify trust didn't decrease
        resp = self.client.get("/api/sdk/trust/state?user_id=lifecycle_user")
        new_trust = resp.json()["trust"]
        assert new_trust >= initial_trust

        # 6. Memory write (backend removed with voice pipeline → 501)
        resp = self.client.post("/api/sdk/memory/write?user_id=lifecycle_user", json={
            "content": "User prefers concise answers",
            "memory_type": "preference",
            "ttl_days": 7,
        })
        assert resp.status_code == 501

        # 8. Audit events accumulated
        resp = self.client.get("/api/sdk/audit/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["total_events"] >= 3  # session.start + asr + trust update

        # 9. Kill switch state
        resp = self.client.get("/api/sdk/killswitches/state")
        assert resp.status_code == 200
        assert resp.json()["flags"]["tts_enabled"] is True

        # 10. Snapshot
        resp = self.client.get("/api/sdk/snapshot?user_id=lifecycle_user")
        assert resp.status_code == 200
        snapshot = resp.json()
        assert "trust" in snapshot
        assert "kill_switches" in snapshot
        assert "audit" in snapshot

        # 11. Shutdown
        resp = self.client.post(f"/api/sdk/shutdown?session_id={session_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "shutdown"

        # 12. Session removed
        from server.routers.sdk_api import _sdk_sessions
        assert session_id not in _sdk_sessions

        # 13. SESSION_START and SESSION_END both logged
        start_events = self.audit.get_events(event_type="session.start", session_id=session_id)
        end_events = self.audit.get_events(event_type="session.end", session_id=session_id)
        assert len(start_events) >= 1
        assert len(end_events) >= 1
