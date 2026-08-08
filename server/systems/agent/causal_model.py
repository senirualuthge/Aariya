import networkx as nx
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class CausalModel:
    """
    Structural Causal Model (SCM) using a DAG.
    Supports basic intervention simulation (do-calculus).
    """
    
    def __init__(self):
        self.graph = nx.DiGraph()
        self.nodes_data = {}

    def add_node(self, name: str, value: Any = 0.0, node_type: str = "variable"):
        """Add a node with metadata."""
        self.graph.add_node(name, type=node_type)
        self.nodes_data[name] = {"value": value, "type": node_type}

    def add_causal_edge(self, cause: str, effect: str, weight: float = 0.5):
        """Add a directed causal edge with weight."""
        if not self.graph.has_node(cause): self.add_node(cause)
        if not self.graph.has_node(effect): self.add_node(effect)
        
        # Check for cycles to maintain DAG property
        self.graph.add_edge(cause, effect, weight=weight)
        if not nx.is_directed_acyclic_graph(self.graph):
            self.graph.remove_edge(cause, effect)
            logger.warning(f"Cycle detected: {cause} -> {effect}. Edge removed.")

    def calculate_total_effect(self, source: str, target: str) -> float:
        """
        Calculate total causal effect using all simple paths.
        Effect(A->B) = sum_{paths} product_{edges in path} weight
        """
        if not self.graph.has_node(source) or not self.graph.has_node(target):
            return 0.0
            
        if not nx.has_path(self.graph, source, target):
            return 0.0
            
        total_effect = 0.0
        for path in nx.all_simple_paths(self.graph, source, target):
            path_effect = 1.0
            for i in range(len(path) - 1):
                u, v = path[i], path[i+1]
                path_effect *= self.graph[u][v].get("weight", 0.5)
            total_effect += path_effect
            
        return min(max(total_effect, -1.0), 1.0)

    def do_intervention(self, node: str, value: Any):
        """
        Simulate a do-intervention by removing incoming edges and fixing value.
        """
        if not self.graph.has_node(node): return
        
        # 1. 'do' operation: cut incoming causal influences
        in_edges = list(self.graph.in_edges(node))
        self.graph.remove_edges_from(in_edges)
        
        # 2. Update value
        if node in self.nodes_data:
            self.nodes_data[node]["value"] = value
            
        return f"Intervention do({node}={value}) completed."

# Global instance
causal = CausalModel()
