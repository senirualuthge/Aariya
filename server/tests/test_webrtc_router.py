"""Tests for the WebRTC capture endpoint (server/realtime/webrtc_server.py).

Covers the authorization gate (paired mobile device only), SDP validation, real
SDP answer negotiation over aiortc, the capture-only utterance path (real
resampling + VAD framing), session limits and teardown.

Every credential here is generated inside the test session against the isolated
tmp SQLite fixture from ``conftest.py``.
"""

from __future__ import annotations

import asyncio
import fractions
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

aiortc = pytest.importorskip("aiortc")

from aiortc import MediaStreamTrack, RTCPeerConnection  # noqa: E402
from aiortc.mediastreams import AudioFrame  # noqa: E402

from server import main as server_main  # noqa: E402
from server.realtime import webrtc_server  # noqa: E402
from server.systems.security.device_auth import create_pairing_code  # noqa: E402
from server.systems.voice import vad as voice_vad  # noqa: E402

OWNER = "u1"


# ── Fixtures / helpers ───────────────────────────────────────────────────────

@pytest.fixture
def strict_auth(isolated_db, monkeypatch):
    monkeypatch.setenv("AARIYA_OWNER_ID", OWNER)
    # No STUN in tests: answer creation must not depend on the network.
    monkeypatch.setattr(webrtc_server, "ICE_SERVERS", [])
    yield isolated_db


@pytest.fixture
def client(strict_auth):
    return TestClient(server_main.app)


@pytest.fixture(autouse=True)
def _isolate_sessions():
    webrtc_server._sessions.clear()
    yield
    sessions = list(webrtc_server._sessions.values())
    webrtc_server._sessions.clear()
    for session in sessions:
        session.closing = True
        if session.watchdog is not None:
            session.watchdog.cancel()


def _pair(client, role="mobile", label="phone", platform="ios"):
    code = create_pairing_code(role=role)
    response = client.post(
        "/api/auth/device/enroll",
        json={"pairing_code": code, "label": label, "platform": platform},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _auth(credential):
    return {"Authorization": f"Bearer {credential}"}


class _SilenceTrack(MediaStreamTrack):
    """Minimal local audio track so the offer carries a real m=audio section."""

    kind = "audio"

    def __init__(self, sample_rate: int = 48000):
        super().__init__()
        self._sample_rate = sample_rate
        self._samples = 960
        self._timestamp = 0

    async def recv(self) -> AudioFrame:
        self._timestamp += self._samples
        frame = AudioFrame(format="s16", layout="mono", samples=self._samples)
        frame.planes[0].update(b"\x00" * (self._samples * 2))
        frame.sample_rate = self._sample_rate
        frame.time_base = fractions.Fraction(1, self._sample_rate)
        return frame


def _client_offer() -> dict:
    """Build a genuine client offer SDP (no HTTP server, no network)."""

    async def _make():
        pc = RTCPeerConnection()
        pc.addTrack(_SilenceTrack())
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)
        sdp = pc.localDescription.sdp
        await pc.close()
        return {"sdp": sdp, "type": "offer"}

    return asyncio.run(_make())


# ── Mounting ─────────────────────────────────────────────────────────────────

def test_router_is_mounted():
    """Routers are included lazily, so inspect the original routers' paths."""
    paths = set()
    for route in server_main.app.routes:
        paths.add(getattr(route, "path", None))
        original = getattr(route, "original_router", None)
        if original is not None:
            paths.update(
                getattr(sub, "path", None) for sub in original.routes
            )

    assert "/offer" in paths
    assert "/interrupt" in paths


# ── Authorization ────────────────────────────────────────────────────────────

def test_offer_without_credential_is_rejected(client):
    response = client.post("/offer", json=_client_offer())
    assert response.status_code == 401


def test_offer_rejects_dashboard_device(client):
    device = _pair(client, role="dashboard", label="laptop", platform="macos")
    response = client.post(
        "/offer",
        json=_client_offer(),
        headers=_auth(device["credential"]),
    )
    assert response.status_code == 403


def test_offer_never_falls_back_to_legacy_mode(isolated_db, monkeypatch):
    monkeypatch.setattr(webrtc_server, "ICE_SERVERS", [])
    client = TestClient(server_main.app)
    response = client.post("/offer", json=_client_offer())
    # Legacy mode must NOT open an anonymous media session.
    assert response.status_code == 401


def test_interrupt_requires_mobile_device(client):
    assert client.post("/interrupt").status_code == 401

    dashboard = _pair(client, role="dashboard", label="laptop", platform="macos")
    response = client.post("/interrupt", headers=_auth(dashboard["credential"]))
    assert response.status_code == 403


# ── Negotiation ──────────────────────────────────────────────────────────────

def test_offer_returns_real_sdp_answer(client):
    device = _pair(client)
    response = client.post(
        "/offer",
        json=_client_offer(),
        headers=_auth(device["credential"]),
    )
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["type"] == "answer"
    assert body["sdp"].startswith("v=0")
    assert "m=audio" in body["sdp"]
    assert body["session_id"] in webrtc_server._sessions


def test_offer_rejects_non_offer_type(client):
    device = _pair(client)
    payload = _client_offer()
    payload["type"] = "answer"
    response = client.post(
        "/offer", json=payload, headers=_auth(device["credential"])
    )
    assert response.status_code == 400


