"""Tests for WebRTC server audio queueing, pacing, and interruption."""
from __future__ import annotations

import asyncio
import fractions
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiortc.mediastreams import AudioFrame
from fastapi.testclient import TestClient

from server.main import app
from server.realtime import webrtc_server
from server.realtime.webrtc_server import (
    AudioReplyTrack,
    VoiceSession,
    close_session,
    enqueue_reply_audio,
)


@pytest.fixture
def client():
    return TestClient(app)


def test_offer_rejects_missing_authentication(client):
    response = client.post(
        "/offer",
        json={
            "sdp": "invalid",
            "type": "offer",
        },
    )
    assert response.status_code in (401, 403)


def test_offer_rejects_invalid_sdp_without_auth(client):
    response = client.post(
        "/offer",
        json={
            "sdp": "",
            "type": "offer",
        },
    )
    assert response.status_code in (401, 403)


def test_audio_reply_track_silence_when_empty():
    track = AudioReplyTrack()

    async def _run():
        frame = await track.recv()
        assert isinstance(frame, AudioFrame)
        assert frame.sample_rate == 48000
        assert frame.samples == 960  # 20ms @ 48kHz
        assert bytes(frame.planes[0]) == b"\x00" * (960 * 2)

    asyncio.run(_run())


def test_audio_reply_track_plays_enqueued_audio():
    track = AudioReplyTrack()
    pcm_frame1 = b"\x01\x00" * 960
    pcm_frame2 = b"\x02\x00" * 960

    assert track.enqueue_pcm(pcm_frame1 + pcm_frame2) is True

    async def _run():
        frame1 = await track.recv()
        assert bytes(frame1.planes[0]) == pcm_frame1

        frame2 = await track.recv()
        assert bytes(frame2.planes[0]) == pcm_frame2

        # Third frame falls back to silence
        frame3 = await track.recv()
        assert bytes(frame3.planes[0]) == b"\x00" * (960 * 2)

    asyncio.run(_run())


def test_audio_reply_track_clear_drops_audio():
    track = AudioReplyTrack()
    track.enqueue_pcm(b"\x03\x00" * 1920)

    track.clear()

    async def _run():
        frame = await track.recv()
        assert bytes(frame.planes[0]) == b"\x00" * (960 * 2)

    asyncio.run(_run())


def test_audio_reply_track_queue_full_raises():
    track = AudioReplyTrack(sample_rate=48000)
    # Configure 60s queue limit to exactly 2 frames for testing
    track._max_queued_bytes = 960 * 2 * 2
    # Fill queue
    assert track.enqueue_pcm(b"\x01\x00" * (960 * 2)) is True
    # Next frame should exceed limit and return False
    assert track.enqueue_pcm(b"\x01\x00" * 960) is False


def test_enqueue_reply_audio_helper():
    mock_peer = MagicMock()
    mock_peer.close = AsyncMock()
    mock_peer.connectionState = "connected"

    reply_track = AudioReplyTrack()
    session = VoiceSession(
        session_id="rtc_enqueue_test",
        device_id="dev_1",
        owner_id="u1",
        device_label="phone",
        peer=mock_peer,
        reply=reply_track,
        created_at=time.time(),
    )
    webrtc_server._sessions["rtc_enqueue_test"] = session

    async def _run():
        try:
            data = b"\x04\x00" * 960
            enqueued = await enqueue_reply_audio("rtc_enqueue_test", data)
            assert enqueued is True

            frame = await reply_track.recv()
            assert bytes(frame.planes[0]) == data

            with pytest.raises(RuntimeError, match="WebRTC session is no longer active"):
                await enqueue_reply_audio("rtc_does_not_exist", data)
        finally:
            await close_session(session, "test cleanup")

    asyncio.run(_run())


def test_get_active_session_rejects_closed_session():
    assert webrtc_server.get_active_session("does_not_exist") is None


def test_get_active_session_returns_live_session():
    mock_peer = MagicMock()
    session = VoiceSession(
        session_id="rtc_active_test",
        device_id="device_1",
        owner_id="owner_1",
        device_label="phone",
        peer=mock_peer,
        reply=AudioReplyTrack(),
        created_at=time.time(),
    )
    webrtc_server._sessions[session.session_id] = session
    try:
        assert webrtc_server.get_active_session(session.session_id) is session
    finally:
        webrtc_server._sessions.pop(session.session_id, None)

