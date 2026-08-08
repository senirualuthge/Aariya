import asyncio
from typing import Dict, Any, List

from .agents.base import Agent
from .agents.planner import PlannerAgent
from .agents.emotion import EmotionAgent
from .agents.critic import CriticAgent
from .agents.vision import VisionAgent
from server.systems.security.agents.api_security_agent import APISecurityAgent
from server.systems.security.agents.integrity_agent import IntegrityAgent
from server.systems.security.agents.network_agent import NetworkAgent
from server.systems.security.agents.memory_agent import MemorySecurityAgent
from server.systems.security.agents.cve_agent import CVEAgent
from server.systems.security.agents.sandbox_agent import SandboxAgent
from server.systems.security.agents.mobile_agent import MobileAgent
from server.systems.security.risk_engine import RiskEngine
from server.systems.security.remediation_engine import RemediationEngine
from server.systems.security.event_logger import get_event_logger

class SwarmSystem:
    """
    Orchestrates specialized sub-agents running in parallel
    for decentralized multi-agent cognitive architecture.
    """
    def __init__(self):
        self.planner = PlannerAgent()
        self.emotion = EmotionAgent()
        self.critic  = CriticAgent()
        self.vision  = VisionAgent()

        self.active_agents = [self.planner, self.emotion, self.vision]

        self.security_agents = [
            APISecurityAgent(),
            IntegrityAgent(),
            NetworkAgent(),
            MemorySecurityAgent(),
            CVEAgent(),
            SandboxAgent(),
            MobileAgent(),
        ]
        self.risk_engine = RiskEngine()
        self.remediation_engine = RemediationEngine()
        self.event_logger = get_event_logger()

    async def process_turn(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute swarm cognition loop using async parallel execution.
        """
        # 1. Parallel Agent Thoughts
        tasks = [agent.act(state) for agent in self.active_agents]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        valid_results = []
        for res in results:
            if isinstance(res, Exception):
                print(f"[Swarm Error] Agent failed: {res}")
            else:
                valid_results.append(res)
                
        # 2. Add Critic Evaluation
        # valid_results contains only dicts (exceptions filtered above)
        clean_results: List[Dict[str, Any]] = [r for r in valid_results if isinstance(r, dict)]
        evaluation = await self.critic.act(state, proposals=clean_results)
        
        # 3. Aggregate Swarm Memory (Return unified structured payload)
        # Extract vision context string from VisionAgent result (if present)
        vision_context = ""
        for r in valid_results:
            if isinstance(r, dict) and r.get("agent") == "vision":
                vision_context = r.get("context", "")
                break

        aggregated = {
            "swarm_decisions":  valid_results,
            "critic_evaluation": evaluation,
            "vision_context":   vision_context,
        }

        return aggregated

    async def run_security_agents(self, data: Dict[str, Any]) -> Dict[str, Any]:
        all_issues: List[Dict[str, Any]] = []
        tasks = [agent.run(data) for agent in self.security_agents]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for agent, res in zip(self.security_agents, results):
            if isinstance(res, list):
                for issue in res:
                    all_issues.append(issue)
                    self.event_logger.log(
                        event_type="THREAT_DETECTED",
                        agent=agent.name,
                        issue=issue,
                    )

        risk = self.risk_engine.calculate(all_issues)
        self.event_logger.log_risk(risk)

        fixes = await self.remediation_engine.apply(all_issues)
        for action in fixes:
            self.event_logger.log_action(action)

        timeline = self.event_logger.get_timeline(limit=50)

        return {
            "issues": all_issues,
            "risk": risk,
            "actions": fixes,
            "timeline": timeline,
        }

# Global instance pattern similar to other FIXV2 modules
_swarm_instance = None

def get_swarm_system() -> SwarmSystem:
    global _swarm_instance
    if _swarm_instance is None:
        _swarm_instance = SwarmSystem()
    return _swarm_instance
