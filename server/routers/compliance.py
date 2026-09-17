"""
Compliance endpoints for GDPR / EU AI Act + companion governance.

GDPR / EU AI Act:
  * export-user-data   — Article 20 data portability.
  * delete-user-data   — Article 17 right to be forgotten.
  * personality-profile— Article 13 transparency.

Companion governance (fills the *AI Girl 2* governance gaps — previously the
revocation endpoint was a logging-only TODO):
  * consent-status / consent  — granular consent toggles with REAL feature-flag
                                enforcement (emotion_tracking, personality_drift,
                                memory_storage).
  * age-band                  — age policy locked to 18+ (no minor bands).
  * personality freeze/reset/export — drift pause, default restore, export.
  * health                    — Stability Index / Over-Attachment Risk / reviewer
                                scores (real, persisted relationship state).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from server.infrastructure.observability import logger

router = APIRouter(prefix="/api/compliance", tags=["compliance"])


# ── Request models ────────────────────────────────────────────────────────────

class ConsentUpdateRequest(BaseModel):
    user_id: str
    consent: Dict[str, bool]  # e.g. {"emotion_tracking": False, ...}


class AgeBandRequest(BaseModel):
    user_id: str
    age_band: str  # "13-17" | "18+"


class FreezeRequest(BaseModel):
    user_id: str


class FeedbackRequest(BaseModel):
    """Transparency Satisfaction feedback (*AI Girl 2* §health metrics §4)."""
    user_id: str = "user_default"
    rating: float = 0.5   # 0-1: did the system's behavior make sense?
    discomfort: bool = False  # RED-LINE: reported emotional discomfort
    note: str = ""
    action: str = ""     # "clear" → user says it's fine: clear the red-line


async def _emit_event(severity: str, title: str, payload: Dict[str, Any] | None = None) -> None:
    """Push a REAL event into the dashboard Event Log (GOVERNANCE chip).

    Best-effort: an unavailable Event Log bus never breaks a control request —
    the chained safety log inside ConsentStore already persisted the change.
    The try/except guards the lazy import (emit_real_event itself is already
    best-effort), matching the file's lazy-import convention.
    """
    try:
        from server.systems.signal_bus import emit_real_event
        await emit_real_event("GOVERNANCE", severity, title, payload)
    except Exception as exc:
        logger.debug(f"[compliance] event-log emission skipped: {exc}")


# ── GDPR / EU AI Act ──────────────────────────────────────────────────────────

class DataExportResponse(BaseModel):
    user_id: str
    export_timestamp: str
    data: Dict[str, Any]


class PersonalityProfileResponse(BaseModel):
    user_id: str
    current_personality: Dict[str, float]
    personality_history: List[Dict[str, Any]]
    model_version: str
    last_updated: str


class ConsentRevocationRequest(BaseModel):
    user_id: str
    consent_types: List[str]  # ['emotion_tracking', 'personality_drift', 'memory_storage']


@router.get("/export-user-data", response_model=DataExportResponse)
async def export_user_data(user_id: str = Query(..., description="User ID to export data for")):
    """
    Export all user data in JSON format (GDPR Article 20).
    """
    try:
        db = _db()
        db.execute_update(
            "INSERT INTO audit_logs (user_id, action_type, action_details, performed_by) VALUES (?, ?, ?, ?)",
            (user_id, 'data_export', 'User data exported via API', 'system')
        )
        data: Dict[str, Any] = {}
        for table in ("users", "personality_snapshots", "sessions", "memories",
                      "trust_history", "contradiction_history", "episodic_memory",
                      "pattern_memory"):
            try:
                rows = db.execute_query(
                    f"SELECT * FROM {table} WHERE user_id = ? ORDER BY rowid DESC LIMIT 500",
                    (user_id,)
                )
                data[table] = rows or []
            except Exception:
                data[table] = []  # table may not exist in this deployment
        # Governance bundle (consent, age band, safety events, personality files).
        try:
            from server.systems.governance.consent_store import ConsentStore
            data["governance"] = ConsentStore(user_id).status()
        except Exception as exc:
            data["governance"] = {"error": str(exc)[:120]}
        logger.info(f"Data export completed for user {user_id}")
        return DataExportResponse(
            user_id=user_id,
            export_timestamp=datetime.utcnow().isoformat() + 'Z',
            data=data,
        )
    except Exception as e:
        logger.error(f"Data export failed for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Data export failed: {str(e)}")


@router.delete("/delete-user-data")
async def delete_user_data(user_id: str = Query(..., description="User ID to delete data for")):
    """
    Delete all user data (GDPR Article 17 - Right to be Forgotten).
    """
    try:
        db = _db()
        db.execute_update(
            "INSERT INTO audit_logs (user_id, action_type, action_details, performed_by) VALUES (?, ?, ?, ?)",
            (user_id, 'data_deletion', 'All user data deleted via API', 'system')
        )
        for table in ("contradiction_history", "trust_history", "episodic_memory",
                      "pattern_memory", "memories", "personality_snapshots",
                      "sessions", "users"):
            try:
                db.execute_update(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
            except Exception:
                pass  # table may not exist
        # Also drop the JSON governance / health / evolution files.
        for suffix in ("governance_", "health_", "personality_", "transparency_"):
            try:
                import os
                path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                    "data", f"{suffix}{user_id}.json")
                if os.path.exists(path):
                    os.remove(path)
            except OSError as exc:
                logger.warn(f"[Compliance] failed to remove file for user {user_id}: {exc}")
        logger.info(f"All data deleted for user {user_id}")
        await _emit_event(
            "critical",
            f"All user data deleted for {user_id} (right to be forgotten)",
            {"user_id": user_id, "action": "delete_user_data"},
        )
        return {"status": "success", "message": f"All data for user {user_id} has been deleted"}
    except Exception as e:
        logger.error(f"Data deletion failed for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Data deletion failed: {str(e)}")


@router.get("/personality-profile", response_model=PersonalityProfileResponse)
async def get_personality_profile(user_id: str = Query(..., description="User ID")):
    """
    Get personality profile with transparency (EU AI Act Article 13).
    """
    try:
        db = _db()
        current = db.execute_query(
            "SELECT * FROM personality_snapshots WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1",
            (user_id,),
        )
        history = db.execute_query(
            "SELECT * FROM personality_snapshots WHERE user_id = ? ORDER BY timestamp DESC LIMIT 10",
            (user_id,),
        )
        if not current:
            # Fall back to the live PersonalitySystem defaults rather than 404
            # (snapshots table may be unused in this deployment).
            from server.systems.personality import PersonalitySystem
            return PersonalityProfileResponse(
                user_id=user_id,
                current_personality=PersonalitySystem(user_id).get_current_personality(),
                personality_history=[],
                model_version="personality-v3",
                last_updated=datetime.utcnow().isoformat() + 'Z',
            )
        return PersonalityProfileResponse(
            user_id=user_id,
            current_personality={
                'warmth': current[0]['warmth'],
                'energy': current[0]['energy'],
                'assertiveness': current[0]['assertiveness'],
                'formality': current[0]['formality'],
            },
            personality_history=history or [],
            model_version="1.0.0",
            last_updated=current[0]['timestamp'],
        )
    except Exception as e:
        logger.error(f"Personality profile fetch failed for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch personality profile: {str(e)}")


# ── Companion governance: consent matrix ──────────────────────────────────────

@router.get("/consent-status")
async def consent_status(user_id: str = Query("user_default")):
    """Current consent matrix + age band + freeze + recent safety events."""
    from server.systems.governance.consent_store import ConsentStore
    return ConsentStore(user_id).status()


@router.post("/consent")
async def set_consent(req: ConsentUpdateRequest):
    """Set granular consent toggles — REAL feature-flag enforcement follows."""
    from server.systems.governance.consent_store import ConsentStore, CONSENT_CATEGORIES
    store = ConsentStore(req.user_id)
    prev = store.status()["consents"]
    applied = store.set_consents(req.consent)
    unknown = [k for k in req.consent if k not in applied and k not in CONSENT_CATEGORIES]
    # Real event-log entries so the dashboard Event Log reacts to each toggle —
    # only when the value actually flipped (no fabricated events on no-ops).
    for cat, enabled in applied.items():
        if prev.get(cat) == enabled:
            continue
        await _emit_event(
            "info" if enabled else "warn",
            f"Consent {'granted' if enabled else 'revoked'} for {cat.replace('_', ' ')}",
            {"user_id": req.user_id, "category": cat, "enabled": enabled},
        )
    return {
        "status": "success",
        "applied": applied,
        "feature_flags": store.feature_flags(),
        "unknown_categories": unknown,
    }


@router.post("/revoke-consent")
async def revoke_consent(request: ConsentRevocationRequest):
    """Revoke consent for specific data processing activities (enforced)."""
    from server.systems.governance.consent_store import ConsentStore
    store = ConsentStore(request.user_id)
    prev = store.status()["consents"]
    applied = store.set_consents({t: False for t in request.consent_types})
    try:
        _db().execute_update(
            "INSERT INTO audit_logs (user_id, action_type, action_details, performed_by) VALUES (?, ?, ?, ?)",
            (request.user_id, 'consent_revocation', json.dumps(applied), 'user'),
        )
    except Exception as exc:
        logger.warn(f"[Compliance] audit log write failed for consent revocation: {exc}")
    logger.info(f"Consent revoked for user {request.user_id}: {applied}")
    for cat, enabled in applied.items():
        if prev.get(cat) == enabled:
            continue  # already revoked — nothing changed, no event
        await _emit_event(
            "warn",
            f"Consent revoked for {cat.replace('_', ' ')}",
            {"user_id": request.user_id, "category": cat, "enabled": False},
        )
    return {
        "status": "success",
        "message": f"Consent revoked for: {', '.join(request.consent_types)}",
        "user_id": request.user_id,
        "applied": applied,
    }


# ── Companion governance: age band ────────────────────────────────────────────

@router.post("/age-band")
async def set_age_band(req: AgeBandRequest):
    """Age policy is locked to 18+ — any request for a lower band is rejected.
    This endpoint only ever reports the locked 18+ state."""
    from server.systems.governance.consent_store import ConsentStore, VALID_AGE_BANDS
    if req.age_band != "18+":
        return {"status": "error", "error": "age_band is locked to 18+",
                "age_band": "18+", "guardrails_active": False}
    store = ConsentStore(req.user_id)
    store.set_age_band("18+")
    await _emit_event(
        "info",
        "Age policy locked to 18+",
        {"user_id": req.user_id, "age_band": "18+", "guardrails_active": False},
    )
    return {"status": "success", "age_band": store.age_band(),
            "guardrails": {
                "guarded_states": [],
                "max_emotion_intensity": store.max_emotion_intensity(),
            }}


# ── Companion governance: personality controls ────────────────────────────────

@router.post("/personality/freeze")
async def freeze_personality(req: FreezeRequest):
    """Pause all personality drift (sticky until unfrozen)."""
    from server.systems.governance.consent_store import ConsentStore
    store = ConsentStore(req.user_id)
    store.set_frozen(True)
    await _emit_event("info", "Personality drift frozen", {"user_id": req.user_id})
    return {"status": "success", "frozen": True, "feature_flags": store.feature_flags()}


@router.post("/personality/unfreeze")
async def unfreeze_personality(req: FreezeRequest):
    """Resume organic personality drift."""
    from server.systems.governance.consent_store import ConsentStore
    store = ConsentStore(req.user_id)
    store.set_frozen(False)
    await _emit_event("info", "Personality drift resumed", {"user_id": req.user_id})
    return {"status": "success", "frozen": False, "feature_flags": store.feature_flags()}


@router.post("/personality/reset")
async def reset_personality(req: FreezeRequest):
    """Restore the default persona (drops evolution file; next turn = baseline)."""
    from server.systems.governance.consent_store import ConsentStore
    store = ConsentStore(req.user_id)
    result = store.reset_personality()
    await _emit_event(
        "warn",
        "Personality reset to defaults",
        {"user_id": req.user_id, "removed": result.get("removed", [])},
    )
    return {"status": "success", **result}


@router.get("/personality/export")
async def export_personality(user_id: str = Query("user_default")):
    """Full personality bundle: live traits + evolution state + governance."""
    from server.systems.personality import PersonalitySystem
    from server.systems.governance.consent_store import ConsentStore
    ps = PersonalitySystem(user_id)
    evolution = {}
    try:
        import os
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            "data", f"personality_{user_id}.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                evolution = json.load(f)
    except OSError as exc:
        logger.warn(f"[Compliance] failed to load personality evolution for {user_id}: {exc}")
    return {
        "user_id": user_id,
        "exported_at": datetime.utcnow().isoformat() + 'Z',
        "current_personality": ps.get_current_personality(),
        "evolution": evolution,
        "governance": ConsentStore(user_id).status(),
    }


# ── Companion governance: health metrics ──────────────────────────────────────
# NOTE: this endpoint's shape changed from the original `{"status":"healthy"}`
# liveness check (now at /health-check) to the companion-health snapshot — the
# router was never mounted before, so nothing depended on the old shape.

@router.get("/health")
async def companion_health(user_id: str = Query("user_default")):
    """Stability Index, Over-Attachment Risk, reviewer scores + trends.

    Values come from the persisted per-turn snapshots the brain writes after
    each real turn (companion_health.compute) — never fabricated on request.
    Transparency Satisfaction merges in from its own per-user ring, and the
    Trait Activation Engine bundle rides along from the shared trait singleton
    (the last REAL brain turn's latent / active traits / voice / avatar / ui)
    so mobile + web can refresh trait state over plain REST while idle.
    """
    from server.systems.governance.companion_health import CompanionHealth
    from server.systems.governance.transparency import get_transparency
    from server.systems.trait_engine import get_trait_engine
    ch = CompanionHealth(user_id)
    latest = ch.latest()
    transparency = get_transparency(user_id).compute()
    return {
        "latest": latest,
        "trend": (latest or {}).get("trend", {}),
        "history": ch.history(30),
        "transparency": transparency,
        "trait_engine": get_trait_engine().bundle(),
    }


@router.post("/feedback")
async def submit_feedback(req: FeedbackRequest):
    """Transparency Satisfaction feedback — the user's direct voice.

    Red-line (*AI Girl 2* §4): discomfort=True immediately flips the brain's
    dial-back flag (it soothes, de-escalates and lowers initiative until the
    user signals it's fine). Returns the post-feedback transparency state so
    the panel can react instantly.
    """
    from server.systems.governance.transparency import get_transparency
    monitor = get_transparency(req.user_id)

    # Explicit "it's fine now": clear the red-line (drops unresolved discomfort
    # events — record_feedback alone can't, since old discomfort events stay
    # in the hold window and keep dial_back on).
    if req.action == "clear":
        monitor.clear_dial_back()
        state = monitor.compute()
        await _emit_event(
            "info",
            "Transparency dial-back cleared by user",
            {"user_id": req.user_id, "satisfaction": state["transparency_satisfaction"]},
        )
        return {"status": "success", "transparency": state}

    state = monitor.record_feedback(
        rating=req.rating,
        discomfort=req.discomfort,
        note=req.note,
    )
    # Real event-log entries so the dashboard Event Log reacts to the metric.
    if req.discomfort:
        await _emit_event(
            "warn",
            "Transparency red-line hit — user reported emotional discomfort",
            {"user_id": req.user_id, "rating": req.rating,
             "dial_back": state["dial_back"]},
        )
    else:
        await _emit_event(
            "info",
            f"Transparency feedback recorded (rating {req.rating:.2f})",
            {"user_id": req.user_id, "rating": req.rating,
             "satisfaction": state["transparency_satisfaction"]},
        )
    return {"status": "success", "transparency": state}


def _db():
    from server.infrastructure.postgres_manager import get_postgres
    return get_postgres()


def _band_guarded_states():
    return []  # age policy is locked to 18+ — no guarded states


@router.get("/health-check")
async def compliance_health():
    """Health check for compliance endpoints."""
    return {"status": "healthy", "service": "compliance"}
