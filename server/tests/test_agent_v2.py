import asyncio
import os

import pytest

from server.systems.agent.controller import get_research_agent

# This test drives the REAL research pipeline (web search + LLM synthesis), so
# it needs a reachable LLM / network. Skip by default; run with RUN_LIVE_TESTS=1.
pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_TESTS") != "1",
    reason="requires a live LLM — set RUN_LIVE_TESTS=1 to run",
)


def test_research_pipeline_end_to_end():
    result = asyncio.run(
        get_research_agent().run_research(
            "What are the latest breakthroughs in ambient intelligence as of early 2024?"
        )
    )

    # The pipeline must produce a real answer, not an error dict or an empty
    # fallback (e.g. when the LLM is unreachable).
    assert result, "research returned nothing"
    assert "error" not in result, f"research failed: {result.get('error')}"
    assert result.get("answer"), "research returned no answer"

    trace = result.get("epistemic_trace", {})
    assert "logic_score" in trace
    assert isinstance(result.get("citations"), list)
