"""
Tools Router — REST surface for the MCP tool ecosystem (AccessFIles §33).

  GET  /api/tools                → every registered tool (builtin + mcp:*)
  GET  /api/tools/mcp/status     → configured MCP servers + connection state
  POST /api/tools/mcp/sync       → connect configured servers, merge tools
  POST /api/tools/call           → invoke any registered tool by name
  GET  /api/knowledge/graph      → facts about an entity from the real graph
  POST /api/knowledge/ingest     → fold current real signals into the graph

MCP servers are never defined here — they come from AARIYA_MCP_SERVERS env or
server/data/mcp_servers.json. With no configuration, /mcp/status reports zero
configured servers and the registry keeps only its built-in tools.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from server.systems.llm_router import get_mcp_registry
from server.systems.mcp_client import load_server_configs, sync_remote_tools

logger = logging.getLogger("aariya.tools.router")
router = APIRouter(prefix="/api", tags=["tools", "knowledge"])


class ToolCallRequest(BaseModel):
    name: str
    arguments: Optional[Dict[str, Any]] = None


class IngestRequest(BaseModel):
    user_id: str = "user_default"


@router.get("/tools")
async def list_tools():
    """All callable tools across builtin + connected MCP servers."""
    reg = get_mcp_registry()
    return {"tools": reg.list_tools(), "count": len(reg.list_tools())}


@router.get("/tools/mcp/status")
async def mcp_status():
    configs = load_server_configs()
    reg = get_mcp_registry()
    remote = [t for t in reg.list_tools() if t.get("source", "").startswith("mcp:")]
    return {
        "configured_servers": len(configs),
        "servers": [
            {"name": c.get("name"), "command": c.get("command")}
            for c in configs if isinstance(c, dict)
        ],
        "remote_tools": len(remote),
    }


@router.post("/tools/mcp/sync")
async def mcp_sync():
    """Discover tools from the configured MCP servers right now."""
    summary = await sync_remote_tools()
    return {"ok": True, **summary}


@router.post("/tools/call")
async def call_tool(req: ToolCallRequest):
    result = await get_mcp_registry().call(req.name, req.arguments)
    return result


@router.get("/knowledge/graph")
async def knowledge_query(entity: str):
    from server.systems.agent.graph_feeder import query_entity
    facts = query_entity(entity)
    return {"entity": entity, "facts": facts, "count": len(facts)}


@router.post("/knowledge/ingest")
async def knowledge_ingest(req: IngestRequest):
    """Fold the system's current real signals into the persistent graph."""
    from server.systems.agent.graph_feeder import ingest_real_signals
    added = ingest_real_signals(req.user_id)
    return {"ok": True, "added": added}


class CodeIndexRequest(BaseModel):
    root: str = "."
    max_files: int = 400


@router.post("/knowledge/code-index")
async def knowledge_code_index(req: CodeIndexRequest):
    """AST-parse real Python sources under an allowed root (AccessFIles §70)
    and fold the module/class/function structure into the graph."""
    import asyncio

    from server.systems.agent.code_indexer import index_python_repo
    summary = await asyncio.get_running_loop().run_in_executor(
        None,
        lambda: index_python_repo(
            req.root,
            max_files=max(1, min(req.max_files, 2000)),
        ),
    )
    return summary


@router.get("/knowledge/symbol")
async def knowledge_symbol(symbol: str):
    """Where does this symbol live? (defines/imports/inherits edges)"""
    from server.systems.agent.code_indexer import symbol_usages
    return symbol_usages(symbol)
