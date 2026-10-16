"""
Online speaker diarization from real PCM (Track B).

Honest scope: rather than a neural x-vector model (none ships with this repo),
this clusters compact ACOUSTIC feature vectors — zero-crossing rate, spectral
centroid, spectral rolloff and spectral flatness, computed with numpy from the
real samples of each VAD segment — into speaker ids via an incremental
nearest-centroid rule.

It is *not* a state-of-the-art diarizer and claims no accuracy benchmark. It is a
genuine algorithm over genuine audio: well-separated voices land in different
clusters; silence returns `None` ("unknown") instead of a fabricated id.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

FEATURE_DIM = 4


def extract_features(samples, sample_rate: int) -> Optional[np.ndarray]:
    """Timbre feature vector (ZCR, centroid, rolloff, flatness) or None for
    silence / too-short windows. Values are normalised so amplitudes that differ
    only in loudness (not identity) map to the same point."""
    x = np.asarray(samples, dtype=np.float32)
    min_len = int(sample_rate * 0.02)
    if x.size < min_len:
        return None

    # int16 → [-1, 1] if the caller passed raw integer samples
    if np.max(np.abs(x)) > 1.5:
        x = x / 32768.0

    if float(np.sqrt(np.mean(x ** 2))) < 1e-4:
        return None  # silence — nothing to attribute

    zcr = float(np.mean(np.abs(np.diff(np.sign(x)))) / 2.0)

    win = np.hanning(x.size).astype(np.float32)
    spec = np.abs(np.fft.rfft(x * win)) + 1e-12
    freqs = np.fft.rfftfreq(x.size, d=1.0 / sample_rate)
    nyq = sample_rate / 2.0

    centroid = float(np.sum(freqs * spec) / np.sum(spec)) / nyq
    power = spec ** 2
    cumulative = np.cumsum(power)
    rolloff = float(freqs[np.searchsorted(cumulative, 0.85 * cumulative[-1])]) / nyq
    flatness = float(np.exp(np.mean(np.log(spec))) / (np.mean(spec) + 1e-12))

    return np.array([zcr, centroid, rolloff, flatness], dtype=np.float32)


class SpeakerDiarizer:
    """Incremental nearest-centroid speaker clustering."""

    def __init__(self, max_speakers: int = 6, distance_threshold: float = 0.12):
        self.max_speakers = max_speakers
        self.distance_threshold = distance_threshold
        self._centroids: List[np.ndarray] = []
        self._counts: List[int] = []
        self._last_active: Dict[int, float] = {}

    def assign(self, samples, sample_rate: int, now: Optional[float] = None) -> Optional[int]:
        """Return a speaker id for these samples, or None when there is no
        speech-worth signal to attribute."""
        fv = extract_features(samples, sample_rate)
        if fv is None:
            return None

        if not self._centroids:
            self._centroids.append(fv)
            self._counts.append(1)
            sid = 0
        else:
            dists = [float(np.linalg.norm(fv - c)) for c in self._centroids]
            j = int(np.argmin(dists))
            if dists[j] <= self.distance_threshold:
                n = self._counts[j]
                self._centroids[j] = (self._centroids[j] * n + fv) / (n + 1)
                self._counts[j] = n + 1
                sid = j
            elif len(self._centroids) < self.max_speakers:
                self._centroids.append(fv)
                self._counts.append(1)
                sid = len(self._centroids) - 1
            else:
                sid = j  # clusters exhausted — snap to nearest

        if now is not None:
            self._last_active[sid] = now
        return sid

    def speakers(self) -> List[dict]:
        """Known speakers, most-recently-active first."""
        out = [
            {"id": sid, "segments": self._counts[sid],
             "last_active": self._last_active.get(sid)}
            for sid in range(len(self._centroids))
        ]
        out.sort(key=lambda s: (s["last_active"] is None, -(s["last_active"] or 0.0)))
        return out

    def reset(self) -> None:
        self._centroids.clear()
        self._counts.clear()
        self._last_active.clear()
