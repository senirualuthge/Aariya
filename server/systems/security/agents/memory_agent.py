from server.systems.security.agents.base import SecurityAgent
from typing import Dict, Any, List

class MemorySecurityAgent(SecurityAgent):
    name = "memory"

    async def run(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        issues = []
        text = data.get("text", "")
        if not text:
            return issues

        sensitive_keywords = ["password", "api_key", "token"]
        text_lower = text.lower()
        
        for keyword in sensitive_keywords:
            if f"{keyword}=" in text_lower or f"{keyword}:" in text_lower:
                issues.append(self.format_issue(
                    issue=f"Sensitive data detected in input: {keyword}",
                    severity="HIGH",
                    fix="Mask or avoid storing sensitive data",
                    reason="Prevents data leakage into logs or memory systems"
                ))

        return issues
