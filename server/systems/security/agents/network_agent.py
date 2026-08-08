try:
    import psutil as _psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _psutil = None  # type: ignore[assignment]
    _PSUTIL_AVAILABLE = False

from server.systems.security.agents.base import SecurityAgent
from typing import Dict, Any, List

class NetworkAgent(SecurityAgent):
    name = "network"

    async def run(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        issues = []

        if not _PSUTIL_AVAILABLE:
            issues.append(self.format_issue(
                issue="Network monitoring unavailable (psutil not installed)",
                severity="LOW",
                fix="Run: pip install psutil",
                reason="psutil is required for live connection monitoring",
            ))
            return issues

        try:
            connections = _psutil.net_connections(kind='inet')  # type: ignore
            for conn in connections:
                if conn.status == "ESTABLISHED" and conn.raddr:
                    ip = conn.raddr.ip
                    if not ip.startswith("127.") and not ip.startswith("192.168.") and not ip.startswith("::1"):
                        issues.append(self.format_issue(
                            issue=f"Unknown external connection: {ip}",
                            severity="MEDIUM",
                            fix="Review process and block if untrusted",
                            reason="May indicate external communication channel",
                        ))
        except Exception:
            # psutil may raise AccessDenied if not run as root — gracefully ignore
            pass

        # Deduplicate and cap at top 5
        unique_issues = {iss["issue"]: iss for iss in issues}
        return list(unique_issues.values())[:5]
