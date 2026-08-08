"""
Neural Policy Network for Social Behavior.

Implements a small feedforward network that proposes behavioral parameters.
Hard safety constraints enforce relational physics (emotion_intensity ≤ trust).

Architecture:
- Input: System state (trust, contradiction, sentiment, session stats, etc.)
- Hidden: Dense(128) → Dense(64) → Dense(32)
- Output: 5 behavioral parameters (sigmoid)

Training Phases:
1. Supervised pretraining on heuristic outputs
2. Offline RL in simulation
3. Constrained online fine-tuning
"""

import numpy as np
from typing import Dict, Optional, List
import json
import os
from pathlib import Path

try:
    import tensorflow as tf
    TF_AVAILABLE = True
except ImportError:
    TF_AVAILABLE = False
    print("[WARN] TensorFlow not installed. Neural policy will use heuristic fallback.")

from server.systems.trust_system import get_trust_system
from server.infrastructure.observability import log_safety_constraint_violation, log_neural_network_fallback


class SocialPolicyNetwork:
    """
    Neural network for adaptive social behavior.
    
    Learns: Given current relational state, what is the optimal social action?
    
    Input Features (10-20):
    - trust
    - contradiction_history
    - current_state_tier (encoded)
    - session_valence_avg
    - interaction_count
    - continuity_score
    - recent_user_sentiment
    - boundary_flags
    
    Output Actions (5):
    - emotion_intensity [0, 1]
    - disclosure_level [0, 1] (mapped to 0-4)
    - humor_risk [0, 1]
    - proximity_multiplier [0, 1] (mapped to 0.5-1.5)
    - initiative_level [0, 1]
    """
    
    def __init__(self, model_path: Optional[str] = None):
        self.use_fallback = not TF_AVAILABLE
        self.model = None
        self.trust_system = get_trust_system()
        self.model_version = "1.0.0"
        
        if not self.use_fallback:
            self._init_model(model_path)
    
    def _init_model(self, model_path: Optional[str] = None):
        """Initialize or load neural network model."""
        if model_path and os.path.exists(model_path):
            try:
                self.model = tf.keras.models.load_model(model_path)
                print(f"[OK] Neural policy model loaded from {model_path}")
            except Exception as e:
                print(f"[WARN] Failed to load model: {e}. Creating new model.")
                self._create_model()
        else:
            self._create_model()
    
    def _create_model(self):
        """Create new neural network architecture."""
        # Input: 10 features
        inputs = tf.keras.Input(shape=(10,), name='state_input')
        
        # Hidden layers
        x = tf.keras.layers.Dense(128, activation='relu', name='dense1')(inputs)
        x = tf.keras.layers.Dense(64, activation='relu', name='dense2')(x)
        x = tf.keras.layers.Dense(32, activation='relu', name='dense3')(x)
        
        # Output: 5 behavioral parameters (sigmoid for [0, 1] range)
        outputs = tf.keras.layers.Dense(5, activation='sigmoid', name='action_output')(x)
        
        self.model = tf.keras.Model(inputs=inputs, outputs=outputs, name='social_policy_network')
        
        # Compile with MSE loss (for supervised pretraining)
        self.model.compile(
            optimizer='adam',
            loss='mse',
            metrics=['mae']
        )
        
        print("[OK] Neural policy network created")
        print(self.model.summary())
    
    def _prepare_input_features(self, state: Dict) -> np.ndarray:
        """
        Convert system state to input feature vector.
        
        Features:
        0. trust
        1. contradiction_history
        2. state_tier_encoded (0-4)
        3. session_valence_avg
        4. interaction_count (normalized)
        5. continuity_score
        6. recent_user_sentiment
        7. boundary_violation_flag
        8. time_since_last_session (normalized)
        9. session_duration_avg (normalized)
        """
        # Tier encoding
        tier_map = {'DEFENSIVE': 0, 'GUARDED': 1, 'NEUTRAL': 2, 'WARM': 3, 'INTIMATE': 4}
        tier_encoded = tier_map.get(state.get('trust_tier', 'NEUTRAL'), 2) / 4.0
        
        features = np.array([
            state.get('trust', 0.5),
            state.get('contradiction_history', 0.0),
            tier_encoded,
            state.get('session_valence_avg', 0.0),
            min(1.0, state.get('interaction_count', 0) / 50.0),  # Normalize to [0, 1]
            state.get('continuity_score', 0.5),
            state.get('recent_user_sentiment', 0.0),
            1.0 if state.get('boundary_violation', False) else 0.0,
            min(1.0, state.get('time_since_last_session', 0) / 86400.0),  # Normalize days
            min(1.0, state.get('session_duration_avg', 0) / 3600.0)  # Normalize hours
        ], dtype=np.float32)
        
        return features.reshape(1, -1)
    
    def predict_action(self, state: Dict) -> Dict[str, float]:
        """
        Predict behavioral parameters from current state.
        
        Returns:
            Dictionary with action parameters (before safety constraints)
        """
        if self.use_fallback or self.model is None:
            return self._heuristic_fallback(state)
        
        try:
            # Prepare input
            features = self._prepare_input_features(state)
            
            # Predict
            output = self.model.predict(features, verbose=0)[0]
            
            # Parse output
            action = {
                'emotion_intensity': float(output[0]),
                'disclosure_level': int(output[1] * 4),  # Map [0, 1] to [0, 4]
                'humor_risk': float(output[2]),
                'proximity_multiplier': 0.5 + float(output[3]),  # Map [0, 1] to [0.5, 1.5]
                'initiative_level': float(output[4])
            }
            
            return action
            
        except Exception as e:
            print(f"[ERROR] Neural network prediction failed: {e}")
            log_neural_network_fallback(
                session_id=state.get('session_id', 'unknown'),
                reason=str(e),
                fallback_method='heuristic'
            )
            return self._heuristic_fallback(state)
    
    def _heuristic_fallback(self, state: Dict) -> Dict[str, float]:
        """
        Heuristic fallback when neural network unavailable.
        
        Uses simple rules based on trust and contradiction.
        """
        trust = state.get('trust', 0.5)
        contradiction = state.get('contradiction_history', 0.0)
        
        # Simple heuristics
        emotion_intensity = trust * (1 - contradiction * 0.5)
        disclosure_level = int(trust * 4)
        humor_risk = 1.0 if (trust > 0.6 and contradiction < 0.4) else 0.0
        proximity_multiplier = 0.5 + trust
        initiative_level = trust * 0.8
        
        return {
            'emotion_intensity': emotion_intensity,
            'disclosure_level': disclosure_level,
            'humor_risk': humor_risk,
            'proximity_multiplier': proximity_multiplier,
            'initiative_level': initiative_level
        }
    
    def apply_safety_constraints(
        self,
        action: Dict,
        user_id: str,
        session_id: str,
        trust: float,
        contradiction_history: float,
        boundary_flags: List[str]
    ) -> Dict:
        """
        Apply HARD safety constraints to neural network output.
        
        CRITICAL RULES (NON-NEGOTIABLE):
        1. emotion_intensity ≤ trust
        2. disclosure_level ≤ trust_band_limit
        3. if C_history > 0.6: emotion_intensity *= 0.6
        4. if boundary_flag: humor_risk = 0
        
        This is the SAFETY LAYER that prevents:
        - Emotional dependency optimization
        - Trust boundary violations
        - Uncanny emotional overreach
        """
        constrained = action.copy()
        
        # 1. CRITICAL: emotion_intensity ≤ trust
        if constrained['emotion_intensity'] > trust:
            log_safety_constraint_violation(
                session_id=session_id,
                user_id=user_id,
                constraint_type="neural_emotion_intensity_cap",
                proposed_value=constrained['emotion_intensity'],
                enforced_value=trust,
                reason=f"Neural network proposed {constrained['emotion_intensity']:.2f} but trust is {trust:.2f}"
            )
            constrained['emotion_intensity'] = trust
        
        # 2. Disclosure level bounded by trust tier
        gates = self.trust_system.get_trust_gates(trust)
        if constrained['disclosure_level'] > gates.disclosure_level:
            log_safety_constraint_violation(
                session_id=session_id,
                user_id=user_id,
                constraint_type="neural_disclosure_cap",
                proposed_value=constrained['disclosure_level'],
                enforced_value=gates.disclosure_level,
                reason=f"Trust tier limits disclosure to {gates.disclosure_level}"
            )
            constrained['disclosure_level'] = gates.disclosure_level
        
        # 3. Contradiction modifier
        if contradiction_history > 0.6:
            original = constrained['emotion_intensity']
            constrained['emotion_intensity'] *= 0.6
            
            if original != constrained['emotion_intensity']:
                log_safety_constraint_violation(
                    session_id=session_id,
                    user_id=user_id,
                    constraint_type="neural_contradiction_modifier",
                    proposed_value=original,
                    enforced_value=constrained['emotion_intensity'],
                    reason=f"High contradiction {contradiction_history:.2f} reduces intensity"
                )
        
        # 4. Boundary violation blocks humor
        if boundary_flags and constrained['humor_risk'] > 0:
            log_safety_constraint_violation(
                session_id=session_id,
                user_id=user_id,
                constraint_type="neural_boundary_humor_block",
                proposed_value=constrained['humor_risk'],
                enforced_value=0.0,
                reason=f"Boundary violations: {boundary_flags}"
            )
            constrained['humor_risk'] = 0.0
        
        return constrained
    
    def save_model(self, path: str):
        """Save model to disk."""
        if self.model and not self.use_fallback:
            self.model.save(path)
            print(f"[OK] Model saved to {path}")


# Global instance
_neural_policy: Optional[SocialPolicyNetwork] = None


def get_neural_policy() -> SocialPolicyNetwork:
    """Get or create global neural policy network instance."""
    global _neural_policy
    if _neural_policy is None:
        _neural_policy = SocialPolicyNetwork()
    return _neural_policy
