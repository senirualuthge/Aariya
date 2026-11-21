"""Tests for audio pipeline (transcription, speech generation, audio session)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.protocol import BrainState, MultimodalInput, MultimodalOutput
from server.realtime import audio_session
from server.realtime.audio_session import AudioSessionService, process_utterance
from server.realtime.speech_generation import SpeechGenerationService
from server.realtime.speech_recognition import SpeechRecognitionService
from server.realtime.webrtc_server import CapturedUtterance


@pytest.mark.asyncio
async def test_audio_requires_authenticated_owner():
    utterance = SimpleNamespace(
        owner_id=None,
        device_id="device-1",
        pcm=b"\x00\x00",
        sample_rate=16000,
        session_id="session-1",
    )
    with pytest.raises(PermissionError):
        await audio_session.process_utterance(utterance)


@pytest.mark.asyncio
async def test_audio_requires_authenticated_device():
    utterance = SimpleNamespace(
        owner_id="user-1",
        device_id=None,
        pcm=b"\x00\x00",
        sample_rate=16000,
        session_id="session-1",
    )
    with pytest.raises(PermissionError):
        await audio_session.process_utterance(utterance)


def test_speech_recognition_validation():
    service = SpeechRecognitionService()

    async def _run():
        with pytest.raises(ValueError, match="Empty audio input"):
            await service.transcribe(b"")

        with pytest.raises(ValueError, match="Expected 16000 Hz audio"):
            await service.transcribe(b"\x00\x00", sample_rate=48000)

        with pytest.raises(ValueError, match="Invalid PCM16 audio"):
            await service.transcribe(b"\x00\x00\x01")  # odd number of bytes

    asyncio.run(_run())


def test_speech_recognition_transcribe_mocked():
    service = SpeechRecognitionService()

    mock_segment = MagicMock()
    mock_segment.start = 0.0
    mock_segment.end = 1.0
    mock_segment.text = "Hello Aariya"

    mock_info = MagicMock()
    mock_info.language = "en"
    mock_info.language_probability = 0.99
    mock_info.duration = 1.0

    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([mock_segment], mock_info)

    async def _run():
        with patch.object(service, "_load_model", return_value=mock_model):
            pcm = b"\x00\x00" * 16000  # 1 second of silence
            result = await service.transcribe(pcm, sample_rate=16000)

            assert result["text"] == "Hello Aariya"
            assert result["language"] == "en"
            assert len(result["segments"]) == 1

    asyncio.run(_run())


def test_speech_generation_validation():
    service = SpeechGenerationService()

    async def _run():
        with pytest.raises(ValueError, match="Cannot generate empty speech"):
            await service.generate("")

        with pytest.raises(ValueError, match="Cannot generate empty speech"):
            await service.generate("   ")

    asyncio.run(_run())


def test_speech_generation_mocked():
    service = SpeechGenerationService()

    async def mock_stream():
        yield {"type": "audio", "data": b"mock-mp3-chunk"}

    mock_comm = MagicMock()
    mock_comm.stream = mock_stream

    fake_pcm = b"\x01\x00" * 960

    async def _run():
        with patch("edge_tts.Communicate", return_value=mock_comm):
            with patch.object(service, "_decode_to_pcm", return_value=fake_pcm):
                pcm = await service.generate("Hello world")
                assert pcm == fake_pcm

    asyncio.run(_run())


def test_audio_session_process_utterance():
    utterance = CapturedUtterance(
        session_id="rtc_test_123",
        device_id="dev_456",
        device_label="Test Phone",
        owner_id="u1",
        pcm=b"\x00\x00" * 8000,
        sample_rate=16000,
        duration_seconds=0.5,
        started_at=100.0,
        ended_at=100.5,
    )

    mock_transcription = {"text": "What time is it?"}
    mock_output = MultimodalOutput(text="It is time to build.", expression="happy")
    mock_brain_state = BrainState(user_id="u1", trust=0.8, emotion="joy")
    fake_tts_pcm = b"\x02\x00" * 1920

    async def _run():
        with patch("server.realtime.audio_session.speech_recognition.transcribe", AsyncMock(return_value=mock_transcription)) as mock_transcribe:
            with patch("server.realtime.audio_session.cognitive_sessions.process_turn", AsyncMock(return_value=(mock_output, mock_brain_state))) as mock_process_turn:
                with patch("server.realtime.audio_session.speech_generation.generate", AsyncMock(return_value=fake_tts_pcm)) as mock_gen:
                    with patch("server.realtime.webrtc_server.enqueue_reply_audio", AsyncMock(return_value=2)) as mock_enqueue:
                        result = await process_utterance(utterance)

                        assert result is not None
                        assert result["user_text"] == "What time is it?"
                        assert result["reply_text"] == "It is time to build."
                        assert result["audio_bytes"] == len(fake_tts_pcm)
                        assert result["queued_frames"] == 2

                        mock_transcribe.assert_awaited_once_with(utterance.pcm, sample_rate=utterance.sample_rate)
                        mock_process_turn.assert_awaited_once()
                        turn_args = mock_process_turn.call_args[0]
                        assert turn_args[0] == "u1"
                        assert isinstance(turn_args[1], MultimodalInput)
                        assert turn_args[1].text == "What time is it?"

                        mock_gen.assert_awaited_once_with("It is time to build.")
                        mock_enqueue.assert_awaited_once_with("rtc_test_123", fake_tts_pcm)

    asyncio.run(_run())


def test_audio_session_empty_transcription_returns_none():
    utterance = CapturedUtterance(
        session_id="rtc_test_empty",
        device_id="dev_456",
        device_label="Test Phone",
        owner_id="u1",
        pcm=b"\x00\x00" * 4800,
        sample_rate=16000,
        duration_seconds=0.3,
        started_at=100.0,
        ended_at=100.3,
    )

    async def _run():
        with patch("server.realtime.audio_session.speech_recognition.transcribe", AsyncMock(return_value={"text": "   "})):
            result = await process_utterance(utterance)
            assert result is None

    asyncio.run(_run())
