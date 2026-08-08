import hashlib
import os
from server.systems.security.agents.base import SecurityAgent
from typing import Dict, Any, List, Optional

class IntegrityAgent(SecurityAgent):
    name = "integrity"

    def hash_file(self, path: str) -> Optional[str]:
        """Calculate SHA256 of a file if it exists."""
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    async def run(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        issues = []
        critical_file = "server/main.py"
        trusted_hash = getattr(self, "trusted_hash", None)
        
        current_hash = self.hash_file(critical_file)
        
        # In a real environment, load trusted_hash securely from DB/ENV.
        # Here we initialize it on the first scan to avoid false alarms initially.
        if trusted_hash is None and current_hash is not None:
            self.trusted_hash = current_hash
        elif current_hash and current_hash != trusted_hash:
            issues.append(self.format_issue(
                issue=f"File tampering detected: {critical_file}",
                severity="HIGH",
                fix="Restore from trusted backup",
                reason="Prevents malicious code injection"
            ))

        return issues
