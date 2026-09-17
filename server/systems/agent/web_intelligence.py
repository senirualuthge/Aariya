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
        Priority: Bing > SerpAPI > Serper > DuckDuckGo (keyless) > Wikipedia
        (keyless). The final fallback returns an honest "unavailable" row —
        results are never fabricated.
        """
        if self.bing_api_key:
            return self._search_bing(query, num_results)
        elif self.serpapi_key:
            return self._search_serpapi(query, num_results)
        elif hasattr(config, "SERPER_API_KEY") and config.SERPER_API_KEY:
            return self._search_serper(query, num_results)
        else:
            for provider in (self._search_duckduckgo, self._search_wikipedia):
                try:
                    results = provider(query, num_results)
                except Exception as e:
                    logger.warning("[web] %s failed: %s",
                                   provider.__name__, e)
                    continue
                if results:
                    return results
            logger.warning("No search providers reachable (no API keys, "
                           "keyless providers failed).")
            return [
                {
                    "title": "Search Unavailable",
                    "url": "#",
                    "snippet": "No search API key is configured and the "
                               "keyless providers (DuckDuckGo/Wikipedia) were "
                               "unreachable. Add SERPER_API_KEY, BING_API_KEY, "
                               "or SERPAPI_KEY to your .env file."
                }
            ]

    def _search_duckduckgo(self, query: str, num_results: int) -> List[Dict[str, str]]:
        """Keyless DuckDuckGo HTML endpoint — REAL results, no API key."""
        from bs4 import BeautifulSoup

        response = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers={"User-Agent": self.user_agent},
            timeout=config.REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "lxml")

        results = []
        for anchor in soup.select("a.result__a")[:num_results]:
            href = str(anchor.get("href", ""))
            # DDG wraps outbound links in /l/?uddg=<urlencoded>
            if href.startswith("//duckduckgo.com/l/") or href.startswith("/l/"):
                from urllib.parse import urlparse, parse_qs
                parsed = parse_qs(urlparse("https:" + href if href.startswith("//") else href).query)
                href = parsed.get("uddg", [href])[0]
            snippet_node = anchor.find_next(attrs={"class": "result__snippet"})
            results.append({
                "title": anchor.get_text(" ", strip=True),
                "url": href,
                "snippet": snippet_node.get_text(" ", strip=True) if snippet_node else "",
            })
        return results

    def _search_wikipedia(self, query: str, num_results: int) -> List[Dict[str, str]]:
        """Keyless Wikipedia OpenSearch API — real encyclopedic results."""
        response = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "opensearch",
                "search": query,
                "limit": max(1, min(num_results, 10)),
                "namespace": 0,
                "format": "json",
            },
            headers={"User-Agent": self.user_agent},
            timeout=config.REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        titles, descriptions, links = data[1], data[2], data[3]
        return [
            {"title": t, "url": u, "snippet": d}
            for t, d, u in zip(titles, descriptions, links)
        ]

    def _search_bing(self, query: str, num_results: int) -> List[Dict[str, str]]:
        """Search using Bing Web Search API."""
        endpoint = "https://api.bing.microsoft.com/v7.0/search"
        headers = {"Ocp-Apim-Subscription-Key": self.bing_api_key}
        params = {"q": query, "count": num_results}
        
        try:
            response = requests.get(endpoint, headers=headers, params=params, timeout=config.REQUEST_TIMEOUT)  # type: ignore[arg-type]
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
