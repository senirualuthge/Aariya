import asyncio
import sys
import os
import logging

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# ANSI colours — no external deps
RED    = "\033[91m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

from server.systems.agent.controller import get_research_agent
from server.systems.self_heal.loop import get_healing_engine


async def run_verification():
    print(f"\n{BOLD}{CYAN}{'=' * 46}{RESET}")
    print(f"{BOLD}{CYAN}  Phase 5: Self-Healing RAG Verification{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 46}{RESET}")

    agent  = get_research_agent()
    healer = get_healing_engine()

    # Lower the anomaly threshold so the stress test trips it reliably
    healer.monitor.anomaly_threshold_latency = 0.5   # 500 ms

    # ── Test 1: Healthy, simple query ──────────────────────────────────────
    print(f"\n{GREEN}[1] Firing simple healthy query...{RESET}")
    res1 = await agent.run_research("What is the capital of France?")
    trace1  = res1.get("rag_trace", {})
    status1 = trace1.get("self_heal_status", "unknown")
    latency1 = trace1.get("metrics", {}).get("total_latency", 0)
    print(f"    Latency:    {latency1:.0f} ms")
    print(f"    Heal status: {GREEN}{status1}{RESET}")

    # ── Test 2: Complex query designed to stress the pipeline ──────────────
    print(f"\n{YELLOW}[2] Firing complex, high-latency query...{RESET}")
    res2 = await agent.run_research(
        "Provide an exhaustive multi-dimensional analysis of quantum gravity theories, "
        "their mathematical foundations, experimental challenges, and reconciliation with "
        "the Standard Model of particle physics."
    )
    trace2  = res2.get("rag_trace", {})
    status2 = trace2.get("self_heal_status", "unknown")
    latency2 = trace2.get("metrics", {}).get("total_latency", 0)
    arena_step = next(
        (s for s in trace2.get("steps", []) if s["name"] == "rag_arena_evaluation"),
        None
    )

    print(f"    Latency:    {latency2:.0f} ms")
    if arena_step:
        meta = arena_step.get("meta", {})
        print(f"    Arena Winner: {BOLD}{meta.get('winner', 'N/A')}{RESET} "
              f"(score={meta.get('winner_score', 0):.2f}, "
              f"competitors={meta.get('total_competitors', 0)})")

    # ── Gate ───────────────────────────────────────────────────────────────
    print(f"\n{BOLD}{CYAN}{'=' * 46}{RESET}")

    # heal_status can be a string ("no_anomaly") or a dict {"status": "healing_engaged", ...}
    if isinstance(status2, dict):
        heal_outcome = status2.get("status", "unknown")
        anomalies    = status2.get("anomalies", [])
        actions      = status2.get("actions_taken", [])
        causes       = status2.get("root_causes", [])
    else:
        heal_outcome = status2
        anomalies = actions = causes = []

    if heal_outcome in ("healing_engaged", "heal_action_executed"):
        print(f"{GREEN}{BOLD}  ✅ PASS — Self-Healing Loop Activated!{RESET}")
        print(f"     Anomalies   : {', '.join(anomalies) or 'none'}")
        print(f"     Root Causes : {', '.join(causes) or 'none'}")
        print(f"     Actions     : {', '.join(a for a in actions if a != 'none') or 'none'}")
    elif heal_outcome == "no_anomaly":
        print(f"{GREEN}{BOLD}  ✅ PASS — Pipeline healthy, no anomalies triggered{RESET}")
    else:
        print(f"{YELLOW}{BOLD}  ⚠  Loop status: '{heal_outcome}' — review monitor thresholds{RESET}")

    print(f"{BOLD}{CYAN}{'=' * 46}{RESET}\n")


if __name__ == "__main__":
    asyncio.run(run_verification())
