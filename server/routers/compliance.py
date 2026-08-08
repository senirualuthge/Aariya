"""
Compliance endpoints for GDPR and EU AI Act.
Provides data export, deletion, transparency, and consent management.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
from datetime import datetime
import json

from server.infrastructure.postgres_manager import get_postgres
from server.infrastructure.observability import logger

router = APIRouter(prefix="/api/compliance", tags=["compliance"])


class DataExportResponse(BaseModel):
    """User data export response."""
    user_id: str
    export_timestamp: str
    data: Dict[str, Any]


class PersonalityProfileResponse(BaseModel):
    """Personality profile transparency response."""
    user_id: str
    current_personality: Dict[str, float]
    personality_history: List[Dict[str, Any]]
    model_version: str
    last_updated: str


class ConsentRevocationRequest(BaseModel):
    """Consent revocation request."""
    user_id: str
    consent_types: List[str]  # ['emotion_tracking', 'personality_drift', 'memory_storage']


@router.get("/export-user-data", response_model=DataExportResponse)
async def export_user_data(user_id: str = Query(..., description="User ID to export data for")):
    """
    Export all user data in JSON format (GDPR Article 20).
    
    Returns:
        Complete user data including personality, memories, sessions, trust history, etc.
    """
    try:
        db = get_postgres()
        
        # Log audit event
        db.execute_update(
            "INSERT INTO audit_logs (user_id, action_type, action_details, performed_by) VALUES (?, ?, ?, ?)",
            (user_id, 'data_export', 'User data exported via API', 'system')
        )
        
        # Collect all user data
        data = {}
        
        # User profile
        user = db.execute_query("SELECT * FROM users WHERE user_id = ?", (user_id,))
        data['user_profile'] = user[0] if user else None
        
        # Personality snapshots
        personality = db.execute_query(
            "SELECT * FROM personality_snapshots WHERE user_id = ? ORDER BY timestamp DESC",
            (user_id,)
        )
        data['personality_history'] = personality or []
        
        # Sessions
        sessions = db.execute_query(
            "SELECT * FROM sessions WHERE user_id = ? ORDER BY start_time DESC",
            (user_id,)
        )
        data['sessions'] = sessions or []
        
        # Memories
        memories = db.execute_query(
            "SELECT * FROM memories WHERE user_id = ? ORDER BY timestamp DESC",
            (user_id,)
        )
        data['memories'] = memories or []
        
        # Trust history
        trust = db.execute_query(
            "SELECT * FROM trust_history WHERE user_id = ? ORDER BY timestamp DESC",
            (user_id,)
        )
        data['trust_history'] = trust or []
        
        # Contradiction history
        contradiction = db.execute_query(
            "SELECT * FROM contradiction_history WHERE user_id = ? ORDER BY timestamp DESC",
            (user_id,)
        )
        data['contradiction_history'] = contradiction or []
        
        # Episodic memory
        episodic = db.execute_query(
            "SELECT * FROM episodic_memory WHERE user_id = ? ORDER BY timestamp DESC",
            (user_id,)
        )
        data['episodic_memory'] = episodic or []
        
        # Pattern memory
        patterns = db.execute_query(
            "SELECT * FROM pattern_memory WHERE user_id = ? ORDER BY last_observed DESC",
            (user_id,)
        )
        data['pattern_memory'] = patterns or []
        
        logger.info(f"Data export completed for user {user_id}")
        
        return DataExportResponse(
            user_id=user_id,
            export_timestamp=datetime.utcnow().isoformat() + 'Z',
            data=data
        )
        
    except Exception as e:
        logger.error(f"Data export failed for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Data export failed: {str(e)}")


@router.delete("/delete-user-data")
async def delete_user_data(user_id: str = Query(..., description="User ID to delete data for")):
    """
    Delete all user data (GDPR Article 17 - Right to be Forgotten).
    
    This is irreversible and will delete all personality, memory, and session data.
    """
    try:
        db = get_postgres()
        
        # Log audit event BEFORE deletion
        db.execute_update(
            "INSERT INTO audit_logs (user_id, action_type, action_details, performed_by) VALUES (?, ?, ?, ?)",
            (user_id, 'data_deletion', 'All user data deleted via API', 'system')
        )
        
        # Delete in reverse dependency order
        tables = [
            'contradiction_history',
            'trust_history',
            'episodic_memory',
            'pattern_memory',
            'memories',
            'personality_snapshots',
            'sessions',
            'users'
        ]
        
        for table in tables:
            db.execute_update(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
        
        logger.info(f"All data deleted for user {user_id}")
        
        return {"status": "success", "message": f"All data for user {user_id} has been deleted"}
        
    except Exception as e:
        logger.error(f"Data deletion failed for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Data deletion failed: {str(e)}")


@router.get("/personality-profile", response_model=PersonalityProfileResponse)
async def get_personality_profile(user_id: str = Query(..., description="User ID")):
    """
    Get personality profile with transparency (EU AI Act Article 13).
    
    Returns current personality, history, and model information.
    """
    try:
        db = get_postgres()
        
        # Get current personality
        current = db.execute_query(
            "SELECT * FROM personality_snapshots WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1",
            (user_id,)
        )
        
        # Get personality history (last 10 snapshots)
        history = db.execute_query(
            "SELECT * FROM personality_snapshots WHERE user_id = ? ORDER BY timestamp DESC LIMIT 10",
            (user_id,)
        )
        
        if not current:
            raise HTTPException(status_code=404, detail=f"No personality data found for user {user_id}")
        
        return PersonalityProfileResponse(
            user_id=user_id,
            current_personality={
                'warmth': current[0]['warmth'],
                'energy': current[0]['energy'],
                'assertiveness': current[0]['assertiveness'],
                'formality': current[0]['formality']
            },
            personality_history=history or [],
            model_version="1.0.0",  # TODO: Make this dynamic
            last_updated=current[0]['timestamp']
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Personality profile fetch failed for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch personality profile: {str(e)}")


@router.post("/revoke-consent")
async def revoke_consent(request: ConsentRevocationRequest):
    """
    Revoke consent for specific data processing activities.
    
    This will disable features based on revoked consent types.
    """
    try:
        db = get_postgres()
        
        # Log audit event
        db.execute_update(
            "INSERT INTO audit_logs (user_id, action_type, action_details, performed_by) VALUES (?, ?, ?, ?)",
            (request.user_id, 'consent_revocation', json.dumps(request.consent_types), 'user')
        )
        
        # TODO: Implement feature flags based on consent
        # For now, just log the revocation
        
        logger.info(f"Consent revoked for user {request.user_id}: {request.consent_types}")
        
        return {
            "status": "success",
            "message": f"Consent revoked for: {', '.join(request.consent_types)}",
            "user_id": request.user_id
        }
        
    except Exception as e:
        logger.error(f"Consent revocation failed for user {request.user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Consent revocation failed: {str(e)}")


@router.get("/health")
async def compliance_health():
    """Health check for compliance endpoints."""
    return {"status": "healthy", "service": "compliance"}
