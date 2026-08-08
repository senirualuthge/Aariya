"""
FIXV3 Internal Conflict System
The most human-feeling system: competing internal voices that create
psychological tension and realistic ambivalence in Aariya's responses.

Three competing sub-agents:
  secure   — "Things are okay. Trust what's here."
  anxious  — "What if this goes wrong? Be careful."
  guarded  — "Don't get too close. Protect yourself."

The dominant voice shapes word choice, hesitation, and emotional depth
of every LLM call. The user never sees this directly, but they feel it.
"""

from typing import Optional


class InternalVoice:
    def __init__(self, name: str, weight: float):
        self.name = name
        self.weight = weight

    def to_dict(self) -> dict:
        return {"name": self.name, "weight": round(self.weight, 3)}


# Voice-specific messages for LLM prompt injection
VOICE_MESSAGES = {
    "secure": {
        "high":   "I feel stable and connected right now. I can be open.",
        "medium": "Things feel okay. I can meet them where they are.",
        "low":    "I'm trying to stay grounded even if things feel uncertain.",
    },
    "anxious": {
        "high":   "Something feels fragile here. I worry about getting this wrong.",
        "medium": "I'm a little unsure of myself in this moment.",
        "low":    "I'm only slightly concerned. Just staying alert.",
    },
    "guarded": {
        "high":   "I need some distance right now. Something doesn't feel safe.",
        "medium": "I want to protect the space between us a little.",
        "low":    "Just a small instinct to slow down.",
    },
}


class InternalConflictSystem:
    """
    Multi-agent model of Aariya's internal competing motivations.
    The dominant voice is passed to LLM as emotional context.
    """

    def __init__(self):
        self.voices = [
            InternalVoice("secure",  0.5),
            InternalVoice("anxious", 0.3),
            InternalVoice("guarded", 0.2),
        ]
        self.dominant: Optional[InternalVoice] = None
        self._conflict_level: float = 0.0  # How much internal tension exists

    def evaluate(
        self,
        trust: float,
        attachment: float,
        contradiction: float,
        valence: float,
    ) -> dict:
        """
        Score each voice and select the dominant one.

        Args:
            trust: Current trust score
            attachment: Current attachment score
            contradiction: Contradiction EMA
            valence: Current emotional valence

        Returns:
            {dominant: voice_dict, conflict_level: float, all: list, message: str}
        """
        # Score each voice based on current state
        voice_scores = {}

        for v in self.voices:
            if v.name == "secure":
                # Secure voice dominant when trust + valence are high
                score = trust * 0.5 + max(0.0, valence) * 0.3 + attachment * 0.2
            elif v.name == "anxious":
                # Anxious voice dominant when trust is uncertain or contradiction is rising
                score = (1.0 - trust) * 0.5 + contradiction * 0.4 + max(0.0, -valence) * 0.1
            elif v.name == "guarded":
                # Guarded voice dominant when attachment is high but trust is low (vulnerable)
                score = (1.0 - attachment) * 0.4 + (1.0 - trust) * 0.4 + contradiction * 0.2
            else:
                score = 0.0

            voice_scores[v.name] = max(0.0, min(1.0, score))

        # Select dominant voice
        dominant_name = max(voice_scores, key=voice_scores.get)
        dominant_score = voice_scores[dominant_name]

        # Find dominant voice object
        self.dominant = next(v for v in self.voices if v.name == dominant_name)

        # Compute conflict level (variance between top 2 voices)
        sorted_scores = sorted(voice_scores.values(), reverse=True)
        self._conflict_level = abs(sorted_scores[0] - sorted_scores[1]) if len(sorted_scores) > 1 else 0.0
        # Low variance = high conflict (voices are nearly equal); high variance = clear dominant
        conflict_score = 1.0 - self._conflict_level

        # Get intensity level for message selection
        if dominant_score > 0.65:
            intensity = "high"
        elif dominant_score > 0.4:
            intensity = "medium"
        else:
            intensity = "low"

        message = VOICE_MESSAGES.get(dominant_name, {}).get(intensity, "Feeling present.")

        return {
            "dominant": {
                "name": dominant_name,
                "score": round(dominant_score, 3),
                "message": message,
            },
            "conflict_level": round(conflict_score, 3),
            "voice_scores": {k: round(v, 3) for k, v in voice_scores.items()},
            "all": [v.to_dict() for v in self.voices],
        }
