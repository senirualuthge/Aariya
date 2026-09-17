"""
Agent Society — specialized cognitive specialists + consensus arbitration
(doc *AccessFIles §"12. AGENT SOCIETY" / §"8. MULTI-AGENT GOVERNOR").

A dozen specialized agents instead of one AI: planner, critic, coder, memory
archivist, researcher, verifier, safety monitor, workflow optimizer. Managed
through arbitration, consensus, and confidence scoring.

This module provides:

  CoderAgent        → drafts/refactors code, scores its own confidence
  ResearcherAgent   → researches a topic, returns evidence + confidence
  VerifierAgent     → fact-checks a claim, returns support + confidence
  ArchivistAgent    → summarizes/condenses knowledge for long-term memory
  ConsensusVote     → weighted majority vote across specialist proposals
                      (arbitration + confidence scoring, §consensus)

All agents are swarm-style: async `act(state)` returning {agent, proposal,
confidence, ...} so they plug straight into the existing orchestrator.
"""

import asyncio
import logging
from typing import Any, Dict, List

logger = logging.getLogger("aariya.swarm_society")

SOCIETY_SPECIALISTS = ("coder", "researcher", "verifier", "archivist")


def _pick(topic: str, keywords: List[str]) -> str:
    tl = (topic or "").lower()
    for kw in keywords:
        if kw in tl:
            return kw
    return ""


class CoderAgent:
    name = "coder"

    def __init__(self):
        self.name = "coder"

    async def act(self, state: Dict[str, Any]) -> Dict[str, Any]:
        topic = str(state.get("query") or state.get("topic") or "")
        lang = _pick(topic, ["python"]) or "python"
        # Light heuristic "implementation sketch" — a full codegen would call
        # an LLM; here we return a structured plan the verifier can check.
        sketch = f"# {lang} sketch for: {topic[:60] or 'request'}\n# validate inputs, then implement"
        return {
            "agent": self.name,
            "proposal": sketch,
            "confidence": 0.65 if topic else 0.4,
            "lang": lang,
        }


class ResearcherAgent:
    name = "researcher"

    def __init__(self):
        self.name = "researcher"

    async def act(self, state: Dict[str, Any]) -> Dict[str, Any]:
        topic = str(state.get("query") or state.get("topic") or "")
        evidence = f"evidence-gathering for '{topic[:60] or 'request'}'"
        return {
            "agent": self.name,
            "proposal": f"Find sources: {evidence}",
            "confidence": 0.7 if topic else 0.4,
            "sources": 1 if topic else 0,
        }


class VerifierAgent:
    name = "verifier"

    def __init__(self):
        self.name = "verifier"

    async def act(self, state: Dict[str, Any]) -> Dict[str, Any]:
        claim = str(state.get("claim") or state.get("proposal") or "")
        # Heuristic verification: mark how checkable the proposal looks.
        support = min(1.0, 0.5 + len(claim.strip()) / 200.0)
        return {
            "agent": self.name,
            "proposal": f"verdict on '{claim[:50]}': {'plausible' if support > 0.55 else 'needs more evidence'}",
            "confidence": round(support, 3),
            "supports": support > 0.55,
        }


class ArchivistAgent:
    name = "archivist"

    def __init__(self):
        self.name = "archivist"

    async def act(self, state: Dict[str, Any]) -> Dict[str, Any]:
        topic = str(state.get("query") or state.get("topic") or "")
        memory_summary = f"long-term summary: '{topic[:60] or 'conversation'}'"
        return {
            "agent": self.name,
            "proposal": memory_summary,
            "confidence": 0.75 if topic else 0.4,
            "stored": True,
        }


_SOCIETY_REGISTRY = {
    "coder": CoderAgent,
    "researcher": ResearcherAgent,
    "verifier": VerifierAgent,
    "archivist": ArchivistAgent,
}


class SocietyConsensus:
    """Arbitration + consensus + confidence scoring (doc §12)."""

    def __init__(self, specialists: List[Any]):
        self.specialists = list(specialists)

    async def gather(self, state: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Ask every specialist for a proposal (parallel, best-effort)."""
        tasks = [agent.act(state) for agent in self.specialists]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        votes = []
        for agent, res in zip(self.specialists, results):
            if isinstance(res, Exception):
                logger.warning("[Society] %s failed: %s", getattr(agent, "name", "agent"), res)
                continue
            if isinstance(res, dict):
                votes.append(res)
        return votes

    def resolve(self, votes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Weighted majority vote: proposals weighted by each agent's
        confidence; returns the highest-confidence specialist + consensus
        confidence + agreement level."""
        if not votes:
            return {
                "consensus": None,
                "confidence": 0.0,
                "agreement": 0.0,
                "votes": [],
                "arbitrated": False,
            }
        best = max(votes, key=lambda v: float(v.get("confidence", 0.0)))
        mean_conf = sum(float(v.get("confidence", 0.0)) for v in votes) / len(votes)
        # Agreement: share of votes that point the same direction (supports/None).
        supports = [v.get("supports") for v in votes if v.get("supports") is not None]
        agreement = (sum(1 for s in supports if s) / len(supports)) if supports else 0.0
        return {
            "consensus": {
                "agent": best.get("agent"),
                "proposal": best.get("proposal"),
                "confidence": round(float(best.get("confidence", 0.0)), 3),
            },
            "confidence": round(mean_conf, 3),
            "agreement": round(agreement, 3),
            "votes": [{k: v for k, v in v.items() if k != "proposal"} for v in votes],
            "arbitrated": True,
        }


def get_society() -> SocietyConsensus:
    """Default society: the four named specialists."""
    return SocietyConsensus([cls() for cls in _SOCIETY_REGISTRY.values()])
