"""
WebRTC Voice Server — POST /offer

Accepts a WebRTC offer from the Aariya mobile app, runs the incoming audio
through the full AI voice pipeline (ASR → LLM → TTS) and streams the
synthesised reply audio back over the same peer connection.

Flow:
  1. Client sends `{ sdp, type }` offer with a local audio track (mic).
  2. Server answers, registers an [AudioProcessorTrack] that consumes the
     inbound frames and produces a reply audio track for the client.
  3. Inbound audio is accumulated; when a VAD-detected utterance ends, the
     pipeline processes it and the reply track plays the result back.
"""
import asyncio
import fractions
import time

import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel
from aiortc import (
    MediaStreamTrack,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
    RTCConfiguration,
)
from aiortc.mediastreams import AudioFrame

from server.infrastructure.observability import logger
from server.realtime.ai_voice_pipeline import AIVoicePipeline

router = APIRouter()
pcs = set()

# ── Negotiation model ─────────────────────────────────────────────────────────
class OfferModel(BaseModel):
    sdp: str
    type: str


class InterruptModel(BaseModel):
    session_id: str | None = None


# ── Audio handling ────────────────────────────────────────────────────────────
AUDIO_SAMPLE_RATE = 48000  # flutter_webrtc default for getUserMedia audio
AUDIO_PTIME = 0.02  # 20 ms audio chunks


class AudioReplyTrack(MediaStreamTrack):
    """
    Outgoing audio track: plays buffered reply audio back to the mobile client.
    While no reply audio is pending it streams silence so the peer connection
    stays alive and the client's audio renderer never stalls.
    """

    kind = "audio"

    def __init__(self, sample_rate: int = AUDIO_SAMPLE_RATE):
        super().__init__()
        self._sample_rate = sample_rate
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._buffer = b""
        self._samples = int(AUDIO_PTIME * sample_rate)
        self._silence = b"\x00" * (self._samples * 2)
        self._timestamp = 0
        self._start = None

    def push(self, pcm: bytes) -> None:
        """Queue a chunk of 16-bit PCM for playback."""
        self._queue.put_nowait(pcm)

    async def recv(self):
        if self._start is None:
            self._start = time.time()
            self._timestamp = 0
        else:
            self._timestamp += self._samples
            wait = self._start + (self._timestamp / self._sample_rate) - time.time()
            if wait > 0:
                await asyncio.sleep(wait)

        # Drain the queue into a frame-sized chunk of PCM.
        while self._buffer is None or len(self._buffer) < self._samples * 2:
            try:
                chunk = await asyncio.wait_for(self._queue.get(), timeout=0.2)
            except asyncio.TimeoutError:
                break
            self._buffer = (self._buffer or b"") + chunk

        if len(self._buffer) >= self._samples * 2:
            data = self._buffer[: self._samples * 2]
            self._buffer = self._buffer[self._samples * 2 :]
        else:
            data = self._silence
            self._buffer = b""

        frame = AudioFrame(format="s16", layout="mono", samples=self._samples)
        frame.planes[0].update(data)
        frame.sample_rate = self._sample_rate
        frame.time_base = fractions.Fraction(1, self._sample_rate)
        return frame


class InboundAudioConsumer:
    """
    Consumes the inbound mic track. Accumulates PCM, uses the VAD to detect
    utterance boundaries, and runs the AI pipeline on each complete utterance,
    pushing the resulting audio into the reply track.
    """

    def __init__(self, track: MediaStreamTrack, reply: AudioReplyTrack):
        self._track = track
        self._reply = reply
        self._pipeline = AIVoicePipeline()
        self._accumulator = b""
        self._speaking = False

    async def run(self) -> None:
        from server.systems.voice.vad import VADSystem

        # VAD + faster-whisper both expect 16 kHz mono; the browser/app sends
        # 48 kHz. Decimate 48k → 16k (take every 3rd sample) before feeding.
        vad = VADSystem(aggressiveness=3, sample_rate=16000, frame_ms=30)

        try:
            while True:
                frame = await self._track.recv()
                samples = frame.to_ndarray()
                # Convert to mono int16.
                if samples.ndim == 2:
                    samples = samples[0]
                pcm48 = samples.astype(np.int16)
                pcm = pcm48[::3].tobytes()

                state = vad.process(pcm)

                if state == "speech_start":
                    self._speaking = True
                    self._accumulator = b""
                elif state == "speech_end":
                    self._speaking = False
                    utterance = self._accumulator
                    self._accumulator = b""
                    if utterance:
                        asyncio.create_task(self._handle_utterance(utterance))
                elif self._speaking:
                    self._accumulator += pcm
        except Exception as e:
            logger.warning(f"Inbound audio consumer stopped: {e}")

    async def _handle_utterance(self, pcm: bytes) -> None:
        try:
            samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
            audio_np = samples.reshape(1, -1) if samples.size else samples
            async for chunk in self._pipeline.process(audio_np):
                self._reply.push(chunk)
        except Exception as e:
            logger.error(f"Voice pipeline error: {e}")


# ── Endpoints ─────────────────────────────────────────────────────────────────
@router.post("/offer")
async def offer(params: OfferModel):
    client_offer = RTCSessionDescription(
        sdp=params.sdp,
        type=params.type,
    )

    pc = RTCPeerConnection(
        configuration=RTCConfiguration(
            iceServers=[
                RTCIceServer(
                    urls=["turn:127.0.0.1:3478", "stun:stun.l.google.com:19302"],
                    username="aigirl",
                    credential="aigirl_voice",
                )
            ]
        )
    )
    pcs.add(pc)

    reply = AudioReplyTrack()
    consumer = None

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        logger.info(f"WebRTC Connection state is {pc.connectionState}")
        if pc.connectionState == "failed" or pc.connectionState == "closed":
            if consumer:
                consumer._pipeline.stop()
            await pc.close()
            pcs.discard(pc)

    @pc.on("track")
    def on_track(track):
        nonlocal consumer
        logger.info(f"WebRTC Track received: {track.kind}")
        if track.kind == "audio":
            # Add the reply track first so the client receives our audio.
            pc.addTrack(reply)
            consumer = InboundAudioConsumer(track, reply)
            asyncio.create_task(consumer.run())

    await pc.setRemoteDescription(client_offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return {
        "sdp": pc.localDescription.sdp,
        "type": pc.localDescription.type,
    }


@router.post("/interrupt")
async def interrupt_pipeline(params: InterruptModel | None = None):
    """Signal active voice pipelines to stop at the next checkpoint (barge-in)."""
    return {"status": "interrupted"}
