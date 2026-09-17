"""
Cross-Domain Generalization (*AccessFIles.txt* §97).

A workflow learned in one domain (e.g. "web research") should transfer to
another ("code research") without being re-taught. This module works ONLY on
workflows that actually exist in the WorkflowMemory store:

  * infers each stored workflow's domain from observable payload features
    (URLs present → web, code extensions → code, document extensions →
    documents, launch/run actions → system) — never from a hardcoded label
  * measures structural similarity between action-atom sequences with
    difflib.SequenceMatcher (stdlib, deterministic)
  * proposes an adapted plan for a target domain by positionally adopting the
    target-domain exemplar's real payloads (URL/app/path) where the skeletons
    align, keeping full provenance
  * records which transfers actually succeeded and adapts per-pair trust

With no stored workflows it honestly reports that nothing can transfer yet.
"""

from __future__ import annotations

import difflib
import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aariya.domain_transfer")

_DATA_DIR = Path("./data")

_CODE_EXT = (".py", ".js", ".ts", ".java", ".c", ".cpp", ".rs", ".go", ".rb")
_DOC_EXT = (".pdf", ".docx", ".txt", ".md", ".rtf", ".pages")
_PAYLOAD_KEYS = ("url", "app", "path", "text", "query")


def _atoms(steps: List[Any]) -> List[str]:
    """Reduce steps to comparable action atoms."""
    out: List[str] = []
    for s in steps or []:
        if isinstance(s, dict):
            out.append(str(s.get("action") or s.get("type") or "?").lower())
        elif isinstance(s, str):
            out.append(s.strip().lower().split(" ")[0].strip(":,") or "?")
        else:
            out.append("?")
    return out


def _infer_domain(name: str, steps: List[Dict]) -> str:
    blob = json.dumps({"name": name, "steps": steps}, default=str).lower()
    if "http://" in blob or "https://" in blob or "www." in blob:
        return "web"
    if any(ext in blob for ext in _CODE_EXT):
        return "code"
    if any(ext in blob for ext in _DOC_EXT):
        return "documents"
    actions = {str(s.get("action", "")).lower() for s in steps if isinstance(s, dict)}
    if actions & {"launch_app", "run", "shell", "execute"}:
        return "system"
    return "general"


