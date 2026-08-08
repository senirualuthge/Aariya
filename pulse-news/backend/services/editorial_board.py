from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from services.agents import OrchestratorAgent

logger = logging.getLogger("pulse.editorial_board")

class EditorialBoard:
    def __init__(self):
        self.orchestrator = OrchestratorAgent()
        
    def curate_and_select_stories(self, articles: List[Dict[str, Any]], user_settings: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Processes a batch of articles through the full multi-agent editorial board.
        Filters, ranks, and selects the top stories that warrant alerts or publishing.
        """
        logger.info(f"[EditorialBoard] Reviewing batch of {len(articles)} articles.")
        
        reviewed_articles = []
        for article in articles:
            # Pass through the orchestrator which invokes Fact, Trend, Narrative, Graph, and Contradiction agents.
            reviewed = self.orchestrator.review_article(article, user_settings)
            reviewed_articles.append(reviewed)
            
        # Selection logic:
        # 1. Must be factual (trend_score > 0.0)
        valid_stories = [a for a in reviewed_articles if a.get("trend_score", 0.0) > 0.0]
        
        # Sort by combination of trend_score and importance
        valid_stories.sort(
            key=lambda x: (x.get("trend_score", 0.0) * 0.6 + (x.get("importance", 0) / 10.0) * 0.4), 
            reverse=True
        )
        
        # Select top 5 stories as the curated board output
        top_stories = valid_stories[:5]
        
        logger.info(f"[EditorialBoard] Selected {len(top_stories)} top stories from batch.")
        return top_stories
        
    def review_article(self, article: Dict[str, Any], user_settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Review a single article (for compatibility with single-item pipelines).
        """
        return self.orchestrator.review_article(article, user_settings)

editorial_board_manager = EditorialBoard()
