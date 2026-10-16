"""
Meeting Mode acoustic-isolation tests (Track B — partials plan).

Exercises the REAL paths: webrtcvad framing over genuinely synthesised PCM, the
online feature diarizer clustering distinct voices, the meeting-mode gate, and
the no-PCM heuristic fallback. Webrtcvad must be present for the VAD-path tests;
the whole module is skipped if it is not installed.

Run: python -m pytest server/tests/test_meeting_mode_vad.py -v
"""

import base64

import numpy as np
import pytest

from server.systems.voice import vad as vv
from server.systems.voice.diarization import SpeakerDiarizer
from server.systems.meeting_mode import MeetingMode

pytestmark = pytest.mark.skipif(
    not vv.available, reason="webrtcvad not installed — real VAD path unavailable"
)


# ── PCM helpers ──────────────────────────────────────────────────────────────

def _noisy_sine(freq, n, sr=16000, amp=0.3, seed=0):
    t = np.arange(n) / sr
    x = amp * np.sin(2 * np.pi * freq * t)
    x = x + 0.02 * np.random.default_rng(seed).standard_normal(n)
    return vv.float_to_int16(x)


def _b64(arr):
    return base64.b64encode(arr.astype(np.int16).tobytes()).decode()


# ── VAD wrapper ──────────────────────────────────────────────────────────────

def test_float_to_int16_clamps():
    out = vv.float_to_int16(np.array([-2.0, 0.0, 2.0, 0.5], dtype=np.float32))
    assert out.dtype == np.int16
    assert out[0] == -32767 and out[2] == 32767


def test_resample_changes_length():
    y = vv.resample_int16(np.linspace(-1, 1, 4410), 44100, 16000)
    assert y.size == 1600


def test_vad_frame_buffering_is_exact():
    det = vv.VoiceActivityDetector(sample_rate=16000, frame_ms=20)
    assert det.frame_samples == 320
    # 1000 samples → three whole 320-sample frames, 40 buffered
    r1 = det.process_int16(_noisy_sine(200, 1000).tobytes())
    assert r1["total_frames"] == 3
    assert len(r1["frame_bytes"]) == 3
    assert all(len(b) == 640 for b in r1["frame_bytes"])
    # 40 buffered + 600 new = 640 → two more frames
    r2 = det.process_int16(_noisy_sine(200, 600).tobytes())
    assert r2["total_frames"] == 2


def test_vad_rejects_bad_frame_settings():
    with pytest.raises(ValueError):
        vv.VoiceActivityDetector(sample_rate=44100)   # unsupported rate
    with pytest.raises(ValueError):
        vv.VoiceActivityDetector(sample_rate=16000, frame_ms=25)  # bad frame


# ── Diarizer ─────────────────────────────────────────────────────────────────

def test_diarizer_separates_two_voices():
    d = SpeakerDiarizer()
    a = d.assign(_noisy_sine(150, 3200), 16000)
    b = d.assign(_noisy_sine(3000, 3200), 16000)
    c = d.assign(_noisy_sine(155, 3200, seed=1), 16000)  # near-identical to a
    assert a == 0
    assert b == 1
    assert c == 0
    assert len(d.speakers()) == 2


def test_diarizer_returns_none_for_silence():
    d = SpeakerDiarizer()
    assert d.assign(np.zeros(3200, dtype=np.int16), 16000) is None
    assert d.speakers() == []


# ── Meeting mode integration ─────────────────────────────────────────────────

def test_meeting_real_vad_path_used_when_pcm_present():
    m = MeetingMode()
    pcm = np.concatenate([
        _noisy_sine(200, 4800),
        np.zeros(3200, dtype=np.int16),
        _noisy_sine(3000, 4800),
    ])
    res = m.report_audio_frame(0.5, True, pcm_b64=_b64(pcm), sample_rate=16000)
    assert res["used_vad"] is True
    assert 0.0 <= res["speech_ratio"] <= 1.0
    assert m.current_speaker_id is not None
    assert len(m.get_speakers()) >= 1


def test_meeting_heuristic_path_without_pcm():
    m = MeetingMode()
    res = m.report_audio_frame(0.5, True)
    assert res == {"used_vad": False, "speech_ratio": None, "speaker_id": None}
    assert m.get_speakers() == []          # no fabricated speakers


def test_meeting_vad_disabled_by_env(monkeypatch):
    monkeypatch.setenv("AARIYA_MEETING_VAD", "0")
    m = MeetingMode()
    res = m.report_audio_frame(
        0.5, True,
        pcm_b64=_b64(_noisy_sine(200, 3200)), sample_rate=16000,
    )
    assert res["used_vad"] is False        # real path disabled → heuristic only
    assert m.get_speakers() == []


def test_meeting_gate_requires_direct_address_for_ambient():
    m = MeetingMode()
    m.toggle(True)
    # no direct address yet → ambient chatter suppressed
    assert m.should_respond("what do you two think", 1, speaker_id=1) is False
    # direct address opens the window and sets the primary speaker
    assert m.should_respond("aariya, please", 1, speaker_id=1) is True
    assert m.primary_speaker_id == 1
    # the primary speaker keeps the follow-up window
    assert m.should_respond("and then?", 1, speaker_id=1) is True
    # an ambient speaker inside the window is still suppressed
    assert m.should_respond("anyway as I was saying", 1, speaker_id=2) is False


def test_meeting_gate_inactive_always_responds():
    m = MeetingMode()
    assert m.should_respond("random chatter", 1, speaker_id=None) is True


def test_meeting_gate_p0_bypasses():
    m = MeetingMode()
    m.toggle(True)
    assert m.should_respond("fire alarm", 0, speaker_id=2) is True


def test_meeting_status_exposes_vad_fields():
    m = MeetingMode()
    st = m.get_status()
    for key in ("vad_available", "vad_enabled", "vad_active", "last_speech_ratio",
                "current_speaker_id", "primary_speaker_id", "speakers"):
        assert key in st


def test_prompt_modifier_reflects_state():
    m = MeetingMode()
    assert m.get_prompt_modifier() == ""
    m.toggle(True)
    assert "Meeting Mode is ACTIVE" in m.get_prompt_modifier()
