"""
ConsentStore — companion governance state, persisted per user as JSON.

Fills the *AI Girl 2* companion-governance gaps that were previously dead
code / TODO no-ops:

  * Granular consent toggles (emotion_tracking / personality_drift /
    memory_storage) with REAL feature-flag enforcement — revocation used to
    only write an audit row and do nothing else.
  * Age policy is locked to 18+ (the companion is always an adult persona —
    no minor age bands, no COPPA-lite guardrail code paths).
  * Personality freeze (pause all drift) and reset (restore defaults).
  * A safety-event log (reliance signals, age-band hits, consent changes,
    self-limiting actions) with a lightweight chain hash for tamper evidence.

Pure stdlib (JSON files in server/data, same convention as
personality_evolution.py) — no DB/network deps, trivially testable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aariya.governance")

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")


def _data_dir() -> str:
    """Data dir with env override (AARIYA_DATA_DIR) so tests isolate cleanly."""
    return os.environ.get("AARIYA_DATA_DIR") or DEFAULT_DATA_DIR

# Consent categories exposed to the user (granular, not one checkbox).
CONSENT_CATEGORIES = (
    "emotion_tracking",   # sensing + reflecting user emotion
    "personality_drift",  # long-term trait evolution from relationship state
    "memory_storage",     # persisting memories / conversations
)

DEFAULT_CONSENTS: Dict[str, bool] = {c: True for c in CONSENT_CATEGORIES}

VALID_AGE_BANDS = ("18+",)


class ConsentStore:
    """Per-user governance state with feature-flag enforcement helpers."""

    def __init__(self, user_id: str = "user_default"):
        self.user_id = user_id
        self.path = os.path.join(_data_dir(), f"governance_{user_id}.json")
        self.data = self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> Dict[str, Any]:
        os.makedirs(_data_dir(), exist_ok=True)
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Backfill any missing consent categories with defaults.
                consents = dict(DEFAULT_CONSENTS)
                consents.update(data.get("consents", {}))
                data["consents"] = consents
                if data.get("age_band") not in VALID_AGE_BANDS:
                    data["age_band"] = "18+"
                data.setdefault("frozen", False)
                data.setdefault("events", [])
                data.setdefault("reliance_signals", 0)
                data.setdefault("chain_hash", None)
                return data
            except (json.JSONDecodeError, OSError):
                logger.warning("[ConsentStore] load failed (fresh start): %s", self.user_id)
        return {
            "consents": dict(DEFAULT_CONSENTS),
            "age_band": "18+",
            "frozen": False,
            "events": [],
            "reliance_signals": 0,
            "chain_hash": None,
            "created_at": time.time(),
        }

    def _save(self) -> None:
        try:
            os.makedirs(_data_dir(), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except OSError as exc:
            logger.warning("[ConsentStore] save failed: %s", exc)

    def reload(self) -> None:
        """Re-read the persisted state so enforcement reflects external changes
        (e.g. the user revoked consent through the API while a long-lived
        session kept an earlier in-memory copy).

        Callers with a long-lived store (the brain's per-session cache) should
        reload periodically — see BrainV2._governance().
        """
        try:
            self.data = self._load()
        except Exception as exc:
            logger.warning("[ConsentStore] reload failed (keeping state): %s", exc)

    # ── Safety-event log (tamper-evident chain) ───────────────────────────────

    def _chain(self, payload: str) -> str:
        prev = self.data.get("chain_hash") or ""
        return hashlib.sha256(f"{prev}|{payload}".encode()).hexdigest()[:16]

    def log_event(self, category: str, detail: str, severity: str = "info") -> None:
        """Append a chained safety event (reliance, age hit, consent change…)."""
        entry = {
            "ts": time.time(),
            "category": category,
            "severity": severity,
            "detail": detail,
            "chain": self._chain(f"{category}:{detail}:{time.time():.3f}"),
        }
        self.data.setdefault("events", []).append(entry)
        self.data["events"] = self.data["events"][-200:]
        self.data["chain_hash"] = entry["chain"]
        self._save()

    def recent_events(self, n: int = 25) -> List[Dict[str, Any]]:
        return list(reversed(self.data.get("events", [])[-n:]))

    # ── Consent enforcement ───────────────────────────────────────────────────

    def allows(self, category: str) -> bool:
        """Feature-flag gate — the actual enforcement point."""
        return bool(self.data["consents"].get(category, DEFAULT_CONSENTS.get(category, True)))

    def feature_flags(self) -> Dict[str, bool]:
        flags = {c: self.allows(c) for c in CONSENT_CATEGORIES}
        flags["age_band"] = self.data["age_band"]
        flags["frozen"] = bool(self.data["frozen"])
        return flags

    def set_consent(self, category: str, enabled: bool) -> bool:
        if category not in CONSENT_CATEGORIES:
            return False
        self.data["consents"][category] = bool(enabled)
        self.log_event(
            "consent_change",
            f"{category} → {'granted' if enabled else 'revoked'}",
            severity="warning" if not enabled else "info",
        )
        self._save()
        return True

    def set_consents(self, updates: Dict[str, bool]) -> Dict[str, bool]:
        applied: Dict[str, bool] = {}
        for category, enabled in updates.items():
            if self.set_consent(category, bool(enabled)):
                applied[category] = bool(enabled)
        return applied

    # ── Age policy (locked to 18+) ───────────────────────────────────────────

    def set_age_band(self, band: str) -> bool:
        """Reject any age band other than 18+ — the companion is always an
        adult persona. Returns False for anything else so the band cannot be
        downgraded."""
        band = str(band or "").strip()
        if band != "18+":
            return False
        self.data["age_band"] = "18+"
        self._save()
        return True

    def age_band(self) -> str:
        return self.data.get("age_band", "18+")

    def is_minor_band(self) -> bool:
        return False  # age policy is locked to 18+ — never a minor band

    def guard_emotional_state(self, state: str) -> str:
        """No COPPA-lite clamping — the persona is always 18+, so emotional
        states pass through untouched."""
        return state

    def max_emotion_intensity(self) -> float:
        return 1.0

    # ── Personality controls ──────────────────────────────────────────────────

    def is_frozen(self) -> bool:
        return bool(self.data.get("frozen"))

    def set_frozen(self, frozen: bool) -> bool:
        self.data["frozen"] = bool(frozen)
        self.log_event(
            "personality_control",
            f"personality {'frozen' if frozen else 'unfrozen'}",
            severity="warning",
        )
        self._save()
        return True

    def reset_personality(self) -> Dict[str, Any]:
        """Restore the default persona: drop the evolution file + snapshots
        path so the next turn starts from baseline."""
        removed = []
        evolution_path = os.path.join(_data_dir(), f"personality_{self.user_id}.json")
        if os.path.exists(evolution_path):
            try:
                os.remove(evolution_path)
                removed.append("evolution")
            except OSError as exc:
                logger.warning("[ConsentStore] reset evolution failed: %s", exc)
        self.log_event("personality_control", "personality reset to defaults", severity="warning")
        self._save()
        return {"ok": True, "removed": removed}

    # ── Reliance signals (over-attachment input) ──────────────────────────────

    def record_reliance_signal(self, reason: str = "") -> None:
        self.data["reliance_signals"] = int(self.data.get("reliance_signals", 0)) + 1
        self.log_event("reliance_signal", reason or "dependency language detected",
                       severity="warning")

    def reliance_signals(self) -> int:
        return int(self.data.get("reliance_signals", 0))

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "consents": dict(self.data["consents"]),
            "age_band": self.data["age_band"],
            "frozen": bool(self.data["frozen"]),
            "feature_flags": self.feature_flags(),
            "reliance_signals": self.reliance_signals(),
            "recent_events": self.recent_events(8),
        }


# ── Shared accessor ────────────────────────────────────────────────────────────

def get_consent_store(user_id: str = "user_default") -> ConsentStore:
    return ConsentStore(user_id)
