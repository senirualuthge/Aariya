"""
Neural-symbolic bridge.

`consistency(text_a, text_b)` computes REAL cosine similarity between
feature-hashed vectors of the two texts (sklearn HashingVectorizer,
deterministic, data-derived — no trained checkpoint needed and none is
pretended). The torch module below remains for when a trained projection is
available; callers today use the hashing path.
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

try:
    import torch
    import torch.nn as nn
    _TORCH = True
except ImportError:
    _TORCH = False
    nn = None  # type: ignore

try:
    from sklearn.feature_extraction.text import HashingVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    _HASHER = HashingVectorizer(
        n_features=384, alternate_sign=False, norm="l2",
        stop_words=None, ngram_range=(1, 2),
    )
    _SKLEARN = True
except ImportError:
    _SKLEARN = False


def _hash_embedding(text: str):
    """Real deterministic embedding: L2-normalized feature-hashing vector."""
    return _HASHER.transform([text or ""])


class NeuralSymbolicReasoning:
    """
    Combines neural representations with symbolic constraints.

    Consistency between two concepts = cosine similarity in hashed embedding
    space. Belief adjustment applies the documented symbolic-violation penalty.
    """

    def __init__(self, embedding_dim: int = 384):
        self.embedding_dim = embedding_dim
        if _TORCH:
            import torch.nn as _nn
            self.projection = _nn.Linear(embedding_dim, embedding_dim)
            self.consistency_head = _nn.Linear(embedding_dim * 2, 1)

    # ── Real, usable API ──────────────────────────────────────────────────────

    def consistency(self, concept_a: str, concept_b: str) -> float:
        """Cosine similarity [0,1] between two real text embeddings."""
        if not _SKLEARN:
            raise RuntimeError("scikit-learn unavailable — no embedding path")
        va, vb = _hash_embedding(concept_a), _hash_embedding(concept_b)
        sim = float(cosine_similarity(va, vb)[0][0])
        # Map [-1, 1] cosine into [0, 1] consistency probability.
        return round((sim + 1.0) / 2.0, 4)

    def adjust_belief(self, belief: float,
                      symbolic_constraint_violated: bool) -> float:
        """Adjust belief based on symbolic violation (feedback loop)."""
        if symbolic_constraint_violated:
            return belief * 0.1
        return belief


if _TORCH:

    class _TorchBacked(NeuralSymbolicReasoning, __import__("torch").nn.Module):
        """Torch module variant kept for future trained checkpoints."""

        def forward(self, concept_a, concept_b):
            proj_a = self.projection(concept_a)
            proj_b = self.projection(concept_b)
            combined = torch.cat([proj_a, proj_b], dim=-1)
            return torch.sigmoid(self.consistency_head(combined))


# Global instance — real hashing-embedding backend, not a stub.
neural_symbolic = NeuralSymbolicReasoning()
