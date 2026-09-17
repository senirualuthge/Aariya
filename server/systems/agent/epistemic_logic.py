"""
Modal epistemic logic: K(p) -> p, B(p) -> not B(not p).

`consistent_belief(proposition)` is REAL:
  1. The proposition string is parsed into an atomic belief
     (subject, copula, object, negated) — e.g. "the sky is not green".
  2. Every atom checked so far is kept as a named Z3 Bool with its polarity.
  3. Each call builds a FRESH z3.Solver over ALL recorded atoms and asks sat:
     believing p while a prior atom asserted not-p makes the set UNSAT, so the
     belief is inconsistent (False). A fresh solver per check means one bad
     belief never permanently poisons the knowledge base.

Unparseable propositions return True with a debug log — honest "nothing
provable either way", not a fake proof.
"""

from typing import Any, Dict as TDict
import logging

import z3

logger = logging.getLogger(__name__)

_NEGATION_WORDS = {"not", "never", "no", "isn't", "aren't", "wasn't",
                   "weren't", "doesn't", "don't", "didn't", "cannot", "can't"}

_CONTRACTIONS = {
    "isnt": "is", "arent": "are", "wasnt": "was", "werent": "were",
    "doesnt": "does", "dont": "do", "didnt": "did", "cant": "can",
}

_COPULAS = ("is", "are", "was", "were", "has", "have")


def _strip_articles(term):
    words = [w for w in term.split() if w.lower() not in ("the", "a", "an")]
    return " ".join(words).strip().lower()


def parse_atom(proposition):
    """Parse 'S is/has P' (+ optional negation) into a normalized atom.

    Returns (subject, copula, object, negated) or None when unparseable.
    """
    text = " ".join((proposition or "").strip().split())
    lowered = text.lower()
    if not lowered:
        return None

    words = lowered.split()
    negated = any(w.strip("',.;!") in _NEGATION_WORDS for w in words)

    cleaned = []
    for w in words:
        w = w.strip("',.;!")
        stripped = w.replace("'", "")
        if stripped in _CONTRACTIONS:
            # "isn't" keeps its copula ("is"); the negation flag above
            # already captured the polarity.
            cleaned.append(_CONTRACTIONS[stripped])
        elif w not in _NEGATION_WORDS:
            cleaned.append(w)
    lowered = " ".join(cleaned)

    for copula in _COPULAS:
        marker = f" {copula} "
        if marker in f" {lowered} ":
            subject, _, rest = lowered.partition(marker)
            obj = rest.strip()
            subject = subject.strip()
            if subject and obj:
                return (_strip_articles(subject), copula,
                        _strip_articles(obj), negated)
    return None


class EpistemicLogic:
    """Modal logic K/B over Z3-checked atomic beliefs."""

    def __init__(self):
        # atom name -> polarity believed so far (True = believed negated)
        self._atoms = {}

    def evaluate_knowledge(self, proposition: str, belief_score: float,
                           justification: bool,
                           contradictions: bool) -> TDict[str, Any]:
        """K(p) requires high belief + justification + no contradictions."""
        K_THRESHOLD = 0.9
        is_knowledge = (belief_score > K_THRESHOLD
                        and justification and not contradictions)
        return {
            "proposition": proposition,
            "belief_score": belief_score,
            "status": "KNOWLEDGE" if is_knowledge else "BELIEF",
            "justified": justification,
            "consistent": not contradictions,
        }

    def consistent_belief(self, proposition: str) -> bool:
        """Is believing `proposition` consistent with every atom believed so
        far? Decided by a real Z3 satisfiability check."""
        atom = parse_atom(proposition)
        if atom is None:
            logger.debug("[epistemic] unparseable proposition: %r",
                         proposition)
            return True

        subject, copula, obj, negated = atom
        name = f"atom::{subject}::{copula}::{obj}"

        solver = z3.Solver()
        for prior_name, prior_negated in self._atoms.items():
            ref = z3.Bool(prior_name)
            solver.add(z3.Not(ref) if prior_negated else ref)
        ref_new = z3.Bool(name)
        solver.add(z3.Not(ref_new) if negated else ref_new)

        consistent = solver.check() == z3.sat

        if not consistent:
            logger.info("[epistemic] belief contradicts held atoms: %s",
                        proposition)
        else:
            self._atoms.setdefault(name, negated)
        return consistent

    def reset(self) -> None:
        """Forget all recorded atoms."""
        self._atoms.clear()


# Global instance
epistemic = EpistemicLogic()
