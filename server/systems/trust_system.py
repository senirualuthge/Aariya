"""
Trust Gating System
Implements trust-based behavior modulation with psychological coherence.

Trust gates:
- Emotional expressiveness
- Memory recall depth
- Physical proximity (animation)
- Personal disclosure
- Humor risk
- Vulnerability level
- Attachment signals
"""

from typing import Dict, Optional, Tuple
from enum import Enum
from dataclasses import dataclass, field
import time

from server.infrastructure.postgres_manager import get_postgres
from server.infrastructure.redis_manager import get_redis
from server.infrastructure.observability import log_trust_update, log_safety_constraint_violation


class TrustTier(Enum):
    """Trust tier enumeration."""
    DEFENSIVE = "DEFENSIVE"
    GUARDED = "GUARDED"
    NEUTRAL = "NEUTRAL"
    WARM = "WARM"
    INTIMATE = "INTIMATE"


@dataclass
class MicroTrustSignal:
    """
    Short-lived trust modifier. Decays over turns.
    Does NOT affect long-term trust score — session-level only.
    """
    delta: float            # Positive or negative modifier
    turns_remaining: int    # How many turns until expired
    reason: str = ""        # For dashboard display
    created_at: float = field(default_factory=time.time)


@dataclass
class TrustGates:
    """Trust-based behavioral constraints."""
    emotion_intensity_cap: float  # Max emotional intensity allowed
    disclosure_level: int  # 0-4 scale
    memory_depth: int  # Number of past sessions to recall
    proximity_multiplier: float  # Animation distance modifier
    humor_risk_allowed: bool  # Whether risky humor is permitted
    vulnerability_level: float  # How vulnerable AI can be


