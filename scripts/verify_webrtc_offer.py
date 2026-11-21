"""End-to-end verification of POST /offer with REAL media negotiation.

Runs a genuine uvicorn server (device-auth + WebRTC routers) in this process,
pairs a throwaway mobile device against a throwaway SQLite database, then opens
an aiortc peer over real ICE/DTLS/SRTP and streams actual speech (synthesised
with macOS ``say``) at 48 kHz.

It asserts:
  * the credential gate rejects an unauthenticated offer,
  * the answer is a real SDP answer that completes ICE,
  * the server receives the audio track,
  * the server resamples to 16 kHz, runs webrtcvad, and cuts an utterance,
  * the captured PCM is genuine speech (duration + energy), not silence.

Nothing touches ``data/brain_v4.db`` and no credential is reused: the device row
and the database live in a temporary directory that is deleted at the end.

Usage (from the repo root):
    server/.venv/bin/python scripts/verify_webrtc_offer.py
"""

from __future__ import annotations

import asyncio
import fractions
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import List, Optional

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OWNER = "u1"
SAMPLE_RATE = 48000
FRAME_SAMPLES = 960  # 20 ms at 48 kHz


def _fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def _ok(message: str) -> None:
    print(f"  ok  {message}")


def _say_to_pcm(path: Path, text: str) -> np.ndarray:
    """Synthesise real speech with macOS `say`, then read it as int16 PCM."""
    result = subprocess.run(
        ["say", "-o", str(path), "--data-format", "LEI16@48000", text],
        capture_output=True,
    )
    if result.returncode != 0 or not path.exists():
        _fail(f"`say` could not synthesise speech: {result.stderr.decode()}")

    with wave.open(str(path), "rb") as handle:
        if handle.getnchannels() != 1 or handle.getframerate() != SAMPLE_RATE:
            _fail(
                "unexpected speech format: "
                f"{handle.getnchannels()}ch @ {handle.getframerate()}Hz"
            )
        pcm = np.frombuffer(
            handle.readframes(handle.getnframes()), dtype=np.int16
        )
    if pcm.size == 0:
        _fail("synthesised speech is empty")
    return pcm


