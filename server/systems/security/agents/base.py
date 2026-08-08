from abc import ABC, abstractmethod
from typing import Dict, Any, List

class SecurityAgent(ABC):
    name: str = "base"

    @abstractmethod
    async def run(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        pass

    def format_issue(self, issue: str, severity: str, fix: str, reason: str) -> Dict[str, Any]:
        return {
            "agent": self.name,
            "issue": issue,
            "severity": severity,
            "fix": fix,
            "reason": reason
        }
