"""
agent_scanner.py
────────────────
AST-based agent auto-discovery. Zero imports of user code — pure static analysis.

Detection strategies (all run on every scan):
  1. INHERITANCE  — class Foo(BaseAgent), class Foo(SwarmAgent), any *Agent base
  2. FOLDER       — any .py file inside a directory named agents/ or agent/
  3. DECORATOR    — @agent, @swarm_agent, @register_agent on class or function

Returns a flat list of AgentRecord dicts ready for the registry.
"""

from __future__ import annotations
import ast
import os
import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

# ── Configurable ────────────────────────────────────────────────────────────

# Root path to scan. Override via env or pass directly to Scanner.
DEFAULT_ROOT = Path(__file__).resolve().parents[2]  # project root

# Folder names treated as "agent directories" for strategy 2
AGENT_FOLDER_NAMES = {"agents", "cognitive_agents"}

# Base-class name patterns (case-insensitive substring match)
AGENT_BASE_PATTERNS = [
    r".*agent.*",
    r".*cognitive.*module.*",
]

# Decorator name patterns
AGENT_DECORATOR_PATTERNS = [
    "agent",
    "swarm_agent",
    "register_agent",
    "cognitive_agent",
    "aariya_agent",
]

# Directories to always skip
SKIP_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "node_modules",
    "dist", "build", ".mypy_cache", ".pytest_cache",
}

# ── Data model ───────────────────────────────────────────────────────────────

@dataclass
class AgentRecord:
    id: str                          # stable unique key  (file_hash:class_name)
    name: str                        # raw class / function name
    display_name: str                # human-readable spaced name (CamelCase → spaced)
    file: str                        # relative path from project root
    line: int                        # line number of definition
    kind: str                        # "class" | "function"
    detection: list[str]             # which strategies matched
    base_classes: list[str]          # for inheritance strategy
    decorators: list[str]            # raw decorator names found
    docstring: Optional[str]         # first docstring line
    file_hash: str                   # sha1 of file content (change detection)
    scanned_at: str                  # ISO timestamp

    def to_dict(self) -> dict:
        return asdict(self)


# ── Core Scanner ─────────────────────────────────────────────────────────────

class AgentScanner:
    """
    Walk the project tree and return all discovered AgentRecords.

    Usage:
        scanner = AgentScanner(root="/path/to/project")
        records = scanner.scan()
    """

    def __init__(self, root: Union[str, Path] = DEFAULT_ROOT):
        self.root = Path(root).resolve()

    # ── Public ───────────────────────────────────────────────────────────────

    def scan(self) -> list[dict]:
        """Full scan. Returns list of AgentRecord dicts."""
        records: dict[str, AgentRecord] = {}

        for py_file in self._iter_python_files():
            try:
                file_records = self._scan_file(py_file)
                for rec in file_records:
                    # Merge detections if same id appears in multiple strategies
                    if rec.id in records:
                        records[rec.id].detection = list(
                            set(records[rec.id].detection + rec.detection)
                        )
                    else:
                        records[rec.id] = rec
            except (SyntaxError, UnicodeDecodeError):
                pass  # skip unparseable files silently

        return [r.to_dict() for r in records.values()]

    # ── Private helpers ──────────────────────────────────────────────────────

    def _iter_python_files(self):
        for dirpath, dirnames, filenames in os.walk(self.root):
            # Prune skip dirs in-place (affects os.walk recursion)
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fname in filenames:
                if fname.endswith(".py"):
                    yield Path(dirpath) / fname

    def _scan_file(self, path: Path) -> list[AgentRecord]:
        source = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source, filename=str(path))
        file_hash = hashlib.sha1(source.encode()).hexdigest()[:12]
        rel_path = str(path.relative_to(self.root))
        in_agent_folder = self._is_in_agent_folder(path)

        records = []
        now = datetime.now(timezone.utc).isoformat()

        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.AsyncFunctionDef, ast.FunctionDef)):
                # Skip dunder/private methods — they are implementation details, not agents
                if node.name.startswith('__') or node.name.startswith('_'):
                    continue

                detections = []
                base_classes = []
                decorators = []

                # Strategy 1 — inheritance (classes only)
                if isinstance(node, ast.ClassDef):
                    bases = self._extract_base_names(node)
                    matched = [b for b in bases if self._matches_agent_base(b)]
                    if matched:
                        detections.append("inheritance")
                        base_classes = bases

                # Strategy 2 — folder location (classes only by default, functions need decorators)
                if in_agent_folder and isinstance(node, ast.ClassDef):
                    detections.append("folder")

                # Strategy 3 — decorator
                decs = self._extract_decorator_names(node)
                matched_decs = [d for d in decs if d.lower() in AGENT_DECORATOR_PATTERNS]
                if matched_decs:
                    detections.append("decorator")
                    decorators = decs

                if not detections:
                    continue  # not an agent

                kind = "class" if isinstance(node, ast.ClassDef) else "function"
                docstring = ast.get_docstring(node)
                doc_first_line = docstring.split("\n")[0].strip() if docstring else None

                stable_id = f"{file_hash}:{node.name}"
                display_name = self._to_display_name(node.name)

                records.append(AgentRecord(
                    id=stable_id,
                    name=node.name,
                    display_name=display_name,
                    file=rel_path,
                    line=node.lineno,
                    kind=kind,
                    detection=detections,
                    base_classes=base_classes,
                    decorators=decorators,
                    docstring=doc_first_line,
                    file_hash=file_hash,
                    scanned_at=now,
                ))

        return records

    def _is_in_agent_folder(self, path: Path) -> bool:
        return any(part.lower() in AGENT_FOLDER_NAMES for part in path.parts)

    def _extract_base_names(self, node: ast.ClassDef) -> list[str]:
        names = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                names.append(base.id)
            elif isinstance(base, ast.Attribute):
                names.append(f"{base.value.id}.{base.attr}" if isinstance(base.value, ast.Name) else base.attr)
        return names

    def _extract_decorator_names(self, node) -> list[str]:
        names = []
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                names.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                names.append(dec.attr)
            elif isinstance(dec, ast.Call):
                func = dec.func
                if isinstance(func, ast.Name):
                    names.append(func.id)
                elif isinstance(func, ast.Attribute):
                    names.append(func.attr)
        return names

    def _matches_agent_base(self, name: str) -> bool:
        name_lower = name.lower()
        return any(re.match(pat, name_lower) for pat in AGENT_BASE_PATTERNS)

    @staticmethod
    def _to_display_name(raw: str) -> str:
        """Convert CamelCase / snake_case identifiers into readable Title Case.
        e.g. 'EmotionAgent'    → 'Emotion Agent'
             'goal_generator'  → 'Goal Generator'
             'OpenAIBridge'    → 'Open AI Bridge'
        """
        # snake_case → words first
        if '_' in raw:
            return ' '.join(w.capitalize() for w in raw.split('_'))
        # CamelCase split
        spaced = re.sub(r'([a-z])([A-Z])', r'\1 \2', raw)
        spaced = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', spaced)
        return spaced.strip()


# ── CLI entry point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json, sys
    root = sys.argv[1] if len(sys.argv) > 1 else str(DEFAULT_ROOT)
    scanner = AgentScanner(root=root)
    results = scanner.scan()
    print(json.dumps(results, indent=2))
    print(f"\n✓ Found {len(results)} agent(s) in {root}", file=sys.stderr)
