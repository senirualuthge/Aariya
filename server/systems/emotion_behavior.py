class EmotionBehavior:
    def get_physical_mapping(self, valence: float, arousal: float):
        if valence > 0.5:
            expression = "joy" if arousal > 0.5 else "smile"
            gestures = ["happy_wave", "leaning_in"]
        elif valence < -0.5:
            expression = "concern" if arousal > 0.5 else "sad"
            gestures = ["comfort_posture"]
        else:
            expression = "neutral"
            gestures = ["idle_sway"]
        return expression, gestures