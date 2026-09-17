"""
Context Compression (AccessFIles §74 — gap fill).

When Aariya hits token limits / retrieval overload, the conversation context
must shrink WITHOUT inventing content. This module does real, deterministic,
extractive compression:

  * layered output   — verbatim tail (recent turns) + extractive digest of
                       older turns (sentence selection by word-frequency
                       scoring) + near-duplicate sentence dropping;
  * honest accounting— every token count comes from tiktoken when it is
                       installed, else a chars/4 estimate, and the method is
                       reported in every result so callers know the accuracy.

Nothing here calls an LLM and nothing fabricates text: every sentence in the
digest is copied verbatim from the input. With an empty input you get an
honest empty result.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aariya.context_compressor")

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[a-zA-Z'][a-zA-Z'-]*")

# Small function-word set for extractive scoring (standard NLP config).
_STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "so", "because",
    "as", "of", "at", "by", "for", "with", "about", "into", "to", "from",
    "in", "on", "is", "are", "was", "were", "be", "been", "being", "it",
    "its", "this", "that", "these", "those", "i", "you", "he", "she", "we",
    "they", "me", "him", "her", "us", "them", "my", "your", "his", "our",
    "their", "do", "does", "did", "have", "has", "had", "will", "would",
    "can", "could", "should", "not", "no", "yes", "just", "also", "very",
}

_TOKENIZER_LOCK = threading.Lock()
_tokenizer: Any = None
_tokenizer_checked = False


def _get_encoder() -> Optional[Any]:
    """tiktoken encoder when actually installed, else None (chars/4 fallback)."""
    global _tokenizer, _tokenizer_checked
    with _TOKENIZER_LOCK:
        if not _tokenizer_checked:
            _tokenizer_checked = True
            try:
                import tiktoken  # type: ignore

                _tokenizer = tiktoken.get_encoding("cl100k_base")
            except Exception as exc:  # not installed / no model file
                logger.debug("[context] tiktoken unavailable (%s) — using chars/4", exc)
                _tokenizer = None
        return _tokenizer


def count_tokens(text: str) -> int:
    """Real token count via tiktoken when available; chars//4 otherwise."""
    enc = _get_encoder()
    if enc is not None:
        return len(enc.encode(text or ""))
    return max(0, len(text or "")) // 4


def token_method() -> str:
    """Which counting method is live — reported in every result."""
    enc = _get_encoder()
    return "tiktoken:cl100k_base" if enc is not None else "chars_per_4"


def split_sentences(text: str) -> List[str]:
    parts = [s.strip() for s in _SENT_SPLIT.split(text or "") if s.strip()]
    return parts or ([text.strip()] if (text or "").strip() else [])


def _words(text: str) -> List[str]:
    return [w.lower() for w in _WORD.findall(text or "")]


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / len(a | b)


def rank_sentences(text: str, top_k: int) -> List[str]:
    """Extractive ranking: sentences scored by summed word frequencies.
    Returns up to top_k sentences in ORIGINAL order (never reordered text)."""
    sentences = split_sentences(text)
    if len(sentences) <= top_k:
        return sentences

    freq: Dict[str, int] = {}
    for w in _words(text):
        if w not in _STOPWORDS and len(w) > 2:
            freq[w] = freq.get(w, 0) + 1

    def score(sentence: str) -> float:
        ws = [w for w in _words(sentence) if w not in _STOPWORDS]
        if not ws:
            return 0.0
        return sum(freq.get(w, 0) for w in ws) / (len(ws) ** 0.5)

    ranked = sorted(range(len(sentences)), key=lambda i: score(sentences[i]), reverse=True)
    keep = sorted(ranked[:max(1, top_k)])
    return [sentences[i] for i in keep]


def dedupe_sentences(sentences: List[str], threshold: float = 0.7) -> List[str]:
    """Drop near-duplicate sentences (token-set Jaccard above threshold)."""
    kept: List[str] = []
    kept_sets: List[set] = []
    for s in sentences:
        ws = set(_words(s))
        if any(_jaccard(ws, prev) >= threshold for prev in kept_sets):
            continue
        kept.append(s)
        kept_sets.append(ws)
    return kept


