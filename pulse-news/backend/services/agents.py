from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from db import db_cursor, get_learned_weight  # type: ignore

logger = logging.getLogger("pulse.agents")

_SOURCE_CREDIBILITY: Dict[str, float] = {}
_DEFAULT_CREDIBILITY = float(os.getenv("PULSE_DEFAULT_CREDIBILITY", "0.60"))

_raw = os.getenv("PULSE_TRUSTED_DOMAINS", "")
if _raw:
    for pair in _raw.split(","):
        if ":" in pair:
            domain, score = pair.rsplit(":", 1)
            try:
                _SOURCE_CREDIBILITY[domain.strip()] = float(score)
            except ValueError:
                pass
if not _SOURCE_CREDIBILITY:
    _SOURCE_CREDIBILITY = {
        "reuters.com": 0.95, "apnews.com": 0.95, "bbc.com": 0.92,
        "nytimes.com": 0.90, "wsj.com": 0.90, "washingtonpost.com": 0.88,
        "bloomberg.com": 0.88, "economist.com": 0.90, "theguardian.com": 0.85,
        "npr.org": 0.85, "cnn.com": 0.80,
    }

_ALERT_COOLDOWN: Dict[str, float] = {}  # topic_hash -> timestamp


def _domain_credibility(url: str) -> float:
    for domain, score in _SOURCE_CREDIBILITY.items():
        if domain in url:
            return score
    return _DEFAULT_CREDIBILITY


def _source_diversity(category: str, hours: int = 1) -> float:
    with db_cursor() as cur:
        cur.execute(
            "SELECT COUNT(DISTINCT source_id) FROM articles WHERE category = %s AND ingested_at > now() - INTERVAL '%s hours'",
            (category, hours),
        )
        row = cur.fetchone()
        count = row["count"] if row else 0
    return min(1.0, count / 5.0)


def _check_cooldown(article: Dict[str, Any], cooldown_mins: int = 30) -> bool:
    topic = article.get("category", "other") or "other"
    title = article.get("title", "")
    topic_hash = f"{topic}:{hash(title) % 10000}"
    now = time.time()
    last = _ALERT_COOLDOWN.get(topic_hash, 0)
    if now - last < cooldown_mins * 60:
        return False
    _ALERT_COOLDOWN[topic_hash] = now
    return True


