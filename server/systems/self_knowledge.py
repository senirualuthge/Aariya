"""
SelfKnowledge — Aariya's awareness of where her own data lives.

Resolves the real data locations from the environment (.env) and the
filesystem, then builds a machine-readable inventory plus a prompt
block that can be injected into the conversation context so Aariya can
answer questions like "where is my memory stored?" honestly.

Inventory categories:
  - sqlite   : file-backed SQLite databases (brain, integrity, stores, ~/.aariya)
  - postgres : connection strings (DATABASE_URL, PULSE_DATABASE_URL)
  - chroma   : ChromaDB persist directories (vector memory)
  - vaults   : Obsidian dual-vault RAG sources
  - json     : JSON datastores (identity, trust, energy, server/data/*)
  - dirs     : empty/auxiliary storage directories

Every path is checked against the actual filesystem (exists / size /
age) so the inventory reflects reality, not just config.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger("aariya.self_knowledge")

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_env_file_fallback() -> None:
    """
    If python-dotenv is unavailable (as in some deployments), parse the
    project .env file directly so OBSIDIAN_* / DATABASE_URL / *_PATH
    values are still visible to the inventory. Existing env vars win.
    """
    if os.getenv("_AARIYA_ENV_LOADED"):
        return
    env_file = PROJECT_ROOT / ".env"
    if not env_file.is_file():
        os.environ["_AARIYA_ENV_LOADED"] = "1"
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        if value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        if key and not os.getenv(key):
            os.environ[key] = value
    os.environ["_AARIYA_ENV_LOADED"] = "1"


_load_env_file_fallback()

# Known relative storage roots used by the codebase (resolved vs PROJECT_ROOT).
STORAGE_ROOTS = [
    PROJECT_ROOT / "data",
    PROJECT_ROOT / "server" / "data",
    Path.home() / ".aariya",
]

# SQLite databases we know the server touches.
SQLITE_CANDIDATES = [
    ("brain_v4.db",      PROJECT_ROOT / "data" / "brain_v4.db"),
    ("integrity.db",     PROJECT_ROOT / "data" / "integrity.db"),
    ("stores.db",        PROJECT_ROOT / "data" / "stores.db"),
    ("aariya_home.db",   Path.home() / ".aariya" / "data.db"),
]

# Postgres connection strings from env.
POSTGRES_CANDIDATES = [
    ("aariya_postgres", "DATABASE_URL"),
    ("pulse_news",      "PULSE_DATABASE_URL"),
]

# ChromaDB persist directories.
CHROMA_CANDIDATES = [
    ("obsidian_vaults", os.getenv("OBSIDIAN_PERSIST_DIR", "data/chroma/obsidian")),
    ("episodic",        "data/episodic"),
    ("default_chroma",  os.getenv("CHROMA_DB_PATH", "memory_db")),
]

# Obsidian vault paths.
VAULT_CANDIDATES = [
    ("developer", "OBSIDIAN_DEVELOPER_VAULT_PATH"),
    ("runtime",   "OBSIDIAN_RUNTIME_VAULT_PATH"),
]

# JSON datastores: (label, path, purpose).
JSON_CANDIDATES = [
    ("identity",          PROJECT_ROOT / "data" / "identity_default.json",          "core identity"),
    ("trust_states",      PROJECT_ROOT / "data" / "trust_states.json",              "trust state"),
    ("conversation_energy", PROJECT_ROOT / "data" / "conversation_energy_default.json", "conversation energy"),
    ("server_identity",   PROJECT_ROOT / "server" / "data" / "identity_user_default.json", "server identity"),
    ("server_narrative",  PROJECT_ROOT / "server" / "data" / "narrative_user_default.json", "narrative"),
    ("server_personality", PROJECT_ROOT / "server" / "data" / "personality_user_default.json", "personality snapshot"),
]

# Auxiliary directories.
DIR_CANDIDATES = [
    ("users",     PROJECT_ROOT / "data" / "users"),
    ("learning",  PROJECT_ROOT / "data" / "learning"),
    ("federated", PROJECT_ROOT / "data" / "federated"),
    ("episodic_dir", PROJECT_ROOT / "data" / "episodic"),
    ("chroma_dir",   PROJECT_ROOT / "data" / "chroma"),
]


@dataclass
class DataLocation:
    """A single resolved data location."""
    label: str
    path: str
    kind: str                     # sqlite | postgres | chroma | vault | json | dir
    exists: bool = False
    size_bytes: int = 0
    note: str = ""

    @property
    def size_human(self) -> str:
        if self.kind == "postgres":
            return "remote"
        b = self.size_bytes
        if b >= 1 << 30:
            return f"{b / (1 << 30):.2f} GB"
        if b >= 1 << 20:
            return f"{b / (1 << 20):.1f} MB"
        if b >= 1 << 10:
            return f"{b / (1 << 10):.0f} KB"
        return f"{b} B"

    def to_dict(self) -> Dict[str, object]:
        return {
            "label": self.label,
            "path": self.path,
            "kind": self.kind,
            "exists": self.exists,
            "size_bytes": self.size_bytes,
            "size_human": self.size_human,
            "note": self.note,
        }


@dataclass
class SelfKnowledge:
    """Full inventory of where Aariya's data lives."""
    project_root: str
    locations: List[DataLocation] = field(default_factory=list)
    scanned_at: float = 0.0

    def scan(self) -> "SelfKnowledge":
        """Re-resolve every location against the current env + filesystem."""
        self.locations.clear()

        # SQLite
        for label, path in SQLITE_CANDIDATES:
            self.locations.append(_stat_location(label, str(path), "sqlite"))

        # Postgres
        for label, env_name in POSTGRES_CANDIDATES:
            url = os.getenv(env_name, "")
            if url:
                self.locations.append(DataLocation(label, url, "postgres", exists=True, note="configured"))
            else:
                self.locations.append(DataLocation(label, "(not configured)", "postgres", note=f"{env_name} unset"))

        # Chroma
        for label, rel in CHROMA_CANDIDATES:
            p = Path(rel)
            if not p.is_absolute():
                p = PROJECT_ROOT / p
            self.locations.append(_stat_location(label, str(p), "chroma"))

        # Vaults
        for label, env_name in VAULT_CANDIDATES:
            raw = os.getenv(env_name, "")
            if raw:
                self.locations.append(_stat_location(label, raw, "vault"))
            else:
                self.locations.append(DataLocation(label, "(not configured)", "vault", note=f"{env_name} unset"))

        # JSON
        for label, path, purpose in JSON_CANDIDATES:
            loc = _stat_location(label, str(path), "json")
            if not loc.note:
                loc.note = purpose
            self.locations.append(loc)

        # Dirs
        for label, path in DIR_CANDIDATES:
            self.locations.append(_stat_location(label, str(path), "dir"))

        self.scanned_at = time.time()
        return self

    # ── Prompt injection ─────────────────────────────────────────────────────

    def format_for_prompt(self) -> str:
        """
        Human-readable block for the LLM system prompt.
        Aariya reads this as "where my data lives" so she can answer
        questions about her storage honestly.
        """
        if not self.locations:
            self.scan()

        lines = [
            "[self_knowledge] You have direct knowledge of your own data storage. "
            "These are the real locations on disk (verified at runtime):"
        ]

        for kind in ("sqlite", "postgres", "chroma", "vault", "json", "dir"):
            group = [loc for loc in self.locations if loc.kind == kind and loc.exists]
            if not group:
                continue
            label = {
                "sqlite": "SQLite databases",
                "postgres": "PostgreSQL databases",
                "chroma": "Vector memory (ChromaDB)",
                "vault": "Obsidian vaults",
                "json": "JSON datastores",
                "dir": "Auxiliary directories",
            }[kind]
            lines.append(f"- {label}:")
            for loc in group:
                note = f" ({loc.note})" if loc.note else ""
                lines.append(f"    * {loc.label}: {loc.path} [{loc.size_human}]{note}")

        missing = [loc for loc in self.locations if not loc.exists and loc.kind != "postgres"]
        if missing:
            lines.append("- Not currently present (may be created on demand):")
            for loc in missing:
                lines.append(f"    * {loc.label}: {loc.path}")

        lines.append(
            "You may refer to these paths when asked about your data, memory, "
            "or files. Do not fabricate locations that are not listed here."
        )
        return "\n".join(lines)

    def inventory_json(self) -> Dict[str, object]:
        """Machine-readable snapshot for the /api/self-knowledge endpoint."""
        return {
            "project_root": self.project_root,
            "scanned_at": self.scanned_at,
            "data_root": str(PROJECT_ROOT / "data"),
            "locations": [loc.to_dict() for loc in self.locations],
        }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _stat_location(label: str, path: str, kind: str) -> DataLocation:
    """Check existence + size of a single path."""
    p = Path(path).expanduser()
    try:
        if p.is_file():
            return DataLocation(label, str(p), kind, exists=True, size_bytes=p.stat().st_size)
        if p.is_dir():
            total = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            return DataLocation(label, str(p), kind, exists=True, size_bytes=total)
    except OSError as exc:
        logger.debug("[SelfKnowledge] stat failed for %s: %s", path, exc)
    return DataLocation(label, str(p), kind)


