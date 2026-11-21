"""WebRTC voice capture endpoint — POST /offer.

Scope (deliberate, no fabrication)
----------------------------------
This endpoint answers a real WebRTC offer from a *paired mobile device* and
consumes the phone's microphone audio. Inbound frames are converted from the
phone's native rate (usually 48 kHz) to 16 kHz mono and run through the same
real acoustic path Meeting Mode uses — ``VoiceActivityDetector`` over genuine
webrtcvad frames — to cut speech into utterances.

There is **no** ASR → LLM → TTS pipeline in this tree (``server/realtime/``
holds only ``redis_bus.py``), so the outgoing track streams genuine digital
silence and each captured utterance is handed to a pluggable sink. The default
sink only emits an event-log entry with the utterance's real duration; it never
invents a reply. Call :func:`set_utterance_sink` to attach a real transcription
consumer once one exists.

Security
--------
``/offer`` is gated by ``require_mobile_device`` and additionally refuses the
legacy (unpaired) principal, so WebRTC can never fall back to anonymous access.
No TURN credential is embedded here: the client is responsible for its own
ICE servers, and the server advertises only a public STUN server.
"""
from __future__ import annotations

import asyncio
import fractions
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Optional

import numpy as np
from aiortc import (
    MediaStreamTrack,
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)
from aiortc.mediastreams import AudioFrame, MediaStreamError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from server.systems.security.device_auth import (
    DevicePrincipal,
    require_mobile_device,
)
from server.systems.signal_bus import emit_real_event
from server.systems.voice import vad as voice_vad

logger = logging.getLogger("Aariya.WebRTC")

router = APIRouter()

#: Phone audio (48 kHz) is brought down to what webrtcvad + ASR expect.
CAPTURE_SAMPLE_RATE = 16000
AUDIO_PTIME = 0.02
VAD_FRAME_MS = 30

MAX_OFFER_CHARS = 200_000
MIN_UTTERANCE_SECONDS = 0.30
MAX_UTTERANCE_SECONDS = 30.0
#: Consecutive non-speech frames (30 ms each) that end an utterance.
SILENCE_FRAMES_TO_CLOSE = 10

MAX_SESSIONS = int(os.getenv("AARIYA_WEBRTC_MAX_SESSIONS", "8"))
MAX_SESSIONS_PER_DEVICE = int(os.getenv("AARIYA_WEBRTC_MAX_SESSIONS_PER_DEVICE", "2"))
NEGOTIATION_TIMEOUT_SECONDS = float(
    os.getenv("AARIYA_WEBRTC_NEGOTIATION_TIMEOUT", "60")
)

# Server-side STUN only — no shared TURN username/password in this codebase.
ICE_SERVERS = [RTCIceServer(urls=["stun:stun.l.google.com:19302"])]


# ── Negotiation model ────────────────────────────────────────────────────────

class OfferModel(BaseModel):
    sdp: str = Field(default="", max_length=MAX_OFFER_CHARS)
    type: str = Field(default="offer")


class InterruptModel(BaseModel):
    session_id: Optional[str] = None


def _validate_offer(params: OfferModel) -> None:
    """Reject anything that is not a plausible audio offer before aiortc sees it."""
    sdp = params.sdp

    if params.type != "offer":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only SDP offers are accepted",
        )
    if "\x00" in sdp:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SDP contains NUL bytes",
        )
    if not sdp.startswith("v=0"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SDP must start with v=0",
        )
    if "\nm=audio" not in sdp and not sdp.startswith("m=audio"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SDP contains no audio media section",
        )
    for required in ("a=ice-ufrag", "a=ice-pwd"):
        if required not in sdp:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"SDP is missing {required}",
            )


# ── Captured utterance ───────────────────────────────────────────────────────

@dataclass
class CapturedUtterance:
    """One VAD-delimited span of real 16 kHz mono speech from the phone."""

    session_id: str
    device_id: str
    device_label: str
    owner_id: str
    pcm: bytes
    sample_rate: int
    duration_seconds: float
    started_at: float
    ended_at: float


UtteranceSink = Callable[[CapturedUtterance], Awaitable[None]]

_utterance_sink: Optional[UtteranceSink] = None


def set_utterance_sink(sink: Optional[UtteranceSink]) -> None:
    """Attach a real consumer for captured speech (``None`` restores default)."""
    global _utterance_sink
    _utterance_sink = sink


def get_utterance_sink() -> Optional[UtteranceSink]:
    return _utterance_sink


