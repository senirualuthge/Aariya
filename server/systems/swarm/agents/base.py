from typing import Dict, Any, List

class Agent:
    """
    Base class for all Swarm Agents.
    Every specialized agent must implement the 'act' method.
    """
    def __init__(self, name: str):
        self.name = name

    async def act(self, state: Dict[str, Any]) -> Any:
        """
        Process the incoming state and return the agent's decision or output.
        Must be implemented by subclasses.
        """
        raise NotImplementedError("Agents must implement the act method.")
