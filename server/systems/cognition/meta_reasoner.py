"""
Meta-Reasoner — the system reasons about its own reasoning.

Answers: which agent should handle this, how confident are we, and does the
task need verification. Pure heuristic for now; designed to be swapped for a
learned router later (see PredictionEngine docs §Meta-Reasoning).
"""

from typing import Dict, Any

# Default routing when no match is found.
_DEFAULT = {"confidence": 0.5, "requires_verification": True, "best_agent": "general_agent"}


class MetaReasoner:
    def evaluate(self, task: Dict[str, Any]) -> Dict[str, Any]:
        if not task:
            return dict(_DEFAULT)

        intent = str(task.get("intent") or task.get("type") or "").lower()
        keywords = str(task.get("query") or task.get("goal") or "").lower()

        # High-confidence specialized routes.
        if "file" in intent or "fs" in intent or intent in ("read_file", "write_file", "search_files") \
                or any(k in keywords for k in ("read file", "write file", "write a file", "create file",
                                               "create a file", "list files", "list the files", "open file",
                                               "delete file", "folder", "directory", "workspace")):
            return {"confidence": 0.9, "requires_verification": False, "best_agent": "filesystem_agent"}
        if intent in ("search", "research", "web_search") \
                or any(k in keywords for k in ("search", "research", "look up", "find out", "google")):
            return {"confidence": 0.75, "requires_verification": True, "best_agent": "research_agent"}
        if intent in ("code", "refactor", "debug", "implement") \
                or any(k in keywords for k in ("write code", "fix the bug", "refactor", "implement", "debug", "program", "python")):
            return {"confidence": 0.7, "requires_verification": True, "best_agent": "coding_agent"}
        if "emotion" in intent or "mood" in keywords:
            return {"confidence": 0.8, "requires_verification": False, "best_agent": "emotion_agent"}
        if intent in ("memory", "recall", "remember") \
                or any(k in keywords for k in ("remember", "do you recall", "what do you know about")):
            return {"confidence": 0.85, "requires_verification": False, "best_agent": "local_knowledge_agent"}
        if intent in ("plan", "goal", "decompose") \
                or any(k in keywords for k in ("plan", "goal", "break down", "steps to", "roadmap")):
            return {"confidence": 0.8, "requires_verification": False, "best_agent": "planner_agent"}

        return dict(_DEFAULT)