def main() -> None:
    from server import db as server_db

    workdir = Path(tempfile.mkdtemp(prefix="aariya-webrtc-e2e-"))
    db_path = workdir / "brain_e2e.db"

    # Isolate every write from the real brain database.
    server_db.DB_PATH = str(db_path)

    os.environ["AARIYA_OWNER_ID"] = OWNER
    os.environ["AARIYA_DEVICE_AUTH_REQUIRED"] = "1"
    os.environ["AARIYA_PAIRING_RATE_KEY"] = (
        "e2e-only-pairing-rate-key-0123456789abcdef"
    )
    os.environ.setdefault("WS_SECRET_TOKEN", "e2e-only-ws-secret")
    os.environ.setdefault("LOG_LEVEL", "WARNING")

    server_db.init_db()

    import uvicorn
    from fastapi import FastAPI

    from server.realtime import webrtc_server
    from server.routers.device_auth_router import router as device_auth_router
    from server.systems.security.device_auth import create_pairing_code

    app = FastAPI(title="aariya-webrtc-e2e")
    app.include_router(device_auth_router)
    app.include_router(webrtc_server.router)

    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, log_level="warning", access_log=False
    )
    server = uvicorn.Server(config)

    def _serve() -> None:
        asyncio.run(server.serve())

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()

    deadline = time.time() + 30
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        _fail("server did not start")

    port = server.servers[0].sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    print(f"server: {base} (db={db_path.name})")

    captured: List[webrtc_server.CapturedUtterance] = []
    seen_pcm: List[int] = []

    async def sink(utterance: webrtc_server.CapturedUtterance) -> None:
        captured.append(utterance)

    webrtc_server.set_utterance_sink(sink)

    async def run() -> None:
        import httpx
        from aiortc import (
            MediaStreamTrack,
            RTCConfiguration,
            RTCPeerConnection,
            RTCSessionDescription,
        )
        from aiortc.mediastreams import AudioFrame, MediaStreamError

        class SpeechTrack(MediaStreamTrack):
            kind = "audio"

            def __init__(self, pcm: np.ndarray):
                super().__init__()
                self._pcm = pcm
                self._offset = 0
                self._start: Optional[float] = None
                self._timestamp = 0

            async def recv(self) -> AudioFrame:
                if self._start is None:
                    self._start = time.time()
                self._timestamp += FRAME_SAMPLES
                wait = self._start + (self._timestamp / SAMPLE_RATE) - time.time()
                if wait > 0:
                    await asyncio.sleep(wait)

                chunk = self._pcm[self._offset : self._offset + FRAME_SAMPLES]
                self._offset += FRAME_SAMPLES
                if chunk.size < FRAME_SAMPLES:  # pad the tail with silence
                    chunk = np.pad(chunk, (0, FRAME_SAMPLES - chunk.size))
                seen_pcm.append(int(np.max(np.abs(chunk))))

                frame = AudioFrame(
                    format="s16", layout="mono", samples=FRAME_SAMPLES
                )
                frame.planes[0].update(chunk.astype(np.int16).tobytes())
                frame.sample_rate = SAMPLE_RATE
                frame.time_base = fractions.Fraction(1, SAMPLE_RATE)
                return frame

        transport = httpx.Client(timeout=20.0, base_url=base)

        # 1) Unauthenticated offer must be refused outright.
        unauthenticated = transport.post("/offer", json={"sdp": "v=0", "type": "offer"})
        if unauthenticated.status_code != 401:
            _fail(
                "unauthenticated /offer returned "
                f"{unauthenticated.status_code}, expected 401"
            )
        _ok("unauthenticated /offer rejected (401)")

        # 2) Pair a throwaway mobile device.
        code = create_pairing_code(role="mobile")
        enroll = transport.post(
            "/api/auth/device/enroll",
            json={"pairing_code": code, "label": "e2e-phone", "platform": "ios"},
        )
        if enroll.status_code != 200:
            _fail(f"enrollment failed: {enroll.status_code} {enroll.text}")
        credential = enroll.json()["credential"]
        headers = {"Authorization": f"Bearer {credential}"}
        _ok(f"paired throwaway device {enroll.json()['device_id']}")

        pcm = _say_to_pcm(workdir / "speech.wav", "Hello Aariya, this is a real audio test.")
        speech_seconds = pcm.size / SAMPLE_RATE
        print(f"speech: {speech_seconds:.2f}s at 48 kHz")
        if not np.any(pcm):
            _fail("synthesised speech is silent")

        pc = RTCPeerConnection(
            configuration=RTCConfiguration(iceServers=[])
        )
        received_tracks: List[str] = []
        remote_audio: List[int] = []
        connected = asyncio.Event()

        @pc.on("track")
        def on_track(track):
            received_tracks.append(track.kind)

            @track.on("ended")
            def on_ended():
                pass

        @pc.on("connectionstatechange")
        def on_state():
            print(f"client peer state: {pc.connectionState}")
            if pc.connectionState == "connected":
                connected.set()

        pc.addTrack(SpeechTrack(pcm))

        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)

        response = transport.post(
            "/offer",
            json={"sdp": pc.localDescription.sdp, "type": "offer"},
            headers=headers,
        )
        if response.status_code != 200:
            _fail(f"/offer failed: {response.status_code} {response.text}")
        body = response.json()
        if body.get("type") != "answer" or not str(body.get("sdp", "")).startswith("v=0"):
            _fail(f"/offer returned a non-answer: {body}")
        session_id = body.get("session_id")
        _ok(f"/offer answered with a real SDP ({len(body['sdp'])} chars, {session_id})")
        if os.getenv("AARIYA_E2E_DEBUG"):
            directions = [
                line
                for line in body["sdp"].splitlines()
                if line.startswith(("m=", "a=send", "a=recv", "a=inactive"))
            ]
            print("answer media:", directions)

        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=body["sdp"], type=body["type"])
        )

        try:
            await asyncio.wait_for(connected.wait(), timeout=20)
        except asyncio.TimeoutError:
            _fail(f"peer never connected (state={pc.connectionState})")
        _ok("ICE/DTLS connected with the real server")

        # 3) Stream the speech, then trailing silence to close the utterance.
        await asyncio.sleep(speech_seconds + 1.5)

        if os.getenv("AARIYA_E2E_DEBUG"):
            reports = await pc.getStats()
            for report in reports.values():
                if report.type in ("outbound-rtp", "inbound-rtp"):
                    print(
                        f"stats {report.type}: "
                        f"packets={getattr(report, 'packetsSent', getattr(report, 'packetsReceived', '?'))}"
                    )

        if "audio" not in received_tracks:
            _fail("client never received the server's audio track")
        _ok("server returned an audio track (reply slot present)")

        session = webrtc_server._sessions.get(session_id)
        if session is None or session.consumer is None:
            _fail("server did not attach an inbound audio consumer")
        _ok("server attached its VAD consumer to the phone's track")

        deadline_at = time.time() + 10
        while not captured and time.time() < deadline_at:
            await asyncio.sleep(0.1)

        if not captured:
            peak = max(seen_pcm) if seen_pcm else 0
            _fail(
                "no utterance captured (frames sent="
                f"{len(seen_pcm)}, peak={peak})"
            )

        utterance = captured[0]
        samples = np.frombuffer(utterance.pcm, dtype=np.int16)
        peak = int(np.max(np.abs(samples))) if samples.size else 0
        rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) if samples.size else 0.0

        if utterance.sample_rate != webrtc_server.CAPTURE_SAMPLE_RATE:
            _fail(f"utterance rate {utterance.sample_rate} != 16000")
        if utterance.duration_seconds < 0.5:
            _fail(f"utterance too short: {utterance.duration_seconds:.2f}s")
        if peak < 500 or rms < 50:
            _fail(f"captured PCM is not real speech (peak={peak}, rms={rms:.1f})")

        _ok(
            f"captured {utterance.duration_seconds:.2f}s of real 16 kHz speech "
            f"(peak={peak}, rms={rms:.1f})"
        )

        # 4) Real barge-in clears buffered speech and reports the session.
        interrupt = transport.post("/interrupt", headers=headers)
        if interrupt.status_code != 200:
            _fail(f"/interrupt failed: {interrupt.status_code} {interrupt.text}")
        if interrupt.json().get("sessions") != 1:
            _fail(f"/interrupt saw {interrupt.json().get('sessions')} sessions")
        _ok("/interrupt reached this device's live session")

        await pc.close()
        deadline_at = time.time() + 10
        while session_id in webrtc_server._sessions and time.time() < deadline_at:
            await asyncio.sleep(0.1)
        if session_id in webrtc_server._sessions:
            _fail("server did not release the session after the client closed")
        _ok("server released the session after disconnect")

        transport.close()

    try:
        asyncio.run(run())
    finally:
        webrtc_server.set_utterance_sink(None)
        server.should_exit = True
        thread.join(timeout=15)
        shutil.rmtree(workdir, ignore_errors=True)

    print("PASS: real WebRTC negotiation + authenticated capture verified")


if __name__ == "__main__":
    main()