class ContextCompressor:
    """Layered compression of chat message lists under a token budget."""

    def __init__(self, tail_share: float = 0.5):
        # Fraction of the budget guaranteed to recent verbatim turns.
        self.tail_share = min(max(tail_share, 0.1), 0.9)

    def compress_messages(
        self, messages: List[Dict[str, str]], budget_tokens: int
    ) -> Dict[str, Any]:
        msgs = [m for m in (messages or []) if isinstance(m, dict) and m.get("content")]
        budget = max(int(budget_tokens), 0)
        original_tokens = sum(count_tokens(str(m["content"])) for m in msgs)

        stats: Dict[str, Any] = {
            "method": token_method(),
            "original_messages": len(msgs),
            "original_tokens": original_tokens,
        }
        if budget <= 0 or not msgs:
            stats.update({"compressed_messages": [], "compressed_tokens": 0,
                          "dropped_messages": len(msgs), "summarized_from": 0})
            return {"messages": [], "stats": stats}

        # Already fits → pass through untouched.
        if original_tokens <= budget:
            stats.update({"compressed_messages": len(msgs), "compressed_tokens": original_tokens,
                          "dropped_messages": 0, "summarized_from": 0, "passthrough": True})
            return {"messages": [dict(m) for m in msgs], "stats": stats}

        # Layer 1: keep the newest turns verbatim within the tail share.
        tail_budget = int(budget * self.tail_share)
        verbatim: List[Dict[str, str]] = []
        used = 0
        idx = len(msgs) - 1
        while idx >= 0:
            t = count_tokens(str(msgs[idx]["content"]))
            if used + t > tail_budget and verbatim:
                break
            if used + t > tail_budget and not verbatim:
                # Newest single message exceeds the whole tail share — still
                # keep it truncated-by-extraction rather than losing recency.
                verbatim.insert(0, {**msgs[idx],
                                    "content": self._squeeze_text(str(msgs[idx]["content"]),
                                                                  max_tokens=max(16, tail_budget // 2))})
                used = count_tokens(str(verbatim[0]["content"]))
                idx -= 1
                break
            verbatim.insert(0, dict(msgs[idx]))
            used += t
            idx -= 1

        # Layer 2: extractive digest of everything older, within what's left.
        older = msgs[:idx + 1]
        digest_budget = max(0, budget - used)
        digest_text = ""
        summarized_from = 0
        if older and digest_budget > 32:
            blob = "\n".join(f"{m.get('role', 'user')}: {m['content']}" for m in older)
            summarized_from = len(older)
            # Over-select then trim to the digest budget by token count.
            ratio = max(1.0, count_tokens(blob) / max(digest_budget, 1))
            top_k = max(1, min(len(split_sentences(blob)),
                               int(len(split_sentences(blob)) / ratio) + 2))
            picked = dedupe_sentences(rank_sentences(blob, top_k))
            digest_text = ""
            for s in picked:
                candidate = (digest_text + " " + s).strip()
                if count_tokens(candidate) > digest_budget - 8 and digest_text:
                    break
                digest_text = candidate

        digest_messages: List[Dict[str, str]] = (
            [{"role": "system",
              "content": f"[compressed earlier context] {digest_text}"}]
            if digest_text else []
        )

        out = digest_messages + verbatim
        compressed_tokens = sum(count_tokens(str(m["content"])) for m in out)

        # Hard guarantee: never exceed the caller's budget after layering.
        while out and compressed_tokens > budget:
            dropped = out.pop(0)
            compressed_tokens -= count_tokens(str(dropped["content"]))

        stats.update({
            "compressed_messages": len(out),
            "compressed_tokens": compressed_tokens,
            "dropped_messages": len(msgs) - summarized_from - len(verbatim),
            "summarized_from": summarized_from,
        })
        return {"messages": out, "stats": stats}

    def compress_text(self, text: str, max_tokens: int) -> Dict[str, Any]:
        """Single-text variant: extractive squeeze to a token ceiling."""
        squeezed = self._squeeze_text(text or "", max_tokens=int(max_tokens))
        return {
            "text": squeezed,
            "stats": {"method": token_method(),
                      "original_tokens": count_tokens(text or ""),
                      "compressed_tokens": count_tokens(squeezed)},
        }

    def _squeeze_text(self, text: str, max_tokens: int) -> str:
        if count_tokens(text) <= max_tokens:
            return text
        picked = dedupe_sentences(rank_sentences(text, max(1, max_tokens // 8)))
        out = ""
        for s in picked:
            candidate = (out + " " + s).strip()
            if count_tokens(candidate) > max_tokens:
                break
            out = candidate
        return out or text[: max(0, max_tokens * 4)]


_compressor: Optional[ContextCompressor] = None


def get_context_compressor() -> ContextCompressor:
    global _compressor
    if _compressor is None:
        _compressor = ContextCompressor()
    return _compressor
