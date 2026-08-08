"""
GroundingValidator — post-generation Layer 1 guard (FIXV5).

Scans Aariya's generated reply for contradictions against the durable memories
(Layer 1 ground truth) she was prompted with, BEFORE the reply is persisted and
sent to clients. This is the code-level enforcement that the layer-separation
prompt rule alone cannot guarantee: even if the model ignores the "LAYER 1
wins" instruction, a deterministic scan of the final text catches direct
negations of remembered facts.

Deliberately conservative and dependency-free (no LLM, no NLI model, no ML):
it flags reply sentences that restate a remembered fact under a negation
marker ("You never loved stargazing" against the memory "I love stargazing
at night"). Hedged uncertainty ("I'm not sure you love stargazing") is not a
contradiction and is skipped. Paraphrase-level contradictions that share no
content words are out of scope by design — this is a mechanical veto layer,
not a semantic NLI model.

SCOPE: facts come from the durable memories only (recall_prompt), the Layer 1
ground truth she reasons from. Contradicting what the user said IN the current
conversation is intentionally not scanned — in-conversation mind-changes make
that a false-positive minefield.
"""

import logging
import re
from dataclasses import dataclass
from typing import List

logger = logging.getLogger(__name__)

# Negation markers (contractions and expansions). Bare "no" is intentionally
# excluded — "You have no idea how much I love stargazing" would be a false
# positive; direct negation of a fact is still caught via the other markers.
_NEGATION_MARKERS = (
    "don't", "do not", "doesn't", "does not", "didn't", "did not",
    "won't", "wouldn't", "can't", "cannot", "isn't", "is not",
    "aren't", "are not", "wasn't", "was not", "weren't", "were not",
    "haven't", "have not", "hasn't", "has not", "hadn't", "had not",
    "never", "not",
)

# Hedged phrases soften a claim into uncertainty rather than contradiction —
# "I don't remember if you love stargazing" must not be flagged as denying it.
_HEDGE_PHRASES = (
    "don't remember", "do not remember", "don't recall", "do not recall",
    "don't think", "do not think", "don't know", "do not know",
    "not sure", "not certain", "not entirely", "not quite",
    "maybe", "perhaps", "might be", "could be",
)

# Clause separators: a negation in one clause must not taint another. Splits
# "I don't sleep much, but I love stargazing" so the negated clause never
# borrows the overlapping content words from the affirming clause.
_CLAUSE_SPLIT = re.compile(r"[,;—–]|\bbut\b")

# Content-word stopwords — high-frequency words carry no factual signal.
_STOPWORDS = {
    "about", "again", "also", "been", "being", "both", "could", "from",
    "have", "into", "just", "like", "make", "more", "most", "much",
    "only", "other", "over", "should", "some", "such", "than", "that",
    "them", "then", "these", "they", "thing", "things", "this", "those",
    "very", "want", "well", "were", "what", "when", "where", "which",
    "will", "with", "would", "your",
}

# Minimum overlapping content words between a fact and a reply sentence for a
# negation to count as a contradiction.
_MIN_OVERLAP = 2


def _stem(word: str) -> str:
    """Minimal suffix stemming so love/loved/loving, dog/dogs and
    stargaze/stargazing all normalize to the same stem."""
    w = word.lower()
    if w.endswith("ing") and len(w) > 5:
        w = w[:-3]
    elif w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    elif w.endswith("ed") and len(w) > 4 and not w.endswith("eed"):
        w = w[:-2]
    elif w.endswith("es") and len(w) > 4:
        w = w[:-2]
    elif w.endswith("s") and len(w) > 3 and not w.endswith("ss"):
        w = w[:-1]
    # love→lov, stargaze→stargaz — matches the forms produced by the
    # suffix rules above (loved→lov, stargazing→stargaz).
    if w.endswith("e") and len(w) > 3:
        w = w[:-1]
    return w


# Affirmation verbs: negating these flips the polarity INTO affirmation —
# "I'll never forget our stargazing nights" / "I won't forget" AFFIRM the
# fact, so they must never be flagged as contradictions. (Defined after
# _stem since it stems at import time.)
_AFFIRM_STEMS = {
    _stem(w)
    for w in ("forget", "forgot", "forgotten", "remember", "recall")
}


def _content_tokens(text: str) -> set:
    words = re.findall(r"[a-z']+", text.lower())
    return {_stem(w) for w in words if len(w) >= 4 and w not in _STOPWORDS}


def _negates_affirm_verb(clause: str) -> bool:
    """True when a negation marker directly precedes an affirmation verb
    (forget/remember/recall), i.e. the polarity flips INTO affirmation."""
    for marker in _NEGATION_MARKERS:
        idx = clause.find(marker)
        if idx == -1:
            continue
        # Only the few tokens immediately after the marker belong to it.
        tail = clause[idx + len(marker):].split()
        for word in tail[:3]:
            if _stem(word) in _AFFIRM_STEMS:
                return True
    return False


@dataclass
class GroundingIssue:
    """One detected contradiction between her reply and a remembered fact."""

    fact: str
    reply: str  # the offending sentence of her reply
    reason: str

    def to_dict(self) -> dict:
        return {"fact": self.fact, "reply": self.reply, "reason": self.reason}


class GroundingValidator:
    """
    Deterministic post-generation scan of a reply against Layer 1 memories.
    """

    def facts_from_memory_context(self, memory_context: str) -> List[str]:
        """Parse ConversationLog.recall_prompt() output ('- text' lines)."""
        if not memory_context:
            return []
        facts = []
        for line in memory_context.splitlines():
            line = line.strip()
            if line:
                facts.append(
                    line.removeprefix("- ").strip()
                )
        return facts

    def validate(self, reply: str, facts: List[str]) -> List[GroundingIssue]:
        """Return every reply sentence that directly negates a remembered fact.

        Deliberately scoped to the durable memories (the Layer 1 ground truth
        she reasons from). The negation must live in the SAME clause as the
        overlapping content words, so "I don't sleep much, but I love
        stargazing" is not a contradiction; hedged uncertainty and negated
        affirmation verbs ("never forget") are excluded.
        """
        if not reply or not facts:
            return []

        sentences = re.split(r"(?<=[.!?])\s+", reply.strip())
        issues: List[GroundingIssue] = []

        for fact in facts:
            fact_tokens = _content_tokens(fact)
            if len(fact_tokens) < _MIN_OVERLAP:
                continue  # too little signal in this memory to judge
            for sentence in sentences:
                lower = sentence.lower()
                # Uncertainty about a fact is not the same as denying it.
                if any(h in lower for h in _HEDGE_PHRASES):
                    continue
                for clause in _CLAUSE_SPLIT.split(lower):
                    clause = clause.strip()
                    if not any(n in clause for n in _NEGATION_MARKERS):
                        continue
                    # Negated affirmation verbs affirm the fact instead of
                    # denying it ("never forget stargazing").
                    if _negates_affirm_verb(clause):
                        continue
                    overlap = fact_tokens & _content_tokens(clause)
                    if len(overlap) >= _MIN_OVERLAP:
                        issues.append(GroundingIssue(
                            fact=fact,
                            reply=sentence.strip(),
                            reason=(
                                f"Reply negates the remembered fact: {len(overlap)} "
                                f"overlapping content words "
                                f"({', '.join(sorted(overlap))}) under a negation marker"
                            ),
                        ))
                        break  # one issue per sentence
        return issues


# Global instance (mirrors symbolic_validator / contradiction module style)
grounding_validator = GroundingValidator()
