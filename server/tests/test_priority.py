import pytest

from server.systems.priority_pipeline import get_priority_pipeline, Priority

CASES = [
    ("HELP ME EMERGENCY", Priority.P0_EMERGENCY),
    ("Hey, what is the weather today?", Priority.P1_DIRECT),
    ("How are you doing lately?", Priority.P1_DIRECT),
    ("That sounds very interesting, tell me more.", Priority.P2_CONVERSATIONAL),
    ("hmm", Priority.P3_AMBIENT),
    ("ok", Priority.P3_AMBIENT),
    ("", Priority.P4_IDLE),
]


@pytest.mark.parametrize("text,expected", CASES)
def test_priority_classifier(text, expected):
    assert get_priority_pipeline().classify(text) == expected, (
        f"'{text}' classified incorrectly"
    )
