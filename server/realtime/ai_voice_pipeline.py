"""
AI Voice Pipeline - Real-time streaming ASR → LLM → TTS pipeline.
Designed for use with WebRTC audio frames (aiortc).
"""
import asyncio
import numpy as np
from typing import AsyncIterator

try:
    from faster_whisper import WhisperModel
    _whisper = WhisperModel("tiny", compute_type="int8")  # fastest, load once
except ImportError:
    _whisper = None

try:
    import edge_tts
    _TTS_VOICE = "en-US-AriaNeural"
except ImportError:
    edge_tts = None  # type: ignore

from server.infrastructure.observability import logger


class AIVoicePipeline:
    """
    Full streaming pipeline: audio chunk → text → tokens → audio chunks.
    Each stage streams into the next — no buffering full responses.
    """

    def __init__(self):
        self._interrupt = False

    # ─── ASR ──────────────────────────────────────────────────────────────────
    async def transcribe(self, audio_np: np.ndarray) -> str:
        """Convert raw PCM numpy array to text using faster-whisper."""
        if _whisper is None:
            logger.warn("faster-whisper not installed, returning empty transcript")
            return ""
        try:
            # Run synchronous whisper in thread pool to avoid blocking event loop
            loop = asyncio.get_event_loop()
            segments, _ = await loop.run_in_executor(
                None,
                lambda: _whisper.transcribe(
                    audio_np.astype(np.float32),
                    beam_size=1,
                    language="en",
                )
            )
            return "".join(seg.text for seg in segments).strip()
        except Exception as e:
            logger.error(f"ASR error: {e}")
            return ""

    # ─── LLM ──────────────────────────────────────────────────────────────────
    async def llm_stream(self, text: str) -> AsyncIterator[str]:
        """
        Streaming LLM generation.
        Currently a mock echoing words — replace with the project's LLMEngine.
        """
        from server.systems.llm import LLMEngine  # local import to avoid circular deps
        engine = LLMEngine()
        messages = [
            {"role": "system", "content": "You are Aariya, a warm AI companion. Be concise."},
            {"role": "user", "content": text},
        ]
        try:
            async for token in engine.chat_completion_stream(messages):
                if self._interrupt:
                    return
                yield token
        except Exception as e:
            logger.error(f"LLM stream error: {e}")

    # ─── TTS ──────────────────────────────────────────────────────────────────
    async def tts_stream(
        self, text_stream: AsyncIterator[str]
    ) -> AsyncIterator[bytes]:
        """
        Converts streaming LLM tokens to audio chunks via edge-tts.
        Sentence-buffers before synthesizing to keep speech natural.
        """
        if edge_tts is None:
            logger.warn("edge-tts not installed — yielding silence")
            return

        buffer = ""
        sentence_endings = {".", "!", "?", "\n"}

        async for token in text_stream:
            if self._interrupt:
                return

            buffer += token

            # Synthesize whenever we have a complete sentence
            if any(buffer.strip().endswith(e) for e in sentence_endings):
                sentence = buffer.strip()
                buffer = ""

                try:
                    communicate = edge_tts.Communicate(sentence, _TTS_VOICE)
                    async for audio_data in communicate.stream():
                        if self._interrupt:
                            return
                        if audio_data["type"] == "audio":
                            yield audio_data["data"]
                except Exception as e:
                    logger.error(f"TTS stream error: {e}")

        # Flush remaining buffer
        if buffer.strip() and not self._interrupt:
            try:
                communicate = edge_tts.Communicate(buffer.strip(), _TTS_VOICE)
                async for audio_data in communicate.stream():
                    if not self._interrupt and audio_data["type"] == "audio":
                        yield audio_data["data"]
            except Exception as e:
                logger.error(f"TTS flush error: {e}")

    # ─── Full Pipeline ─────────────────────────────────────────────────────────
    async def process(self, audio_np: np.ndarray) -> AsyncIterator[bytes]:
        """
        Entry point: accepts raw PCM audio, yields TTS audio byte chunks.
        Use with WebRTC by sending each yielded chunk back as an audio frame.
        """
        self._interrupt = False

        text = await self.transcribe(audio_np)

        if not text:
            logger.info("No speech detected in audio frame")
            return

        logger.info(f"ASR transcript: {text!r}")

        text_gen = self.llm_stream(text)

        async for audio_chunk in self.tts_stream(text_gen):
            if self._interrupt:
                break
            yield audio_chunk

    def stop(self):
        """Signal the pipeline to stop at the next safe checkpoint."""
        self._interrupt = True
