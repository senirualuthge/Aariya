"""
Real MCP (Model Context Protocol) stdio client (AccessFIles §33/§47).

Speaks the actual wire protocol — newline-delimited JSON-RPC 2.0 over a
spawned server process's stdin/stdout, exactly as the MCP spec defines for
the stdio transport:

    → initialize          ← capabilities + serverInfo
    → notifications/initialized
    → tools/list          ← [{name, description, inputSchema}, ...]
    → tools/call          ← {content: [...], isError}

Servers are NOT hardcoded anywhere in this module. They come from real
operator configuration, either:

  * env var  AARIYA_MCP_SERVERS   = JSON array of
        {"name": "fs", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"]}
  * or the file server/data/mcp_servers.json with the same shape

With no configuration there are zero connections and the registry keeps only
its built-in tools — nothing is faked.

Discovered remote tools are merged into the shared MCPRegistry with
source="mcp:<server>" so the governor/meta-reasoner can enumerate and call
them like any other tool.
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aariya.mcp_client")

MCP_PROTOCOL_VERSION = "2024-11-05"
_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "mcp_servers.json")
_CALL_TIMEOUT = float(os.getenv("AARIYA_MCP_TIMEOUT", "20"))


def load_server_configs() -> List[Dict[str, Any]]:
    """Read real operator config. Returns [] when none is provided."""
    raw = os.getenv("AARIYA_MCP_SERVERS", "")
    if raw.strip():
        try:
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except ValueError:
            logger.warning("[mcp] AARIYA_MCP_SERVERS is not valid JSON — ignoring")
            return []
    try:
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


class MCPServerConnection:
    """One live MCP server over stdio."""

    def __init__(self, name: str, command: str, args: Optional[List[str]] = None,
                 env: Optional[Dict[str, str]] = None):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._next_id = 1
        self.tools: List[Dict[str, Any]] = []
        self.server_info: Dict[str, Any] = {}
        self.connected = False

    # ── Framing ──────────────────────────────────────────────────────────────

    def _request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        req = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            req["params"] = params
        self._next_id += 1
        return req

    @staticmethod
    def _extract_result(payload: Dict[str, Any]) -> Any:
        if "error" in payload and payload["error"] is not None:
            raise RuntimeError(f"MCP error: {payload['error']}")
        return payload.get("result")

    async def _roundtrip(self, method: str,
                         params: Optional[Dict[str, Any]] = None) -> Any:
        """Send one request, read lines until its matching id comes back.
        Server-initiated requests/notifications between our calls are ignored
        (logged at debug) rather than treated as errors."""
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            raise RuntimeError(f"[{self.name}] not connected")
        req = self._request(method, params)
        want_id = req["id"]
        line = json.dumps(req) + "\n"
        self._proc.stdin.write(line.encode("utf-8"))
        await self._proc.stdin.drain()
        while True:
            raw = await asyncio.wait_for(self._proc.stdout.readline(), timeout=_CALL_TIMEOUT)
            if not raw:
                raise RuntimeError(f"[{self.name}] server closed stdout")
            try:
                payload = json.loads(raw.decode("utf-8"))
            except ValueError:
                continue  # not JSON — skip noise line
            if not isinstance(payload, dict):
                continue
            if payload.get("id") == want_id:
                return self._extract_result(payload)
            logger.debug("[mcp:%s] skipped non-matching frame: %s",
                         self.name, str(payload)[:120])

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def connect(self) -> bool:
        env = dict(os.environ)
        env.update(self.env)
        try:
            self._proc = await asyncio.create_subprocess_exec(
                self.command, *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env=env,
            )
        except (OSError, ValueError) as exc:
            logger.warning("[mcp:%s] spawn failed (%s): %s", self.name, self.command, exc)
            return False

        result = await self._roundtrip("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "aariya", "version": "1.0"},
        }) if await self._handshake_ok() else None
        if result is None:
            return False
        self.server_info = result if isinstance(result, dict) else {}

        # Spec-required notification after a successful initialize.
        if self._proc and self._proc.stdin:
            note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
            self._proc.stdin.write((json.dumps(note) + "\n").encode("utf-8"))
            await self._proc.stdin.drain()

        self.connected = True
        logger.info("[mcp:%s] connected to %s",
                    self.name, (self.server_info or {}).get("serverInfo", {}))
        return True

    async def _handshake_ok(self) -> bool:
        return self._proc is not None

    def close(self) -> None:
        if self._proc is not None:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
                self._proc.terminate()
            except ProcessLookupError:
                pass
            self._proc = None
        self.connected = False

    # ── Tools ────────────────────────────────────────────────────────────────

    async def list_tools(self) -> List[Dict[str, Any]]:
        result = await self._roundtrip("tools/list")
        tools = (result or {}).get("tools") if isinstance(result, dict) else None
        self.tools = tools or []
        return self.tools

    async def call_tool(self, name: str,
                        arguments: Optional[Dict[str, Any]] = None) -> Any:
        result = await self._roundtrip(
            "tools/call", {"name": name, "arguments": arguments or {}}
        )
        if isinstance(result, dict) and result.get("isError"):
            content = result.get("content") or []
            text = content[0].get("text", "") if content else ""
            raise RuntimeError(f"tool error: {str(text)[:200]}")
        return result


# ── Registry merge ────────────────────────────────────────────────────────────

async def sync_remote_tools(registry=None) -> Dict[str, Any]:
    """Connect every configured MCP server and merge discovered tools into
    the shared registry. Never raises — a dead server just doesn't contribute
    tools. Returns a status summary for the API layer."""
    if registry is None:
        from server.systems.llm_router import get_mcp_registry
        registry = get_mcp_registry()

    configs = [c for c in load_server_configs()
               if isinstance(c, dict) and c.get("name") and c.get("command")]
    servers: List[Dict[str, Any]] = []
    added = 0

    for cfg in configs:
        conn = MCPServerConnection(str(cfg["name"]), str(cfg["command"]),
                                   cfg.get("args") or [], cfg.get("env") or {})
        track_connection(conn)
        ok = False
        tools: List[Dict[str, Any]] = []
        try:
            ok = await conn.connect()
            if ok:
                tools = await conn.list_tools()
        except Exception as exc:
            logger.warning("[mcp:%s] discovery failed: %s", conn.name, exc)
            conn.close()

        source = f"mcp:{conn.name}"
        if ok:
            for t in tools[:64]:  # sane cap per server
                name = str(t.get("name", "")).strip()
                if not name:
                    continue
                qualified = f"{source}.{name}"

                def make_caller(c=conn, n=name):
                    async def caller(arguments: Optional[Dict[str, Any]] = None):
                        return await c.call_tool(n, arguments)
                    return caller

                registry.register(
                    qualified,
                    str(t.get("description", ""))[:300],
                    make_caller(),
                    input_schema=t.get("inputSchema") or {"type": "object", "properties": {}},
                    source=source,
                )
                added += 1
        servers.append({
            "name": conn.name,
            "command": conn.command,
            "connected": ok,
            "tools": len(tools),
            "server_info": conn.server_info.get("serverInfo", {}),
        })

    return {"configured": len(configs), "connected": sum(1 for s in servers if s["connected"]),
            "tools_added": added, "servers": servers}


# ── Singleton connections (for status/close from routers) ────────────────────

_live_connections: List[MCPServerConnection] = []


def track_connection(conn: MCPServerConnection) -> None:
    if conn not in _live_connections:
        _live_connections.append(conn)


def shutdown_all() -> None:
    for c in _live_connections:
        c.close()
    _live_connections.clear()
