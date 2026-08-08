from typing import List, Dict, Any, Optional
import time

class Citation:
    """
    Minimal citation object.
    """
    
    def __init__(self, url: str, excerpt: str, title: str = "", credibility: float = 0.5):
        self.url = url
        self.excerpt = excerpt
        self.title = title
        self.credibility = credibility
        self.verification_score = 1.0  # Initial 1.0, updated by Agent
        self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "excerpt": self.excerpt,
            "credibility": self.credibility,
            "verification_score": self.verification_score,
            "timestamp": self.timestamp
        }

class CitationManager:
    """
    Tracks and formats citations for the Research Agent.
    """
    
    def __init__(self):
        self.citations: List[Citation] = []

    def add_citation(self, url: str, excerpt: str, title: Optional[str] = None, credibility: float = 0.5):
        """
        Add or update a citation. Deduplicates by URL and appends unique excerpts.
        """
        # Check for existing citation
        for cit in self.citations:
            if cit.url == url:
                # Update if new excerpt is unique
                if excerpt and excerpt not in cit.excerpt:
                    cit.excerpt += f" | {excerpt}"
                # Keep highest credibility
                cit.credibility = max(cit.credibility, credibility)
                return cit
                
        # New citation
        cit = Citation(url, excerpt or "", title or url, credibility)
        self.citations.append(cit)
        return cit

    def get_citations(self) -> List[Dict[str, Any]]:
        return [c.to_dict() for c in self.citations]

    def format_as_markdown(self) -> str:
        """
        Generate a professional Markdown bibliography with credibility markers.
        """
        if not self.citations:
            return ""
            
        md = "\n---\n### 📚 Sources & Evidence\n\n"
        # Sort by credibility
        sorted_citations = sorted(self.citations, key=lambda x: x.credibility, reverse=True)
        
        for i, cit in enumerate(sorted_citations, 1):
            cred_label = "Verified" if cit.credibility > 0.8 else "Reliable" if cit.credibility > 0.6 else "Informative"
            md += f"**[{i}]** [{cit.title}]({cit.url}) — *({cred_label})*\n"
            if cit.excerpt:
                # Show first 200 chars of excerpt
                excerpt_clean = cit.excerpt.replace("\n", " ").strip()
                md += f"> \"{excerpt_clean[:200]}...\"\n\n"
            
        return md

    def clear(self):
        """Reset the manager for a new research task."""
        self.citations = []

# Global instance
_citation_manager = CitationManager()

def get_citation_manager() -> CitationManager:
    return _citation_manager
