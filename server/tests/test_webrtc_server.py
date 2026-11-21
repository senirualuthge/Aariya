"""Tests for WebRTC server audio queueing, pacing, and interruption."""
from __future__ import annotations

import asyncio
import fractions
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiortc.mediastreams import AudioFrame

from server.realtime import webrtc_server
from server.realtime.webrtc_server import (
    AudioReplyTrack,
    VoiceSession,
    close_session,
    enqueue_reply_audio,
)


def test_audio_reply_track_silence_when_empty():
    track = AudioReplyTrack(sample_rate=48000)

    async def _run():
        frame = await track.recv()
        assert isinstance(frame, AudioFrame)
        assert frame.sample_rate == 48000
        assert frame.samples == 960  # 20ms @ 48kHz
        assert bytes(frame.planes[0]) == b"\x00" * (960 * 2)

    asyncio.run(_run())


def test_audio_reply_track_plays_enqueued_audio():
    track = AudioReplyTrack(sample_rate=48000)
    pcm_frame1 = b"\x01\x00" * 960
    pcm_frame2 = b"\x02\x00" * 960

    track.enqueue_pcm(pcm_frame1 + pcm_frame2)

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
    track = AudioReplyTrack(sample_rate=48000)
    track.enqueue_pcm(b"\x03\x00" * 1920)

    track.clear()

    async def _run():
        frame = await track.recv()
        assert bytes(frame.planes[0]) == b"\x00" * (960 * 2)

    asyncio.run(_run())


def test_enqueue_reply_audio_helper():
    mock_peer = MagicMock()
    mock_peer.close = AsyncMock()

    reply_track = AudioReplyTrack(sample_rate=48000)
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
            enqueued = enqueue_reply_audio("rtc_enqueue_test", data, sample_rate=48000)
            assert enqueued is True

            frame = await reply_track.recv()
            assert bytes(frame.planes[0]) == data

            assert enqueue_reply_audio("rtc_does_not_exist", data) is False
        finally:
            await close_session(session, "test cleanup")

    asyncio.run(_run())
