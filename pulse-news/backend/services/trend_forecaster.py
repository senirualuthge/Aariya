from __future__ import annotations

import logging
from typing import Any, Dict, List
from datetime import datetime, timezone

from .qdrant_rag import qdrant_db
from .ml_pipeline import forecaster
from .rag import query_rag

logger = logging.getLogger("pulse.trend_forecaster")

class MultiDayTrendForecaster:
    def __init__(self):
        self.ml_forecaster = forecaster
        self.rag = qdrant_db

    def analyze_trend(self, topic_query: str, days: int = 3) -> Dict[str, Any]:
        """
        Analyzes a multi-day trend for a given topic using RAG contexts
        and the ML forecasting pipeline.
        """
        logger.info(f"[TrendForecaster] Analyzing trend for '{topic_query}' over past {days} days.")
        
        # 1. Fetch multi-day context from RAG (Qdrant)
        # Using a higher limit to get more context for trend analysis
        rag_hits = self.rag.search(topic_query, limit=20)
        
        if not rag_hits:
            return {
                "topic": topic_query,
                "status": "insufficient_data",
                "trend_prediction": 0.0,
                "velocity_analysis": "Not enough articles found in the RAG store to establish a trend."
            }

        # 2. Extract features simulating a batch processing for ML Pipeline
        velocity_recent = len([h for h in rag_hits[:5]])  # simulated 1h
        velocity_24h = len(rag_hits)                      # simulated 24h
        
        novelty_score = 0.5
        source_diversity = min(1.0, len(rag_hits) / 10.0)

        features = {
            "velocity_1h": float(velocity_recent),
            "velocity_24h": float(velocity_24h),
            "novelty_score": novelty_score,
            "source_credibility": 0.7,
            "entity_count": 3.0,
            "importance": 6.0,
            "engagement_rate": 0.1,
            "source_diversity": source_diversity,
            "burst_score": min(1.0, velocity_recent / max(1, velocity_24h - velocity_recent)),
            "sentiment": 0.0,
        }

        # 3. Use ML models (XGBoost/TFT) for trend prediction
        prediction_score = self.ml_forecaster.predict_importance(features)
        breaking_prob = self.ml_forecaster.predict_breaking_probability(features)
        
        # 4. Generate LLM Narrative for the trend
        context_str = "\n".join(f"- {h.get('title')}: {h.get('summary')}" for h in rag_hits[:5])
        narrative_prompt = f"Analyze the following recent news about '{topic_query}' and provide a 2-sentence trend forecast.\n\nContext:\n{context_str}"
        
        # Reuse local RAG query mechanism as a generic LLM call
        narrative = query_rag(narrative_prompt)
        
        return {
            "topic": topic_query,
            "status": "emerging" if prediction_score > 0.6 else "stable",
            "trend_score": prediction_score,
            "breaking_probability": breaking_prob,
            "narrative": narrative,
            "data_points_analyzed": len(rag_hits)
        }

trend_forecaster = MultiDayTrendForecaster()