def _burst_detection_score(category: str) -> float:
    with db_cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) as cnt FROM articles
            WHERE category = %s AND ingested_at > now() - INTERVAL '1 hour'
            """,
            (category,),
        )
        recent = cur.fetchone()["count"] or 0
        cur.execute(
            """
            SELECT COUNT(*) as cnt FROM articles
            WHERE category = %s
              AND ingested_at BETWEEN now() - INTERVAL '2 hours' AND now() - INTERVAL '1 hour'
            """,
            (category,),
        )
        prev = cur.fetchone()["count"] or 1
    if prev == 0:
        return 0.0
    ratio = recent / prev
    return min(1.0, max(0.0, (ratio - 1.0) / 3.0))


class TrendAgent:
    def analyze(self, article: Dict[str, Any]) -> float:
        cat = article.get("category", "other") or "other"
        imp = article.get("importance", 5) or 5
        diversity = _source_diversity(cat, hours=1)
        burst = _burst_detection_score(cat)
        velocity = article.get("importance", 5) / 10.0

        w_imp = get_learned_weight("trend_impact_weight", 0.35)
        w_div = get_learned_weight("trend_diversity_weight", 0.20)
        w_burst = get_learned_weight("trend_burst_weight", 0.25)
        w_vel = get_learned_weight("trend_velocity_weight", 0.20)
        total = w_imp + w_div + w_burst + w_vel
        if total > 0:
            w_imp, w_div, w_burst, w_vel = (w_imp / total, w_div / total, w_burst / total, w_vel / total)
        score = w_imp * (imp / 10.0) + w_div * diversity + w_burst * burst + w_vel * velocity
        return round(min(1.0, score), 4)


class FactAgent:
    def verify(self, article: Dict[str, Any]) -> bool:
        url = article.get("url", "")
        credibility = _domain_credibility(url)
        if credibility < 0.4:
            return False
        sources = article.get("source_id", "")
        if "serpapi" in sources or "gdelt" in sources:
            return credibility > 0.55
        return credibility > 0.50

    def confidence(self, article: Dict[str, Any]) -> float:
        return _domain_credibility(article.get("url", ""))


class ContradictionAgent:
    def __init__(self):
        self._llm_available = bool(os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY"))

    def detect(self, article: Dict[str, Any]) -> Dict[str, Any]:
        title = article.get("title", "")
        summary = article.get("summary", "")
        category = article.get("category", "other")

        with db_cursor() as cur:
            cur.execute(
                """
                SELECT title, summary FROM articles
                WHERE category = %s AND id != %s
                  AND ingested_at > now() - INTERVAL '24 hours'
                ORDER BY ingested_at DESC LIMIT 5
                """,
                (category, article.get("id", "")),
            )
            peers = [dict(r) for r in cur.fetchall()]

        if not peers:
            return {"has_contradiction": False, "confidence": 1.0, "details": "No peer articles for comparison"}

        if self._llm_available:
            return self._llm_detect(article, peers)
        return self._rule_detect(article, peers)

    def _rule_detect(self, article: Dict[str, Any], peers: List[Dict[str, Any]]) -> Dict[str, Any]:
        title_lower = (article.get("title", "") or "").lower()
        summary_lower = (article.get("summary", "") or "").lower()
        contradiction_signals = {
            "however", "but", "contradicts", "disputes", "refutes",
            "on the other hand", "in contrast", "misleading", "false",
            "debunked", "actually", "contrary",
        }
        self_contradicts = any(s in title_lower or s in summary_lower for s in contradiction_signals)
        if self_contradicts:
            return {"has_contradiction": True, "confidence": 0.6, "details": "Article contains contradiction signals in text"}

        cross_contradictions = 0
        for p in peers:
            p_title = (p.get("title", "") or "").lower()
            for s in contradiction_signals:
                if s in p_title:
                    cross_contradictions += 1
                    break

        return {
            "has_contradiction": cross_contradictions >= 2,
            "confidence": min(1.0, 0.5 + 0.1 * cross_contradictions),
            "details": f"Found {cross_contradictions} potentially contradictory peer articles",
        }

    def _llm_detect(self, article: Dict[str, Any], peers: List[Dict[str, Any]]) -> Dict[str, Any]:
        try:
            from openai import OpenAI
            client = OpenAI(
                api_key=os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY", ""),
                base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            )
            peer_texts = "\n".join(f"- {p.get('title')}: {p.get('summary', '')[:200]}" for p in peers[:3])
            prompt = f"""Analyze if this news article contradicts other recent reports on the same topic.

Current article:
Title: {article.get('title', '')}
Summary: {article.get('summary', '')}

Recent related articles:
{peer_texts}

