import logging
import requests
import trafilatura
from typing import List, Dict, Any, Optional
from server.systems.agent.config import config

logger = logging.getLogger(__name__)

class WebIntelligence:
    """
    Handles web search and content extraction.
    """
    def __init__(self):
        self.bing_api_key = config.BING_API_KEY
        self.serpapi_key = config.SERPAPI_KEY
        self.user_agent = "AI-Girl-Agent/1.0"

    def search(self, query: str, num_results: int = 5) -> List[Dict[str, str]]:
        """
        Execute a web search using configured provider.
        Priority: Bing > SerpAPI > Serper > Mock
        """
        if self.bing_api_key:
            return self._search_bing(query, num_results)
        elif self.serpapi_key:
            return self._search_serpapi(query, num_results)
        elif hasattr(config, "SERPER_API_KEY") and config.SERPER_API_KEY:
            return self._search_serper(query, num_results)
        else:
            logger.warning("No search API keys configured. Returning mock results.")
            return self._search_mock(query, num_results)

    def _search_bing(self, query: str, num_results: int) -> List[Dict[str, str]]:
        """Search using Bing Web Search API."""
        endpoint = "https://api.bing.microsoft.com/v7.0/search"
        headers = {"Ocp-Apim-Subscription-Key": self.bing_api_key}
        params = {"q": query, "count": num_results}
        
        try:
            response = requests.get(endpoint, headers=headers, params=params, timeout=config.REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            
            results = []
            for item in data.get("webPages", {}).get("value", []):
                results.append({
                    "title": item.get("name"),
                    "url": item.get("url"),
                    "snippet": item.get("snippet")
                })
            return results
        except Exception as e:
            logger.error(f"Bing search failed: {e}")
            return []

    def _search_serpapi(self, query: str, num_results: int) -> List[Dict[str, str]]:
        """Search using SerpAPI (Google)."""
        endpoint = "https://serpapi.com/search"
        params = {
            "q": query,
            "api_key": self.serpapi_key,
            "engine": "google",
            "num": num_results
        }
        
        try:
            response = requests.get(endpoint, params=params, timeout=config.REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            
            results = []
            for item in data.get("organic_results", []):
                results.append({
                    "title": item.get("title"),
                    "url": item.get("link"),
                    "snippet": item.get("snippet")
                })
            return results
        except Exception as e:
            logger.error(f"SerpAPI search failed: {e}")
            return []

    def _search_serper(self, query: str, num_results: int) -> List[Dict[str, str]]:
        """Search using Serper.dev API."""
        endpoint = "https://google.serper.dev/search"
        headers = {
            "X-API-KEY": config.SERPER_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {"q": query, "num": num_results}
        
        try:
            response = requests.post(endpoint, headers=headers, json=payload, timeout=config.REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            
            results = []
            for item in data.get("organic", []):
                results.append({
                    "title": item.get("title"),
                    "url": item.get("link"),
                    "snippet": item.get("snippet")
                })
            return results
        except Exception as e:
            logger.error(f"Serper search failed: {e}")
            return []

    def _search_mock(self, query: str, num_results: int) -> List[Dict[str, str]]:
        """Return proper mock structure for testing."""
        return [
            {
                "title": f"Mock Result {i+1} for {query}",
                "url": f"https://example.com/mock/{i+1}",
                "snippet": f"This is a simulated search result for query: {query}"
            }
            for i in range(num_results)
        ]

    def fetch_content(self, url: str) -> str:
        """
        Download and extract clean text from a URL using trafilatura.
        """
        try:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                # Use advanced extraction options from the spec
                text = trafilatura.extract(
                    downloaded, 
                    include_comments=False, 
                    include_tables=True,
                    no_fallback=False
                )
                return text if text else ""
            return ""
        except Exception as e:
            logger.error(f"Content fetch failed for {url}: {e}")
            return ""

# Global instance
web_intel = WebIntelligence()
