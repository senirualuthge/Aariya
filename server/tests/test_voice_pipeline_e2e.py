"""Real-provider integration test for Aariya's voice pipeline.

Run only with a genuine recorded speech file and a designated test owner.
"""
from __future__ import annotations

import os
from pathlib import Path

import av
import pytest

from server.protocol import MultimodalInput
from server.realtime.speech_generation import speech_generation
from server.realtime.speech_recognition import speech_recognition
from server.systems.cognitive_session_coordinator import cognitive_sessions

AUDIO_FILE = os.getenv("AARIYA_E2E_AUDIO_FILE")
OWNER_ID = os.getenv("AARIYA_E2E_OWNER_ID")
pytestmark = pytest.mark.integration


def _load_real_audio(path: str) -> bytes:
    container = av.open(path)
    resampler = av.AudioResampler(
        format="s16",
        layout="mono",
        rate=16000,
    )
    pcm = bytearray()
    try:
        for frame in container.decode(audio=0):
            for resampled in resampler.resample(frame):
                if resampled.planes:
                    pcm.extend(bytes(resampled.planes[0]))
    finally:
        container.close()
    return bytes(pcm)


@pytest.mark.asyncio
async def test_voice_pipeline_requires_real_providers():
    assert speech_recognition is not None
    assert speech_generation is not None


@pytest.mark.asyncio
async def test_real_voice_pipeline_e2e():
    if not AUDIO_FILE or not OWNER_ID:
        pytest.skip(
            "Requires genuine AARIYA_E2E_AUDIO_FILE and AARIYA_E2E_OWNER_ID"
        )

    path = Path(AUDIO_FILE)
    if not path.is_file():
        pytest.skip(f"Audio file not found: {AUDIO_FILE}")

    pcm = _load_real_audio(str(path))
    assert len(pcm) > 0, "Real audio file produced no PCM"

    # 1. Transcribe with real ASR
    asr_result = await speech_recognition.transcribe(pcm, sample_rate=16000)
    text = asr_result.get("text", "").strip()
    assert text, f"Real ASR transcription was empty for {AUDIO_FILE}"

    # 2. Process turn with real cognitive session
    response, brain_state = await cognitive_sessions.process_turn(
        owner_id=OWNER_ID,
        user_input=MultimodalInput(
            text=text,
            metadata={"source": "e2e_voice_test"},
        ),
    )
    assert response is not None
    assert brain_state is not None

    # 3. Generate speech with real TTS if response has text
    if response.text and response.text.strip():
        audio_bytes = await speech_generation.generate(response.text)
        assert len(audio_bytes) > 0
        assert len(audio_bytes) % 2 == 0
