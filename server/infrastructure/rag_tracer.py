import time
import uuid

class RAGTracer:
    def __init__(self, query: str):
        self.trace_id = str(uuid.uuid4())
        self.start_time = time.time()
        
        self.data = {
            "trace_id": self.trace_id,
            "query": query,
            "intent": None,
            "steps": [],
            "chunks": [],
            "context": {},
            "metrics": {
                "total_latency": 0.0,
                "retrieval_confidence": 0.0,
                "hallucination_risk": 0.0
            }
        }

    def set_intent(self, intent: str):
        self.data["intent"] = intent

    def step(self, name: str, start_time: float, meta=None):
        self.data["steps"].append({
            "name": name,
            "latency": round((time.time() - start_time) * 1000, 2),
            "meta": meta or {}
        })

    def add_chunk(self, text: str, score: float, source: str, tokens: int = 0):
        self.data["chunks"].append({
            "text": text[:300] if text else "",
            "score": score,
            "source": source,
            "tokens": tokens
        })

    def set_context_stats(self, total_tokens: int, sources_used: int):
        self.data["context"] = {
            "total_tokens": total_tokens,
            "sources_used": sources_used
        }

    def finalize(self):
        self.data["metrics"]["total_latency"] = round(
            (time.time() - self.start_time) * 1000, 2
        )

        scores = [c["score"] for c in self.data["chunks"]]
        if scores:
            self.data["metrics"]["retrieval_confidence"] = sum(scores) / len(scores)

        if self.data["metrics"]["retrieval_confidence"] < 0.5:
            self.data["metrics"]["hallucination_risk"] = 0.8
        else:
            self.data["metrics"]["hallucination_risk"] = 0.2

        return self.data
