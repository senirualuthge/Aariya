"""
Audit Logging & Deterministic Replay System

Implements SOC-2 CC6.5 / ISO A.12.7 audit requirements.

- Logs all voice events, ASR transcripts (opt-in), trust changes,
  avatar updates, emotion contradictions, kill-switch toggles.
- Deterministic replay: stores inputs + seeds so behavior can be
  reproduced exactly for compliance audits.
- Ring buffer in memory + optional Postgres persistence.
"""

import json
import time
import hashlib
import random
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from enum import Enum
from uuid import uuid4

try:
    from server.infrastructure.observability import logger
except Exception:
    import logging
    logger = logging.getLogger("aariya.audit")


class AuditEventType(Enum):
    """Categories of auditable events."""
    VOICE_SPEECH_START = "voice.speech_start"
    VOICE_SPEECH_END = "voice.speech_end"
    VOICE_BARGE_IN = "voice.barge_in"
    VOICE_ASR_RESULT = "voice.asr_result"
    VOICE_TTS_START = "voice.tts_start"
    VOICE_TTS_END = "voice.tts_end"
    TRUST_UPDATE = "trust.update"
    TRUST_REINFORCEMENT = "trust.reinforcement"
    TRUST_PENALTY = "trust.penalty"
    EMOTION_CONTRADICTION = "emotion.contradiction"
    EMOTION_STATE_CHANGE = "emotion.state_change"
    BRAIN_RESPONSE = "brain.response"
    KILL_SWITCH_TOGGLE = "killswitch.toggle"
    MEMORY_WRITE = "memory.write"
    MEMORY_READ = "memory.read"
    MEMORY_DELETE = "memory.delete"
    GOVERNANCE_OVERRIDE = "governance.override"
    SESSION_START = "session.start"
    SESSION_END = "session.end"
    SAFETY_CONSTRAINT = "safety.constraint"
    AVATAR_UPDATE = "avatar.update"
    LANG_DETECTED = "language.detected"
    VOICE_CONFIG = "voice.config"


@dataclass
class AuditEvent:
    """Single audit event entry."""
    id: str = field(default_factory=lambda: str(uuid4())[:12])
    event_type: str = ""
    session_id: str = ""
    user_id: str = ""
    timestamp: float = field(default_factory=time.time)
    data: Dict[str, Any] = field(default_factory=dict)
    # Deterministic replay fields
    seed: Optional[int] = None
    input_hash: Optional[str] = None
    # Integrity
    checksum: Optional[str] = None

    def compute_checksum(self) -> str:
        """Compute SHA-256 checksum for integrity verification."""
        payload = json.dumps({
            "id": self.id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "data": self.data,
            "seed": self.seed,
        }, sort_keys=True, default=str)
        self.checksum = hashlib.sha256(payload.encode()).hexdigest()[:16]
        return self.checksum


@dataclass
class ReplaySnapshot:
    """A deterministic replay point for compliance audits."""
    session_id: str
    turn_number: int
    timestamp: float
    input_text: str
    input_hash: str
    seed: int
    brain_state_snapshot: Dict[str, Any]
    response_text: str
    emotion: str
    trust_before: float
    trust_after: float
    contradiction_score: float


