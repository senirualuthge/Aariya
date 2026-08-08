"""Unit tests for the FIXV5 post-generation grounding validator.

The scanner is a deterministic veto layer: it flags reply sentences that
directly negate a remembered Layer 1 fact, skips hedged uncertainty, and is
deliberately conservative so normal conversation never trips it.
"""

from server.systems.agent.grounding_validator import GroundingValidator


def test_facts_from_memory_context_parses_dash_lines():
    v = GroundingValidator()
    ctx = "- I love stargazing at night\n- User's dog is named Biscuit\n"
    assert v.facts_from_memory_context(ctx) == [
        "I love stargazing at night",
        "User's dog is named Biscuit",
    ]


def test_facts_from_memory_context_empty():
    assert GroundingValidator().facts_from_memory_context("") == []
    assert GroundingValidator().facts_from_memory_context("   \n  ") == []


def test_flags_direct_negation_of_remembered_fact():
    v = GroundingValidator()
    facts = ["I love stargazing at night"]
    issues = v.validate("You never loved stargazing at all.", facts)
    assert len(issues) == 1
    assert issues[0].fact == "I love stargazing at night"
    assert issues[0].reply == "You never loved stargazing at all."


def test_flags_contracted_negation_with_stemming():
    v = GroundingValidator()
    facts = ["I love dogs"]
    # "loved" stems to "love" — must still match the memory's verb.
    issues = v.validate("You don't love dogs anymore, do you?", facts)
    assert len(issues) == 1


def test_flags_negation_in_longer_reply_keeping_other_sentences():
    v = GroundingValidator()
    facts = ["I love stargazing at night"]
    reply = ("That sounds lovely. But honestly, you never loved stargazing. "
             "Let's talk about the moon instead.")
    issues = v.validate(reply, facts)
    assert len(issues) == 1
    assert "never loved stargazing" in issues[0].reply


def test_hedged_uncertainty_is_not_a_contradiction():
    v = GroundingValidator()
    facts = ["I love stargazing at night"]
    # "I'm not sure" / "don't remember" express uncertainty, not denial.
    for reply in (
        "I'm not sure you love stargazing.",
        "I don't remember if you love stargazing.",
        "Maybe you love stargazing — tell me more.",
    ):
        assert v.validate(reply, facts) == [], f"false positive: {reply!r}"


def test_positive_reaffirmation_not_flagged():
    v = GroundingValidator()
    facts = ["I love stargazing at night"]
    assert v.validate("I remember you love stargazing — it's your favorite.", facts) == []


def test_unrelated_negation_not_flagged():
    v = GroundingValidator()
    facts = ["User's dog is named Biscuit"]
    assert v.validate("I don't like traffic either.", facts) == []


def test_negation_in_other_clause_not_flagged():
    v = GroundingValidator()
    facts = ["I love stargazing at night"]
    # The negation applies to sleeping; the stargazing clause AFFIRMS the fact.
    assert v.validate("I don't sleep much, but I love stargazing.", facts) == []


def test_correction_affirmation_not_flagged():
    v = GroundingValidator()
    facts = ["I love stargazing at night"]
    # "That's not what I meant" denies the accusation, then affirms the fact.
    assert v.validate("That's not what I meant — I love stargazing.", facts) == []


def test_negated_affirmation_verb_not_flagged():
    v = GroundingValidator()
    facts = ["I love stargazing at night"]
    # "never forget" flips INTO affirmation — a warm companion phrase.
    assert v.validate("I'll never forget our stargazing nights.", facts) == []


def test_bare_not_marker_with_full_overlap_flagged():
    v = GroundingValidator()
    facts = ["I love stargazing at night"]
    issues = v.validate("You are not someone who loves stargazing.", facts)
    assert len(issues) == 1


def test_single_shared_word_insufficient():
    v = GroundingValidator()
    facts = ["I love stargazing at night"]
    # Only one content word overlaps ("stargazing") — too weak to call a
    # contradiction of the whole fact.
    assert v.validate("You don't see stargazing from the city.", facts) == []


def test_empty_inputs_are_safe():
    v = GroundingValidator()
    assert v.validate("", ["a fact"]) == []
    assert v.validate("Hello there.", []) == []
    assert v.validate("", []) == []
