from typing import List, Dict, Any, Optional
import asyncio
import json
import time
import logging

from server.systems.agent.retriever import get_retriever
from server.systems.agent.citation import get_citation_manager
from server.systems.agent.multi_hop import multi_hop
from server.systems.agent.bayesian import bayesian
from server.systems.agent.temporal import temporal
from server.systems.agent.contradiction import contradiction
from server.systems.agent.self_debate import debate
from server.systems.agent.causal_model import causal
from server.systems.agent.symbolic_validator import validator
from server.systems.rag.query_rewriter import get_query_rewriter
from server.systems.rag.arena import get_rag_arena
from server.systems.rag.obsidian_indexer import SIMILARITY_FLOOR, get_obsidian_indexer
from server.systems.llm import LLMEngine
from server.infrastructure.rag_tracer import RAGTracer

logger = logging.getLogger(__name__)


class WebIntelligenceAgent:
    """
    Orchestrates the Research & Web Intelligence pipeline.
    Integrates the RAGArena (Phase 2), multi-hop reasoning,
    Bayesian synthesis, and Epistemic logic.
    """

    def __init__(self, llm: Optional[LLMEngine] = None):
        self.llm       = llm or LLMEngine()
        self.retriever = get_retriever()
        self.citations = get_citation_manager()

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _build_analysis_prompt(self, query: str, context: str) -> str:
        return (
            f'Research Question: "{query}"\n'
            f"Source Content: {context[:3000]}\n\n"
            "Analyze and provide:\n"
            "1. Answer/finding relative to the question.\n"
            "2. Direct representative quote.\n"
            "3. Credibility score (0.0 to 1.0).\n"
            "4. Direction: Support (1), Contradict (-1), or Neutral (0).\n\n"
            "Return ONLY JSON:\n"
            '{"finding": "...", "quote": "...", "credibility": 0.0, "direction": 1}'
        )

    def _analyze_sources(self, query: str, evidence: List[Dict[str, Any]]) -> tuple:
        """Analyze evidence sources and return (findings, evidence_for_bayesian, sources)."""
        sources: Dict[str, List[str]] = {}
        for item in evidence:
            url = item.get("metadata", {}).get("url", "unknown")
            sources.setdefault(url, []).append(item.get("content", ""))

        findings: List[Dict[str, Any]] = []
        evidence_for_bayesian: List[Dict[str, Any]] = []

        for url, chunks in sources.items():
            context = "\n---\n".join(chunks[:3])
            prompt  = self._build_analysis_prompt(query, context)
            try:
                response = self.llm.chat_completion(
                    [
                        {"role": "system", "content": "You are a senior research analyst."},
                        {"role": "user",   "content": prompt},
                    ],
                    temperature=0.1,
                )
                data = json.loads(
                    response.replace("```json", "").replace("```", "").strip()
                )
                findings.append(data)
                evidence_for_bayesian.append(
                    {
                        "id":        url,
                        "strength":  data.get("credibility", 0.5),
                        "direction": data.get("direction", 1),
                    }
                )
            except Exception as exc:
                logger.error("Analysis error for %s: %s", url, exc)

        return findings, evidence_for_bayesian, sources

    # Chroma returns top-k regardless of relevance (no threshold of its own), so
    # drop clearly-unrelated chunks before injecting them into the prompt. The
    # floor is shared with /api/obsidian/search (defined in obsidian_indexer.py)
    # and calibrated on the live vaults: real matches score >= 0.167 while
    # boilerplate noise (e.g. an empty vault's Welcome.md, gibberish queries)
    # measures 0.0-0.128. Code-heavy chunks can still score moderately on
    # unrelated queries — the LLM is told to use the context only when relevant.

    def _gather_vault_context(self, question: str, k: int = 3) -> str:
        """
        Pull relevant notes from both Obsidian vaults and return them as a
        labeled prompt block. Each vault has a distinct role:

          obsidian_developer -> the codebase / architecture vault (read-only
                                context so Aariya understands her own code)
          obsidian_runtime   -> the runtime vault (episodic logs of how Aariya
                                is actually running)

        Empty when no vault is configured, Chroma is unavailable, or the
        question matches nothing — retrieval failures must never break research.
        """
        try:
            indexer = get_obsidian_indexer()
            dev = [m for m in indexer.retrieve(question, k=k, mem_type="obsidian_developer")
                   if m.get("similarity", 0) > SIMILARITY_FLOOR]
            run = [m for m in indexer.retrieve(question, k=k, mem_type="obsidian_runtime")
                   if m.get("similarity", 0) > SIMILARITY_FLOOR]
        except Exception as exc:
            logger.warning("Obsidian vault retrieval failed: %s", exc)
            return ""

        blocks = []
        if dev:
            blocks.append(
                "[Codebase context — developer Obsidian vault:]\n"
                + indexer.format_for_prompt(dev, limit=3)
            )
        if run:
            blocks.append(
                "[Running details — runtime Obsidian vault:]\n"
                + indexer.format_for_prompt(run, limit=3)
            )
        return "\n\n".join(blocks)

    # ─────────────────────────────────────────────────────────────────────────
    # Per-strategy runner (used inside asyncio.gather)
    # ─────────────────────────────────────────────────────────────────────────

    async def _run_strategy(self, strat: Dict[str, Any]) -> Dict[str, Any]:
        t0          = time.time()
        strat_query = strat.get("query", "")
        strat_type  = strat.get("strategy", "base")

        reasoning_result  = multi_hop.execute_reasoning_chain(strat_query)
        evidence          = reasoning_result.get("evidence", [])
        sub_questions     = reasoning_result.get("sub_questions", [])

        findings, evidence_for_bayesian, sources = self._analyze_sources(strat_query, evidence)

        return {
            "strategy":              strat_type,
            "query":                 strat_query,
            "findings":              findings,
            "evidence_for_bayesian": evidence_for_bayesian,
            "sub_questions":         sub_questions,
            "latency":               time.time() - t0,
            "sources":               sources,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Main research pipeline
    # ─────────────────────────────────────────────────────────────────────────

    async def run_research(self, question: str) -> Dict[str, Any]:
        """Execute the full research pipeline for a question."""
        logger.info("Starting Multi-Hop Research: %s", question)
        tracer = RAGTracer(question)
        tracer.set_intent("multi_hop_research")

        try:
            # ── Phase 2: RAGArena — generate & pit strategies ─────────────
            rewriter = get_query_rewriter()
            arena    = get_rag_arena()

            t0         = time.time()
            strategies = await rewriter.generate_strategies(question, num_strategies=2)
            tracer.step("generate_strategies", t0, {"count": len(strategies)})

            logger.info("Executing %d strategies in RAG Arena.", len(strategies))
            completed = await asyncio.gather(*[self._run_strategy(s) for s in strategies])

            t0 = time.time()
            winning, ranked = arena.evaluate_strategies(list(completed))
            tracer.step(
                "rag_arena_evaluation",
                t0,
                {
                    "winner":            winning["strategy"],
                    "winner_score":      winning["arena_metrics"]["score"],
                    "total_competitors": len(ranked),
                },
            )

            # Adopt the winner's context
            findings              = winning["findings"]
            evidence_for_bayesian = winning["evidence_for_bayesian"]
            sub_questions         = winning["sub_questions"]

            for bay_item, find_data in zip(evidence_for_bayesian, findings):
                url        = bay_item["id"]
                quote      = find_data.get("quote", "")
                credibility = find_data.get("credibility", 0.5)
                self.citations.add_citation(
                    url=url,
                    excerpt=quote,
                    title=url.split("/")[-1].replace("_", " "),
                    credibility=credibility,
                )
                tracer.add_chunk(quote, credibility, url, len(quote) // 4)

            # ── Bayesian Synthesis ─────────────────────────────────────────
            t0 = time.time()
            bayesian_result = bayesian.sequential_update(0.5, evidence_for_bayesian)
            tracer.step("bayesian_synthesis", t0, {"evidence": len(evidence_for_bayesian)})

            # ── Epistemic logic ────────────────────────────────────────────
            t0 = time.time()
            temporal_conflicts = temporal.detect_timeline_conflicts(evidence_for_bayesian)
            contradictions     = contradiction.detect_conflicts(evidence_for_bayesian)
            tracer.step(
                "epistemic_logic",
                t0,
                {"conflicts": len(temporal_conflicts) + len(contradictions)},
            )

            # ── Obsidian vault context (codebase + running details) ────────
            t0 = time.time()
            vault_context = self._gather_vault_context(question)
            tracer.step("obsidian_vault_retrieval", t0, {"chars": len(vault_context)})

            # ── Self-Debate ────────────────────────────────────────────────
            t0 = time.time()
            initial_synthesis              = await self._synthesize(question, findings, vault_context)
            refined_answer, logic_confidence = await debate.conduct_debate(
                question, initial_synthesis, str(findings)
            )
            tracer.step("self_debate", t0, {"logic_confidence": logic_confidence})

            # ── Final Bayesian update ──────────────────────────────────────
            t0 = time.time()
            final_belief = bayesian.sequential_update(
                bayesian_result.get("final_belief", 0.5),
                [{"id": "self_debate", "strength": logic_confidence, "direction": 1}],
            )
            tracer.step("final_bayesian_update", t0)

            tracer.set_context_stats(
                sum(len(f.get("quote", "")) // 4 for f in findings),
                len(winning["sources"]),
            )
            rag_trace = tracer.finalize()
            if vault_context:
                rag_trace["obsidian_vault_context"] = vault_context[:2000]

            # ── Self-Healing ingestion ─────────────────────────────────────
            from server.systems.self_heal.loop import get_healing_engine
            heal_status = await get_healing_engine().ingest_and_evaluate(rag_trace)
            rag_trace["self_heal_status"] = heal_status

            # ── Runtime log — Aariya's running details -> runtime vault ─────
            # Research turns are notable activity; append a compact entry so
            # the runtime vault accumulates real running details over time
            # Skip when the answer came back empty (e.g. LLM unreachable) — an
            # empty "running detail" is just noise.
            if refined_answer:
                try:
                    log_path = get_obsidian_indexer().append_runtime_note(
                        f"Research turn. Question: {question}\n"
                        f"Answer: {refined_answer[:400]}",
                        title=f"Research · {winning['strategy']}",
                    )
                    if log_path:
                        rag_trace["runtime_log_file"] = log_path
                except Exception as exc:
                    logger.warning("Runtime note write failed: %s", exc)

            return {
                "query":    question,
                "answer":   refined_answer,
                "confidence": final_belief.get("final_belief", logic_confidence),
                "epistemic_trace": {
                    "bayesian":          final_belief.get("trace", []),
                    "temporal_conflicts": temporal_conflicts,
                    "contradictions":    contradictions,
                    "logic_score":       logic_confidence,
                    "sub_questions":     sub_questions,
                },
                "citations":    self.citations.get_citations(),
                "bibliography": self.citations.format_as_markdown(),
                "rag_trace":    rag_trace,
            }

        except Exception as exc:
            tracer.step("error", time.time())
            rag_trace = tracer.finalize()

            # The self-heal pass is best-effort telemetry. If IT fails, that
            # must never mask the original research error or escape this
            # handler — run_research always returns a dict so callers (the
            # autonomy executor, background learner) can degrade gracefully.
            try:
                from server.systems.self_heal.loop import get_healing_engine
                heal_status = await get_healing_engine().ingest_and_evaluate(rag_trace)
                rag_trace["self_heal_status"] = heal_status
            except Exception as heal_exc:
                logger.warning("Self-heal ingest failed during research error path: %s", heal_exc)
                rag_trace["self_heal_status"] = {"status": "skipped", "error": str(heal_exc)[:200]}

            logger.error("Research failed: %s", exc)
            return {"error": str(exc), "status": "failed", "rag_trace": rag_trace}

    async def _synthesize(
        self,
        query: str,
        findings: List[Dict[str, Any]],
        vault_context: str = "",
    ) -> str:
        """First-pass LLM synthesis (optionally grounded on Obsidian vaults)."""
        prompt = (
            f"Synthesize a factual answer for '{query}' based on: "
            f"{json.dumps(findings)}"
        )
        if vault_context:
            prompt += (
                "\n\nLocal knowledge from Aariya's Obsidian vaults "
                "(codebase context and running details). Use it when it is "
                f"relevant to the question:\n{vault_context}"
            )
        return self.llm.chat_completion([{"role": "user", "content": prompt}])

    async def run(self, question: str) -> Dict[str, Any]:
        """Alias for run_research to match server main expectations."""
        return await self.run_research(question)


# ── Singleton ─────────────────────────────────────────────────────────────────
_agent: Optional[WebIntelligenceAgent] = None


def get_research_agent() -> WebIntelligenceAgent:
    global _agent
    if _agent is None:
        _agent = WebIntelligenceAgent()
    return _agent


controller = get_research_agent()
