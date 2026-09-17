import networkx as nx
import json
import logging
from typing import List, Dict, Any, Optional
from server.systems.agent.config import config
import os

logger = logging.getLogger(__name__)

class KnowledgeGraph:
    """
    Manages structured knowledge using a graph database.
    Stores Extract-Transform-Load (ETL) triples.
    """
    
    def __init__(self):
        self.graph = nx.DiGraph()
        self.path = config.KNOWLEDGE_GRAPH_PATH
        self._load_graph()
        
    def add_triple(self, subject: str, relation: str, object_: str, metadata: Dict = {}):
        """Add a fact triple to the graph."""
        self.graph.add_edge(subject, object_, relation=relation, **metadata)
        self._save_graph()
        
    def query(self, entity: str) -> List[Dict[str, Any]]:
        """Retrieve related facts for an entity."""
        facts = []
        if entity in self.graph:
            # Outgoing edges
            for neighbor in self.graph.successors(entity):
                edge_data = self.graph.get_edge_data(entity, neighbor)
                facts.append({
                    "subject": entity,
                    "relation": edge_data.get("relation"),
                    "object": neighbor,
                    "meta": edge_data
                })
        return facts

    def query_incoming(self, entity: str) -> List[Dict[str, Any]]:
        """Facts where the entity is the OBJECT (e.g. which files define
        a given function/class). Complements query()."""
        facts = []
        if entity in self.graph:
            for subject in self.graph.predecessors(entity):
                edge_data = self.graph.get_edge_data(subject, entity)
                facts.append({
                    "subject": subject,
                    "relation": edge_data.get("relation"),
                    "object": entity,
                    "meta": edge_data
                })
        return facts

    def _save_graph(self):
        """Persist graph to JSON."""
        try:
            data = nx.node_link_data(self.graph)
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logger.error(f"Failed to save knowledge graph: {e}")

    def _load_graph(self):
        """Load graph from JSON."""
        if os.path.exists(self.path):
            try:
                with open(self.path, 'r') as f:
                    data = json.load(f)
                self.graph = nx.node_link_graph(data)
            except Exception as e:
                logger.error(f"Failed to load knowledge graph: {e}")
                self.graph = nx.DiGraph()

# Global instance
kg = KnowledgeGraph()
