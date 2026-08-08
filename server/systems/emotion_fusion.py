import math

class EmotionFusion:
    """
    Multimodal emotion fusion with persistence.
    AI emotions have inertia and decay toward a neutral baseline over time.
    """
    
    def __init__(self, decay_rate: float = 0.1, inertia: float = 0.4):
        """
        Args:
            decay_rate: Rate at which emotion returns to 0.0 per turn if no input.
            inertia: Weight of the previous turn's emotion [0, 1].
        """
        self.decay_rate = decay_rate
        self.inertia = inertia
        self.last_valence = 0.0

    def compute_text_confidence(self, text: str, sentiment_score: float) -> float:
        """Dynamic text confidence calculation."""
        if not text or not text.strip():
            return 0.0

        word_count = len(text.split())
        length_factor = 1 / (1 + math.exp(-0.3 * (word_count - 6)))
        polarity_factor = min(abs(sentiment_score) * 1.5, 1.0)
        exclaim_count = text.count('!') + text.count('?')
        punct_boost = min(exclaim_count * 0.05, 0.15)
        
        confidence = 0.4 + (length_factor * 0.35) + (polarity_factor * 0.15) + punct_boost
        return round(min(confidence, 0.95), 3)

    def fuse_with_persistence(
        self,
        face_valence: float, face_conf: float,
        audio_valence: float, audio_conf: float,
        text_valence: float, text: str, sentiment_score: float,
        dt_ms: float = 500.0,
        eps: float = 1e-6
    ) -> dict:
        """
        Confidence-weighted multimodal emotion fusion with temporal inertia.
        """
        # 1. Compute turn-instantaneous valence
        text_conf = self.compute_text_confidence(text, sentiment_score)
        total_conf = face_conf + audio_conf + text_conf + eps
        
        instant_valence = (
            face_valence  * face_conf  +
            audio_valence * audio_conf +
            text_valence  * text_conf
        ) / total_conf

        # 2. Apply inertia (blend with last state)
        # If confidence is very low, inertia dominates
        effective_inertia = self.inertia * (1.0 - min(1.0, total_conf))
        fused_valence = (instant_valence * (1.0 - effective_inertia)) + (self.last_valence * effective_inertia)

        # 3. Apply decay toward neutral (0.0)
        # This simulates emotional 'cool down' over time
        if abs(fused_valence) > 0.01:
            decay = self.decay_rate * (dt_ms / 1000.0)
            if fused_valence > 0:
                fused_valence = max(0.0, fused_valence - decay)
            else:
                fused_valence = min(0.0, fused_valence + decay)

        # 4. Update state
        self.last_valence = fused_valence

        return {
            "final_valence": round(float(fused_valence), 4),
            "text_confidence": text_conf,
            "instant_valence": round(float(instant_valence), 4),
            "dominant_signal": max(
                [("face", face_conf), ("audio", audio_conf), ("text", text_conf)],
                key=lambda x: x[1]
            )[0]
        }

# For backward compatibility (global if needed)
_global_fusion = EmotionFusion()

def compute_text_confidence(text: str, sentiment_score: float) -> float:
    return _global_fusion.compute_text_confidence(text, sentiment_score)

def fuse_emotions(
    face_valence: float, face_conf: float,
    audio_valence: float, audio_conf: float,
    text_valence: float, text: str, sentiment_score: float
) -> dict:
    return _global_fusion.fuse_with_persistence(
        face_valence, face_conf, audio_valence, audio_conf, text_valence, text, sentiment_score
    )
