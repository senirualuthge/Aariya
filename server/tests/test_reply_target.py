"""
Meeting Mode reply-target labelling (B4 — spatial-audio honest subset).

The backend labels every reply with the REAL diarized speaker it is addressed to
plus a stable, id-ordered seating slot. `get_reply_target()` must never invent a
speaker: with Meeting Mode off, or with nothing diarized, every field is None/0.

Run: python -m pytest server/tests/test_reply_target.py -v
"""

from server.systems.meeting_mode import MeetingMode


class _RosterDiarizer:
    """Stand-in exposing the same id-ordered `speakers()` contract as the real
    SpeakerDiarizer, so slot assignment can be driven without live PCM."""

    def __init__(self, ids):
        self._ids = list(ids)

    def speakers(self):
        return [{"id": i, "segments": 1, "last_active": 0.0} for i in self._ids]


def test_reply_target_none_when_meeting_inactive():
    m = MeetingMode()
    assert m.active is False
    assert m.get_reply_target() == {"speaker_id": None, "slot": None, "count": 0}


def test_reply_target_none_without_diarized_speakers():
    m = MeetingMode()
    m.toggle(True)
    assert m.get_reply_target() == {"speaker_id": None, "slot": None, "count": 0}


def test_reply_target_slot_follows_id_order():
    m = MeetingMode()
    m.toggle(True)
    m._diarizer = _RosterDiarizer([0, 1, 2])

    m.current_speaker_id = 2
    assert m.get_reply_target() == {"speaker_id": 2, "slot": 2, "count": 3}

    m.current_speaker_id = 0
    assert m.get_reply_target() == {"speaker_id": 0, "slot": 0, "count": 3}


def test_reply_target_slot_absent_for_unknown_speaker():
    m = MeetingMode()
    m.toggle(True)
    m._diarizer = _RosterDiarizer([0, 1])
    m.current_speaker_id = 7  # never diarized
    assert m.get_reply_target() == {"speaker_id": 7, "slot": None, "count": 2}


def test_reply_target_count_is_the_real_roster_size():
    m = MeetingMode()
    m.toggle(True)
    m._diarizer = _RosterDiarizer([0, 1])
    m.current_speaker_id = 1
    assert m.get_reply_target()["count"] == 2
