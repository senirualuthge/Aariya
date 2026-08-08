class SelfAwareness:
    def __init__(self):
        self.valence = 0.0
        self.arousal = 0.0
        self.trust = 0.5
        self._last_trust = 0.5
        self.attachment = 0.3
        self.identity_stability = 0.8

    def reflect(self, input_data, tom):
        # Social confirmation bias: if user is happy, AI feels more stable
        if tom.valence > 0.5:
            self.valence = min(1.0, self.valence + 0.05)
            self.trust = min(1.0, self.trust + 0.01)
        elif tom.valence < -0.5:
            self.valence = max(-1.0, self.valence - 0.1)
            self.trust = max(0.0, self.trust - 0.02)
        
        # Internal decay back to baseline
        self.valence *= 0.95
        self.arousal *= 0.9