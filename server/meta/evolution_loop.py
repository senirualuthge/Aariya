import asyncio
import logging
from ..infrastructure.agent_registry import get_registry
from .scoring_engine import compute_score, classify_state
from .policy_engine import PolicyEngine
from .rewriter import rewrite_agent
from .gap_detector import scan_for_gaps, trigger_spawner
from ..realtime.redis_bus import publish

logger = logging.getLogger("aariya.evolution")

async def evolution_tick():
    """
    The background heartbeat of the Darwin engine.
    Periodically checks agent fitness and gap requirements.
    """
    while True:
        try:
            registry = get_registry()
            agents = registry.get_active_agents()
            
            # 1. Evaluate fitness
            for t_agent in agents:
                score = compute_score(t_agent['name'])
                state = classify_state(score)
                
                # Assign latest computed meta values
                t_agent['score'] = score
                t_agent['lifecycle_state'] = state
                
                # Broadcast the real-time update to the Neural Swarm UI
                publish("AGENT_UPDATE", {
                    "name": t_agent['name'],
                    "score": score,
                    "state": state
                })
                
                if state == "REWRITE":
                    logger.info(f"[Evolution] Agent {t_agent['name']} decaying (score={score:.2f}). Checking policy...")
                    if PolicyEngine.can_rewrite(t_agent):
                        logger.warning(f"[Evolution] Policy approved. Executing LLM rewrite on {t_agent['name']}...")
                        # Run blocking rewriter in threadpool
                        success = await asyncio.get_event_loop().run_in_executor(
                            None, rewrite_agent, t_agent
                        )
                        if success:
                            # Record successful rewrite
                            t_agent["rewrites_last_hour"] = t_agent.get("rewrites_last_hour", 0) + 1
                            t_agent["version"] = t_agent.get("version", 1) + 1
                            publish("AGENT_EVOLVED", {
                                "name": t_agent['name'],
                                "version": t_agent["version"]
                            })
                    else:
                        logger.info(f"[Evolution] Rewrite blocked by Policy Engine.")
                        
            # 2. Check for missing ecosystem links
            gaps = scan_for_gaps(agents)
            for gap in gaps:
                # trigger_spawner may block on an LLM call — run it in a threadpool
                # (same pattern as rewrite_agent above).
                spawn_result = await asyncio.get_event_loop().run_in_executor(
                    None, trigger_spawner, gap
                )
                if not spawn_result.get("ok"):
                    logger.warning(
                        "[Evolution] Spawn failed for %r: %s",
                        gap, spawn_result.get("error"),
                    )
                publish("AGENT_SPAWNED", {
                    "type": gap,
                    "state": "NEW",
                    "score": 0.3
                })
                
        except Exception as e:
            logger.error(f"[Evolution] Tick failed: {e}")
            
        await asyncio.sleep(60) # Run evaluation loop every minute
