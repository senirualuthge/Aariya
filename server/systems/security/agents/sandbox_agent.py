"""
Sandbox Agent — safe defensive simulation.
Tests incoming payloads for DoS vectors, injection patterns,
and schema violations WITHOUT executing any exploit code.
"""
import asyncio
import json
import re
from typing import Dict, Any, List, Optional

from server.systems.security.agents.base import SecurityAgent

# Patterns that commonly indicate injection attempts
INJECTION_PATTERNS = [
    (re.compile(r"DROP\s+TABLE", re.IGNORECASE),      "SQL injection (DROP TABLE)"),
    (re.compile(r"SELECT\s+\*\s+FROM", re.IGNORECASE),"SQL injection (SELECT *)"),
    (re.compile(r"<script[\s\S]*?>", re.IGNORECASE),   "XSS script tag"),
    (re.compile(r"\$\{.*?\}"),                          "Template injection (${...})"),
    (re.compile(r"\{\{.*?\}\}"),                        "Template injection ({{...}})"),
    (re.compile(r"__import__\s*\(", re.IGNORECASE),    "Python code injection"),
    (re.compile(r"eval\s*\(",re.IGNORECASE),            "eval() injection"),
    (re.compile(r"\.\./|\.\.\\"),                       "Path traversal (..)"),
]

MAX_ALLOWED_BYTES  = 32_768   # 32 KB — raise flag above this
MAX_ALLOWED_CHARS  = 16_000   # character limit for text field


class SandboxAgent(SecurityAgent):
    name = "sandbox"

    async def run(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []

        # Run all tests concurrently inside a tight timeout
        tests = [
            self._test_payload_size(data),
            self._test_text_injection(data),
            self._test_json_structure(data),
        ]
        results = await asyncio.gather(*tests, return_exceptions=True)

        for res in results:
            if isinstance(res, dict):
                issues.append(res)
            elif isinstance(res, list):
                issues.extend(res)

        return issues

    # ── Individual tests ─────────────────────────────────────────────────────

    async def _test_payload_size(self, data: Dict[str, Any]) -> Optional[Dict]:
        try:
            raw = json.dumps(data).encode("utf-8")
        except (TypeError, ValueError):
            raw = str(data).encode("utf-8")

        if len(raw) > MAX_ALLOWED_BYTES:
            return self.format_issue(
                issue=f"Payload size too large: {len(raw):,} bytes (limit {MAX_ALLOWED_BYTES:,})",
                severity="MEDIUM",
                fix="Add request body size limit in FastAPI middleware",
                reason="Prevents memory exhaustion / DoS attacks via oversized payloads",
            )

        text = data.get("text", "")
        if isinstance(text, str) and len(text) > MAX_ALLOWED_CHARS:
            return self.format_issue(
                issue=f"Text field too long: {len(text):,} chars",
                severity="MEDIUM",
                fix="Truncate or reject inputs exceeding character limit",
                reason="Prevents token flooding and prompt injection via large inputs",
            )

        return None

    async def _test_text_injection(self, data: Dict[str, Any]) -> List[Dict]:
        text = data.get("text", "")
        if not isinstance(text, str) or not text:
            return []

        findings = []
        for pattern, label in INJECTION_PATTERNS:
            if pattern.search(text):
                findings.append(
                    self.format_issue(
                        issue=f"Injection pattern detected: {label}",
                        severity="HIGH",
                        fix="Sanitize and reject inputs containing injection patterns",
                        reason="Prevents code/query injection through user-supplied text",
                    )
                )

        return findings

    async def _test_json_structure(self, data: Dict[str, Any]) -> Optional[Dict]:
        """Make sure the data is a proper dict — reject anything else."""
        if not isinstance(data, dict):
            return self.format_issue(
                issue="Malformed input: expected JSON object",
                severity="HIGH",
                fix="Add strict Pydantic schema validation at the WebSocket handler",
                reason="Prevents parser crashes and unexpected control flow",
            )
        return None