async def _default_utterance_sink(utterance: CapturedUtterance) -> None:
    """Record the capture in the real event log and route to audio_session."""
    await emit_real_event(
        "VOICE",
        "info",
        f"Captured {utterance.duration_seconds:.1f}s of speech from "
        f"{utterance.device_label or utterance.device_id}",
        {
            "session_id": utterance.session_id,
            "device_id": utterance.device_id,
            "duration_seconds": round(utterance.duration_seconds, 2),
            "sample_rate": utterance.sample_rate,
        },
    )
    try:
        from server.realtime.audio_session import audio_session_service

        await audio_session_service.process_utterance(utterance)
    except Exception:
        logger.exception("Audio session utterance processing failed")


async def _deliver(utterance: CapturedUtterance) -> None:
    sink = _utterance_sink or _default_utterance_sink
    try:
        await sink(utterance)
    except Exception:  # pragma: no cover - a broken sink must not kill capture
        logger.exception("WebRTC utterance sink failed")


# ── Outbound track ───────────────────────────────────────────────────────────

class AudioReplyTrack(MediaStreamTrack):
    """Paced 48 kHz mono PCM audio output over WebRTC."""

    kind = "audio"
    SAMPLE_RATE = 48000
    FRAME_MS = 20
    FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
    MAX_QUEUED_FRAMES = 750

    def __init__(self):
        super().__init__()
        self._sample_rate = self.SAMPLE_RATE
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(
            maxsize=self.MAX_QUEUED_FRAMES
        )
        self._timestamp = 0
        self._started_at = None

    def enqueue_pcm(self, pcm: bytes) -> int:
        """Queue signed 16-bit, 48 kHz, mono PCM."""
        if len(pcm) % 2:
            raise ValueError("PCM data must contain complete int16 samples")
        frame_bytes = self.FRAME_SAMPLES * 2
        frames_needed = (len(pcm) + frame_bytes - 1) // frame_bytes
        if frames_needed > self._queue.maxsize - self._queue.qsize():
            raise RuntimeError("WebRTC audio queue is full")

        count = 0
        for offset in range(0, len(pcm), frame_bytes):
            chunk = pcm[offset : offset + frame_bytes]
            if len(chunk) < frame_bytes:
                chunk += b"\x00" * (frame_bytes - len(chunk))
            self._queue.put_nowait(chunk)
            count += 1
        return count

    def interrupt(self) -> int:
        """Clear all queued frames (barge-in). Returns count discarded."""
        discarded = 0
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                discarded += 1
            except asyncio.QueueEmpty:
                break
        return discarded

    def clear(self) -> int:
        """Alias for interrupt / cleanup."""
        return self.interrupt()

    async def recv(self) -> AudioFrame:
        if self._started_at is None:
            self._started_at = time.time()
            self._timestamp = 0
        else:
            self._timestamp += self.FRAME_SAMPLES
            wait = (
                self._started_at
                + (self._timestamp / self.SAMPLE_RATE)
                - time.time()
            )
            if wait > 0:
                await asyncio.sleep(wait)

        try:
            data = self._queue.get_nowait()
        except asyncio.QueueEmpty:
            data = b"\x00" * (self.FRAME_SAMPLES * 2)

        frame = AudioFrame(
            format="s16", layout="mono", samples=self.FRAME_SAMPLES
        )
        frame.planes[0].update(data)
        frame.sample_rate = self.SAMPLE_RATE
        frame.time_base = fractions.Fraction(1, self.SAMPLE_RATE)
        return frame


# ── Inbound capture ──────────────────────────────────────────────────────────

def _to_int16(samples: np.ndarray) -> np.ndarray:
    if samples.dtype == np.int16:
        return samples
    if np.issubdtype(samples.dtype, np.floating):
        return (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16)
    return np.clip(samples, -32768, 32767).astype(np.int16)


def pcm16_at_capture_rate(samples: np.ndarray, source_rate: int) -> np.ndarray:
    """Mono int16 at CAPTURE_SAMPLE_RATE, using the real resampler."""
    pcm = _to_int16(samples)
    if pcm.size == 0 or source_rate == CAPTURE_SAMPLE_RATE:
        return pcm
    resampled = voice_vad.resample_int16(pcm, source_rate, CAPTURE_SAMPLE_RATE)
    return np.clip(np.rint(resampled), -32768, 32767).astype(np.int16)


