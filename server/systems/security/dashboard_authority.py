"""
Dashboard Authority — authority-layer command execution (laptop only).

The mirror of `mobile_authority.py`: mobile is the CONTROL layer (commands
denied), the laptop dashboard is the AUTHORITY layer (commands executed).
The live `/ws/brain_metrics` endpoint dispatches `command` frames here.

Supported actions (all authority-only — see mobile_authority.py):
  wipe_memory      → clears the in-memory session context
  set_personality  → applies a named preset vector to the baseline persona
  override_mode    → forces a behaviour mode, broadcast to all surfaces
  force_mode       → same family — hard behaviour override

Every command returns an `authority.ack` frame for the requesting dashboard;
state-changing commands also emit a broadcast frame so every surface (phones,
main UI, other dashboards) syncs to the new mode.

⚠️ TRUST MODEL — This channel is UNauthenticated by design. Unlike the mobile
gate, nothing here distinguishes "the laptop" from any client that can reach
port 8000 (or any XSS on the dashboard); the whole codebase has no WS auth.
The security story is the *channel split* (destructive commands are denied on
/mobile and executed here), not a credential check. Treat anything reachable
as trusted or add auth at the transport level before exposing this publicly.

Module docstring mirrors the resolved Zero-Interference contract from
`*Mobile Achi v2.txt`: "Mobile = control layer, Laptop = authority layer."
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional, Tuple

from server.systems.personality import PersonalitySystem

logger = logging.getLogger("aariya.dashboard_authority")

# The exact authority-only set — kept in lock-step with mobile_authority.py.
AUTHORITY_ACTIONS = frozenset({
    "wipe_memory",
    "set_personality",
    "override_mode",
    "force_mode",
})

# Behaviour modes accepted by override_mode / force_mode (UI-facing names).
BEHAVIOUR_MODES = frozenset({
    "focus", "relax", "guard", "chat", "social", "deep",
})


def authority_ack(action: str, ok: bool, **extra) -> Dict:
    """Build the response frame sent back to the requesting dashboard."""
    return {"type": "authority.ack", "action": action, "ok": ok, **extra}


async def execute_authority_command(
    action: str,
    message: dict,
) -> Tuple[Dict, Optional[Dict]]:
    """
    Execute one authority-layer command from the dashboard channel.

    Args:
        action:  the command action (wipe_memory, set_personality, ...)
        message: the full incoming frame (mode / preset values live here)

    Returns:
        (ack_frame, broadcast_frame_or_None). The ack is sent back to the
        requesting dashboard by the caller; the broadcast frame, when present,
        is pushed to every connected surface by the caller so phones / main UI
        / other dashboards sync.
    """
    if action not in AUTHORITY_ACTIONS:
        logger.warning(f"[Dashboard Authority] unknown action: {action!r}")
        return authority_ack(action, ok=False, error=f"unknown action: {action}"), None

    # ── wipe_memory: clear the active session context ───────────────────────
    if action == "wipe_memory":
        try:
            from server.systems.memory_hierarchy import get_memory_hierarchy
            get_memory_hierarchy().clear_session_memory("user_default")
            logger.info("[Dashboard Authority] memory wipe executed (authority layer)")
            return (
                authority_ack("wipe_memory", ok=True),
                {"type": "memory_wiped", "by": "dashboard", "timestamp": time.time()},
            )
        except Exception as exc:  # noqa: BLE001 — report, never crash the socket
            logger.error(f"[Dashboard Authority] wipe_memory failed: {exc}")
            return (
                authority_ack("wipe_memory", ok=False, error=str(exc)),
                None,
            )

    # ── set_personality: overwrite the baseline persona with a preset ───────
    if action == "set_personality":
        preset_id = str(message.get("preset") or message.get("mode") or "").strip()
        system = PersonalitySystem("user_default")
        if not preset_id or not system.apply_preset(preset_id):
            known = ", ".join(sorted(PersonalitySystem.PRESETS_KEYS()))
            logger.warning(
                f"[Dashboard Authority] unknown personality preset: {preset_id!r}"
            )
            return (
                authority_ack(
                    "set_personality", ok=False,
                    error=f"unknown preset: {preset_id!r}",
                    known=known,
                ),
                None,
            )
        logger.info(
            f"[Dashboard Authority] personality set to {preset_id!r} "
            f"(authority layer)"
        )
        return (
            authority_ack("set_personality", ok=True, preset=preset_id),
            {
                "type": "override_mode",
                "mode": preset_id,
                "by": "dashboard",
                "timestamp": time.time(),
            },
        )

    # ── override_mode / force_mode: broadcast a behaviour-mode override ──────
    mode = str(message.get("mode") or "").strip()
    if not mode:
        return authority_ack(action, ok=False, error="missing 'mode'"), None
    if mode not in BEHAVIOUR_MODES:
        known = ", ".join(sorted(BEHAVIOUR_MODES))
        logger.warning(
            f"[Dashboard Authority] unknown behaviour mode: {mode!r}"
        )
        return (
            authority_ack(action, ok=False, error=f"unknown mode: {mode!r}", known=known),
            None,
        )
    logger.info(f"[Dashboard Authority] {action} → {mode!r} (authority layer)")
    return (
        authority_ack(action, ok=True, mode=mode),
        {
            "type": "override_mode",
            "mode": mode,
            "by": "dashboard",
            "timestamp": time.time(),
        },
    )
