import requests
import trafilatura
from bs4 import BeautifulSoup
from typing import List, Dict, Optional, Any
import os
import numpy as np
try:
    import faiss
    from sentence_transformers import SentenceTransformer
    HAS_VEC = True
except Exception:
    # Optional vector stack — a broken/absent install (ImportError, or a
    # TypeError from importlib.metadata in some numpy/transformers combos)
    # must NEVER break retrieval. HAS_VEC=False falls back to keyword search.
    HAS_VEC = False

class Retriever:
    """
    Handles web content retrieval, extraction, and chunking.
    Uses trafilatura for boilerplate removal.
    """
    
    def __init__(self, user_agent: str = "AariyaResearchAgent/1.0"):
        self.headers = {"User-Agent": user_agent}
        self.chunk_size = 1000  # Default characters
        self.chunk_overlap = 200
        
        # New Vector Cache
        self.index = None
        self.chunks = []
        self.source_metadata = []
        
        if HAS_VEC:
            try:
                # Small, fast model for local research
                self.model = SentenceTransformer('all-MiniLM-L6-v2')
            except Exception as e:
                print(f"[Retriever] Failed to load embedding model: {e}")
                self.model = None
        else:
            self.model = None

    def fetch_url(self, url: str) -> Optional[str]:
        """
        Download raw HTML from a URL.
        """
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.text
        except Exception as e:
            print(f"[Retriever] Error fetching {url}: {e}")
            return None

    def extract_text(self, html: str) -> str:
        """
        Extract clean text content from HTML.
        Prioritizes trafilatura for high-quality extraction.
        """
        # 1. Try trafilatura (best for articles/news)
        extracted = trafilatura.extract(html, include_comments=False, include_tables=True)
        
        if extracted:
            return extracted
            
        # 2. Fallback to BeautifulSoup (general extraction)
        soup = BeautifulSoup(html, "html.parser")
        
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
            
        return soup.get_text(separator="\n", strip=True)

    def chunk_text(self, text: str, size: int = 1000, overlap: int = 200) -> List[str]:
        """
        Split text into overlapping chunks for RAG.
        """
        if not text:
            return []
            
        chunks = []
        start = 0
        while start < len(text):
            end = start + size
            chunks.append(text[start:end])
            start += size - overlap
            
        return chunks

    def add_document(self, text: str, metadata: Dict[str, Any]):
        """
        Add a document to the index for retrieval.
        """
        new_chunks = self.chunk_text(text)
        if not new_chunks:
            return
            
        if self.model and HAS_VEC:
            embeddings = self.model.encode(new_chunks)
            dim = embeddings.shape[1]
            
            if self.index is None:
                self.index = faiss.IndexFlatL2(dim)
            
            self.index.add(np.array(embeddings).astype('float32'))
            
        self.chunks.extend(new_chunks)
        self.source_metadata.extend([metadata] * len(new_chunks))

    def retrieve(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Retrieve relevant chunks using vector similarity or keyword search.
        """
        if not self.chunks:
            return []
            
        if self.model and self.index and HAS_VEC:
            query_embedding = self.model.encode([query])
            D, I = self.index.search(np.array(query_embedding).astype('float32'), top_k)
            
            results = []
            for i, idx in enumerate(I[0]):
                if idx < len(self.chunks) and idx != -1:
                    results.append({
                        "content": self.chunks[idx],
                        "metadata": self.source_metadata[idx],
                        "score": float(D[0][i])
                    })
            return results
        else:
            # Fallback to simple keyword/substring search
            results = []
            for i, chunk in enumerate(self.chunks):
                if query.lower() in chunk.lower():
                    results.append({
                        "content": chunk,
                        "metadata": self.source_metadata[i],
                        "score": 1.0
                    })
                if len(results) >= top_k:
                    break
            return results

    def process_url(self, url: str) -> Dict[str, Any]:
        """
        Full pipeline: Fetch -> Extract -> Chunk.
        """
        html = self.fetch_url(url)
        if not html:
            return {"url": url, "text": "", "chunks": [], "error": "Fetch failed"}
            
        text = self.extract_text(html)
        chunks = self.chunk_text(text)
        
        # Add to index automatically during processing
        self.add_document(text, {"url": url})
        
        return {
            "url": url,
            "text": text,
            "chunks": chunks,
            "char_count": len(text),
            "chunk_count": len(chunks)
        }

# Global instance for easy access
_retriever = Retriever()

def get_retriever() -> Retriever:
    return _retriever
