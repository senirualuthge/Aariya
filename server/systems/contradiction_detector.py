"""
Contradiction Detection System
Implements the formal contradiction algorithm from Fixv2.txt.

Detects and quantifies emotional inconsistency across modalities (face, voice, text) over time.
Converts contradiction into trust decay pressure, uncertainty modifiers, and suspicion triggers.
"""

import math
from typing import Any, Dict, Optional, Tuple
from dataclasses import dataclass

from server.infrastructure.postgres_manager import get_postgres
from server.infrastructure.redis_manager import get_redis
from server.infrastructure.observability import log_contradiction


@dataclass
class EmotionVector:
    """Emotion in valence-arousal space."""
    valence: float  # [-1, 1]
    arousal: float  # [-1, 1]
    confidence: float  # [0, 1]


class ContradictionDetector:
    """
    Detects emotional inconsistency across modalities.
    
    Mathematical Implementation:
    1. Euclidean distance in valence-arousal space
    2. Pairwise modality distance computation
    3. Confidence-weighted contradiction scoring
    4. Exponential Moving Average (EMA) for temporal memory
    5. Trust decay pressure calculation
    """
    
    def __init__(self, beta: float = 0.05, lambda_decay: float = 0.03):
        """
        Args:
            beta: EMA smoothing factor for contradiction history (default: 0.05)
            lambda_decay: Trust decay rate per contradiction unit (default: 0.03)
        """
        self.beta = beta
        self.lambda_decay = lambda_decay
        self.db = get_postgres()
        self.redis = get_redis()
        
        # Maximum possible distance in valence-arousal space
        # sqrt((2)^2 + (2)^2) = sqrt(8) ≈ 2.828
        self.max_distance = math.sqrt(8)
    
    def calculate_euclidean_distance(
        self,
        emotion1: EmotionVector,
        emotion2: EmotionVector
    ) -> float:
        """
        Calculate Euclidean distance between two emotions in valence-arousal space.
        
        Formula: D_ij = sqrt[(V_i - V_j)^2 + (A_i - A_j)^2]
        
        Returns:
            Distance in range [0, 2.828]
        """
        valence_diff = emotion1.valence - emotion2.valence
        arousal_diff = emotion1.arousal - emotion2.arousal
        return math.sqrt(valence_diff**2 + arousal_diff**2)
    
    def calculate_magnitude_mismatch(self, emotion1: EmotionVector, emotion2: EmotionVector) -> float:
        """
        NEW: Intensity mismatch — same direction but very different magnitudes.
        Returns 0.0 (no mismatch) to 1.0 (extreme intensity difference).
        """
        mag_a = math.sqrt(emotion1.valence**2 + emotion1.arousal**2)
        mag_b = math.sqrt(emotion2.valence**2 + emotion2.arousal**2)
        if mag_a < 1e-6 and mag_b < 1e-6:
            return 0.0
        max_mag = max(mag_a, mag_b, 1e-6)
        mismatch = abs(mag_a - mag_b) / max_mag
        min_signal_strength = min(mag_a, mag_b)
        if min_signal_strength < 0.2:
            mismatch *= 0.4
        return float(min(max(mismatch, 0.0), 1.0))
    
    def calculate_pairwise_distances(
        self,
        face: EmotionVector,
        voice: EmotionVector,
        text: EmotionVector
    ) -> Dict[str, float]:
        """
        Compute all pairwise distances between modalities.
        
        Returns:
            Dictionary with keys: 'face_voice', 'face_text', 'voice_text', 'mean'
        """
        d_face_voice = self.calculate_euclidean_distance(face, voice)
        d_face_text = self.calculate_euclidean_distance(face, text)
        d_voice_text = self.calculate_euclidean_distance(voice, text)
        
        mean_distance = (d_face_voice + d_face_text + d_voice_text) / 3.0
        
        return {
            'face_voice': d_face_voice,
            'face_text': d_face_text,
            'voice_text': d_voice_text,
            'mean': mean_distance
        }
    
    def calculate_instantaneous_contradiction(
        self,
        face: EmotionVector,
        voice: EmotionVector,
        text: EmotionVector
    ) -> Tuple[float, float, float, float]:
        """
        Calculate instantaneous contradiction score for current turn.
        
        Steps:
        1. Compute pairwise distances
        2. Normalize by max possible distance
        3. Weight by confidence
        
        Returns:
            Tuple of (raw_contradiction, confidence_weighted_contradiction)
            Both in range [0, 1] where 0 = consistent, 1 = maximally contradictory
        """
        # Step A: Compute pairwise distances
        distances = self.calculate_pairwise_distances(face, voice, text)
        mean_distance = distances['mean']
        
        # Step B: Normalize
        direction_score = mean_distance / self.max_distance
        
        # Step B2: Intensity mismatch (face vs voice primarily)
        intensity_score = self.calculate_magnitude_mismatch(face, voice)
        
        # Weighted combination
        direction_weight = 0.6
        intensity_weight = 0.4
        contradiction_raw = (direction_score * direction_weight) + (intensity_score * intensity_weight)
        
        # Step C: Confidence weighting
        confidence_mean = (face.confidence + voice.confidence + text.confidence) / 3.0
        contradiction_weighted = contradiction_raw * confidence_mean
        
        return contradiction_raw, contradiction_weighted, direction_score, intensity_score  # type: ignore[return-value]
    
    def update_contradiction_history(
        self,
        user_id: str,
        current_score: float,
        previous_ema: Optional[float] = None
    ) -> float:
        """
        Update temporal contradiction memory using EMA.
        
        Formula: C_history(t) = (1 - β) * C_history(t-1) + β * C_turn(t)
        
        Args:
            user_id: User identifier
            current_score: Current turn contradiction score
            previous_ema: Previous EMA value (fetched from Redis if None)
        
        Returns:
            Updated EMA value
        """
        if previous_ema is None:
            previous_ema = self.redis.get_contradiction_history(user_id) or 0.0
        
        # EMA update
        new_ema = (1 - self.beta) * previous_ema + self.beta * current_score
        
        # Store in Redis for fast access
        self.redis.set_contradiction_history(user_id, new_ema)
        
        return new_ema
    
    def calculate_trust_decay(
        self,
        current_trust: float,
        contradiction_history: float
    ) -> float:
        """
        Calculate trust decay pressure from contradiction.
        
        Formula: trust(t+1) = trust(t) - λ * C_history(t)
        
        Args:
            current_trust: Current trust score [0, 1]
            contradiction_history: Contradiction EMA [0, 1]
        
        Returns:
            Trust delta (negative value)
        """
        decay = -self.lambda_decay * contradiction_history
        return decay
    
    def calculate_uncertainty_modifier(
        self,
        contradiction_history: float,
        k: float = 0.7
    ) -> float:
        """
        Calculate uncertainty bias for conversational guardedness.
        
        Formula: uncertainty_bias = clamp(C_history * k, 0, 1)
        
        This feeds into:
        - Reduced emotional mirroring
        - Reduced vulnerability
        - Slightly more neutral tone
        
        Returns:
            Uncertainty modifier [0, 1]
        """
        return min(1.0, max(0.0, contradiction_history * k))
    
    def check_suspicion_trigger(
        self,
        contradiction_history: float,
        threshold: float = 0.6
    ) -> bool:
        """
        Check if contradiction level triggers suspicion behavior.
        
        If C_history > 0.6:
        - System shifts into clarification behavior
        - "Are you feeling okay?" probing
        - Slower emotional alignment
        
        Returns:
            True if suspicion should be triggered
        """
        return contradiction_history > threshold
    
    def process_turn(
        self,
        user_id: str,
        session_id: str,
        turn_number: int,
        face_emotion: Dict[str, float],
        voice_emotion: Dict[str, float],
        text_sentiment: float,
        confidences: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Process a complete turn and update contradiction metrics.
        
        Args:
            user_id: User identifier
            session_id: Session identifier
            turn_number: Turn number in session
            face_emotion: {'valence': float, 'arousal': float}
            voice_emotion: {'valence': float, 'arousal': float}
            text_sentiment: Sentiment valence [-1, 1]
            confidences: {'face': float, 'voice': float, 'text': float}
        
        Returns:
            Dictionary with contradiction metrics and effects
        """
        # Create emotion vectors
        face = EmotionVector(
            valence=face_emotion.get('valence', 0.0),
            arousal=face_emotion.get('arousal', 0.0),
            confidence=confidences.get('face', 0.5)
        )
        
        voice = EmotionVector(
            valence=voice_emotion.get('valence', 0.0),
            arousal=voice_emotion.get('arousal', 0.0),
            confidence=confidences.get('voice', 0.5)
        )
        
        # Text only has valence (sentiment)
        text = EmotionVector(
            valence=text_sentiment,
            arousal=0.0,  # Text doesn't have arousal
            confidence=confidences.get('text', 0.5)
        )
        
        # Calculate instantaneous contradiction
        contradiction_raw, contradiction_weighted, direction_score, intensity_score = self.calculate_instantaneous_contradiction(
            face, voice, text
        )  # type: ignore
        
        # Update temporal memory (EMA)
        contradiction_ema = self.update_contradiction_history(
            user_id, contradiction_weighted
        )
        
        # Store in database for long-term tracking
        self.db.execute_update("""
            INSERT INTO contradiction_history (
                user_id, session_id, turn_number,
                face_valence, face_arousal, face_confidence,
                voice_valence, voice_arousal, voice_confidence,
                text_sentiment, text_confidence,
                contradiction_score, contradiction_ema, confidence_mean
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, session_id, turn_number,
            face.valence, face.arousal, face.confidence,
            voice.valence, voice.arousal, voice.confidence,
            text.valence, text.confidence,
            contradiction_weighted, contradiction_ema,
            (face.confidence + voice.confidence + text.confidence) / 3.0
        ))
        
        # Calculate effects
        uncertainty_modifier = self.calculate_uncertainty_modifier(contradiction_ema)
        suspicion_triggered = self.check_suspicion_trigger(contradiction_ema)
        
        # Log for observability
        log_contradiction(
            session_id=session_id,
            user_id=user_id,
            turn_number=turn_number,
            contradiction_score=contradiction_weighted,
            contradiction_ema=contradiction_ema,
            modalities={
                'face': {'valence': face.valence, 'arousal': face.arousal, 'confidence': face.confidence},
                'voice': {'valence': voice.valence, 'arousal': voice.arousal, 'confidence': voice.confidence},
                'text': {'valence': text.valence, 'confidence': text.confidence}
            }
        )
        
        return {
            'contradiction_raw': contradiction_raw,
            'contradiction_weighted': contradiction_weighted,
            'contradiction_ema': contradiction_ema,
            'uncertainty_modifier': uncertainty_modifier,
            'suspicion_triggered': suspicion_triggered,
            'trust_decay_pressure': self.calculate_trust_decay(1.0, contradiction_ema),  # Placeholder trust
            'contradiction_type': 'direction' if direction_score > intensity_score else 'intensity'
        }


# Global instance
_contradiction_detector: Optional[ContradictionDetector] = None


def get_contradiction_detector() -> ContradictionDetector:
    """Get or create global contradiction detector instance."""
    global _contradiction_detector
    if _contradiction_detector is None:
        _contradiction_detector = ContradictionDetector()
    return _contradiction_detector
