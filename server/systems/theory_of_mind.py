class TheoryOfMind:
    def __init__(self):
        self.valence = 0.0
        self.arousal = 0.0
        self.engagement = 0.5

    def update(self, valence, arousal):
        # Exponential moving average for user emotion tracking
        alpha = 0.3
        self.valence = (1 - alpha) * self.valence + alpha * valence
        self.arousal = (1 - alpha) * self.arousal + alpha * arousal