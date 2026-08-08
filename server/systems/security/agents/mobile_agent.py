"""
Mobile Agent — analyses permission signals sent from the Flutter client.

The Flutter app sends security.mobile payloads like:
{
    "type": "security.mobile",
    "permissions": {
        "camera":     true | false,
        "microphone": true | false,
        "location":   true | false
    },
    "active_session": true | false
}

These arrive through the WebSocket as part of `data["mobile"]` after
being merged into the main request payload by the input handler.
"""
from typing import Dict, Any, List

from server.systems.security.agents.base import SecurityAgent


# Permissions that raise an alarm if granted without an active session
SENSITIVE_BG_PERMS: List[str] = ["microphone", "camera"]

# Permissions that are always considered sensitive
HIGH_SENSITIVITY_PERMS: List[str] = ["microphone"]


class MobileAgent(SecurityAgent):
    name = "mobile"

    async def run(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []

        mobile_data = data.get("mobile", {})
        if not mobile_data:
            return issues

        perms: Dict[str, bool] = mobile_data.get("permissions", {})
        active_session: bool = bool(mobile_data.get("active_session", False))

        # Microphone / camera active without an open session → background surveillance risk
        for perm in SENSITIVE_BG_PERMS:
            if perms.get(perm) and not active_session:
                issues.append(
                    self.format_issue(
                        issue=f"Permission '{perm}' active with no active AI session",
                        severity="HIGH",
                        fix=f"Revoke '{perm}' permission when app is backgrounded or session is closed",
                        reason="Prevents silent background surveillance / eavesdropping",
                    )
                )

        # Location granted — always flag for awareness (not necessarily malicious)
        if perms.get("location"):
            issues.append(
                self.format_issue(
                    issue="Location permission granted to app",
                    severity="LOW",
                    fix="Ensure location is used only with explicit user consent",
                    reason="Minimises privacy surface — location data can expose sensitive patterns",
                )
            )

        # All three high-sensitivity perms active at once
        all_sensitive = all(perms.get(p) for p in ["camera", "microphone", "location"])
        if all_sensitive:
            issues.append(
                self.format_issue(
                    issue="Camera + microphone + location all granted simultaneously",
                    severity="HIGH",
                    fix="Audit why all three are needed; revoke any that are unnecessary",
                    reason="Combined access to A/V and GPS is a strong indicator of a surveillance profile",
                )
            )

        return issues
