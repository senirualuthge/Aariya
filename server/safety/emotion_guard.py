class EmotionGuard:
    @staticmethod
    def clamp_state(valence: float, arousal: float):
        # Prevent AI from entering 'unstable' regions of affective space
        return max(-0.9, min(0.9, valence)), max(0.0, min(0.9, arousal))