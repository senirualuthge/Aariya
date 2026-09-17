"""
Causal Reasoning / Internal Simulation (AdvancedPrediction §Causal-Reasoning).

Extends the base CausalGraph with counterfactual reasoning and intervention
analysis so the brain can run mental simulations before acting:

  simulate_node(node, value)      → propagate a hypothetical value downstream
  intervene(source, target, ...)  → what happens if we force an effect
  counterfactual(observed, node)  → what would need to change to flip an outcome
  common_causes(a, b)             → shared upstream drivers (confounders)

Everything is pure graph traversal on the shared PredictionEngine causal graph.
"""

from typing import Any, Dict, List, Optional, Tuple

from server.systems.prediction.prediction_core import CausalEdge


class CausalSimulator:
    def __init__(self, causal_graph):
        self._graph = causal_graph

    # ── Downstream simulation ──────────────────────────────────────────────────

    def simulate_node(self, node: str, value: float) -> Dict[str, Any]:
        """Propagate a hypothetical value through the causal graph, weighted by
        edge confidence. Returns each reachable effect and its induced delta."""
        effects: Dict[str, float] = {}
        for edge in self._graph.successors(node):
            induced = value * edge.confidence
            if edge.target in effects:
                effects[edge.target] = max(effects[edge.target], induced)
            else:
                effects[edge.target] = induced
            # Second-order ripple (single hop beyond direct children).
            for e2 in self._graph.successors(edge.target):
                ripple = induced * e2.confidence
                effects[e2.target] = max(effects.get(e2.target, 0.0), ripple)
        return {
            "node": node,
            "input_value": value,
            "effects": [{"target": k, "induced": round(v, 3)} for k, v in sorted(effects.items(), key=lambda x: -x[1])],
        }

    def intervene(self, source: str, target: str, new_value: float,
                  relation: str = "influences") -> Dict[str, Any]:
        """Do-calculus style mental intervention: force the effect target to
        `new_value` and inspect what changes downstream of it."""
        edge = CausalEdge(source=source, relation=relation, target=target, confidence=0.95)
        self._graph.add_edge(edge)
        try:
            return self.simulate_node(target, new_value)
        finally:
            # Keep the graph clean — interventions are simulations, not facts.
            self._graph.edges = [e for e in self._graph.edges if not (
                e.source == source and e.target == target)]

    def counterfactual(self, observed: Dict[str, float], node: str) -> Dict[str, Any]:
        """
        Given an observed downstream outcome, ask: what upstream change could
        have flipped it? Returns predecessor nodes whose (source * confidence)
        direction matches the desired flip.
        """
        target_value = observed.get(node, 0.0)
        desired = 1.0 if target_value < 0.5 else -1.0
        candidates = []
        for pred in self._graph.predecessors(node):
            contribution = pred.confidence  # how much this cause moves the target
            candidates.append({
                "cause": pred.source,
                "relation": pred.relation,
                "confidence": round(pred.confidence, 3),
                "needed_delta": round(desired / (pred.confidence or 1.0), 3),
                "would_flip": pred.confidence >= 0.5,
            })
        candidates.sort(key=lambda c: -c["confidence"])
        return {
            "node": node,
            "observed_value": target_value,
            "counterfactual_causes": candidates,
            "most_plausible": candidates[0] if candidates else None,
        }

    def common_causes(self, a: str, b: str) -> List[Dict[str, Any]]:
        """Confounders: nodes that influence both a and b."""
        causes_a = {e.source for e in self._graph.predecessors(a)}
        causes_b = {e.source for e in self._graph.predecessors(b)}
        shared = causes_a & causes_b
        return [
            {
                "cause": c,
                "a_relation": next((e.relation for e in self._graph.predecessors(a) if e.source == c), "?"),
                "b_relation": next((e.relation for e in self._graph.predecessors(b) if e.source == c), "?"),
            }
            for c in shared
        ]

    def simulate(self, engine, features: Dict[str, float]) -> Dict[str, Any]:
        """Full internal-simulation pass on the current prediction state."""
        return {
            "causal_chains": engine.causal_chains(list(features.keys())[0]) if features else [],
            "effects": self.simulate_node(list(features.keys())[0], next(iter(features.values()))) if features else {},
            "stability": self._graph_stability(),
        }

    def _graph_stability(self) -> float:
        """Fraction of nodes that are effects of at least one cause (DAG density)."""
        if not self._graph.edges:
            return 0.0
        sources = {e.source for e in self._graph.edges}
        targets = {e.target for e in self._graph.edges}
        all_nodes = sources | targets
        return round(len(targets) / len(all_nodes), 3) if all_nodes else 0.0
