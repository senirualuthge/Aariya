"""
Cognitive Filesystem Agent — swarm agent wrapping FileSystemAgent.

Maps task intents to guarded FS operations. Destructive intents are never
executed automatically: they return `requires_confirmation` so an upstream
governor can prompt the user first.
"""

from typing import Dict, Any

from server.systems.filesystem.filesystem_agent import FileSystemAgent
from server.safety.governor import SafetyGovernor
from server.systems.filesystem.drive_monitor import removable_drives


class CognitiveFilesystemAgent:
    def __init__(self):
        self.fs = FileSystemAgent()
        self.governor = SafetyGovernor(self.fs)
        self.name = "filesystem_agent"

    async def act(self, state: Dict[str, Any]) -> Any:
        task = state.get("task") if isinstance(state, dict) else None
        return await self.process(task) if task else {"status": "no_task"}

    async def process(self, task: Dict[str, Any]) -> Dict[str, Any]:
        intent = task.get("intent")

        if intent == "list":
            return {"status": "ok", "items": self.fs.list_directory(task["path"])}

        if intent == "read_file":
            content = self.fs.read_file(task["path"])
            if content in ("File not found.", "File not accessible.", "Cannot read directory."):
                return {"status": "denied", "reason": content}
            return {"status": "ok", "content": content}

        if intent == "write_file":
            ok = self.governor.write_file(task["path"], task.get("content", ""))
            return {"status": "ok" if ok else "denied", "path": task["path"]}

        if intent == "append_file":
            ok = self.governor.append_file(task["path"], task.get("content", ""))
            return {"status": "ok" if ok else "denied", "path": task["path"]}

        if intent == "delete_file":
            if not task.get("confirmed"):
                return {"status": "requires_confirmation", "action": "delete", "path": task["path"]}
            ok = self.governor.delete_file(task["path"], confirmed=True)
            return {"status": "ok" if ok else "denied", "path": task["path"]}

        if intent == "search_files":
            return {
                "status": "ok",
                "results": self.fs.search_files(task.get("root", "~"), task["query"]),
            }

        if intent == "open":
            ok = self.fs.open_path(task["path"])
            return {"status": "ok" if ok else "denied", "action": "open"}

        if intent == "drives":
            return {"status": "ok", "drives": removable_drives()}

        if intent == "capabilities":
            return {"status": "ok", "capabilities": self.fs.capabilities()}

        return {"status": "not_found", "intent": intent}
