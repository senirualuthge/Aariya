"""Real speech recognition for Aariya WebRTC audio."""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict

import numpy as np
from faster_whisper import WhisperModel


class SpeechRecognitionService:
    def __init__(self) -> None:
        self.model_size = os.getenv("AARIYA_WHISPER_MODEL", "base")
        self.device = os.getenv("AARIYA_WHISPER_DEVICE", "cpu")
        self.compute_type = os.getenv("AARIYA_WHISPER_COMPUTE_TYPE", "int8")
        self._model: WhisperModel | None = None
        self._lock = asyncio.Lock()

    def _load_model(self) -> WhisperModel:
        if self._model is None:
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
        return self._model

    async def transcribe(
        self,
        pcm: bytes,
        sample_rate: int = 16000,
    ) -> Dict[str, Any]:
        if not pcm:
            raise ValueError("Empty audio input")
        if sample_rate != 16000:
            raise ValueError("Expected 16000 Hz audio")
        if len(pcm) % 2 != 0:
            raise ValueError("Invalid PCM16 audio")

        async with self._lock:
            return await asyncio.to_thread(
                self._transcribe_sync,
                pcm,
            )

    def _transcribe_sync(self, pcm: bytes) -> Dict[str, Any]:
        model = self._load_model()
        samples = (
            np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        )
        segments, info = model.transcribe(
            samples,
            beam_size=5,
            language=os.getenv("AARIYA_WHISPER_LANGUAGE", "en"),
            condition_on_previous_text=False,
        )
        text_segments = list(segments)
        full_text = " ".join(s.text.strip() for s in text_segments).strip()
        return {
            "text": full_text,
            "language": getattr(info, "language", "en"),
            "language_probability": getattr(info, "language_probability", 1.0),
            "duration": getattr(info, "duration", 0.0),
            "segments": [
                {
                    "start": getattr(s, "start", 0.0),
                    "end": getattr(s, "end", 0.0),
                    "text": getattr(s, "text", ""),
                }
                for s in text_segments
            ],
        }


speech_recognition = SpeechRecognitionService()
