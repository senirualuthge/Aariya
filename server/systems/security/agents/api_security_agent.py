from server.systems.security.agents.base import SecurityAgent
from typing import Dict, Any, List

class APISecurityAgent(SecurityAgent):
    name = "api_security"

    async def run(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        issues = []
        metadata = data.get("metadata", {})
        
        # Heuristic check for missing auth on assumed remote connections
        if "token" not in metadata and not metadata.get("is_local", True):
            issues.append(self.format_issue(
                issue="Missing authentication token on remote request",
                severity="HIGH",
                fix="Reject connection or require token validation",
                reason="Prevents unauthorized access to WebSocket / API"
            ))

        text = data.get("text", None)
        if text is not None and not isinstance(text, str):
            issues.append(self.format_issue(
                issue="Invalid input type (expected string)",
                severity="MEDIUM",
                fix="Validate input schema properly",
                reason="Prevents injection or malformed payloads"
            ))

        return issues
