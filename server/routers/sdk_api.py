"""
SDK API Routes — Public-facing REST contract for the HumanAI SDK.

Provides endpoints for:
- Trust: query, update, history
- Emotion: contradiction metrics, consistency scores
- Memory: write, read, delete (trust-gated)
- Audit: event log, replay snapshots, integrity verification
- Kill Switches: flag status, toggle, audit log
- Language: session language stats

All endpoints are session-scoped and respect kill-switch gating.
"""

import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from server.systems.trust_system import get_trust_system
from server.systems.contradiction_detector import get_contradiction_detector
from server.systems.kill_switches import get_kill_switches, FeatureFlag
from server.systems.audit_logger import get_audit_logger, AuditEventType

router = APIRouter(prefix="/api/sdk", tags=["SDK"])


# ── Session store (in-memory, keyed by session_id) ─────────────────────────────
_sdk_sessions: Dict[str, Dict[str, Any]] = {}


# ── Request / Response models ─────────────────────────────────────────────────

class SDKInitRequest(BaseModel):
    sdk_key: str = Field(..., description="SDK API key")
    device_id: str = Field(..., description="Hashed device identifier")
    capabilities: Dict[str, bool] = Field(
        default_factory=lambda: {"voice": True, "avatar": True, "memory": True},
        description="Client capabilities",
    )


class ConversationInputRequest(BaseModel):
    text: str = Field(..., description="User text (post-ASR or direct)")
    language: str = Field("en", description="Detected language code")
    session_id: str = Field("", description="Voice session ID")


class TrustUpdateRequest(BaseModel):
    delta: float = Field(..., description="Trust change amount (-1.0 to 1.0)")
    reason: str = Field("", description="Reason for the trust update")
    trigger_event: str = Field("api_update", description="Event that triggered this update")


class MemoryWriteRequest(BaseModel):
    content: str = Field(..., description="Memory content to store")
    memory_type: str = Field("preference", description="Type of memory")
    ttl_days: int = Field(30, description="Time-to-live in days")
    session_id: str = Field("", description="Session ID for traceability")


class MemoryDeleteRequest(BaseModel):
    memory_id: Optional[str] = Field(None, description="Specific memory ID to delete, or None for all")


class KillSwitchToggleRequest(BaseModel):
    flag: str = Field(..., description="Flag name to toggle")
    enabled: bool = Field(..., description="New state")
    reason: str = Field("manual toggle", description="Reason for the change")


class EmotionCapRequest(BaseModel):
    cap: float = Field(..., ge=0.0, le=1.0, description="Emotion intensity cap (0.0-1.0)")
    reason: str = Field("manual adjustment", description="Reason for change")


# ── SDK Init & Lifecycle (Gaps 1, 5) ──────────────────────────────────────────

@router.post("/init")
async def sdk_init(req: SDKInitRequest):
    """Initialize an SDK session (Gap 1). Returns session_id + enabled features."""
    # Validate SDK key against env (spec: sdk_key = os.getenv('SDK_API_KEY'))
    import os
    expected_key = os.getenv("SDK_API_KEY", "")
    if expected_key and req.sdk_key != expected_key:
        raise HTTPException(status_code=401, detail="Invalid SDK API key")
    from uuid import uuid4
    session_id = str(uuid4())
    ks = get_kill_switches()
    features = {
        "emotion": ks.is_enabled(FeatureFlag.EMOTION_TRACKING),
        "trust": ks.is_enabled(FeatureFlag.TRUST_GATING),
        "audit": ks.is_enabled(FeatureFlag.AUDIT_LOGGING),
        "memory": ks.is_enabled(FeatureFlag.MEMORY_WRITE),
        "micro_expressions": ks.is_enabled(FeatureFlag.MICRO_EXPRESSIONS),
        "multi_language": ks.is_enabled(FeatureFlag.MULTI_LANGUAGE),
    }
    _sdk_sessions[session_id] = {
        "device_id": req.device_id,
        "capabilities": req.capabilities,
        "features": features,
        "created_at": time.time(),
    }
    audit = get_audit_logger()
    audit.log(AuditEventType.SESSION_START, session_id, req.device_id,
              data={"sdk_key": req.sdk_key[:8] + "...", "capabilities": req.capabilities})
    return {"session_id": session_id, "features": features}


@router.post("/shutdown")
async def sdk_shutdown(session_id: str = Query(...)):
    """Shutdown an SDK session (Gap 5)."""
    if session_id in _sdk_sessions:
        del _sdk_sessions[session_id]
    audit = get_audit_logger()
    audit.log(AuditEventType.SESSION_END, session_id, "",
              data={"reason": "sdk_shutdown"})
    return {"status": "shutdown", "session_id": session_id}


# ── Conversation API (Gap 17) ─────────────────────────────────────────────────

