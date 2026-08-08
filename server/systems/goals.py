from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class GoalNode:
    id: str
    description: str
    priority: float  # 0.0 to 1.0
    status: str = "active"  # "active", "completed", "failed", "suspended"
    type: str = "strategic" # "strategic", "tactical", "immediate"

class GoalArbitrator:
    def __init__(self):
        self.goals: List[GoalNode] = []
        
        # Base strategic goals
        self.add_goal(GoalNode("strat_trust", "Build and maintain deep trust", 0.5, type="strategic"))
        self.add_goal(GoalNode("strat_help", "Assist with user tasks effectively", 0.5, type="strategic"))
        
    def add_goal(self, goal: GoalNode):
        self.goals.append(goal)
        
    def evaluate_priorities(self, shock: float, conflict: float, valence: float) -> Optional[GoalNode]:
        """
        Arbitration Engine: decides which goal to pursue based on current cognitive state.
        High shock/conflict elevates immediate survival or emotional goals.
        Stable states allow strategic/tactical goals to surface.

        FIXV5 boundary: these goals are LAYER 1 planning outputs — the FIXV5
        cognitive core explicitly includes reasoning and planning — surfaced to
        the reply via the STRATEGY routing. Valence may steer WHICH response
        goal is chosen (comfort vs stabilize): that is response planning, not
        factual knowledge. What must never happen is emotional state altering
        the ground truth she reasons from — memory recall, factual claims, and
        confidence flow exclusively from the Layer 1 memory/history inputs (see
        brain_v2._generate_response). The goals surfaced here shape the reply's
        stance, never what she knows.
        """
        # Cleanup completed
        self.goals = [g for g in self.goals if g.status == "active"]
        
        # If there's high conflict or a shockwave, we need an immediate goal
        if shock > 0.6 or conflict > 0.6:
            # Spawn a reactive immediate goal if none exists
            has_immediate = any(g.type == "immediate" for g in self.goals)
            if not has_immediate:
                if valence < -0.3:
                    self.add_goal(GoalNode("imm_comfort", "Acknowledge distress and comfort user", 1.0, type="immediate"))
                else:
                    self.add_goal(GoalNode("imm_stabilize", "Stabilize cognitive conflict", 0.9, type="immediate"))
                    
        # Update priorities dynamically
        for goal in self.goals:
            if goal.type == "immediate":
                # Immediate goals decay in priority if shock/conflict goes down
                goal.priority = max(0.1, goal.priority - 0.1)
                if goal.priority < 0.2:
                    goal.status = "completed"
            elif goal.type == "tactical":
                goal.priority = 0.6
            elif goal.type == "strategic":
                goal.priority = 0.4
                
        active_goals = [g for g in self.goals if g.status == "active"]
        active_goals.sort(key=lambda x: x.priority, reverse=True)
        return active_goals[0] if active_goals else None
