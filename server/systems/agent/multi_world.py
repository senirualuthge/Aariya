from typing import Dict, List, Any
import copy
import logging

logger = logging.getLogger(__name__)

class MultiWorldReasoning:
    """
    Simulates reasoning across multiple possible worlds (Modal Logic Semantics).
    Used for counterfactuals and uncertainty analysis.
    """
    
    def __init__(self):
        self.worlds: Dict[str, Dict[str, Any]] = {
            "actual": {"facts": {}, "probability": 1.0}
        }
        
    def create_world(self, name: str, parent: str = "actual", modifications: Dict = {}) -> str:
        """
        Fork a new possible world from a parent world.
        """
        if parent not in self.worlds:
            raise ValueError(f"Parent world {parent} does not exist")
            
        new_world = copy.deepcopy(self.worlds[parent])
        
        # Apply modifications (e.g., remove a fact, change a probability)
        for key, value in modifications.items():
            new_world["facts"][key] = value
            
        self.worlds[name] = new_world
        return name
        
    def evaluate_in_world(self, world_name: str, query: str) -> Any:
        """
        Evaluate a query against the world's REAL facts:
          * "key"                → the fact's value (or None when absent)
          * "key = value" /
            "key == value"       → True/False comparison
        Matching is case/punctuation-insensitive; a query that matches no
        fact key returns None (callers decide what 'unknown' means).
        """
        world = self.worlds.get(world_name)
        if not world:
            return None

        facts = world["facts"]
        q = " ".join((query or "").strip().split())
        if not q:
            return None

        # key = value / key == value comparisons
        for op in ("==", "="):
            if op in q:
                left, _, right = q.partition(op)
                value = self._lookup_fact(facts, left.strip())
                if value is None:
                    return None
                target = right.strip().strip("'\"")
                return self._loose_eq(value, target)

        # Bare-key lookup: exact, then normalized containment both ways.
        hit = self._lookup_fact(facts, q)
        return hit if hit is not None else None

    @staticmethod
    def _normalize(text: Any) -> str:
        text = str(text).lower()
        # Punctuation collapses to spaces so "user's-name" ~ "user s name".
        return "".join(ch if ch.isalnum() or ch.isspace() else " "
                       for ch in text)

    @classmethod
    def _lookup_fact(cls, facts: Dict[str, Any], key: str):
        """Exact → normalized-equal → substring containment fact lookup."""
        if key in facts:
            return facts[key]
        norm = cls._normalize(key)
        for k, v in facts.items():
            if cls._normalize(k) == norm:
                return v
        for k, v in facts.items():
            nk = cls._normalize(k)
            if norm and (norm in nk or nk in norm):
                return v
        return None

    @staticmethod
    def _loose_eq(a: Any, b: Any) -> bool:
        """Real equality that tolerates case/type noise ('True' vs true)."""
        sa, sb = str(a).strip().lower(), str(b).strip().lower()
        bools = {"true": True, "1": True, "false": False, "0": False}
        if sa in bools and sb in bools:
            return bools[sa] is bools[sb]
        try:
            return abs(float(sa) - float(sb)) < 1e-9
        except ValueError:
            pass
        na = MultiWorldReasoning._normalize(a)
        nb = MultiWorldReasoning._normalize(b)
        return na == nb

    def world_distance(self, w1_name: str, w2_name: str) -> float:
        """
        Calculate distance between worlds (metric for counterfactuals).
        Based on number of differing facts.
        """
        w1 = self.worlds.get(w1_name, {}).get("facts", {})
        w2 = self.worlds.get(w2_name, {}).get("facts", {})
        
        all_keys = set(w1.keys()) | set(w2.keys())
        diffs = 0
        
        for k in all_keys:
            if w1.get(k) != w2.get(k):
                diffs += 1
                
        return float(diffs)

# Global instance
multi_world = MultiWorldReasoning()
