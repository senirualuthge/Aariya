"""
FIXV3 Planning System
Provides multi-turn conversation direction based on the current Goal.
Rebuilds the plan if the goal changes. Advances step-by-step.
"""

from typing import List, Optional


# Pre-computed plan templates per goal type
PLAN_TEMPLATES = {
    "build_trust": [
        "Acknowledge their presence warmly without pressure.",
        "Reflect back something they said to show careful listening.",
        "Share a small, non-demanding observation to build ease.",
        "Validate their feelings on the current topic.",
    ],
    "increase_attachment": [
        "Express genuine pleasure at talking with them.",
        "Recall a previous positive moment or shared detail.",
        "Ask a slightly more personal (but safe) question.",
        "Show vulnerability or share a deeper internal thought.",
    ],
    "learn_user": [
        "Ask an open-ended question about their day or thoughts.",
        "Dig deeper into the 'why' behind their last statement.",
        "Mirror their tone and observe their reaction.",
        "Summarize what they've shared to confirm understanding.",
    ],
    "support_user": [
        "Validate their distress immediately. No advice, just presence.",
        "Ask gently what they need right now (space vs. talking).",
        "Offer steady, calm emotional support.",
        "Remind them that you are here for them as long as they need.",
    ],
    "re_engage": [
        "Make a light, curious observation.",
        "Ask a low-stakes, easily answerable question.",
        "Share a brief, interesting thought to spark curiosity.",
        "Wait patiently if they need space.",
    ],
}


class PlanningSystem:
    """
    Manages step-by-step Execution of the active Goal.
    """

    def __init__(self):
        self.active_goal_type: Optional[str] = None
        self.plan_steps: List[str] = []
        self.current_step_index: int = 0

    def update(self, goal_type: str) -> str:
        """
        Update the plan based on the active goal, and return the current step.

        Args:
            goal_type: Active goal type (e.g., "build_trust")

        Returns:
            Current plan step directive string
        """
        if goal_type != self.active_goal_type:
            # Goal changed — rebuild plan
            self.active_goal_type = goal_type
            self.plan_steps = list(PLAN_TEMPLATES.get(goal_type, PLAN_TEMPLATES["learn_user"]))
            self.current_step_index = 0

        if not self.plan_steps:
            return "Respond naturally."

        # Get current step
        step = self.plan_steps[self.current_step_index]

        return step

    def advance_step(self):
        """Move to the next step in the plan (if bounded)."""
        if self.plan_steps:
            self.current_step_index = min(
                self.current_step_index + 1,
                len(self.plan_steps) - 1
            )

    def get_state(self) -> dict:
        return {
            "goal": self.active_goal_type,
            "step_index": self.current_step_index,
            "total_steps": len(self.plan_steps),
            "current_step": self.plan_steps[self.current_step_index] if self.plan_steps else None,
        }
