"""Connect WebRTC speech to Aariya's shared cognitive sessions."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from server.protocol import MultimodalInput
from server.systems.cognitive_session_coordinator import cognitive_sessions
from server.realtime.speech_recognition import speech_recognition
from server.realtime.speech_generation import speech_generation

logger = logging.getLogger("Aariya.AudioSession")


class AudioSessionService:
    async def process_utterance(self, utterance: Any) -> Optional[Dict[str, Any]]:
        # 1. Transcribe real microphone input.
        transcription = await speech_recognition.transcribe(
            utterance.pcm,
            utterance.sample_rate,
        )
        text = transcription.get("text", "").strip()
        if not text:
            return None

        logger.info(
            "Transcribed audio session=%s device=%s: %s",
            utterance.session_id,
            utterance.device_id,
            text,
        )

        # 2. Feed into shared cognitive session (never instantiate another BrainV2)
        input_model = MultimodalInput(
            text=text,
            metadata={
                "mode": "voice",
                "session_id": utterance.session_id,
                "device_id": utterance.device_id,
                "source": "webrtc",
            },
        )

        output, brain_state = await cognitive_sessions.process_turn(
            utterance.owner_id,
            input_model,
        )

        reply_text = output.text if output and output.text else ""
        if not reply_text.strip():
            return None

        # 3. Real speech generation via Edge TTS
        pcm = await speech_generation.generate(reply_text)

        # 4. Enqueue playback on the live WebRTC session
        from server.realtime.webrtc_server import enqueue_reply_audio

        enqueued = enqueue_reply_audio(utterance.session_id, pcm)

        return {
            "user_text": text,
            "reply_text": reply_text,
            "audio_bytes": len(pcm),
            "enqueued": enqueued,
        }


audio_session_service = AudioSessionService()