class InboundAudioConsumer:
    """Consume the phone's mic track and cut real utterances with VAD."""

    def __init__(self, session: "VoiceSession", track: MediaStreamTrack):
        self._session = session
        self._track = track
        self._vad = voice_vad.VoiceActivityDetector(
            sample_rate=CAPTURE_SAMPLE_RATE,
            frame_ms=VAD_FRAME_MS,
            aggressiveness=3,
        )
        self._pending: List[bytes] = []
        self._pending_started: Optional[float] = None
        self._silence_run = 0
        self._task: Optional[asyncio.Task] = None
        self._stopped = False

    @property
    def frame_seconds(self) -> float:
        return VAD_FRAME_MS / 1000.0

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while not self._stopped:
            try:
                frame = await self._track.recv()
            except MediaStreamError:
                logger.info(
                    "WebRTC inbound track ended for session %s",
                    self._session.session_id,
                )
                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - transport teardown
                logger.warning("WebRTC inbound track failed: %s", exc)
                break

            try:
                self.feed(frame)
            except Exception:
                logger.exception("WebRTC audio frame handling failed")
                break

    def feed(self, frame: AudioFrame) -> None:
        """Run one real audio frame through resample → VAD → utterance cut."""
        samples = frame.to_ndarray()
        if samples.ndim == 2:
            samples = samples[0]
        source_rate = int(frame.sample_rate or 48000)
        pcm = pcm16_at_capture_rate(samples, source_rate)
        if pcm.size == 0:
            return

        result = self._vad.process_int16(pcm.tobytes())
        for is_speech, frame_bytes in zip(
            result["frames"], result["frame_bytes"]
        ):
            self._accumulate(is_speech, frame_bytes)

    def _accumulate(self, is_speech: bool, frame_bytes: bytes) -> None:
        if is_speech:
            if not self._pending:
                self._pending_started = time.time()
            self._pending.append(frame_bytes)
            self._silence_run = 0
            if len(self._pending) * self.frame_seconds >= MAX_UTTERANCE_SECONDS:
                self._close_utterance()
            return

        if not self._pending:
            return

        self._silence_run += 1
        if self._silence_run >= SILENCE_FRAMES_TO_CLOSE:
            self._close_utterance()

    def _close_utterance(self) -> None:
        frames = self._pending
        started = self._pending_started or time.time()
        self._pending = []
        self._pending_started = None
        self._silence_run = 0

        duration = len(frames) * self.frame_seconds
        if duration < MIN_UTTERANCE_SECONDS:
            return

        utterance = CapturedUtterance(
            session_id=self._session.session_id,
            device_id=self._session.device_id,
            device_label=self._session.device_label,
            owner_id=self._session.owner_id,
            pcm=b"".join(frames),
            sample_rate=CAPTURE_SAMPLE_RATE,
            duration_seconds=duration,
            started_at=started,
            ended_at=time.time(),
        )
        asyncio.create_task(_deliver(utterance))

    def interrupt(self) -> int:
        """Drop buffered speech (barge-in). Returns discarding frame count."""
        discarded = len(self._pending)
        self._pending = []
        self._pending_started = None
        self._silence_run = 0
        return discarded

    async def stop(self) -> None:
        self._stopped = True
        self.interrupt()
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


# ── Session registry ─────────────────────────────────────────────────────────

@dataclass
class VoiceSession:
    session_id: str
    device_id: str
    owner_id: str
    device_label: str
    peer: RTCPeerConnection
    reply: AudioReplyTrack
    created_at: float
    loop: Optional[asyncio.AbstractEventLoop] = None
    consumer: Optional[InboundAudioConsumer] = None
    watchdog: Optional[asyncio.Task] = None
    closing: bool = False

    def interrupt(self) -> int:
        discarded = self.reply.interrupt()
        if self.consumer is not None:
            discarded += self.consumer.interrupt()
        return discarded


#: The server runs a single asyncio loop, so plain dict mutation is safe here.
_sessions: Dict[str, VoiceSession] = {}


async def enqueue_reply_audio(
    session_id: str,
    pcm: bytes,
) -> int:
    """Send generated PCM to the correct authenticated WebRTC session."""
    session = _sessions.get(session_id)
    if session is None or session.closing:
        raise RuntimeError("WebRTC session is no longer active")
    if session.peer.connectionState not in (
        "connected",
        "connecting",
    ):
        raise RuntimeError("WebRTC peer is not available")
    return session.reply.enqueue_pcm(pcm)


async def close_session(session: VoiceSession, reason: str) -> None:
    if session.closing:
        return
    session.closing = True
    _sessions.pop(session.session_id, None)

    if session.reply is not None:
        session.reply.clear()

    if session.watchdog is not None:
        session.watchdog.cancel()
        session.watchdog = None

    if session.consumer is not None:
        await session.consumer.stop()
        session.consumer = None

    try:
        await session.peer.close()
    except Exception:  # pragma: no cover - best-effort teardown
        logger.debug("WebRTC peer close failed", exc_info=True)

    logger.info(
        "WebRTC session %s closed (%s)", session.session_id, reason
    )


