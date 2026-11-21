"""Authenticated WebRTC audio -> ASR -> shared brain -> TTS -> WebRTC."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from server.realtime.webrtc_server import CapturedUtterance

from server.protocol import MultimodalInput
from server.systems.cognitive_session_coordinator import cognitive_sessions
from server.realtime.speech_recognition import speech_recognition
from server.realtime.speech_generation import speech_generation

logger = logging.getLogger("Aariya.AudioSession")


async def process_utterance(utterance: CapturedUtterance) -> Optional[dict[str, Any]]:
    if not getattr(utterance, "owner_id", None) or not getattr(utterance, "device_id", None):
        raise PermissionError("Authenticated device identity required")

    # Transcribe genuine microphone audio.
    transcript = await speech_recognition.transcribe(
        utterance.pcm,
        sample_rate=utterance.sample_rate,
    )
    text = transcript.get("text", "").strip()
    if not text:
        return None

    logger.info(
        "Transcribed audio session=%s device=%s: %s",
        utterance.session_id,
        utterance.device_id,
        text,
    )

    # Use the existing personal cognitive session.
    result, state = await cognitive_sessions.process_turn(
        utterance.owner_id,
        MultimodalInput(
            text=text,
            metadata={
                "mode": "voice",
                "session_id": utterance.session_id,
                "device_id": utterance.device_id,
                "source": "webrtc",
            },
        ),
    )

    reply_text = result.text if result and result.text else ""
    if not reply_text.strip():
        return None

    pcm = await speech_generation.generate(reply_text)

    from server.realtime.webrtc_server import enqueue_reply_audio

    queued = await enqueue_reply_audio(utterance.session_id, pcm)

    return {
        "user_text": text,
        "reply_text": reply_text,
        "audio_bytes": len(pcm),
        "audio_queued": queued,
    }


class AudioSessionService:
    async def process_utterance(self, utterance: Any) -> Optional[dict]:
        return await process_utterance(utterance)


audio_session_service = AudioSessionService()
