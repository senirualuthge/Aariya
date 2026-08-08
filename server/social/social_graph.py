"""
FIXV3 Social Graph
Multi-user relationship tracking. Scores by trust × attachment × recency.
Drives autonomous initiation decisions.
"""

from typing import Dict, List, Optional
import time

class SocialNode:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.trust = 0.5
        self.attachment = 0.1
        self.last_interaction = 0.0
        self.engagement_score = 0.0

class SocialGraph:
    """
    Tracks multiple users. Helps AutonomousManager select who to interact with.
    """

    def __init__(self):
        self.nodes: Dict[str, SocialNode] = {}

    def update_node(self, user_id: str, trust: float, attachment: float):
        if user_id not in self.nodes:
            self.nodes[user_id] = SocialNode(user_id)
        
        node = self.nodes[user_id]
        node.trust = trust
        node.attachment = attachment
        node.last_interaction = time.time()
        
        # Calculate overall engagement score
        # High trust + high attachment = high score
        # Favor users we haven't spoken to too recently (e.g. > 2 hours) but not too long ago
        time_since = (time.time() - node.last_interaction) / 3600.0
        
        recency_multiplier = 1.0
        if time_since < 2.0:
            recency_multiplier = 0.2  # Too recent, don't spam
        elif time_since > 72.0:
            recency_multiplier = 0.5  # Too long, fading connection
            
        node.engagement_score = (trust * 0.6 + attachment * 0.4) * recency_multiplier

    def get_priority_users(self) -> List[SocialNode]:
        """Returns sorted list of users to potentially reach out to."""
        return sorted(self.nodes.values(), key=lambda n: n.engagement_score, reverse=True)

# Global singleton
_social_graph: Optional[SocialGraph] = None

def get_social_graph() -> SocialGraph:
    global _social_graph
    if _social_graph is None:
        _social_graph = SocialGraph()
    return _social_graph
