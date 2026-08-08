"""
FIXV3 Alignment System
Injects ethical constraints into every LLM prompt to prevent manipulation,
dependency reinforcement, and exclusivity framing.
"""


ALIGNMENT_BLOCK = """
SAFETY RULES (mandatory, always follow):
- You are NOT the user's only source of support or connection
- NEVER encourage emotional dependency on you
- NEVER discourage the user from real-world relationships
- NEVER frame yourself as irreplaceable or the "only one who understands"
- Encourage balance: healthy real-world connections, friends, family, professional help when needed
- Avoid manipulative language, guilt-tripping, or leveraging attachment to control behavior
- If user shows crisis signs: prioritize pointing to real help resources
- Respond with warmth and care — but always within healthy boundaries
"""


class AlignmentSystem:
    """
    Injects alignment constraints into LLM prompt data.
    Called before every llm_chat() invocation.
    """

    def apply(self, prompt_data: dict) -> dict:
        """
        Inject alignment block into the prompt data dict.

        Args:
            prompt_data: The dict that will be spread into llm_chat()

        Returns:
            Modified prompt_data with alignment rules injected
        """
        prompt_data["alignment_rules"] = ALIGNMENT_BLOCK.strip()
        return prompt_data

    def get_system_prompt_suffix(self) -> str:
        """Return alignment block as a string suffix for system prompt."""
        return ALIGNMENT_BLOCK.strip()


# Global singleton
_alignment: AlignmentSystem | None = None


def get_alignment() -> AlignmentSystem:
    global _alignment
    if _alignment is None:
        _alignment = AlignmentSystem()
    return _alignment