@router.post("/conversation/input")
async def conversation_input(req: ConversationInputRequest, user_id: str = Query("user_default")):
    """Submit user text for AI processing (Gap 17)."""
    ts = get_trust_system()
    trust = ts.get_trust_score(user_id)
    audit = get_audit_logger()
    audit.log(AuditEventType.VOICE_ASR_RESULT, req.session_id or "sdk_api", user_id,
              data={"text_length": len(req.text), "language": req.language, "source": "rest"})
    return {
        "status": "accepted",
        "text": req.text,
        "language": req.language,
        "trust": round(trust, 4),
    }


@router.get("/conversation/response")
async def conversation_response(session_id: str = Query(""), user_id: str = Query("user_default")):
    """Get the latest AI response for a session (Gap 17)."""
    audit = get_audit_logger()
    events = audit.get_events(event_type="brain.response", session_id=session_id, limit=1)
    if not events:
        return {"text": "", "emotion": "neutral", "intent": "none"}
    latest = events[-1]
    return {
        "text": latest.get("data", {}).get("text", ""),
        "emotion": latest.get("data", {}).get("emotion", "neutral"),
        "intent": latest.get("data", {}).get("intent", "assist"),
        "expressiveness": latest.get("data", {}).get("emotion_intensity", 0.5),
        "follow_up": False,
    }


# ── Trust endpoints ───────────────────────────────────────────────────────────

@router.get("/trust/state")
async def trust_state(user_id: str = Query("user_default")):
    """Get current trust state for a user (Gap 18: real trend)."""
    ts = get_trust_system()
    trust = ts.get_trust_score(user_id)
    effective = ts.get_effective_trust(user_id)
    tier = ts.get_trust_tier(trust)
    gates = ts.get_trust_gates(trust)

    # Gap 18: Compute real trust trend from recent audit events
    audit = get_audit_logger()
    trust_events = audit.get_events(event_type="trust.update", limit=10)
    trend = "stable"
    if len(trust_events) >= 2:
        deltas = [e.get("data", {}).get("trust_delta", 0) for e in trust_events]
        recent = deltas[-5:]  # last 5 deltas
        avg_delta = sum(recent) / len(recent)
        if avg_delta > 0.01:
            trend = "rising"
        elif avg_delta < -0.01:
            trend = "falling"

    return {
        "trust": round(trust, 4),
        "effective_trust": round(effective, 4),
        "tier": tier.value,
        "gates": {
            "emotion_intensity_cap": gates.emotion_intensity_cap,
            "disclosure_level": gates.disclosure_level,
            "memory_depth": gates.memory_depth,
            "humor_risk_allowed": gates.humor_risk_allowed,
            "vulnerability_level": gates.vulnerability_level,
        },
        "micro_signals": ts.get_active_micro_signals(),
        "trend": trend,
    }


@router.post("/trust/update")
async def trust_update(req: TrustUpdateRequest, user_id: str = Query("user_default")):
    """Update trust score with delta and reason."""
    ts = get_trust_system()
    ks = get_kill_switches()

    if not ks.is_enabled(FeatureFlag.TRUST_GATING):
        raise HTTPException(status_code=403, detail="Trust gating is disabled by kill switch")

    old_trust, new_trust = ts.update_trust(
        user_id=user_id,
        session_id="sdk_api",
        session_valence=req.delta,
        contradiction_history=0.0,
        continuity_score=0.5,
        trigger_event=req.trigger_event,
    )

    # Audit log
    audit = get_audit_logger()
    audit.log_trust_event(
        session_id="sdk_api", user_id=user_id,
        trust_before=old_trust, trust_after=new_trust,
        reason=req.reason, trigger_event=req.trigger_event,
    )

    return {
        "trust_before": round(old_trust, 4),
        "trust_after": round(new_trust, 4),
        "delta": round(new_trust - old_trust, 4),
        "reason": req.reason,
    }


# ── Emotion endpoints ─────────────────────────────────────────────────────────

@router.get("/emotion/contradiction")
async def emotion_contradiction(user_id: str = Query("user_default")):
    """Get contradiction metrics for a user."""
    cd = get_contradiction_detector()
    from server.infrastructure.redis_manager import get_redis
    redis = get_redis()
    ema = redis.get_contradiction_history(user_id) or 0.0
    uncertainty = cd.calculate_uncertainty_modifier(ema)
    suspicion = cd.check_suspicion_trigger(ema)
    return {
        "contradiction_ema": round(ema, 4),
        "uncertainty_modifier": round(uncertainty, 4),
        "suspicion_triggered": suspicion,
        "thresholds": {
            "suspicion_threshold": 0.6,
            "uncertainty_k": 0.7,
        },
    }


# ── Memory endpoints (trust-gated) ───────────────────────────────────────────

@router.post("/memory/write")
async def memory_write(req: MemoryWriteRequest, user_id: str = Query("user_default")):
    """Write a memory entry (trust-gated, TTL-enforced, Gap 12).

    Voice-session memory was removed with the voice pipeline; SDK memory
    endpoints now return 501 until a non-voice memory backend is wired.
    """
    raise HTTPException(status_code=501, detail="Memory backend removed with voice pipeline")