class TrustSystem:
    """
    Manages trust scoring and trust-based behavior gating.
    
    Trust Formula:
    Δtrust = a * V_session
           + b * (1 - C_history)
           + c * continuity_score
           - d * boundary_violation
    """
    
    # Trust tier boundaries
    TIER_BOUNDARIES = {
        TrustTier.DEFENSIVE: (0.0, 0.2),
        TrustTier.GUARDED: (0.2, 0.4),
        TrustTier.NEUTRAL: (0.4, 0.7),
        TrustTier.WARM: (0.7, 0.85),
        TrustTier.INTIMATE: (0.85, 1.0)
    }
    
    # Behavior modifiers per tier
    TIER_GATES = {
        TrustTier.DEFENSIVE: TrustGates(
            emotion_intensity_cap=0.2,
            disclosure_level=0,
            memory_depth=1,
            proximity_multiplier=0.5,
            humor_risk_allowed=False,
            vulnerability_level=0.0
        ),
        TrustTier.GUARDED: TrustGates(
            emotion_intensity_cap=0.4,
            disclosure_level=1,
            memory_depth=2,
            proximity_multiplier=0.7,
            humor_risk_allowed=False,
            vulnerability_level=0.2
        ),
        TrustTier.NEUTRAL: TrustGates(
            emotion_intensity_cap=0.6,
            disclosure_level=2,
            memory_depth=3,
            proximity_multiplier=1.0,
            humor_risk_allowed=False,
            vulnerability_level=0.5
        ),
        TrustTier.WARM: TrustGates(
            emotion_intensity_cap=0.8,
            disclosure_level=3,
            memory_depth=4,
            proximity_multiplier=1.2,
            humor_risk_allowed=True,
            vulnerability_level=0.7
        ),
        TrustTier.INTIMATE: TrustGates(
            emotion_intensity_cap=1.0,
            disclosure_level=4,
            memory_depth=5,
            proximity_multiplier=1.5,
            humor_risk_allowed=True,
            vulnerability_level=1.0
        )
    }
    
    def __init__(
        self,
        a: float = 0.1,  # Session valence weight
        b: float = 0.15,  # Consistency weight
        c: float = 0.05,  # Continuity weight
        d: float = 0.3   # Boundary violation penalty
    ):
        """
        Args:
            a: Weight for session valence
            b: Weight for consistency (1 - contradiction)
            c: Weight for continuity score
            d: Weight for boundary violation penalty
        """
        self.a = a
        self.b = b
        self.c = c
        self.d = d
        self.db = get_postgres()
        self.redis = get_redis()
        self._micro_signals: list[MicroTrustSignal] = []
    
    def get_trust_score(self, user_id: str) -> float:
        """Get current trust score from Redis or database."""
        # Try Redis first (fast)
        trust = self.redis.get_trust_score(user_id)
        
        if trust is None:
            # Fallback to database
            result = self.db.execute_query(
                "SELECT trust_score FROM trust_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1",
                (user_id,)
            )
            trust = result[0]['trust_score'] if result else 0.5  # Default to neutral
            
            # Cache in Redis
            self.redis.set_trust_score(user_id, trust)
        
        return trust
    
    def add_micro_signal(
        self,
        delta: float,
        duration_turns: int,
        reason: str = ""
    ):
        self._micro_signals.append(
            MicroTrustSignal(delta=delta, turns_remaining=duration_turns, reason=reason)
        )

    def get_effective_trust(self, user_id: str) -> float:
        base_score = self.get_trust_score(user_id)
        micro_total = sum(s.delta for s in self._micro_signals)
        effective = base_score + micro_total
        return round(max(0.0, min(1.0, effective)), 4)

    def advance_turn(self):
        active = []
        for signal in self._micro_signals:
            signal.turns_remaining -= 1
            if signal.turns_remaining > 0:
                active.append(signal)
        self._micro_signals = active

    def get_active_micro_signals(self) -> list[Dict]:
        return [
            {
                "delta": s.delta,
                "turns_remaining": s.turns_remaining,
                "reason": s.reason
            }
            for s in self._micro_signals
        ]
    
    def get_trust_tier(self, trust: float) -> TrustTier:
        """Map continuous trust to discrete tier."""
        for tier, (min_val, max_val) in self.TIER_BOUNDARIES.items():
            if min_val <= trust < max_val:
                return tier
        return TrustTier.INTIMATE  # If trust >= 0.85
    
    def get_trust_gates(self, trust: float) -> TrustGates:
        """Get behavioral constraints for current trust level."""
        tier = self.get_trust_tier(trust)
        return self.TIER_GATES[tier]
    
    def calculate_trust_delta(
        self,
        session_valence: float,
        contradiction_history: float,
        continuity_score: float,
        boundary_violation: bool
    ) -> float:
        """
        Calculate trust change using weighted formula.
        
        Formula:
        Δtrust = a * V_session
               + b * (1 - C_history)
               + c * continuity_score
               - d * boundary_violation
        
        Returns:
            Trust delta (can be positive or negative)
        """
        delta = (
            self.a * session_valence +
            self.b * (1 - contradiction_history) +
            self.c * continuity_score -
            (self.d if boundary_violation else 0.0)
        )
        
        return delta
    
    def update_trust(
        self,
        user_id: str,
        session_id: str,
        session_valence: float,
        contradiction_history: float,
        continuity_score: float = 0.5,
        boundary_violation: bool = False,
        trigger_event: str = "session_update"
    ) -> Tuple[float, float]:
        """
        Update trust score and store in database.
        
        Returns:
            Tuple of (old_trust, new_trust)
        """
        current_trust = self.get_trust_score(user_id)
        
        # Calculate delta
        delta = self.calculate_trust_delta(
            session_valence,
            contradiction_history,
            continuity_score,
            boundary_violation
        )
        
        # Apply delta and clamp to [0, 1]
        new_trust = max(0.0, min(1.0, current_trust + delta))
        
        # Store in Redis for fast access
        self.redis.set_trust_score(user_id, new_trust)
        
        # Store in database for long-term tracking
        self.db.execute_update("""
            INSERT INTO trust_history (user_id, session_id, trust_score, trust_delta, trigger_event)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, session_id, new_trust, delta, trigger_event))
        
        # Log for observability
        log_trust_update(
            session_id=session_id,
            user_id=user_id,
            trust_before=current_trust,
            trust_after=new_trust,
            trust_delta=delta,
            trigger_event=trigger_event
        )
        
        return current_trust, new_trust
    
    def apply_trust_gates(
        self,
        user_id: str,
        session_id: str,
        proposed_behavior: Dict,
        contradiction_history: float
    ) -> Dict:
        """
        Apply hard trust-based constraints to proposed behavior.
        
        This is the CRITICAL safety layer that prevents:
        - Emotional overreach at low trust
        - Inappropriate disclosure
        - Uncanny intimacy
        
        Args:
            user_id: User identifier
            session_id: Session identifier
            proposed_behavior: Dictionary with behavioral parameters
            contradiction_history: Current contradiction EMA
        
        Returns:
            Constrained behavior dictionary
        """
        trust = self.get_trust_score(user_id)
        gates = self.get_trust_gates(trust)
        constrained = proposed_behavior.copy()
        
        # 1. Emotional Intensity Cap
        # CRITICAL: emotion_intensity ≤ trust
        if 'emotion_intensity' in constrained:
            proposed_intensity = constrained['emotion_intensity']
            max_intensity = min(gates.emotion_intensity_cap, trust)
            
            if proposed_intensity > max_intensity:
                log_safety_constraint_violation(
                    session_id=session_id,
                    user_id=user_id,
                    constraint_type="emotion_intensity_cap",
                    proposed_value=proposed_intensity,
                    enforced_value=max_intensity,
                    reason=f"Trust level {trust:.2f} limits intensity to {max_intensity:.2f}"
                )
                constrained['emotion_intensity'] = max_intensity
        
        # 2. Disclosure Level
        if 'disclosure_level' in constrained:
            proposed_disclosure = constrained['disclosure_level']
            
            if proposed_disclosure > gates.disclosure_level:
                log_safety_constraint_violation(
                    session_id=session_id,
                    user_id=user_id,
                    constraint_type="disclosure_level",
                    proposed_value=proposed_disclosure,
                    enforced_value=gates.disclosure_level,
                    reason=f"Trust tier {self.get_trust_tier(trust).value} limits disclosure to level {gates.disclosure_level}"
                )
                constrained['disclosure_level'] = gates.disclosure_level
        
        # 3. Memory Depth
        if 'memory_depth' in constrained:
            constrained['memory_depth'] = min(constrained['memory_depth'], gates.memory_depth)
        
        # 4. Proximity Multiplier
        if 'proximity_multiplier' in constrained:
            constrained['proximity_multiplier'] = gates.proximity_multiplier
        
        # 5. Humor Risk
        # Risky humor only if: trust > 0.6 AND C_history < 0.4
        if 'humor_risk' in constrained:
            humor_allowed = gates.humor_risk_allowed and contradiction_history < 0.4
            
            if constrained['humor_risk'] and not humor_allowed:
                log_safety_constraint_violation(
                    session_id=session_id,
                    user_id=user_id,
                    constraint_type="humor_risk",
                    proposed_value=True,
                    enforced_value=False,
                    reason=f"Trust {trust:.2f} or contradiction {contradiction_history:.2f} too high for risky humor"
                )
                constrained['humor_risk'] = False
        
        # 6. Contradiction Modifier
        # If C_history > 0.6, reduce emotional intensity further
        if contradiction_history > 0.6 and 'emotion_intensity' in constrained:
            original = constrained['emotion_intensity']
            constrained['emotion_intensity'] *= 0.6
            
            if original != constrained['emotion_intensity']:
                log_safety_constraint_violation(
                    session_id=session_id,
                    user_id=user_id,
                    constraint_type="contradiction_modifier",
                    proposed_value=original,
                    enforced_value=constrained['emotion_intensity'],
                    reason=f"High contradiction {contradiction_history:.2f} reduces intensity"
                )
        
        # 7. Vulnerability Level
        if 'vulnerability_level' in constrained:
            constrained['vulnerability_level'] = min(
                constrained['vulnerability_level'],
                gates.vulnerability_level
            )
        
        return constrained
    
    def calculate_continuity_score(self, user_id: str) -> float:
        """
        Calculate interaction continuity score.
        
        Based on:
        - Session frequency
        - Time since last session
        - Total interaction count
        
        Returns:
            Continuity score [0, 1]
        """
        # Get user's session history
        result = self.db.execute_query("""
            SELECT 
                COUNT(*) as total_sessions,
                MAX(start_time) as last_session,
                AVG(duration_sec) as avg_duration
            FROM sessions
            WHERE user_id = ?
        """, (user_id,))
        
        if not result or result[0]['total_sessions'] == 0:
            return 0.5  # Neutral for new users
        
        data = result[0]
        total_sessions = data['total_sessions']
        # Calculate base session factor
        session_factor = min(1.0, total_sessions / 10.0)

        # 2. Time-based Decay
        # If user hasn't appeared for a long time, trust drifts toward baseline (0.5)
        last_session_time = data['last_session'] or 0
        hours_since = (time.time() - last_session_time) / 3600.0
        
        # Start decaying after 72 hours (3 days)
        if hours_since > 72:
            days_over = (hours_since - 72) / 24.0
            # Lose 5% continuity per day after 3 days
            decay = days_over * 0.05
            session_factor = max(0.0, session_factor - decay)

        return session_factor

def detect_micro_trust_events(
    trust: TrustSystem,
    user_text: str,
    contradiction_ema: float,
    valence: float,
    prev_contradiction_ema: float
):
    text_lower = user_text.lower().strip()

    hostile_keywords = {"hate", "stupid", "useless", "shut up", "idiot", "dumb", "ugly"}
    if any(kw in text_lower for kw in hostile_keywords):
        trust.add_micro_signal(-0.3, duration_turns=3, reason="hostile_message")

    contradiction_spike = contradiction_ema - prev_contradiction_ema
    if contradiction_spike > 0.25:
        trust.add_micro_signal(-0.2, duration_turns=2, reason="contradiction_spike")

    if valence > 0.6 and contradiction_ema < 0.3:
        trust.add_micro_signal(+0.1, duration_turns=2, reason="genuine_positivity")


# Global instance
_trust_system: Optional[TrustSystem] = None


def get_trust_system() -> TrustSystem:
    """Get or create global trust system instance."""
    global _trust_system
    if _trust_system is None:
        _trust_system = TrustSystem()
    return _trust_system
