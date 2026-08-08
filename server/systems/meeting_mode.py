"""
Meeting Mode — Social QoS + Multi-Speaker VAD
─────────────────────────────────────────────
Handles low-interruption logic for multi-user or shared-space environments.

FIXV4 additions over the original stub:
  • SpeakerTracker — infers ambient speaker count from audio energy variance
    across a rolling time window. No dedicated mic array required; works
    from the single-channel audio energy value already available in the
    main WebSocket frame (userAudioStats.energy).
  • report_audio_frame() — called each turn by the WebSocket handler
  • get_ambient_speaker_count() → int heuristic
  • Dynamic direct_address_window scaling: more speakers → longer window
    so Aariya stays in "follow-up mode" longer before going ambient.
"""

from typing import Dict, List, Optional
import time
import math
import collections


# ── Speaker Tracker ────────────────────────────────────────────────────────────

class SpeakerTracker:
    """
    Lightweight single-channel energy-variance heuristic for estimating
    whether ambient speakers are present.

    Logic:
      – In a single-speaker session, audio energy follows a smooth
        voice-activity pattern: on/off with gradual rises/falls.
      – When multiple people are present, energy variance across a window
        is significantly higher (random cross-talk spikes, overlaps).
      – We track variance in a 30-sample rolling window (~30 s at 1 Hz).

    Output:
      1  → likely just the primary user
      2  → probably one ambient speaker
      3+ → small group / meeting room
    """

    WINDOW_SIZE                = 30      # samples
    SINGLE_SPEAKER_VAR_THRESH  = 0.015   # below → 1 speaker
    MULTI_SPEAKER_VAR_THRESH   = 0.045   # above → 3+ speakers

    def __init__(self):
        self._energy_window: collections.deque = collections.deque(
            maxlen=self.WINDOW_SIZE
        )
        self._last_speaker_count: int = 1
        self._last_report_time: float = 0.0

    def report_frame(self, energy: float, vad_active: bool) -> None:
        """
        Record a single audio frame snapshot.
        Call once per WebSocket turn (or once per second from the sensor loop).

        Args:
            energy: normalised audio energy [0.0 – 1.0]
            vad_active: True if VAD thinks the user is speaking
        """
        self._energy_window.append(energy)
        self._last_report_time = time.time()

    def get_speaker_count(self) -> int:
        """
        Estimate number of speakers based on energy variance.
        Returns cached value if window is too small for reliable estimation.
        """
        if len(self._energy_window) < 5:
            return self._last_speaker_count

        energies = list(self._energy_window)
        mean = sum(energies) / len(energies)
        variance = sum((e - mean) ** 2 for e in energies) / len(energies)

        if variance < self.SINGLE_SPEAKER_VAR_THRESH:
            count = 1
        elif variance < self.MULTI_SPEAKER_VAR_THRESH:
            count = 2
        else:
            count = 3

        self._last_speaker_count = count
        return count

    def reset(self) -> None:
        self._energy_window.clear()
        self._last_speaker_count = 1


# ── Meeting Mode ───────────────────────────────────────────────────────────────

class MeetingMode:
    # How much to expand the follow-up window per additional ambient speaker
    WINDOW_SCALE_PER_SPEAKER = 10.0   # seconds

    def __init__(self):
        self.active: bool = False
        self.ai_names: List[str] = ["aariya", "aaria", "arya"]
        self.last_direct_address: float = 0
        self._base_window: float = 30.0       # configurable base
        self.direct_address_window: float = 30.0

        self._speaker_tracker = SpeakerTracker()

    # ── Audio frame reporting (called by WebSocket handler) ────────────────────

    def report_audio_frame(self, energy: float, vad_user: bool) -> None:
        """
        Feed a normalised audio energy sample into the speaker tracker.
        Called once per incoming WebSocket message from main.py.
        """
        self._speaker_tracker.report_frame(energy, vad_user)
        # Dynamically scale address window based on speaker count
        count = self._speaker_tracker.get_speaker_count()
        self.direct_address_window = (
            self._base_window
            + max(0, count - 1) * self.WINDOW_SCALE_PER_SPEAKER
        )

    # ── Speaker count accessor ─────────────────────────────────────────────────

    def get_ambient_speaker_count(self) -> int:
        """Return current estimated speaker count (1 = user only)."""
        return self._speaker_tracker.get_speaker_count()

    # ── Control ───────────────────────────────────────────────────────────────

    def toggle(self, state: Optional[bool] = None) -> bool:
        if state is not None:
            self.active = state
        else:
            self.active = not self.active
        print(f"[MeetingMode] Active: {self.active}")
        return self.active

    def set_base_window(self, seconds: float) -> None:
        """Update the base direct-address window (before speaker scaling)."""
        self._base_window = max(10.0, seconds)
        self.direct_address_window = self._base_window

    def add_name_alias(self, alias: str) -> None:
        """Add an AI name alias to the trigger list."""
        if alias.lower() not in self.ai_names:
            self.ai_names.append(alias.lower())

    def set_name_aliases(self, names: List[str]) -> None:
        """Replace the full alias list."""
        self.ai_names = [n.lower() for n in names if n.strip()]

    # ── Core gate logic ───────────────────────────────────────────────────────

    def should_respond(self, text: str, priority_level: int) -> bool:
        """
        Logic Gate:
        - If not active: always respond (normal behavior)
        - If active:
            - Respond if P0 (Emergency)
            - Respond if direct address found (name mentioned)
            - Respond if within direct address window (follow-up)
            - Else: Suppress/Ambient only
        """
        if not self.active:
            return True

        # P0 Always bypasses
        if priority_level == 0:
            return True

        text_lower = text.lower()

        # 1. Check for Direct Address
        is_direct = any(name in text_lower for name in self.ai_names)
        if is_direct:
            self.last_direct_address = time.time()
            return True

        # 2. Check for Follow-up window (dynamically scaled by speaker count)
        if time.time() - self.last_direct_address < self.direct_address_window:
            return True

        return False

    def get_prompt_modifier(self) -> str:
        """Instructions for the LLM when in meeting mode."""
        if not self.active:
            return ""

        count = self.get_ambient_speaker_count()
        ambient_note = (
            f" You are in a room with approximately {count} speakers."
            if count > 1
            else ""
        )

        return (
            "SYSTEM NOTICE: Meeting Mode is ACTIVE. Be professional and concise. "
            f"Avoid interrupting the ambient flow unless directly engaged.{ambient_note}"
        )

    def get_status(self) -> dict:
        """Full status dict for the REST API."""
        return {
            "active":                 self.active,
            "ai_names":               self.ai_names,
            "speaker_count":          self.get_ambient_speaker_count(),
            "direct_address_window":  self.direct_address_window,
            "base_window":            self._base_window,
            "last_direct_address_ago": (
                round(time.time() - self.last_direct_address, 1)
                if self.last_direct_address > 0 else None
            ),
        }


# ── Singleton ──────────────────────────────────────────────────────────────────
_meeting_manager = MeetingMode()


def get_meeting_mode() -> MeetingMode:
    return _meeting_manager