# ── Singleton ────────────────────────────────────────────────────────────────

_self_knowledge: Optional[SelfKnowledge] = None
_last_scan: float = 0.0
_SCAN_TTL_SECONDS = 300.0   # re-scan at most every 5 min to stay cheap


def get_self_knowledge(refresh: bool = False) -> SelfKnowledge:
    """Get the cached inventory, re-scanning if stale or refresh requested."""
    global _self_knowledge, _last_scan
    now = time.time()
    if (
        _self_knowledge is None
        or refresh
        or (now - _last_scan) > _SCAN_TTL_SECONDS
    ):
        _self_knowledge = SelfKnowledge(project_root=str(PROJECT_ROOT)).scan()
        _last_scan = now
        logger.debug("[SelfKnowledge] inventory scanned (%d locations)", len(_self_knowledge.locations))
    return _self_knowledge


def format_self_knowledge_prompt() -> str:
    """Convenience wrapper for prompt injection."""
    return get_self_knowledge().format_for_prompt()


if __name__ == "__main__":
    import sys
    sk = get_self_knowledge(refresh=True)
    mode = sys.argv[1] if len(sys.argv) > 1 else "prompt"
    if mode == "json":
        print(json.dumps(sk.inventory_json(), indent=2))
    else:
        print(sk.format_for_prompt())
