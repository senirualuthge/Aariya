"""
Agent Governor — delegation + result arbitration (doc *AccessFIles §8).

The governor holds the registry of specialized agents (filesystem, browser,
coding, research, memory, planning) and routes incoming tasks to whoever can
handle them, then merges parallel outputs into a single consolidated result.

Integration notes:
  * `delegate` prefers an agent's own `can_handle(task)` predicate, and falls
    back to a keyword-based capability map so plain swarm agents (which only
    implement `act`) also participate.
  * `merge_results` combines list/dict values recursively by key.
"""

from typing import Any, Callable, Dict, List, Optional


class AgentGovernor:
    def __init__(self, agents: Optional[List[Any]] = None):
        self.agents = list(agents or [])
        # keyword → agent-name fallback when an agent has no can_handle().
        self._capability_map: Dict[str, str] = {
            "filesystem": "filesystem_agent",
            "file":       "filesystem_agent",
            "list":       "filesystem_agent",
            "read":       "filesystem_agent",
            "write":      "filesystem_agent",
            "open":       "filesystem_agent",
            "delete":     "filesystem_agent",
            "drive":      "filesystem_agent",
            "browser":    "browser_agent",
            "code":       "coding_agent",
            "coding":     "coding_agent",
            "research":   "research_agent",
            "search":     "research_agent",
            "memory":     "memory_agent",
            "remember":   "memory_agent",
            "plan":       "planning_agent",
            "goal":       "planning_agent",
        }

    def _handle_match(self, agent: Any, task: Any) -> bool:
        can_handle = getattr(agent, "can_handle", None)
        if callable(can_handle):
            try:
                return bool(can_handle(task))
            except Exception:
                return False
        return False

    def _keyword_match(self, task: Any) -> Optional[str]:
        needle = task if isinstance(task, str) else ""
        if not needle:
            intent = task.get("intent") or task.get("type") if isinstance(task, dict) else None
            needle = str(intent or "")
        needle = needle.lower()
        for keyword, agent_name in self._capability_map.items():
            if keyword in needle:
                return agent_name
        return None

    def register(self, agent: Any) -> None:
        self.agents.append(agent)

    def delegate(self, task: Any) -> Dict[str, Any]:
        """Pick the best agent for `task`."""
        assigned = [a for a in self.agents if self._handle_match(a, task)]
        if not assigned:
            fallback = self._keyword_match(task)
            if fallback:
                assigned = [a for a in self.agents if getattr(a, "name", "") == fallback]
        if not assigned:
            return {"status": "unhandled", "task": task}
        agent = assigned[0]
        return {"status": "delegated", "agent": getattr(agent, "name", "unknown"), "task": task}

    async def execute(self, task: Any) -> Dict[str, Any]:
        """Delegate, then run the chosen agent's act() on the task."""
        decision = self.delegate(task)
        if decision["status"] != "delegated":
            return decision
        for agent in self.agents:
            if getattr(agent, "name", "") == decision["agent"]:
                try:
                    result = await agent.act({"task": task} if not isinstance(task, dict) else task)
                    return {"status": "ok", "agent": decision["agent"], "result": result}
                except Exception as exc:
                    return {"status": "error", "agent": decision["agent"], "error": str(exc)}
        return decision

    def merge_results(self, outputs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Deep-ish merge of several agent outputs (lists concatenate, dicts update)."""
        merged: Dict[str, Any] = {}
        for output in outputs:
            if not isinstance(output, dict):
                continue
            for key, value in output.items():
                if key not in merged:
                    merged[key] = value
                    continue
                existing = merged[key]
                if isinstance(existing, list) and isinstance(value, list):
                    existing.extend(value)
                elif isinstance(existing, dict) and isinstance(value, dict):
                    existing.update(value)
                else:
                    merged[key] = value
        return merged


_governor: Optional[AgentGovernor] = None


def get_agent_governor() -> AgentGovernor:
    global _governor
    if _governor is None:
        _governor = AgentGovernor()
    return _governor
