"""Authenticated WebRTC audio -> ASR -> shared cognition -> TTS -> WebRTC."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from server.protocol import MultimodalInput
from server.systems.cognitive_session_coordinator import cognitive_sessions
from server.realtime.speech_recognition import speech_recognition
from server.realtime.speech_generation import speech_generation

logger = logging.getLogger("Aariya.AudioSession")

ASR_TIMEOUT_SECONDS = 30
BRAIN_TIMEOUT_SECONDS = 120
TTS_TIMEOUT_SECONDS = 60

# Avoid two speech turns from one WebRTC session producing overlapping audio.
_session_locks: dict[str, asyncio.Lock] = {}
_session_locks_guard = asyncio.Lock()


async def _get_session_lock(session_id: str) -> asyncio.Lock:
    async with _session_locks_guard:
        return _session_locks.setdefault(session_id, asyncio.Lock())


async def process_utterance(utterance: Any) -> Optional[dict[str, Any]]:
    started = time.monotonic()
    session_id = getattr(utterance, "session_id", "")
    device_id = getattr(utterance, "device_id", "")

    if not getattr(utterance, "owner_id", None) or not device_id:
        raise PermissionError("Authenticated device identity required")

    lock = await _get_session_lock(session_id)
    async with lock:
        try:
            transcript = await asyncio.wait_for(
                speech_recognition.transcribe(
                    utterance.pcm,
                    sample_rate=utterance.sample_rate,
                ),
                timeout=ASR_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "ASR timed out after %ds session=%s", ASR_TIMEOUT_SECONDS, session_id
            )
            return None

        text = transcript.get("text", "").strip()
        if not text:
            return None

        # Privacy-safe: log word count only, never the transcript text.
        logger.info(
            "Transcription complete session=%s device=%s words=%d",
            session_id,
            device_id,
            len(text.split()),
        )

        try:
            result, _state = await asyncio.wait_for(
                cognitive_sessions.process_turn(
                    utterance.owner_id,
                    MultimodalInput(
                        text=text,
                        metadata={
                            "mode": "voice",
                            "session_id": session_id,
                            "device_id": device_id,
                            "source": "webrtc",
                        },
                    ),
                ),
                timeout=BRAIN_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Brain timed out after %ds session=%s", BRAIN_TIMEOUT_SECONDS, session_id
            )
            return None

        reply_text = result.text if result and result.text else ""
        if not reply_text.strip():
            return None

        try:
            pcm = await asyncio.wait_for(
                speech_generation.generate(reply_text),
                timeout=TTS_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "TTS timed out after %ds session=%s", TTS_TIMEOUT_SECONDS, session_id
            )
            return None

        from server.realtime.webrtc_server import enqueue_reply_audio

        try:
            queued = await enqueue_reply_audio(session_id, pcm)
        except RuntimeError as exc:
            logger.warning(
                "Could not deliver reply audio session=%s: %s", session_id, exc
            )
            return None

        elapsed = time.monotonic() - started
        logger.info(
            "Audio pipeline complete session=%s latency=%.2fs audio_bytes=%d",
            session_id,
            elapsed,
            len(pcm),
        )

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
