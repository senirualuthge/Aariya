class PolicyEngine:
    """
    Hard Safety Layer for the Evolution System.
    Prevents the system from rewriting critical infrastructure or spiraling out of control.
    """
    MAX_REWRITES_PER_HOUR = 3
    MIN_SCORE_TO_REWRITE = 0.25
    
    # System core agents that should never be autonomously rewritten
    NEVER_TOUCH = {
        "gateway",
        "auth",
        "registry",
        "policy_engine",
        "scoring_engine",
        "agent_watcher",
        "agent_scanner",
        "AgentScanner",
        "AgentRegistry"
    }

    @staticmethod
    def can_rewrite(agent: dict) -> bool:
        """
        Determines if an agent is authorized to be modified by the LLM.
        Expected agent dict format:
        { "name": "emotion_analyzer", "score": 0.2, "rewrites_last_hour": 1 }
        """
        name = agent.get("name", "")
        
        # Check explicit bans
        if name in PolicyEngine.NEVER_TOUCH:
            return False
            
        # Check rate limits
        if agent.get("rewrites_last_hour", 0) >= PolicyEngine.MAX_REWRITES_PER_HOUR:
            return False
            
        # Check score threshold (don't rewrite if doing okay)
        if agent.get("score", 1.0) >= PolicyEngine.MIN_SCORE_TO_REWRITE:
            return False
            
        return True
