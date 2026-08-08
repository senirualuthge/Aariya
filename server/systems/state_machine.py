"""
Formal State Machine for Trust-Based Relational Modes.

Implements discrete state transitions with guard conditions and stability requirements.
Prevents incoherent relational jumps and enforces psychological coherence.
"""

from typing import Optional, Dict
from enum import Enum
from datetime import datetime, timedelta

from server.systems.trust_system import TrustTier, get_trust_system
from server.infrastructure.postgres_manager import get_postgres
from server.infrastructure.redis_manager import get_redis
from server.infrastructure.observability import logger


class StateTransitionEvent(Enum):
    """Events that can trigger state transitions."""
    TRUST_INCREASE = "TRUST_INCREASE"
    TRUST_DECREASE = "TRUST_DECREASE"
    STABILITY_TIMEOUT = "STABILITY_TIMEOUT"
    CONTRADICTION_SPIKE = "CONTRADICTION_SPIKE"
    BOUNDARY_VIOLATION = "BOUNDARY_VIOLATION"


class TrustStateMachine:
    """
    Formal state machine for relational modes.
    
    States: Defensive → Guarded → Neutral → Warm → Intimate
    
    Transition Rules:
    1. Trust must cross boundary threshold
    2. Stability duration ≥ τ_min (3 sessions)
    3. Guard condition: C_history ≤ 0.7 for upward transitions
    4. No skipping states
    """
    
    # Minimum sessions in new trust band before state commit
    MIN_STABILITY_SESSIONS = 3
    
    # State transition graph (allowed transitions)
    ALLOWED_TRANSITIONS = {
        TrustTier.DEFENSIVE: [TrustTier.GUARDED],
        TrustTier.GUARDED: [TrustTier.DEFENSIVE, TrustTier.NEUTRAL],
        TrustTier.NEUTRAL: [TrustTier.GUARDED, TrustTier.WARM],
        TrustTier.WARM: [TrustTier.NEUTRAL, TrustTier.INTIMATE],
        TrustTier.INTIMATE: [TrustTier.WARM]
    }
    
    def __init__(self):
        self.db = get_postgres()
        self.redis = get_redis()
        self.trust_system = get_trust_system()
    
    def get_current_state(self, user_id: str) -> TrustTier:
        """Get user's current committed state."""
        # Try Redis first
        state_str = self.redis.get_session_state(f"state:{user_id}")
        
        if state_str and 'current_tier' in state_str:
            return TrustTier(state_str['current_tier'])
        
        # Fallback: derive from current trust
        trust = self.trust_system.get_trust_score(user_id)
        return self.trust_system.get_trust_tier(trust)
    
    def get_stability_count(self, user_id: str, target_tier: TrustTier) -> int:
        """
        Count how many consecutive sessions user has been in target tier.
        
        Returns:
            Number of consecutive sessions in tier
        """
        # Get recent sessions
        results = self.db.execute_query("""
            SELECT trust_end, session_id
            FROM sessions
            WHERE user_id = ?
            ORDER BY start_time DESC
            LIMIT 10
        """, (user_id,))
        
        if not results:
            return 0
        
        # Count consecutive sessions in target tier
        count = 0
        tier_bounds = self.trust_system.TIER_BOUNDARIES[target_tier]
        
        for row in results:
            trust = row['trust_end']
            if tier_bounds[0] <= trust < tier_bounds[1]:
                count += 1
            else:
                break  # Streak broken
        
        return count
    
    def check_guard_condition(
        self,
        current_state: TrustTier,
        target_state: TrustTier,
        contradiction_history: float
    ) -> bool:
        """
        Check if guard conditions allow transition.
        
        Guard: C_history ≤ 0.7 for upward transitions
        
        Returns:
            True if transition is allowed
        """
        # Determine if upward transition
        tier_order = [
            TrustTier.DEFENSIVE,
            TrustTier.GUARDED,
            TrustTier.NEUTRAL,
            TrustTier.WARM,
            TrustTier.INTIMATE
        ]
        
        current_idx = tier_order.index(current_state)
        target_idx = tier_order.index(target_state)
        
        is_upward = target_idx > current_idx
        
        # High contradiction blocks upward transitions
        if is_upward and contradiction_history > 0.7:
            logger.info(
                f"Upward transition blocked by guard condition",
                user_id="unknown",
                current_state=current_state.value,
                target_state=target_state.value,
                contradiction_history=contradiction_history
            )
            return False
        
        return True
    
    def can_transition(
        self,
        user_id: str,
        current_state: TrustTier,
        target_state: TrustTier,
        contradiction_history: float
    ) -> bool:
        """
        Check if state transition is allowed.
        
        Conditions:
        1. Target state must be in allowed transitions
        2. Stability duration must be met
        3. Guard conditions must pass
        
        Returns:
            True if transition is allowed
        """
        # Check if transition is in allowed graph
        if target_state not in self.ALLOWED_TRANSITIONS.get(current_state, []):
            logger.warn(
                f"Invalid state transition attempted",
                user_id=user_id,
                current_state=current_state.value,
                target_state=target_state.value,
                reason="Not in allowed transitions graph"
            )
            return False
        
        # Check stability duration
        stability_count = self.get_stability_count(user_id, target_state)
        if stability_count < self.MIN_STABILITY_SESSIONS:
            logger.info(
                f"State transition delayed - insufficient stability",
                user_id=user_id,
                current_state=current_state.value,
                target_state=target_state.value,
                stability_count=stability_count,
                required=self.MIN_STABILITY_SESSIONS
            )
            return False
        
        # Check guard conditions
        if not self.check_guard_condition(current_state, target_state, contradiction_history):
            return False
        
        return True
    
    def attempt_transition(
        self,
        user_id: str,
        session_id: str,
        contradiction_history: float
    ) -> Optional[TrustTier]:
        """
        Attempt to transition to new state based on current trust.
        
        Returns:
            New state if transition occurred, None otherwise
        """
        current_state = self.get_current_state(user_id)
        trust = self.trust_system.get_trust_score(user_id)
        target_tier = self.trust_system.get_trust_tier(trust)
        
        # If already in correct state, no transition needed
        if current_state == target_tier:
            return None
        
        # Check if transition is allowed
        if self.can_transition(user_id, current_state, target_tier, contradiction_history):
            # Commit transition
            self._commit_state_transition(user_id, session_id, current_state, target_tier)
            return target_tier
        
        return None
    
    def _commit_state_transition(
        self,
        user_id: str,
        session_id: str,
        from_state: TrustTier,
        to_state: TrustTier
    ):
        """Commit state transition to storage."""
        # Update Redis
        self.redis.update_session_field(f"state:{user_id}", 'current_tier', to_state.value)
        
        # Log to database (using audit_logs for state transitions)
        self.db.execute_update("""
            INSERT INTO audit_logs (user_id, action_type, action_details, performed_by)
            VALUES (?, ?, ?, ?)
        """, (
            user_id,
            'state_transition',
            f"{from_state.value} → {to_state.value} (session: {session_id})",
            'system'
        ))
        
        logger.info(
            f"State transition committed",
            user_id=user_id,
            session_id=session_id,
            from_state=from_state.value,
            to_state=to_state.value
        )


# Global instance
_state_machine: Optional[TrustStateMachine] = None


def get_state_machine() -> TrustStateMachine:
    """Get or create global state machine instance."""
    global _state_machine
    if _state_machine is None:
        _state_machine = TrustStateMachine()
    return _state_machine
