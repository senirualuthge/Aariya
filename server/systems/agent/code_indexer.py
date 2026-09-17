"""
Codebase Intelligence (AccessFIles §70 — repository graph indexing).

Parses REAL Python source under an allowed root with the stdlib `ast` module
and folds the structure into the persistent KnowledgeGraph as triples:

    <file>  defines_function   <name>
    <file>  defines_class      <name>
    <file>  imports_module     <module>
    <class> inherits_from      <base>

No tree-sitter dependency, no fabricated symbols — every triple comes from
parsing actual files on disk. Bounded (max_files / max_lines) so a huge
checkout can't stall the caller; runs fine in a worker thread via the API.
"""

import ast
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger("aariya.agent.code_indexer")

DEFAULT_MAX_FILES = int(os.getenv("AARIYA_CODE_INDEX_MAX_FILES", "400"))
MAX_LINES_PER_FILE = 20_000


def _iter_python_files(root: str, max_files: int) -> List[str]:
    found: List[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip dependency/vendor noise — never useful in a knowledge graph.
        dirnames[:] = [d for d in dirnames if d not in
                       (".venv", "venv", "node_modules", "__pycache__",
                        ".git", "dist", "build", ".mypy_cache", ".pytest_cache")]
        for fn in filenames:
            if fn.endswith(".py"):
                found.append(os.path.join(dirpath, fn))
                if len(found) >= max_files:
                    return found
    return found


def index_python_repo(root: str, *, max_files: int = DEFAULT_MAX_FILES) -> Dict[str, Any]:
    """AST-parse the repo and add structural triples to the knowledge graph.

    Returns a real summary of what was parsed — callers surface it verbatim.
    """
    from server.safety.filesystem_guard import validate_path
    from server.systems.agent.knowledge_graph import kg

    allowed = validate_path(root, require_exists=True)
    if allowed is None or not os.path.isdir(allowed):
        return {"ok": False, "error": f"root not allowed or missing: {root}"}

    files = _iter_python_files(allowed, max_files)
    functions = classes = imports = edges = parse_errors = 0

    for path in files:
        rel = os.path.relpath(path, allowed)
        try:
            if os.path.getsize(path) > MAX_LINES_PER_FILE * 60:
                continue  # absurdly large generated file — skip
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                source = f.read(MAX_LINES_PER_FILE * 120)
            tree = ast.parse(source)
        except (OSError, SyntaxError, ValueError):
            parse_errors += 1
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                kg.add_triple(rel, "defines_function", node.name)
                functions += 1
                edges += 1
            elif isinstance(node, ast.ClassDef):
                kg.add_triple(rel, "defines_class", node.name)
                classes += 1
                edges += 1
                for base in node.bases:
                    base_name = getattr(base, "id", None) or getattr(base, "attr", None)
                    if base_name:
                        kg.add_triple(node.name, "inherits_from", base_name,
                                      {"file": rel})
                        edges += 1
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    kg.add_triple(rel, "imports_module", alias.name.split(".")[0])
                    imports += 1
                    edges += 1
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    kg.add_triple(rel, "imports_module", node.module.split(".")[0])
                    imports += 1
                    edges += 1

    summary = {
        "ok": True,
        "root": allowed,
        "files_parsed": len(files) - parse_errors,
        "parse_errors": parse_errors,
        "functions": functions,
        "classes": classes,
        "imports": imports,
        "graph_edges_added": edges,
    }
    logger.info("[code_indexer] %s", summary)
    return summary


def symbol_usages(symbol: str) -> Dict[str, Any]:
    """Graph query: where a symbol is defined / which files reference it.
    Combines incoming (file → defines → symbol) and outgoing edges."""
    from server.systems.agent.knowledge_graph import kg

    facts = kg.query_incoming(symbol) + kg.query(symbol)
    return {"symbol": symbol, "facts": facts, "count": len(facts)}