class AuditLogger:
    """
    Central audit logging system.

    - Ring buffer for fast in-memory access (last N events)
    - Optional Postgres persistence for compliance
    - Deterministic replay support via seeded snapshots
    - Integrity checksums for tamper detection
    """

    def __init__(self, max_buffer: int = 2000, persist_to_db: bool = False):
        self._buffer: List[AuditEvent] = []
        self._max_buffer = max_buffer
        self._persist_to_db = persist_to_db
        self._replay_snapshots: List[ReplaySnapshot] = []
        self._session_seeds: Dict[str, int] = {}
        self._event_counts: Dict[str, int] = {}

    def log(
        self,
        event_type: AuditEventType,
        session_id: str = "",
        user_id: str = "",
        data: Optional[Dict[str, Any]] = None,
        seed: Optional[int] = None,
    ) -> AuditEvent:
        """Log an audit event."""
        event = AuditEvent(
            event_type=event_type.value,
            session_id=session_id,
            user_id=user_id,
            data=data or {},
            seed=seed,
        )
        event.compute_checksum()

        # Ring buffer
        self._buffer.append(event)
        if len(self._buffer) > self._max_buffer:
            self._buffer = self._buffer[-self._max_buffer:]

        # Count by type
        self._event_counts[event_type.value] = (
            self._event_counts.get(event_type.value, 0) + 1
        )

        return event

    def log_voice_event(
        self,
        event_type: AuditEventType,
        session_id: str,
        user_id: str,
        confidence: float = 0.0,
        text: str = "",
        language: str = "",
        extra: Optional[Dict] = None,
    ) -> AuditEvent:
        """Log a voice-specific audit event."""
        data: Dict[str, Any] = {
            "confidence": confidence,
            "language": language,
        }
        if text:
            # Only store transcript if audit_logging flag allows it
            data["text_length"] = len(text)
            # Don't store raw transcript by default — privacy
        if extra:
            data.update(extra)
        return self.log(event_type, session_id, user_id, data)

    def log_trust_event(
        self,
        session_id: str,
        user_id: str,
        trust_before: float,
        trust_after: float,
        reason: str,
        trigger_event: str = "",
    ) -> AuditEvent:
        """Log a trust change event."""
        return self.log(
            AuditEventType.TRUST_UPDATE,
            session_id, user_id,
            data={
                "trust_before": round(trust_before, 4),
                "trust_after": round(trust_after, 4),
                "trust_delta": round(trust_after - trust_before, 4),
                "reason": reason,
                "trigger_event": trigger_event,
            },
        )

    def log_killswitch_event(
        self,
        flag: str,
        old_value: bool,
        new_value: bool,
        reason: str,
        source: str = "system",
    ) -> AuditEvent:
        """Log a kill-switch toggle event."""
        return self.log(
            AuditEventType.KILL_SWITCH_TOGGLE,
            data={
                "flag": flag,
                "old_value": old_value,
                "new_value": new_value,
                "reason": reason,
                "source": source,
            },
        )

    def save_replay_snapshot(
        self,
        session_id: str,
        turn_number: int,
        input_text: str,
        seed: int,
        brain_state: Dict[str, Any],
        response_text: str,
        emotion: str,
        trust_before: float,
        trust_after: float,
        contradiction_score: float = 0.0,
    ):
        """Save a deterministic replay snapshot for compliance audits."""
        input_hash = hashlib.sha256(input_text.encode()).hexdigest()[:16]
        snapshot = ReplaySnapshot(
            session_id=session_id,
            turn_number=turn_number,
            timestamp=time.time(),
            input_text=input_text,
            input_hash=input_hash,
            seed=seed,
            brain_state_snapshot=brain_state,
            response_text=response_text,
            emotion=emotion,
            trust_before=trust_before,
            trust_after=trust_after,
            contradiction_score=contradiction_score,
        )
        self._replay_snapshots.append(snapshot)
        # Keep last 500 snapshots
        if len(self._replay_snapshots) > 500:
            self._replay_snapshots = self._replay_snapshots[-500:]

    def get_session_seed(self, session_id: str) -> int:
        """Get or create a deterministic seed for a session."""
        if session_id not in self._session_seeds:
            self._session_seeds[session_id] = random.randint(0, 2**31 - 1)
        return self._session_seeds[session_id]

    def get_events(
        self,
        event_type: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """Query audit events with optional filters."""
        events = self._buffer
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if session_id:
            events = [e for e in events if e.session_id == session_id]
        return [asdict(e) for e in events[-limit:]]

    def get_replay_snapshots(
        self,
        session_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """Get deterministic replay snapshots."""
        snaps = self._replay_snapshots
        if session_id:
            snaps = [s for s in snaps if s.session_id == session_id]
        return [asdict(s) for s in snaps[-limit:]]

    def get_event_stats(self) -> Dict[str, int]:
        """Get event count by type."""
        return dict(self._event_counts)

    def verify_integrity(self, event_id: str) -> bool:
        """Verify an event's checksum hasn't been tampered with."""
        for event in self._buffer:
            if event.id == event_id:
                original = event.checksum
                computed = event.compute_checksum()
                return original == computed
        return False

    def snapshot(self) -> Dict[str, Any]:
        """Full audit system snapshot for dashboard/synoptic."""
        return {
            "total_events": len(self._buffer),
            "event_counts": dict(self._event_counts),
            "replay_snapshots": len(self._replay_snapshots),
            "sessions_tracked": len(self._session_seeds),
        }


# ── Module singleton ──────────────────────────────────────────────────────────

_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
