"""
Security Event Logger — maintains a tamper-evident, timestamped timeline
of all security events detected during the session.

Each entry is chained via SHA-256 so the log can be verified for
ex-post-facto tampering (lightweight blockchain pattern).
"""
import hashlib
import time
from collections import deque
from typing import Any, Dict, List, Optional

MAX_EVENTS = 500   # rolling cap to avoid unbounded memory growth


class SecurityEventLogger:
    def __init__(self) -> None:
        self._events: deque[Dict[str, Any]] = deque(maxlen=MAX_EVENTS)
        self._prev_hash: str = "0" * 64   # genesis hash

    # ── Public API ────────────────────────────────────────────────────────────

    def log(self, event_type: str, agent: str, issue: Dict[str, Any]) -> None:
        """Append a new security event to the timeline."""
        entry: Dict[str, Any] = {
            "timestamp": time.time(),
            "type":      event_type,
            "agent":     agent,
            "issue":     issue,
            "hash":      "",
        }
        entry["hash"] = self._chain_hash(entry)
        self._prev_hash = entry["hash"]
        self._events.append(entry)

    def log_risk(self, risk: Dict[str, Any]) -> None:
        """Record a risk assessment result (not tied to a single agent)."""
        entry: Dict[str, Any] = {
            "timestamp":   time.time(),
            "type":        "RISK_ASSESSMENT",
            "agent":       "risk_engine",
            "risk_level":  risk.get("risk_level", "UNKNOWN"),
            "risk_score":  risk.get("risk_score", 0),
            "hash":        "",
        }
        entry["hash"] = self._chain_hash(entry)
        self._prev_hash = entry["hash"]
        self._events.append(entry)

    def log_action(self, action: str) -> None:
        """Record a remediation action taken."""
        entry: Dict[str, Any] = {
            "timestamp": time.time(),
            "type":      "REMEDIATION",
            "agent":     "remediation_engine",
            "action":    action,
            "hash":      "",
        }
        entry["hash"] = self._chain_hash(entry)
        self._prev_hash = entry["hash"]
        self._events.append(entry)

    def get_timeline(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return the most recent events, newest first."""
        events = list(self._events)
        events.reverse()
        return events[:limit]

    def get_threat_events(self) -> List[Dict[str, Any]]:
        """Return only THREAT_DETECTED entries."""
        return [e for e in self._events if e.get("type") == "THREAT_DETECTED"]

    # ── Internal ─────────────────────────────────────────────────────────────

    def _chain_hash(self, entry: Dict[str, Any]) -> str:
        """Chain-hash an entry against the previous hash for tamper evidence."""
        raw = str(entry) + self._prev_hash
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# Module-level singleton — shared across all security agent runs in a session
_logger_instance: Optional[SecurityEventLogger] = None


def get_event_logger() -> SecurityEventLogger:
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = SecurityEventLogger()
    return _logger_instance
