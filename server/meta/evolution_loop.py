import asyncio
import logging
from ..infrastructure.agent_registry import get_registry
from .scoring_engine import compute_score, classify_state
from .policy_engine import PolicyEngine
from .rewriter import rewrite_agent
from .gap_detector import scan_for_gaps, trigger_spawner
from ..realtime.redis_bus import publish

logger = logging.getLogger("aariya.evolution")

# Tracks the last lifecycle state seen per agent so the loop only reports REAL
# transitions (an agent newly decaying into REWRITE) — not the same weak agent
# every 60 s tick.
_last_lifecycle: dict = {}


async def _emit_real_event(source: str, severity: str, title: str,
                           payload: dict | None = None) -> None:
    """
    Push a REAL self-improvement event into the dashboard Event Log.

    Delegates to the shared helper (server/systems/signal_bus
    emit_real_event). Called only when the Darwin engine genuinely acts — a
    new agent module was written, a weak agent was retired (transitioned to
    REWRITE), or a rewrite landed. Best-effort: a missing bus / dead socket
    never breaks a tick.
    """
    try:
        from server.systems.signal_bus import emit_real_event as _emit
        await _emit(source, severity, title, payload)
    except Exception as exc:
        logger.debug("[Evolution] event log emission skipped: %s", exc)


def _bump_functions_grid() -> None:
    """Force the System Health Functions grid to refresh on the next frame."""
    try:
        from server.systems.system_health import get_system_health
        get_system_health().invalidate_functions()
    except Exception as exc:
        logger.debug("[EvolutionLoop] system health invalidate failed: %s", exc)


def _agent_source_path(agent_record: dict):
    """Resolve an agent record to its real file path (same logic as rewriter)."""
    from pathlib import Path
    project_root = Path(__file__).resolve().parents[2]
    return (project_root / agent_record["file"]).resolve()


def _verify_rewritten_agent(agent_record: dict) -> dict:
    """§71 gate: the freshly rewritten module must parse and keep its public
    surface before we accept the rewrite. Runs in a threadpool. The rewriter
    saved the ORIGINAL as .bak — that is the surface we compare against."""
    from server.meta.verify import verify_candidate
    live = _agent_source_path(agent_record)
    if not live.exists():
        return {"ok": False, "failures": [f"rewritten file missing: {live}"]}
    backup = live.with_suffix(".py.bak")
    reference = backup if backup.exists() else live
    return verify_candidate(live, reference)


def _rollback_rewrite(agent_record: dict) -> bool:
    """Restore the .bak backup the rewriter saved when it swapped the file."""
    from pathlib import Path
    import shutil
    live = _agent_source_path(agent_record)
    backup = live.with_suffix(".py.bak")
    if not backup.exists():
        return False
    shutil.copy2(backup, live)
    logger.warning("[Evolution] Rolled back %s from %s", live.name, backup.name)
    return True

async def evolution_tick():
    """
    The background heartbeat of the Darwin engine.
    Periodically checks agent fitness and gap requirements.
    """
    while True:
        try:
            registry = get_registry()
            agents = registry.get_active_agents()

            # Prune transition tracking for agents no longer in the registry
            # (retired/removed) so the dict doesn't grow forever.
            active_names = {a['name'] for a in agents}
            for gone in list(_last_lifecycle):
                if gone not in active_names:
                    _last_lifecycle.pop(gone, None)

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

                # Real transition: agent decayed into REWRITE (retirement).
                # Only reported on the transition, never re-emitted each tick.
                if state == "REWRITE" and _last_lifecycle.get(t_agent['name']) != "REWRITE":
                    await _emit_real_event(
                        "EVOLUTION", "warn",
                        f"Retiring weak agent: {t_agent['name']} (score={score:.2f})",
                        {"agent": t_agent['name'], "score": round(score, 3), "state": state},
                    )
                    _bump_functions_grid()
                _last_lifecycle[t_agent['name']] = state
                
                if state == "REWRITE":
                    logger.info(f"[Evolution] Agent {t_agent['name']} decaying (score={score:.2f}). Checking policy...")
                    if PolicyEngine.can_rewrite(t_agent):
                        logger.warning(f"[Evolution] Policy approved. Executing LLM rewrite on {t_agent['name']}...")
                        # Run blocking rewriter in threadpool
                        success = await asyncio.get_event_loop().run_in_executor(
                            None, rewrite_agent, t_agent
                        )
                        if success:
                            # §71: verify the generated module BEFORE accepting
                            # it. The rewriter already left a .bak rollback.
                            verdict = await asyncio.get_event_loop().run_in_executor(
                                None, _verify_rewritten_agent, t_agent
                            )
                            if not verdict.get("ok"):
                                rolled_back = await asyncio.get_event_loop().run_in_executor(
                                    None, _rollback_rewrite, t_agent
                                )
                                t_agent["rewrites_failed_verification"] = (
                                    t_agent.get("rewrites_failed_verification", 0) + 1)
                                await _emit_real_event(
                                    "EVOLUTION", "error",
                                    f"Rewrite FAILED verification for {t_agent['name']} — "
                                    f"{'rolled back' if rolled_back else 'ROLLBACK MISSING'}",
                                    {"agent": t_agent["name"],
                                     "failures": verdict.get("failures", [])[:5]},
                                )
                                continue  # do not celebrate an unverified rewrite
                            # Record successful rewrite
                            t_agent["rewrites_last_hour"] = t_agent.get("rewrites_last_hour", 0) + 1
                            t_agent["version"] = t_agent.get("version", 1) + 1
                            publish("AGENT_EVOLVED", {
                                "name": t_agent['name'],
                                "version": t_agent["version"]
                            })
                            await _emit_real_event(
                                "EVOLUTION", "info",
                                f"Rewrote weak agent: {t_agent['name']} → v{t_agent['version']} "
                                f"(verified)",
                                {"agent": t_agent['name'], "version": t_agent["version"]},
                            )
                            _bump_functions_grid()
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
                else:
                    publish("AGENT_SPAWNED", {
                        "type": gap,
                        "state": "NEW",
                        "score": 0.3
                    })
                    # Real self-improvement: a new agent module was written.
                    # `skipped` means the file already existed — not a new spawn.
                    if not spawn_result.get("skipped"):
                        await _emit_real_event(
                            "EVOLUTION", "info",
                            f"Spawned new agent: {spawn_result.get('agent_name', gap)} "
                            f"({spawn_result.get('method', 'template')})",
                            {
                                "capability": gap,
                                "method": spawn_result.get("method"),
                                "agent_name": spawn_result.get("agent_name"),
                                "file": spawn_result.get("file"),
                            },
                        )
                        _bump_functions_grid()
                
        except Exception as e:
            logger.error(f"[Evolution] Tick failed: {e}")
            
        await asyncio.sleep(60) # Run evaluation loop every minute
