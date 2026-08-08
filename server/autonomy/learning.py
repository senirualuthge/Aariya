"""
BackgroundLearner — the 'sleeping brain' of Aariya.
────────────────────────────────────────────────────
Runs inside the autonomy daemon at a slow cadence. It:

  1. Detects knowledge gaps from real conversations (LLM-assisted,
     non-blocking — fire-and-forget after each response)
  2. Researches pending gaps using the REAL multi-hop pipeline
  3. Persists what it learns as insights (surfaced to the user later)

Everything is real data — research results come from the actual
research agent (RAG arena + Obsidian vault + web). No mock content.
"""

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional

from server.autonomy.state import AutonomyStore
from server.systems.llm import LLMEngine

logger = logging.getLogger("aariya.autonomy.learning")

_LLM_BASE = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
_LLM_KEY  = os.getenv("LLM_API_KEY",  "lm-studio")
_LLM_MODEL = os.getenv("LLM_MODEL",   "llama3")

_llm: Optional[LLMEngine] = None

def _get_llm() -> LLMEngine:
    global _llm
    if _llm is None:
        _llm = LLMEngine(base_url=_LLM_BASE, api_key=_LLM_KEY, model=_LLM_MODEL)
    return _llm


class BackgroundLearner:
    def __init__(self, store: AutonomyStore):
        self.store = store

    # ── Gap detection (call after each response, non-blocking) ───────────────

    async def detect_and_queue_gaps(self, user_message: str,
                                    assistant_response: str) -> List[Dict[str, Any]]:
        """
        Ask the LLM whether the response showed knowledge gaps, then queue them.
        Runs as a background task so it never delays the reply to the user.
        Returns the list of queued gaps (mostly for logging).
        """
        queued: List[Dict[str, Any]] = []
        if not user_message or not assistant_response:
            return queued
        if len(assistant_response) < 40:
            return queued  # tiny replies rarely betray a gap

        prompt = f"""\
Analyze this AI assistant exchange for genuine knowledge gaps.

User asked: {user_message[:400]}
Assistant answered: {assistant_response[:800]}

Identify 0-2 topics where the assistant made assumptions, hedged with
uncertainty, or clearly lacked information. Return ONLY JSON:
{{"gaps": [{{"topic": "...", "context": "why it matters", "priority": 1-10}}]}}
If no real gaps, return {{"gaps": []}}."""

        try:
            loop = asyncio.get_event_loop()
            raw = await loop.run_in_executor(
                None,
                lambda: _get_llm().chat_completion(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    max_tokens=160,
                ),
            )
            if not raw:
                return queued
            # Robust JSON extraction
            import json, re
            try:
                data = json.loads(raw)
            except Exception:
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                data = json.loads(match.group(0)) if match else {}
            for gap in data.get("gaps", [])[:2]:
                topic = str(gap.get("topic", "")).strip()
                if not topic:
                    continue
                if self.store.add_gap(topic, str(gap.get("context", "")),
                                      int(gap.get("priority", 5))):
                    queued.append(gap)
                    logger.info("[Learner] 🌌 Gap queued: %s", topic)
        except Exception as e:
            logger.debug("[Learner] Gap detection skipped: %s", e)
        return queued

    # ── Background research cycle ────────────────────────────────────────────

    async def run_cycle(self, max_gaps: int = 2) -> Dict[str, Any]:
        """
        Process up to max_gaps pending gaps: research → persist insight.
        Called by the daemon every few minutes while idle.
        """
        pending = self.store.get_pending_gaps(limit=max_gaps)
        if not pending:
            return {"processed": 0, "gaps_left": 0}

        processed = 0
        for gap in pending:
            self.store.update_gap(gap["id"], status="researching")
            try:
                insight_text = await self._research(gap["topic"], gap.get("context", ""))
                if not insight_text:
                    raise ValueError("Research returned no usable content")
                self.store.add_insight(
                    topic=gap["topic"],
                    content=insight_text,
                    source="background_research",
                    confidence=0.7,
                )
                self.store.update_gap(
                    gap["id"], status="resolved",
                    resolved_at=__import__("time").time(),
                    insight=insight_text[:500],
                )
                processed += 1
                logger.info("[Learner] ✅ Learned: %s", gap["topic"])
            except Exception as e:
                logger.warning("[Learner] ❌ Research failed for %s: %s", gap["topic"], e)
                self.store.update_gap(gap["id"], status="failed")

        remaining = len(self.store.get_pending_gaps(limit=10))
        return {"processed": processed, "gaps_left": remaining}

    async def _research(self, topic: str, context: str) -> str:
        """Research a topic via the real multi-hop research agent."""
        from server.systems.agent.controller import get_research_agent
        query = f"{topic} — {context[:120]}" if context else topic
        result = await get_research_agent().run_research(query)
        answer = (result.get("answer") or result.get("summary") or "").strip()
        if not answer:
            raise ValueError("empty research result")
        return answer

    # ── Startup brief ────────────────────────────────────────────────────────

    def get_startup_brief(self, max_insights: int = 3) -> str:
        """
        A summary of everything she learned while the user was away.
        Surfaces the newest unsurfaced insights.
        """
        insights = self.store.get_unsurfaced_insights(limit=max_insights)
        if not insights:
            return ""
        lines = ["🌌 *Aariya has been learning while you were away...*"]
        for ins in insights:
            content = ins["content"]
            lines.append(f"━━━━━━━━━━━━━━━━")
            lines.append(f"📚 **{ins['topic']}**")
            lines.append(content[:400] + ("..." if len(content) > 400 else ""))
        return "\n".join(lines)