def test_offer_rejects_sdp_without_audio(client):
    device = _pair(client)
    response = client.post(
        "/offer",
        json={
            "sdp": "v=0\r\no=- 1 1 IN IP4 0.0.0.0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\n",
            "type": "offer",
        },
        headers=_auth(device["credential"]),
    )
    assert response.status_code == 400


def test_offer_rejects_garbage_sdp(client):
    device = _pair(client)
    response = client.post(
        "/offer",
        json={"sdp": "not an sdp at all", "type": "offer"},
        headers=_auth(device["credential"]),
    )
    assert response.status_code == 400


def test_offer_rejects_missing_body(client):
    device = _pair(client)
    response = client.post("/offer", headers=_auth(device["credential"]))
    assert response.status_code == 422


def test_same_device_session_limit_closes_oldest(client, monkeypatch):
    monkeypatch.setattr(webrtc_server, "MAX_SESSIONS_PER_DEVICE", 1)
    device = _pair(client)
    headers = _auth(device["credential"])

    first = client.post("/offer", json=_client_offer(), headers=headers)
    assert first.status_code == 200, first.text
    first_id = first.json()["session_id"]

    second = client.post("/offer", json=_client_offer(), headers=headers)
    assert second.status_code == 200, second.text
    second_id = second.json()["session_id"]

    assert first_id != second_id
    assert first_id not in webrtc_server._sessions
    assert second_id in webrtc_server._sessions


def test_interrupt_reports_real_session_count(client):
    device = _pair(client)
    headers = _auth(device["credential"])
    assert client.post("/offer", json=_client_offer(), headers=headers).status_code == 200

    response = client.post("/interrupt", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "interrupted"
    assert body["sessions"] == 1
    assert body["discarded_frames"] >= 0


def test_interrupt_is_scoped_to_the_calling_device(client):
    phone_a = _pair(client, label="phone-a")
    phone_b = _pair(client, label="phone-b")

    created = client.post(
        "/offer",
        json=_client_offer(),
        headers=_auth(phone_a["credential"]),
    )
    assert created.status_code == 200, created.text

    response = client.post("/interrupt", headers=_auth(phone_b["credential"]))
    assert response.json()["sessions"] == 0


# ── Capture path ─────────────────────────────────────────────────────────────

def test_resample_brings_48k_to_16k_mono_int16():
    t = np.arange(4800) / 48000.0
    tone = (0.5 * 32767 * np.sin(2 * np.pi * 440 * t)).astype(np.int16)

    out = webrtc_server.pcm16_at_capture_rate(tone, 48000)

    assert out.dtype == np.int16
    assert abs(len(out) - 1600) <= 1
    assert np.max(np.abs(out)) > 1000  # real signal, not silence


def _consumer():
    session = webrtc_server.VoiceSession(
        session_id="rtc_test",
        device_id="dev_1",
        owner_id=OWNER,
        device_label="phone",
        peer=None,  # type: ignore[arg-type]
        reply=None,  # type: ignore[arg-type]
        created_at=time.time(),
    )
    return webrtc_server.InboundAudioConsumer(session, track=None)  # type: ignore[arg-type]


def test_utterance_requires_minimum_speech_duration(monkeypatch):
    captured = []

    async def sink(utterance):
        captured.append(utterance)

    monkeypatch.setattr(webrtc_server, "_utterance_sink", sink)
    consumer = _consumer()
    consumer._vad = voice_vad.VoiceActivityDetector(sample_rate=16000, frame_ms=30)

    async def _run():
        # 5 speech frames = 150 ms < 300 ms minimum.
        for _ in range(5):
            consumer._accumulate(True, b"\x01\x00" * 480)
        for _ in range(webrtc_server.SILENCE_FRAMES_TO_CLOSE):
            consumer._accumulate(False, b"\x00\x00" * 480)
        await asyncio.sleep(0)

    asyncio.run(_run())
    assert captured == []


def test_utterance_closes_after_real_silence(monkeypatch):
    captured = []

    async def sink(utterance):
        captured.append(utterance)

    monkeypatch.setattr(webrtc_server, "_utterance_sink", sink)
    consumer = _consumer()
    consumer._vad = voice_vad.VoiceActivityDetector(sample_rate=16000, frame_ms=30)

    async def _run():
        for _ in range(20):  # 600 ms of "speech"
            consumer._accumulate(True, b"\x02\x00" * 480)
        for _ in range(webrtc_server.SILENCE_FRAMES_TO_CLOSE - 1):
            consumer._accumulate(False, b"\x00\x00" * 480)
        assert captured == []  # silence hold not yet reached
        consumer._accumulate(False, b"\x00\x00" * 480)
        await asyncio.sleep(0)

    asyncio.run(_run())

    assert len(captured) == 1
    utterance = captured[0]
    assert utterance.sample_rate == webrtc_server.CAPTURE_SAMPLE_RATE
    assert utterance.duration_seconds == pytest.approx(0.6, abs=0.05)
    assert len(utterance.pcm) == 20 * 480 * 2
    assert utterance.device_id == "dev_1"


def test_interrupt_discards_buffered_speech():
    consumer = _consumer()
    for _ in range(10):
        consumer._accumulate(True, b"\x03\x00" * 480)

    assert consumer.interrupt() == 10
    assert consumer._pending == []
    assert consumer.interrupt() == 0


def test_pcm_resampler_keeps_silence_silent():
    silence = np.zeros(4800, dtype=np.int16)
    out = webrtc_server.pcm16_at_capture_rate(silence, 48000)
    assert not np.any(out)
