from typing import Dict, Any
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class CredibilityScorer:
    """
    Scores sources based on domain authority and content markers.
    """
    
    def __init__(self):
        self.trusted_domains = {
            ".gov": 0.95,
            ".edu": 0.9,
            ".org": 0.8,
            "wikipedia.org": 0.85,
            "nature.com": 0.98,
            "science.org": 0.98,
            "arxiv.org": 0.8,
            "nytimes.com": 0.85,
            "bbc.com": 0.85,
            "reuters.com": 0.9,
            "apnews.com": 0.9,
            "bloomberg.com": 0.85,
            "wsj.com": 0.85
        }
        self.low_credibility_markers = [
            "click here", "subscribe now", "sponsored", "advertisement",
            "you won't believe", "shocking", "conspiracy"
        ]
        
    def score_source(self, url: str, content: str) -> float:
        """
        Calculate credibility score based on multiple heuristics.
        """
        score = 0.6  # Base score for unknown reputable looking sites
        domain = self._extract_domain(url)
        
        # 1. Domain Authority Check
        for trusted, weight in self.trusted_domains.items():
            if trusted in domain:
                score = max(score, weight)
        
        # 2. Content Length Heuristic
        content_len = len(content)
        if content_len > 5000:
            score += 0.1  # Highly detailed
        elif content_len > 2000:
            score += 0.05
        elif content_len < 500:
            score -= 0.2  # Too thin
            
        # 3. Keyword-based Bias/Low-quality detection
        content_lower = content.lower()
        for marker in self.low_credibility_markers:
            if marker in content_lower:
                score -= 0.1
                
        # 4. Expert terminology (Rough heuristic)
        expert_terms = ["mechanism", "statistical", "significant", "correlation", "data", "analysis", "evidence"]
        expert_hits = sum(1 for term in expert_terms if term in content_lower)
        if expert_hits > 4:
            score += 0.05
            
        return min(max(score, 0.1), 1.0)

    def _extract_domain(self, url: str) -> str:
        try:
            return urlparse(url).netloc
        except:
            return ""

# Global instance
credibility = CredibilityScorer()