@router.get("/memory/read")
async def memory_read(
    user_id: str = Query("user_default"),
    memory_type: Optional[str] = Query(None),
    limit: int = Query(10, le=50),
):
    """Read memories for a user (Gap 20)."""
    raise HTTPException(status_code=501, detail="Memory backend removed with voice pipeline")


@router.delete("/memory/delete")
async def memory_delete(req: MemoryDeleteRequest, user_id: str = Query("user_default")):
    """Delete memory entries (Gap 20)."""
    raise HTTPException(status_code=501, detail="Memory backend removed with voice pipeline")


# ── Audit endpoints ───────────────────────────────────────────────────────────

@router.get("/audit/events")
async def audit_events(
    event_type: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
):
    """Query audit events with optional filters."""
    audit = get_audit_logger()
    events = audit.get_events(event_type=event_type, session_id=session_id, limit=limit)
    return {"events": events, "count": len(events)}


@router.get("/audit/replay")
async def audit_replay(session_id: Optional[str] = Query(None), limit: int = Query(20, le=100)):
    """Get deterministic replay snapshots for compliance audits."""
    audit = get_audit_logger()
    snapshots = audit.get_replay_snapshots(session_id=session_id, limit=limit)
    return {"snapshots": snapshots, "count": len(snapshots)}


@router.get("/audit/stats")
async def audit_stats():
    """Get audit event statistics."""
    audit = get_audit_logger()
    return audit.snapshot()


# ── Avatar endpoints (Gap 6: server-side blendshape mapping) ─────────────────

@router.get("/avatar/blendshapes")
async def avatar_blendshapes(emotion: str = Query("neutral"), intensity: float = Query(0.5)):
    """Get pre-computed blendshape weights for an emotion (Gap 6)."""
    raise HTTPException(status_code=501, detail="Avatar bridge removed with voice pipeline")


@router.get("/avatar/emotion-map")
async def avatar_emotion_map():
    """Get the full emotion → blendshape mapping table."""
    raise HTTPException(status_code=501, detail="Avatar bridge removed with voice pipeline")


@router.get("/audit/verify/{event_id}")
async def audit_verify(event_id: str):
    """Verify an audit event's integrity checksum."""
    audit = get_audit_logger()
    valid = audit.verify_integrity(event_id)
    return {"event_id": event_id, "integrity_valid": valid}


# ── Kill Switch endpoints ─────────────────────────────────────────────────────

@router.get("/killswitches/state")
async def killswitches_state():
    """Get all kill-switch states."""
    ks = get_kill_switches()
    return ks.snapshot()


@router.post("/killswitches/toggle")
async def killswitches_toggle(req: KillSwitchToggleRequest):
    """Toggle a feature flag (audit-logged)."""
    ks = get_kill_switches()
    try:
        flag = FeatureFlag(req.flag)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown flag: {req.flag}")

    event = ks.set_flag(flag, req.enabled, reason=req.reason, source="api")

    # Audit log
    audit = get_audit_logger()
    audit.log_killswitch_event(
        flag=req.flag, old_value=event.old_value, new_value=event.new_value,
        reason=req.reason, source="api",
    )

    return {
        "flag": req.flag,
        "old_value": event.old_value,
        "new_value": event.new_value,
        "reason": req.reason,
    }


@router.post("/killswitches/emotion-cap")
async def killswitches_emotion_cap(req: EmotionCapRequest):
    """Set the global emotion intensity cap."""
    ks = get_kill_switches()
    old = ks.get_emotion_cap()
    ks.set_emotion_cap(req.cap, reason=req.reason)
    return {"old_cap": old, "new_cap": req.cap, "reason": req.reason}


@router.get("/killswitches/audit")
async def killswitches_audit(limit: int = Query(30, le=100)):
    """Get kill-switch toggle audit log."""
    ks = get_kill_switches()
    return {"events": ks.get_audit_log(limit=limit)}


# ── Language endpoints ────────────────────────────────────────────────────────

@router.get("/language/stats")
async def language_stats(session_id: str = Query("default")):
    """Get language statistics for a voice session."""
    raise HTTPException(status_code=501, detail="Multilang manager removed with voice pipeline")


@router.get("/language/supported")
async def language_supported():
    """Get list of supported languages."""
    raise HTTPException(status_code=501, detail="Multilang manager removed with voice pipeline")


# ── Full system snapshot ──────────────────────────────────────────────────────

@router.get("/snapshot")
async def full_snapshot(user_id: str = Query("user_default")):
    """Full SDK system snapshot for dashboard/synoptic."""
    ts = get_trust_system()
    ks = get_kill_switches()
    audit = get_audit_logger()
    trust = ts.get_trust_score(user_id)
    return {
        "trust": {
            "score": round(trust, 4),
            "tier": ts.get_trust_tier(trust).value,
            "effective": round(ts.get_effective_trust(user_id), 4),
        },
        "kill_switches": ks.snapshot(),
        "audit": audit.snapshot(),
        "timestamp": time.time(),
    }
