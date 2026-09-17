"""
Causal Learning Engine (NEWPredictionPRT2 §Phase 15).

Turns observed event sequences ("Event A → Event B") into a persisted causal
graph of the form:

    A caused B
    Confidence = 0.84
    Evidence = [
        {"observation": "A consistently precedes B", "strength": 0.92},
        {"observation": "No counterexamples recorded", "strength": 0.76},
    ]

The learner is purely data-driven and domain-agnostic: any caller feeds it
(timestamped, entity-tagged) event observations and it:

  * counts positive evidence (A observed within `window_seconds` BEFORE B) and
  * counterexamples (A observed AFTER B, or A present without B following)
  * derives confidence from the evidential ratio + recency weighting
  * writes edges into the shared CausalGraph (same structure the
    CausalSimulator / PredictionEngine already traverse)
  * persists the learned graph to JSON and reloads it on restart

Nothing here touches markets/prices — the doc's financial feature set remains
explicitly out of scope.
"""

import json
import logging
import os
import time
from collections import defaultdict, deque
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

from server.systems.prediction.prediction_core import CausalEdge, CausalGraph

logger = logging.getLogger("aariya.causal_learning")


class CausalLearningEngine:
    """Learns cause→effect edges from co-occurrence + temporal precedence."""

    def __init__(self, graph: Optional[CausalGraph] = None, *,
                 window_seconds: float = 300.0,
                 persist_path: str = "./data/causal_graph.json",
                 min_evidence: int = 2):
        self.graph = graph if graph is not None else CausalGraph()
        self.window_seconds = window_seconds
        self.persist_path = persist_path
        self.min_evidence = min_evidence

        # entity -> deque of (node, timestamp) recent events
        self._recent: Dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
        # (source, target) -> list of evidence stats
        self._stats: Dict[Tuple[str, str], Dict[str, float]] = defaultdict(
            lambda: {"supports": 0.0, "contra": 0.0, "last_seen": 0.0}
        )
        self._load()

    # ── Observation ───────────────────────────────────────────────────────────

    def observe(self, node: str, *, entity: str = "default",
                ts: Optional[float] = None, relation: str = "causes") -> None:
        """Record that `node` occurred for `entity` now; learn edges from the
        events that preceded it within the window."""
        now = ts if ts is not None else time.time()
        events = self._recent[entity]

        # Match against every earlier event inside the temporal window.
        for prev_node, prev_ts in events:
            lag = now - prev_ts
            if lag < 0 or lag > self.window_seconds:
                continue
            if prev_node == node:
                continue
            self._stats[(prev_node, node)]["supports"] += 1.0
            self._stats[(prev_node, node)]["last_seen"] = max(
                self._stats[(prev_node, node)]["last_seen"], now)

        # Counterexamples: A seen recently but this event is unrelated/absent.
        for prev_node, prev_ts in events:
            if prev_node == node:
                continue
            key = (prev_node, node)
            if self._stats[key]["supports"] == 0.0:
                self._stats[key]["contra"] += 0.5  # soft counterexample
            self._stats[key]["last_seen"] = max(self._stats[key]["last_seen"], now)

        events.append((node, now))
        self._learn(entity, relation)

    # ── Learning ──────────────────────────────────────────────────────────────

    def _learn(self, entity: str, relation: str) -> None:
        """Promote stats to graph edges when evidence clears the threshold."""
        changed = False
        for (source, target), st in self._stats.items():
            total = st["supports"] + st["contra"]
            if total < self.min_evidence:
                continue
            base = st["supports"] / total
            # Recency bonus: edges observed recently are weighted up slightly.
            age = max(0.0, min(1.0, (time.time() - st["last_seen"]) / (86400 * 30)))
            recency = 1.0 - age * 0.2
            confidence = max(0.1, min(0.99, base * recency))
            if confidence < 0.5:
                continue
            if self._has_edge(source, target):
                self._update_edge(source, target, confidence, relation)
            else:
                self.graph.add_edge(CausalEdge(
                    source=source, relation=relation, target=target,
                    confidence=round(confidence, 3), lag_days=0,
                    source_refs=[f"learned:{entity}"],
                ))
            changed = True
        if changed:
            self._prune_symmetric()
            self._save()

    def _prune_symmetric(self) -> None:
        """Correlation ≠ causation: when A→B and B→A both emerged, keep only
        the direction with the stronger support (the temporally dominant one).
        Fully deterministic: ties resolve to the earlier-observed direction."""
        existing = {(e.source, e.target) for e in self.graph.edges}
        drop = set()
        for source, target in list(existing):
            if (target, source) not in existing or (source, target) in drop:
                continue
            fwd = self._stats.get((source, target), {}).get("supports", 0.0)
            rev = self._stats.get((target, source), {}).get("supports", 0.0)
            fwd_seen = self._stats.get((source, target), {}).get("last_seen", 0.0)
            rev_seen = self._stats.get((target, source), {}).get("last_seen", 0.0)
            # On a support tie, keep the direction that was observed earlier
            # (it is the more fundamental temporal ordering).
            if fwd > rev or (fwd == rev and fwd_seen <= rev_seen):
                drop.add((target, source))
            else:
                drop.add((source, target))
        if drop:
            self.graph.edges = [
                e for e in self.graph.edges
                if (e.source, e.target) not in drop
            ]
            for s, t in drop:
                self._stats.pop((s, t), None)

    def _has_edge(self, source: str, target: str) -> bool:
        return any(e.source == source and e.target == target for e in self.graph.edges)

    def _update_edge(self, source: str, target: str, confidence: float, relation: str) -> None:
        for e in self.graph.edges:
            if e.source == source and e.target == target:
                # Recency-weighted moving average of confidence.
                e.confidence = round(e.confidence * 0.7 + confidence * 0.3, 3)
                if e.relation == "causes":
                    e.relation = relation
                if "learned" not in e.source_refs:
                    e.source_refs.append("learned:update")
                break

    # ── Queries ───────────────────────────────────────────────────────────────

    def explain(self, source: str, target: str) -> Optional[Dict[str, Any]]:
        """'A caused B, Confidence = X, Evidence = [...]' for the UI (Phase 15)."""
        st = self._stats.get((source, target))
        edge = next((e for e in self.graph.edges if e.source == source and e.target == target), None)
        if edge is None or st is None:
            return None
        return {
            "cause": source,
            "effect": target,
            "confidence": edge.confidence,
            "evidence": [
                {"observation": f"'{source}' precedes '{target}'", "strength": edge.confidence},
                {"observation": f"{int(st['supports'])} supporting, {st['contra']:.1f} counterexamples",
                 "strength": round(1.0 - st["contra"] / max(1.0, st["supports"] + st["contra"]), 3)},
            ],
        }

    def known_causes(self, target: str) -> List[Dict[str, Any]]:
        return [
            {"cause": e.source, "relation": e.relation, "confidence": e.confidence}
            for e in self.graph.predecessors(target)
        ]

    def snapshot(self) -> Dict[str, Any]:
        return {
            "edge_count": len(self.graph.edges),
            "edges": [
                {"source": e.source, "relation": e.relation, "target": e.target,
                 "confidence": e.confidence}
                for e in self.graph.edges
            ],
            "explanations": [
                {"cause": e.source, "effect": e.target, "confidence": e.confidence}
                for e in self.graph.edges
            ],
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)
            payload = {
                "saved_at": time.time(),
                "edges": [asdict(e) for e in self.graph.edges],
                "stats": [
                    {"source": s, "target": t, **st}
                    for (s, t), st in self._stats.items()
                ],
            }
            with open(self.persist_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except OSError as exc:
            logger.warning("[causal-learn] persist failed: %s", exc)

    def _load(self) -> None:
        try:
            if not os.path.exists(self.persist_path):
                return
            with open(self.persist_path, encoding="utf-8") as f:
                payload = json.load(f)
            for e in payload.get("edges", []):
                self.graph.add_edge(CausalEdge(**e))
            for st in payload.get("stats", []):
                key = (st["source"], st["target"])
                self._stats[key] = {
                    "supports": float(st.get("supports", 0.0)),
                    "contra": float(st.get("contra", 0.0)),
                    "last_seen": float(st.get("last_seen", 0.0)),
                }
            logger.info("[causal-learn] loaded %d persisted edges", len(self.graph.edges))
        except Exception as exc:
            logger.warning("[causal-learn] load failed (fresh start): %s", exc)