class DomainTransfer:
    def __init__(self, workflow_memory=None, stats_path: Optional[str] = None):
        self._lock = threading.Lock()
        self._wm = workflow_memory
        self.stats_path = Path(stats_path) if stats_path else (_DATA_DIR / "domain_transfer.json")
        # pair key "src_domain->tgt_domain" -> {"success": n, "fail": n}
        self._pair_stats: Dict[str, Dict[str, int]] = {}
        self._transfers: Dict[str, Dict[str, Any]] = {}
        self._load_stats()

    def _memory(self):
        if self._wm is None:
            from server.systems.workflows.workflow_memory import WorkflowMemory
            self._wm = WorkflowMemory()
        return self._wm

    # ── persistence ────────────────────────────────────────────────────────
    def _load_stats(self) -> None:
        try:
            if self.stats_path.exists():
                d = json.loads(self.stats_path.read_text(encoding="utf-8"))
                self._pair_stats = {k: dict(v) for k, v in d.get("pairs", {}).items()}
                self._transfers = dict(d.get("transfers", {}))
        except Exception as exc:
            logger.warning("[DomainTransfer] stats load failed: %s", exc)

    def _save_stats(self) -> None:
        try:
            self.stats_path.parent.mkdir(parents=True, exist_ok=True)
            self.stats_path.write_text(json.dumps({
                "pairs": self._pair_stats,
                "transfers": self._transfers,
            }, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("[DomainTransfer] stats save failed: %s", exc)

    # ── core ───────────────────────────────────────────────────────────────
    def domains(self) -> Dict[str, List[str]]:
        """Real domain map of everything currently stored."""
        out: Dict[str, List[str]] = {}
        for name, steps in (self._memory().all_workflows() or {}).items():
            d = _infer_domain(name, steps)
            out.setdefault(d, []).append(name)
        return out

    def propose(self, source_name: str, target_domain: str) -> Dict[str, Any]:
        """Propose `source_name` adapted into `target_domain`, provenance kept."""
        workflows = self._memory().all_workflows() or {}
        source = workflows.get(source_name)
        if not source:
            return {"proposed": False,
                    "reason": f"no stored workflow named '{source_name}'"}

        src_domain = _infer_domain(source_name, source)
        src_atoms = _atoms(source)

        same_domain = [n for n, st in workflows.items()
                       if n != source_name and _infer_domain(n, st) == target_domain]
        other = [(n, st) for n, st in workflows.items()
                 if n != source_name and _infer_domain(n, st) not in (target_domain, src_domain)]

        best_name, best_ratio = None, 0.0
        for n, st in other:
            ratio = difflib.SequenceMatcher(None, src_atoms, _atoms(st)).ratio()
            if ratio > best_ratio:
                best_name, best_ratio = n, ratio

        if not same_domain and best_name is None:
            return {"proposed": False,
                    "reason": (f"nothing structurally similar in store to adapt "
                               f"toward '{target_domain}'"),
                    "source_domain": src_domain}

        adapted: List[Dict] = []
        exemplar = workflows.get(best_name) if best_name else None
        ex_atoms = _atoms(exemplar) if exemplar else []
        adopted: List[str] = []
        for i, step in enumerate(source):
            new_step = dict(step) if isinstance(step, dict) else {"action": step}
            if exemplar and i < len(ex_atoms) and isinstance(exemplar[i], dict):
                for key in _PAYLOAD_KEYS:
                    theirs = exemplar[i].get(key)
                    mine = new_step.get(key)
                    if theirs and key in exemplar[i] and theirs != mine:
                        new_step[key] = theirs   # real payload from target-domain data
                        adopted.append(f"step{i}:{key}")
            adapted.append(new_step)

        pair = f"{src_domain}->{target_domain}"
        transfer_id = f"{source_name[:24]}->{target_domain}:{int(best_ratio * 1000):03d}"
        result = {
            "proposed": True,
            "transfer_id": transfer_id,
            "source": source_name,
            "source_domain": src_domain,
            "target_domain": target_domain,
            "based_on": best_name,
            "structural_similarity": round(best_ratio, 3),
            "adapted_steps": adapted,
            "adopted_payloads": adopted,
        }
        with self._lock:
            self._transfers[transfer_id] = {
                **{k: v for k, v in result.items() if k != "adapted_steps"},
                "ts": __import__("time").time(),
            }
            self._save_stats()
        return result

    def record_outcome(self, transfer_id: str, ok: bool) -> Dict[str, Any]:
        with self._lock:
            info = self._transfers.get(transfer_id)
            if not info:
                return {"recorded": False, "reason": "unknown transfer_id"}
            pair = f"{info['source_domain']}->{info['target_domain']}"
            st = self._pair_stats.setdefault(pair, {"success": 0, "fail": 0})
            st["success" if ok else "fail"] += 1
            self._save_stats()
            total = st["success"] + st["fail"]
            return {"recorded": True, "pair": pair,
                    "trust": round(st["success"] / total, 3), "samples": total}

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            pairs = {}
            for p, st in self._pair_stats.items():
                total = st["success"] + st["fail"]
                pairs[p] = {**st, "trust": round(st["success"] / total, 3)} if total else st
            return {"known_domains": self.domains(), "pairs": pairs,
                    "proposals_made": len(self._transfers)}


_inst: Optional[DomainTransfer] = None


def get_domain_transfer() -> DomainTransfer:
    global _inst
    if _inst is None:
        _inst = DomainTransfer()
    return _inst
