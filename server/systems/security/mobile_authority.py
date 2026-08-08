"""Mobile command authority policy — resolves the zero-interference rule.

The `*Mobile Achi v2.txt` blueprint contradicts itself:

  * Zero-Interference Rule (Step 6 / Security): "Mobile must NEVER modify
    personality, reset memory, or change RL policy. Only the dashboard
    (laptop) can do that."
  * Phase 4 (Remote Control): hands mobile exactly those commands
    (`wipe_memory`, `set_personality`, `force_mode`).

This module is the single source of truth that resolves the conflict in
favour of the security rule — which the doc itself states as the governing
principle ("Mobile = control layer, Laptop = authority layer. Never let
mobile override core identity directly").

Decision:
  * The mobile control channel may only send *control-layer* messages:
    chat input, interrupts, pings, and monitoring frames.
  * Destructive / identity-mutating commands (`wipe_memory`,
    `set_personality`, `override_mode`, `force_mode`) are **rejected
    server-side** with a `command_denied` frame so a lost/compromised phone
    can never wipe memory or rewrite the persona. Only the primary /
    dashboard surface is allowed to issue them.

To intentionally relax this later, remove an action from
[MOBILE_AUTHORITY_ONLY_ACTIONS] — the gate is data-driven and documented
here so the policy stays auditable.
"""

# ── The authority boundary ───────────────────────────────────────────────────
# Commands a MOBILE client may never execute directly. These require the
# laptop/dashboard (the "authority layer" in the blueprint).
MOBILE_AUTHORITY_ONLY_ACTIONS = frozenset({
    "wipe_memory",      # deletes short-term + conversational hierarchy
    "set_personality",  # rewrites the persona vector
    "override_mode",    # forces a behaviour mode (RL policy override)
    "force_mode",       # same family — hard RL/behaviour override
})

# Reason string surfaced to the client so the UI can explain the denial.
DENIED_REASON = "authority_required"


def is_mobile_allowed(action: str) -> bool:
    """True when a mobile client may execute `action` directly."""
    return action not in MOBILE_AUTHORITY_ONLY_ACTIONS


def denied_frame(action: str) -> dict:
    """Build the `command_denied` frame the server sends back."""
    return {
        "type": "command_denied",
        "action": action,
        "reason": DENIED_REASON,
        "detail": "This command requires the laptop dashboard (authority layer).",
    }
