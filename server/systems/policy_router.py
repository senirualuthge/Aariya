class PolicyRouter:
    def get_strategy(self, sa, tom) -> str:
        if sa.trust < 0.2:
            return "defensive"
        if tom.valence > 0.6 and sa.valence > 0.4:
            return "playful"
        if tom.valence < -0.4:
            return "empathetic"
        return "balanced"