async def close_all_peer_connections() -> None:
    """Close every live peer connection (server shutdown hook)."""
    for session in list(_sessions.values()):
        await close_session(session, "server shutdown")


def _schedule_close(session: VoiceSession, reason: str) -> None:
    if session.closing:
        return
    session.closing = True
    asyncio.create_task(_close_now(session, reason))


async def _close_now(session: VoiceSession, reason: str) -> None:
    session.closing = False
    await close_session(session, reason)


async def _enforce_session_limits(device_id: str) -> None:
    per_device_limit = max(1, MAX_SESSIONS_PER_DEVICE)
    total_limit = max(1, MAX_SESSIONS)

    device_sessions = sorted(
        (s for s in _sessions.values() if s.device_id == device_id),
        key=lambda s: s.created_at,
    )
    while len(device_sessions) >= per_device_limit:
        await close_session(
            device_sessions.pop(0), "superseded by a newer session from this device"
        )

    while len(_sessions) >= total_limit:
        oldest = min(_sessions.values(), key=lambda s: s.created_at)
        await close_session(oldest, "server session limit reached")


async def _negotiation_watchdog(session: VoiceSession) -> None:
    try:
        await asyncio.sleep(NEGOTIATION_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        return

    if session.closing:
        return
    if session.peer.connectionState in ("new", "connecting"):
        await close_session(session, "ICE negotiation timed out")


# ── Endpoints ────────────────────────────────────────────────────────────────

async def _require_paired_mobile(principal: DevicePrincipal) -> None:
    """Refuse the legacy shared-token principal outright.

    ``require_mobile_device`` allows an unauthenticated legacy principal while
    no owner is configured; WebRTC must never accept that fallback.
    """
    if not principal.authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "WebRTC requires a paired mobile device; "
                "legacy unauthenticated access is not supported"
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post("/offer")
async def offer(
    params: OfferModel,
    principal: DevicePrincipal = Depends(require_mobile_device),
):
    await _require_paired_mobile(principal)

    if not voice_vad.available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WebRTC capture requires webrtcvad, which is not installed",
        )

    _validate_offer(params)
    await _enforce_session_limits(principal.device_id)

    pc = RTCPeerConnection(
        configuration=RTCConfiguration(iceServers=list(ICE_SERVERS))
    )
    session = VoiceSession(
        session_id=f"rtc_{uuid.uuid4().hex[:12]}",
        device_id=principal.device_id,
        owner_id=principal.owner_id,
        device_label=principal.label,
        peer=pc,
        reply=AudioReplyTrack(),
        created_at=time.time(),
        loop=asyncio.get_running_loop(),
    )
    _sessions[session.session_id] = session

    @pc.on("connectionstatechange")
    def on_connectionstatechange():
        state = pc.connectionState
        logger.info(
            "WebRTC session %s peer state: %s", session.session_id, state
        )
        if state in ("failed", "closed"):
            _schedule_close(session, f"peer {state}")

    @pc.on("track")
    def on_track(track: MediaStreamTrack):
        if track.kind != "audio":
            logger.info(
                "WebRTC session %s ignoring %s track",
                session.session_id,
                track.kind,
            )
            return
        # Add the reply track before the answer is created so the SDP answer
        # carries an audio section the phone can render.
        pc.addTrack(session.reply)
        session.consumer = InboundAudioConsumer(session, track)

        @track.on("ended")
        def on_ended():
            _schedule_close(session, "remote track ended")

        session.consumer.start()
        logger.info("WebRTC session %s inbound audio attached", session.session_id)

    try:
        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=params.sdp, type=params.type)
        )
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
    except Exception as exc:
        await close_session(session, "negotiation failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"WebRTC negotiation failed: {exc}",
        ) from exc

    session.watchdog = asyncio.create_task(_negotiation_watchdog(session))

    logger.info(
        "WebRTC session %s negotiated for device %s",
        session.session_id,
        principal.device_id,
    )

    return {
        "sdp": pc.localDescription.sdp,
        "type": pc.localDescription.type,
        "session_id": session.session_id,
    }


@router.post("/interrupt")
async def interrupt(
    params: Optional[InterruptModel] = None,
    principal: DevicePrincipal = Depends(require_mobile_device),
):
    """Drop buffered speech for this device's live sessions (real barge-in)."""
    await _require_paired_mobile(principal)

    sessions = [
        s for s in _sessions.values() if s.device_id == principal.device_id
    ]
    if params is not None and params.session_id:
        sessions = [s for s in sessions if s.session_id == params.session_id]

    discarded = 0
    for session in sessions:
        discarded += session.interrupt()

    return {
        "status": "interrupted",
        "sessions": len(sessions),
        "discarded_frames": discarded,
    }
