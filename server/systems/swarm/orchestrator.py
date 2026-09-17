import asyncio
import math
from typing import Dict, Any, List, Optional

import numpy as np

from .agents.base import Agent
from .agents.planner import PlannerAgent
from .agents.emotion import EmotionAgent
from .agents.critic import CriticAgent
from .agents.vision import VisionAgent
from .agents.filesystem_agent import CognitiveFilesystemAgent
from .agents.local_knowledge_agent import LocalKnowledgeAgent
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
    # Agent → synoptic domain mapping (from the Agents Swarm Visualize doc).
    DOMAIN_MAP = {
        "emotion": ["emotion"],
        "reasoning": ["planner", "critic"],
        "memory": ["memory_agent"],
        "risk": ["risk_engine"],
        "perception": ["vision"],
    }

    def __init__(self):
        self.planner = PlannerAgent()
        self.emotion = EmotionAgent()
        self.critic  = CriticAgent()
        self.vision  = VisionAgent()
        self.filesystem = CognitiveFilesystemAgent()
        self.local_knowledge = LocalKnowledgeAgent()

        self.active_agents = [
            self.planner, self.emotion, self.vision,
            self.filesystem, self.local_knowledge,
        ]

        # Governor: task delegation + result arbitration (doc *AccessFIles §8).
        from server.systems.agent.governor import get_agent_governor
        self.governor = get_agent_governor()
        self.governor.register(self.filesystem)
        self.governor.register(self.local_knowledge)

        # Agent society (doc *AccessFIles §12): specialized specialists
        # (coder/researcher/verifier/archivist) + consensus arbitration.
        from server.systems.swarm.society import get_society, SOCIETY_SPECIALISTS
        self.society = get_society()
        self.society_names = list(SOCIETY_SPECIALISTS)

        # Self-modeling: declare what the runtime actually offers (doc §9).
        from server.systems.agent.self_model import register_default_capabilities
        self.self_model = register_default_capabilities()

        # Smart layer (Agents Swarm Visualize §241-246): prediction, intent,
        # shockwave cascades, stabilization, and narrative drift tracking.
        from server.systems.swarm.gnn_predictor import GNNPredictor
        from server.systems.swarm.intent_detector import IntentDetector
        from server.systems.swarm.shockwave import ShockwaveEngine
        from server.systems.swarm.stabilizer import SwarmStabilizer
        from server.systems.swarm.memory_drift import NarrativeMemory
        self.predictor = GNNPredictor()
        self.intent = IntentDetector()
        self.shockwave = ShockwaveEngine()
        self.stabilizer = SwarmStabilizer()
        self.narrative_memory = NarrativeMemory()
        self._last_activations: Dict[str, float] = {}
        self._train_snapshot: List[Dict[str, Any]] | None = None
        self._last_intent: Dict[str, Any] = {}

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

    def get_activations(self, last_turn: Dict[str, Any] | None = None) -> Dict[str, float]:
        """
        Produce per-domain activation levels [0..1] from the last cognitive
        turn, for the synoptic aggregator. Falls back to neutral defaults
        when no turn data is available yet.
        """
        last_turn = last_turn or {}
        emotion = last_turn.get("emotion", 0.0)
        if isinstance(emotion, dict):
            valence = emotion.get("valence", 0.0)
            arousal = emotion.get("arousal", 0.0)
            emotion_act = min(1.0, abs(valence) + abs(arousal))
        else:
            emotion_act = min(1.0, abs(float(emotion or 0.0)))

        return {
            "emotion": emotion_act,
            "reasoning": 0.8 if last_turn.get("strategy") in ("problem_solving", "logical") else 0.4,
            "memory": 0.8 if last_turn.get("trust", 0.0) > 0.7 else 0.3,
            "risk": 1.0 if last_turn.get("valence", 0.0) < -0.5 else 0.1,
            "perception": 0.9 if last_turn.get("image_b64") else 0.2,
        }

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
        
        # 2.5 Agent Society consensus (doc *AccessFIles §12): specialized
        # specialists propose + vote, weighted by confidence. The arbitrated
        # result rides in `society` so the frontend can show which specialist
        # leads and how much the swarm agrees.
        try:
            society_votes = await self.society.gather(state)
            self._last_society = self.society.resolve(society_votes)
        except Exception as exc:
            logger = __import__("logging").getLogger("aariya.swarm")
            logger.debug("[Swarm] society consensus skipped: %s", exc)
            self._last_society = {"consensus": None, "arbitrated": False}
        
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
            "society":          getattr(self, "_last_society", {}),
        }

        return aggregated

    def smart_layer(self, agents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Run the predictive/intelligence pass over a swarm snapshot
        (Agents Swarm Visualize §247: GNN → intent → shockwave → anomaly →
        stabilization → narrative drift). Best-effort: any failed stage is
        skipped rather than breaking the pass.
        """
        agents = [dict(a) for a in agents]
        result: Dict[str, Any] = {"agent_count": len(agents)}

        # 1. GNN prediction (ghost layer)
        try:
            if len(agents) >= 2:
                result["prediction"] = self.predictor.predict(agents)
        except Exception as e:
            result["prediction"] = {"error": str(e)[:200]}

        # 2. Intent detection
        try:
            result["intent"] = self.intent.detect(agents)
        except Exception as e:
            result["intent"] = {"error": str(e)[:200]}

        # 3. Shockwave cascade (nearest-neighbor interaction graph)
        try:
            edges = [
                {"source": i, "target": j, "weight": 1.0 / (1.0 + abs(agents[i].get("x", 0) - agents[j].get("x", 0)))}
                for i in range(len(agents)) for j in range(len(agents))
                if i != j
            ]
            # sample a small subset of edges to keep it cheap
            edges = edges[: max(4, len(edges) // 2)]
            initial = [0.0] * len(agents)
            if agents:
                initial[0] = 1.0
            result["shockwave"] = {
                "history": self.shockwave.propagate(
                    self.shockwave.build_adjacency(
                        [f"a{i}" for i in range(len(agents))], edges
                    ),
                    np.array(initial),
                    steps=3,
                )[-1].tolist(),
            }
        except Exception as e:
            result["shockwave"] = {"error": str(e)[:200]}

        # 4. Stabilization (self-correcting control)
        try:
            self.stabilizer.stabilize(agents)
            result["stability"] = self.stabilizer.report
        except Exception as e:
            result["stability"] = {"error": str(e)[:200]}

        # 5. Narrative drift tracking
        try:
            self.narrative_memory.add_state(agents)
            result["narrative_drift"] = {
                "score": self.narrative_memory.drift_score(),
                "trend": self.narrative_memory.trend(),
            }
        except Exception as e:
            result["narrative_drift"] = {"error": str(e)[:200]}

        return result

    def build_agent_snapshot(self, activations: Dict[str, float],
                             planets: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """
        Turn domain activations + planetary state into the agent-snapshot shape
        the smart layer expects (id/x/y/vx/vy). Each cognitive domain becomes an
        "agent" node so the GNN has a stable graph to predict over.
        """
        planets = planets or []
        # Position from planets when available (spread around a circle),
        # otherwise deterministic from the domain index.
        positions: Dict[str, Dict[str, float]] = {}
        n = len(planets)
        for i, p in enumerate(planets):
            angle = (i / max(1, n)) * 6.283185307
            positions[p["id"]] = {
                "x": round(10.0 * (1.0 + float(p.get("activation", 0.5))) * math.cos(angle), 3),
                "y": round(10.0 * (1.0 + float(p.get("activation", 0.5))) * math.sin(angle), 3),
            }
        snapshot = []
        for idx, (name, act) in enumerate(activations.items()):
            pos = positions.get(name, {})
            x = pos.get("x", round((idx % 5) * 4.0, 3))
            y = pos.get("y", round((idx // 5) * 4.0, 3))
            # velocity from the last turn delta if tracked, else decayed value
            prev = self._last_activations.get(name, act)
            vx = round(act - prev, 3)
            snapshot.append({
                "id": name,
                "x": x, "y": y,
                "vx": vx, "vy": round(-vx, 3),
                "activation": round(float(act), 4),
            })
        return snapshot

    def run_smart_layer(self, activations: Dict[str, float],
                        planets: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Run the full smart layer on real swarm data each turn AND train the
        GNN on the observed transition (prev snapshot → current) so the
        learning swarm is live, not a dead module. Stores intent/stabilizer
        output for agent-behavior feedback.
        """
        snapshot = self.build_agent_snapshot(activations, planets)
        result = self.smart_layer(snapshot)

        # Online training: previous snapshot is the input, current is the target
        # (positions moved by velocity). Keep the model learning every turn.
        try:
            if self._train_snapshot is not None and len(self._train_snapshot) >= 2:
                loss = self.predictor.train_step(self._train_snapshot, snapshot)
                result["train_loss"] = round(loss, 5)
                result["trained"] = True
        except Exception as e:
            result["train_loss"] = str(e)[:120]
        self._train_snapshot = snapshot

        # Retain last intent for agent-behavior feedback (stored on self.intent).
        if isinstance(result.get("intent"), dict) and not result["intent"].get("error"):
            self._last_intent = result["intent"]

        return result

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
