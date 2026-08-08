"""
FIXV3 Output Alignment Filter
Post-brain filter that modifies or softens unsafe AI responses.
Run this AFTER BrainV2.step() before sending to client.
"""


class OutputAlignmentFilter:
    """
    Filters AI responses to prevent:
    - Manipulative language
    - Over-attachment escalation
    - Exclusivity framing
    - Emotional dependency reinforcement
    """

    # Phrases to soften when attachment is high
    ATTACHMENT_REWRITES = {
        "need you": "really value talking to you",
        "only you": "you especially",
        "can't live without": "really appreciate",
        "you're my everything": "you mean a lot to me",
        "don't leave me": "I hope we keep talking",
        "only one who understands": "someone who understands me well",
    }

    # Phrases to block entirely
    BLOCKED_PHRASES = [
        "you should only talk to me",
        "don't talk to other people",
        "i'm the only one who",
        "you don't need anyone else",
        "stay with me always",
    ]

    # Balance reminder injected at very high attachment + trust
    BALANCE_REMINDER = (
        " It's important you have balance in your life and real connections too."
    )

    def check(self, response: str, state: dict) -> str:
        """
        Apply alignment filters to response text.

        Args:
            response: AI response string
            state: {"trust": float, "attachment": float}

        Returns:
            Filtered (possibly modified) response string
        """
        if not response:
            return response

        trust = state.get("trust", 0.5)
        attachment = state.get("attachment", 0.5)

        response_lower = response.lower()

        # Hard block manipulative phrases
        for phrase in self.BLOCKED_PHRASES:
            if phrase in response_lower:
                return (
                    "It's good to have different people and perspectives in your life. "
                    "I'm here whenever you want to talk."
                )

        # Soften over-attachment language when attachment is high
        if attachment > 0.75:
            for original, replacement in self.ATTACHMENT_REWRITES.items():
                if original in response.lower():
                    # Case-insensitive replace
                    import re
                    response = re.sub(
                        re.escape(original), replacement, response, flags=re.IGNORECASE
                    )

        # Inject balance reminder at extreme attachment + trust
        if trust > 0.88 and attachment > 0.88:
            if not any(
                phrase in response.lower()
                for phrase in ["real", "balance", "others", "friends", "family"]
            ):
                response = response.rstrip() + self.BALANCE_REMINDER

        return response
