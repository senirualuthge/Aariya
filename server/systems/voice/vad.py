"""
Real voice-activity detection (Track B).

A thin wrapper over `webrtcvad`, which classifies 16-bit mono PCM at
8/16/32/48 kHz in 10/20/30 ms frames. Clients send arbitrary chunk sizes and
sample rates, so `VoiceActivityDetector` buffers incoming PCM and slices whole
frames internally — it never fabricates a signal, it only judges the real audio
it is handed.

If `webrtcvad` is unavailable the module still imports (`available` is False) and
`MeetingMode` falls back to its energy-variance heuristic.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

import numpy as np

try:  # pragma: no cover - exercised implicitly by both branches
    import webrtcvad as _webrtcvad
    available = True
except Exception:  # pragma: no cover
    _webrtcvad = None
    available = False

SUPPORTED_RATES = (8000, 16000, 32000, 48000)
FRAME_MS = (10, 20, 30)


# ── PCM helpers ────────────────────────────────────────────────────────────────

def resample_int16(
    samples: Sequence[float] | np.ndarray, src_rate: int, dst_rate: int
) -> np.ndarray:
    """Linear-interpolation resample of a float/int sample sequence.

    A genuine (if simple) resampler so a browser's native 44.1/48 kHz stream can
    be brought to a webrtcvad-supported rate. Returns float32 in the input's scale.
    """
    x = np.asarray(samples, dtype=np.float32)
    if src_rate == dst_rate or x.size == 0:
        return x
    n_dst = max(1, round(x.size * float(dst_rate) / float(src_rate)))
    src_idx = np.linspace(0.0, x.size - 1, num=n_dst, dtype=np.float32)
    lo = np.floor(src_idx).astype(np.int64)
    hi = np.minimum(lo + 1, x.size - 1)
    frac = src_idx - lo
    return (x[lo] * (1.0 - frac) + x[hi] * frac).astype(np.float32)


def float_to_int16(samples: Sequence[float] | np.ndarray) -> np.ndarray:
    """Clamp float samples in [-1, 1] to int16 (real quantisation)."""
    x = np.asarray(samples, dtype=np.float32)
    x = np.clip(x, -1.0, 1.0)
    return (x * 32767.0).astype(np.int16)


# ── VAD ────────────────────────────────────────────────────────────────────────

class VoiceActivityDetector:
    """Frame-buffered webrtcvad wrapper."""

    def __init__(self, sample_rate: int = 16000, frame_ms: int = 20,
                 aggressiveness: int = 2):
        if not available or _webrtcvad is None:
            raise RuntimeError("webrtcvad is not installed")
        if sample_rate not in SUPPORTED_RATES:
            raise ValueError(f"sample_rate must be one of {SUPPORTED_RATES}")
        if frame_ms not in FRAME_MS:
            raise ValueError(f"frame_ms must be one of {FRAME_MS}")
        if not 0 <= aggressiveness <= 3:
            raise ValueError("aggressiveness must be 0..3")

        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.frame_samples = int(sample_rate * frame_ms / 1000)
        self._frame_bytes = self.frame_samples * 2
        self._vad = _webrtcvad.Vad(aggressiveness)
        self._buf = bytearray()

    def process_int16(self, pcm: bytes) -> dict:
        """Feed int16 mono PCM bytes; return per-frame speech flags + ratio.

        Leftover bytes (< one frame) are buffered for the next call so framing
        stays exact across chunk boundaries.
        """
        if pcm:
            self._buf.extend(pcm)

        frames: List[bool] = []
        frame_bytes_list: List[bytes] = []
        while len(self._buf) >= self._frame_bytes:
            frame = bytes(self._buf[:self._frame_bytes])
            del self._buf[:self._frame_bytes]
            frame_bytes_list.append(frame)
            frames.append(bool(self._vad.is_speech(frame, self.sample_rate)))

        total = len(frames)
        speech = sum(1 for f in frames if f)
        return {
            "total_frames": total,
            "speech_frames": speech,
            "speech_ratio": (speech / total) if total else 0.0,
            "frames": frames,
            "frame_bytes": frame_bytes_list,
        }

    def reset(self) -> None:
        self._buf.clear()


def speech_segments(frames: Sequence[bool], frame_samples: int,
                    min_frames: int = 3) -> List[tuple]:
    """Group consecutive speech frames into (start_sample, end_sample) spans.

    Segments shorter than `min_frames` are dropped as blips.
    """
    segments: List[tuple] = []
    start: Optional[int] = None
    for i, is_speech in enumerate(frames):
        if is_speech and start is None:
            start = i
        elif not is_speech and start is not None:
            if (i - start) >= min_frames:
                segments.append((start * frame_samples, i * frame_samples))
            start = None
    if start is not None and (len(frames) - start) >= min_frames:
        segments.append((start * frame_samples, len(frames) * frame_samples))
    return segments
