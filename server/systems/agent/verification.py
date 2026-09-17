"""
Citation verification — real lexical NLI over the actual texts.

  * tokenization with stopword removal + light stemming
  * IDF-weighted content-word overlap between claim and excerpt
  * explicit negation/contradiction detection on shared content words
    ("X is not Y" vs "X is Y", antonym pairs, citation hedges)

No model is pretended: results report method="lexical-nli" with confidence
derived from real overlap statistics. A trained NLI checkpoint can later be
dispatched from verify_citation without changing callers.
"""

import logging
import re
from typing import Dict, Any

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9']+")

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "of", "to", "in", "on", "at", "by", "for", "with", "about", "as",
    "and", "or", "but", "if", "then", "than", "so", "because",
    "this", "that", "these", "those", "it", "its", "they", "them",
    "their", "there", "here", "he", "she", "we", "you", "i",
    "have", "has", "had", "do", "does", "did", "will", "would", "can",
    "could", "should", "may", "might", "must", "shall",
}

_NEGATORS = {"not", "no", "never", "none", "neither", "nor", "without",
             "cannot", "cant", "dont", "doesnt", "didnt", "isnt", "arent",
             "wasnt", "werent", "wont", "lack", "lacks", "lacking"}

# Word pairs whose swap across claim/excerpt flips meaning.
_ANTONYM_PAIRS = [
    ("increase", "decrease"), ("increases", "decreases"),
    ("higher", "lower"), ("more", "less"), ("faster", "slower"),
    ("always", "never"), ("all", "none"), ("true", "false"),
    ("safe", "dangerous"), ("effective", "ineffective"),
    ("causes", "prevents"), ("helps", "harms"), ("open", "closed"),
]

_CITATION_HEDGES = ("no evidence", "not supported", "unclear whether",
                    "remains unknown", "unproven")


def _tokens(text: str):
    out = []
    for tok in _TOKEN_RE.findall(text.lower()):
        if tok in _STOPWORDS or len(tok) <= 1:
            continue
        for suf in ("ing", "ed", "es", "s"):
            if tok.endswith(suf) and len(tok) - len(suf) >= 3:
                tok = tok[: -len(suf)]
                break
        out.append(tok)
    return out


def _is_negated(text: str) -> bool:
    lowered = text.lower()
    return any(re.search(r"\b" + re.escape(n), lowered) for n in _NEGATORS)


class VerificationSystem:
    """Verifies claims against source content (citations)."""

    def verify_citation(self, claim: str, excerpt: str) -> Dict[str, Any]:
        claim_toks = _tokens(claim)
        excerpt_toks = _tokens(excerpt)
        if not claim_toks or not excerpt_toks:
            return self._verdict(False, 0.0,
                                 "insufficient content tokens", overlap=0.0)

        claim_set, excerpt_set = set(claim_toks), set(excerpt_toks)
        shared = claim_set & excerpt_set

        # ── Contradiction signals veto support regardless of overlap ──────
        for a, b in _ANTONYM_PAIRS:
            stem_a, stem_b = _tokens(a)[0], _tokens(b)[0]
            if ((stem_a in claim_set and stem_b in excerpt_set
                 and stem_b not in claim_set)
                    or (stem_b in claim_set and stem_a in excerpt_set
                        and stem_a not in claim_set)):
                return self._verdict(
                    False, 0.2, f"antonym conflict: '{a}' vs '{b}'",
                    overlap=len(shared) / len(claim_set))

        claim_negated = _is_negated(claim)
        excerpt_negated = (_is_negated(excerpt)
                           or any(h in excerpt.lower() for h in _CITATION_HEDGES))
        if claim_negated != excerpt_negated and shared:
            return self._verdict(
                False, 0.25, "negation mismatch on shared content",
                overlap=len(shared) / len(claim_set))

        # ── Frequency-weighted overlap scoring ────────────────────────────
        # Shared words that are RARE in the source count as stronger evidence
        # than ubiquitous ones (an IDF-style weighting computable from the
        # pair itself).
        freq: Dict[str, int] = {}
        for t in excerpt_toks:
            freq[t] = freq.get(t, 0) + 1
        max_freq = max(freq.values())

        weighted_hits = sum(
            1.0 + math_log_ratio(freq.get(t, 0), max_freq) for t in shared
        )
        total_weight = sum(
            1.0 + math_log_ratio(freq.get(t, 0), max_freq) for t in claim_set
        )
        overlap = len(shared) / len(claim_set)
        score = weighted_hits / total_weight if total_weight else 0.0

        supports = overlap > 0.3 and score > 0.3
        confidence = min(1.0, max(overlap, score) * 1.6)
        reasoning = (f"weighted-overlap {score:.2f} "
                     f"(raw {overlap:.2f}, {len(shared)} shared terms)")
        return self._verdict(supports, confidence, reasoning, overlap=overlap)

    @staticmethod
    def _verdict(supports: bool, confidence: float, reasoning: str,
                 *, overlap: float) -> Dict[str, Any]:
        return {
            "supports": supports,
            "confidence": round(min(max(confidence, 0.0), 1.0), 3),
            "reasoning": reasoning,
            "method": "lexical-nli",
            "overlap": round(overlap, 3),
        }


def math_log_ratio(term_freq: int, max_freq: int) -> float:
    """Small real-valued rarity bonus in [0, 1): rarer terms score higher."""
    if term_freq <= 0 or max_freq <= 0:
        return 0.0
    ratio = min(term_freq / max_freq, 1.0)
    return 1.0 - ratio


# Global instance
verifier = VerificationSystem()
