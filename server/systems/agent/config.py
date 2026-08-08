import os
from pydantic import BaseModel, Field
from typing import Optional, Dict

class AgentConfig(BaseModel):
    """Configuration for the Agent System."""
    
    # API Keys
    BING_API_KEY: Optional[str] = Field(default_factory=lambda: os.getenv("BING_API_KEY"))
    SERPAPI_KEY: Optional[str] = Field(default_factory=lambda: os.getenv("SERPAPI_KEY"))
    # NOTE: web_intelligence.py checks `hasattr(config, "SERPER_API_KEY")` — this
    # field MUST exist for the Serper provider branch to ever activate.
    SERPER_API_KEY: Optional[str] = Field(default_factory=lambda: os.getenv("SERPER_API_KEY"))
    OPENAI_API_KEY: Optional[str] = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    
    # Model Selection
    PRIMARY_MODEL: str = "mistral"  # Default local model
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    
    # Resource Limits
    MAX_SEARCH_RESULTS: int = 5
    MAX_REASONING_STEPS: int = 10
    MAX_EVIDENCE_ITEMS: int = 20
    REQUEST_TIMEOUT: int = 10
    
    # Feature Flags
    ENABLE_WEB_SEARCH: bool = True
    ENABLE_KNOWLEDGE_GRAPH: bool = True
    ENABLE_FORMAL_LOGIC: bool = False  # Disabled by default until Phase 4
    ENABLE_CAUSAL_MODEL: bool = False
    
    # Paths
    KNOWLEDGE_GRAPH_PATH: str = "server/data/knowledge_graph.json"
    FACT_MEMORY_PATH: str = "server/data/fact_memory.json"
    
    class Config:
        env_file = ".env"

# Global configuration instance
config = AgentConfig()
