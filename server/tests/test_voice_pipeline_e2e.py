"""Integration verification for Aariya's voice pipeline."""
import os
import pytest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_voice_pipeline_configuration():
    required = [
        "TURN_SHARED_SECRET",
        "TURN_URLS",
        "AARIYA_TTS_VOICE",
    ]
    missing = [
        name for name in required
        if not os.getenv(name)
    ]
    assert not missing, (
        f"Missing integration configuration: {missing}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_voice_pipeline_requires_real_providers():
    from server.realtime.speech_recognition import speech_recognition
    from server.realtime.speech_generation import speech_generation

    assert speech_recognition is not None
    assert speech_generation is not None
