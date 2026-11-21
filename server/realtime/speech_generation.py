"""Real speech generation for Aariya."""
from __future__ import annotations

import asyncio
import io
import os

import av
import edge_tts


class SpeechGenerationService:
    def __init__(self) -> None:
        self.voice = os.getenv(
            "AARIYA_TTS_VOICE",
            "en-US-AriaNeural",
        )
        self.rate = os.getenv(
            "AARIYA_TTS_RATE",
            "+0%",
        )

    async def generate(
        self,
        text: str,
        target_sample_rate: int = 48000,
    ) -> bytes:
        text = (text or "").strip()
        if not text:
            raise ValueError("Cannot generate empty speech")

        communicator = edge_tts.Communicate(
            text=text,
            voice=self.voice,
            rate=self.rate,
        )
        mp3_buffer = io.BytesIO()
        async for chunk in communicator.stream():
            if chunk.get("type") == "audio":
                mp3_buffer.write(chunk.get("data", b""))

        mp3_bytes = mp3_buffer.getvalue()
        if not mp3_bytes:
            return b""

        return await asyncio.to_thread(
            self._decode_to_pcm,
            mp3_bytes,
            target_sample_rate,
        )

    def _decode_to_pcm(
        self,
        audio_data: bytes,
        target_sample_rate: int = 48000,
    ) -> bytes:
        if not audio_data:
            return b""
        input_container = av.open(io.BytesIO(audio_data))
        resampler = av.AudioResampler(
            format="s16",
            layout="mono",
            rate=target_sample_rate,
        )
        out_pcm = bytearray()
        for frame in input_container.decode(audio=0):
            resampled = resampler.resample(frame)
            for rf in resampled:
                out_pcm.extend(bytes(rf.planes[0]))
        flushed = resampler.resample(None)
        for rf in flushed:
            out_pcm.extend(bytes(rf.planes[0]))
        return bytes(out_pcm)


speech_generation = SpeechGenerationService()