Return JSON only: {{"has_contradiction": bool, "confidence": 0.0-1.0, "details": "explanation"}}"""

            resp = client.chat.completions.create(
                model=os.getenv("PULSE_CHAT_MODEL", "poolside/laguna-xs.2:free"),
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200, temperature=0.1,
            )
            raw = resp.choices[0].message.content or "{}"
            raw = raw.strip().strip("```json").strip("```").strip()
            result = json.loads(raw)
            return {
                "has_contradiction": bool(result.get("has_contradiction", False)),
                "confidence": float(result.get("confidence", 0.5)),
                "details": result.get("details", ""),
            }
        except Exception as exc:
            logger.debug(f"[ContradictionAgent] LLM failed: {exc}")
            return self._rule_detect(article, peers)


class NarrativeAgent:
    def summarize(self, article: Dict[str, Any]) -> str:
        return article.get("summary", article.get("description", ""))

    def narrate(self, article: Dict[str, Any]) -> str:
        summary = article.get("summary", "")
        entities = article.get("key_entities", [])
        if entities:
            return f"{summary} — involving {', '.join(entities[:3])}"
        return summary


class GraphAgent:
    def entity_connectivity(self, article: Dict[str, Any]) -> float:
        entities: List[str] = article.get("key_entities", [])
        if not entities:
            return 0.0
        with db_cursor() as cur:
            cur.execute(
                "SELECT COUNT(DISTINCT a.id) FROM articles a WHERE a.key_entities && %s::text[] AND a.id != %s",
                (entities, article.get("id", "")),
            )
            row = cur.fetchone()
            linked = row["count"] if row else 0
        return min(1.0, linked / 10.0)

    def page_rank_estimate(self, article: Dict[str, Any]) -> float:
        entities: List[str] = article.get("key_entities", [])
        if not entities:
            return 0.3
        with db_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM articles WHERE key_entities && %s::text[]",
                (entities,),
            )
            row = cur.fetchone()
            mentions = row["count"] if row else 0
        return min(1.0, 0.3 + 0.05 * mentions)


class AlertAgent:
    def __init__(self):
        self._contradiction = ContradictionAgent()

    def should_alert(self, article: Dict[str, Any], cooldown_mins: int = 30) -> bool:
        importance = article.get("importance", 0) or 0
        is_risk = article.get("is_risk", False)
        fact = FactAgent()
        fact_conf = fact.confidence(article)
        diversity = _source_diversity(article.get("category", "other") or "other", hours=2)

        if importance < 7:
            return False
        if diversity < 0.4:
            return False
        if fact_conf < 0.6:
            return False
        if not _check_cooldown(article, cooldown_mins):
            return False

        contradiction = self._contradiction.detect(article)
        if contradiction.get("has_contradiction") and contradiction.get("confidence", 0) > 0.7:
            logger.info(f"[AlertAgent] Suppressed by contradiction: {article.get('title', '')[:60]}")
            return False

        if is_risk:
            return importance >= 6
        return importance >= 8

    def alert_priority(self, article: Dict[str, Any]) -> str:
        imp = article.get("importance", 0) or 0
        is_risk = article.get("is_risk", False)
        if is_risk and imp >= 9:
            return "critical"
        if imp >= 8:
            return "high"
        return "normal"


class OrchestratorAgent:
    def __init__(self):
        self.trend = TrendAgent()
        self.fact = FactAgent()
        self.narrative = NarrativeAgent()
        self.graph = GraphAgent()
        self.alert = AlertAgent()
        self.contradiction = ContradictionAgent()

    def review_article(self, article: Dict[str, Any], user_settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        trend_score = self.trend.analyze(article)
        is_factual = self.fact.verify(article)
        fact_conf = self.fact.confidence(article)
        connectivity = self.graph.entity_connectivity(article)
        pagerank = self.graph.page_rank_estimate(article)

        if not is_factual:
            article["importance"] = max(1, (article.get("importance", 5) or 5) - 3)
            article["agent_reviewed"] = True
            article["trend_score"] = 0.0
            return article

        novelty_score = 1.0 - connectivity
        burst_score = _burst_detection_score(article.get("category", "other") or "other")

        w_trend = get_learned_weight("agent_trend_weight", 0.30)
        w_fact = get_learned_weight("agent_fact_weight", 0.20)
        w_novel = get_learned_weight("agent_novelty_weight", 0.15)
        w_pr = get_learned_weight("agent_pagerank_weight", 0.10)
        w_burst = get_learned_weight("agent_burst_weight", 0.25)
        total_w = w_trend + w_fact + w_novel + w_pr + w_burst
        if total_w > 0:
            w_trend /= total_w
            w_fact /= total_w
            w_novel /= total_w
            w_pr /= total_w
            w_burst /= total_w

        final_score = (
            w_trend * trend_score
            + w_fact * fact_conf
            + w_novel * novelty_score
            + w_pr * pagerank
            + w_burst * burst_score
        )

        if final_score > 0.70 and (article.get("importance", 0) or 0) < 7:
            article["importance"] = max(7, (article.get("importance", 5) or 5))

        cooldown_mins = (user_settings or {}).get("alert_cooldown_mins", 30)
        article["trend_score"] = round(final_score, 4)
        article["agent_reviewed"] = True
        article["should_alert"] = self.alert.should_alert(article, cooldown_mins)
        article["alert_priority"] = self.alert.alert_priority(article)
        article["burst_score"] = round(burst_score, 4)

        contradiction = self.contradiction.detect(article)
        article["contradiction"] = contradiction

        return article


editorial_board = OrchestratorAgent()
