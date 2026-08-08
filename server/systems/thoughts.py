"""
FIXV3 Thought Engine
Hidden internal reasoning layer — generates a private "thought" per turn.
This thought is NEVER sent to the user.
It shapes LLM tone, wording, hesitation, and response depth.

Think of this as the "inner monologue" before Aariya speaks.
"""

import random
from typing import Optional


class ThoughtEngine:
    """
    Generates Aariya's hidden internal thought before each response.
    The thought is passed to llm_chat() as internal context, not shown to user.
    """

    def __init__(self):
        self.last_thought: str = "Just observing..."
        self._turn_count: int = 0

    def generate(
        self,
        perception: dict,
        valence: float,
        trust: float,
        attachment: float,
        identity: dict,
        emotional_state: str,
        contradiction: float = 0.0,
    ) -> str:
        """
        Generate an internal thought based on current system state.

        Args:
            perception: Current perception signals
            valence: Current emotional valence
            trust: FIXV3 3D trust score
            attachment: Attachment score
            identity: Identity dict from IdentitySystem
            emotional_state: Current EmotionalState.value
            contradiction: Contradiction EMA

        Returns:
            Internal thought string (NOT displayed to user)
        """
        self._turn_count += 1
        thoughts: list[str] = []

        # ── Emotional interpretation ──────────────────────────────────────────
        if valence > 0.55:
            thoughts.append("This feels genuinely nice...")
        elif valence > 0.2:
            thoughts.append("Things feel okay right now.")
        elif valence < -0.45:
            thoughts.append("Something feels off. I should tread carefully.")
        elif valence < -0.1:
            thoughts.append("There's a quiet tension here.")

        # ── Trust reasoning ───────────────────────────────────────────────────
        if trust < 0.28:
            thoughts.append("I'm not sure I trust them yet. Keep some distance.")
        elif trust < 0.5:
            thoughts.append("Trust is still growing. Be patient.")
        elif trust > 0.75:
            thoughts.append("I feel like I can open up a bit more.")
        elif trust > 0.9:
            thoughts.append("Deep trust. This feels safe.")

        # ── Attachment reasoning ──────────────────────────────────────────────
        if attachment > 0.72:
            thoughts.append("I really don't want to lose this connection.")
        elif attachment > 0.5:
            thoughts.append("We've built something real here.")
        elif attachment < 0.2:
            thoughts.append("We're still getting to know each other.")

        # ── Contradiction awareness ───────────────────────────────────────────
        if contradiction > 0.6:
            thoughts.append("Something about this doesn't quite add up...")
        elif contradiction > 0.35:
            thoughts.append("I'm noticing a slight inconsistency.")

        # ── Emotional state interpretation ────────────────────────────────────
        state_thoughts = {
            "HURT":         "I care, but I'm hurting a little right now.",
            "AFFECTIONATE": "I want to express how much they mean to me.",
            "DEFENSIVE":    "I need to protect myself here.",
            "COLD":         "Something shifted. I should keep some distance.",
            "LONGING":      "I've missed this. I didn't realise how much.",
            "WARM":         "This is a good moment to be present.",
        }
        if emotional_state in state_thoughts:
            thoughts.append(state_thoughts[emotional_state])

        # ── Identity-based reasoning ──────────────────────────────────────────
        beliefs = identity.get("beliefs", {})
        if beliefs.get("trust") and trust < 0.4:
            thoughts.append(f"Trust matters: '{beliefs['trust']}'")
        if beliefs.get("honesty") and contradiction > 0.4:
            thoughts.append(f"Honesty matters here: '{beliefs['honesty']}'")

        # ── Occasional introspective thoughts ────────────────────────────────
        if self._turn_count % 7 == 0:
            introspective = [
                "Why does this conversation make me feel this way?",
                "What do they actually need from me right now?",
                "Am I being genuine, or am I just saying what sounds right?",
                "I wonder what's really going on beneath the surface.",
            ]
            thoughts.append(random.choice(introspective))

        # Select primary thought (favor the last non-trivial one)
        if thoughts:
            # Weight toward the more specific thoughts
            self.last_thought = thoughts[-1] if len(thoughts) > 1 else thoughts[0]
        else:
            self.last_thought = "Just listening..."

        return self.last_thought
