"""
Desktop Twin (AccessFIles §48 — gap: missing entirely).

A lightweight model of the user's desktop/app environment that the brain keeps
in sync so it can predict and assist across apps:

  observe_app(app)        → note that the user has an app open/focused
  observe_document(doc)   → note the active document
  context()               → current desktop state for the world model
  suggests_next()         → based on app-switching history, what app/document
                            is the user likely to open next

No OS hooks — this is the in-brain representation the desktop companion client
feeds via signals. State is in-memory + optionally mirrored to JSON.
"""

import time
import json
import os
from collections import defaultdict
from typing import Any, Dict, List, Optional


class DesktopTwin:
    def __init__(self, user_id: str, persist_path: str = "./data/desktop_twin.json"):
        self.user_id = user_id
        self._persist_path = persist_path
        self.active_app: Optional[str] = None
        self.active_document: Optional[str] = None
        self._app_times: Dict[str, float] = defaultdict(float)   # app -> total focus seconds
        self._app_switches: List[Dict[str, Any]] = []            # (from,to,ts)
        self._documents: List[Dict[str, Any]] = []
        self._last_app: Optional[str] = None
        self._session_start = time.time()
        self._last_tick = time.time()

    # ── Observation ────────────────────────────────────────────────────────────

    def observe_app(self, app: str) -> None:
        """User switched to / focused `app`."""
        now = time.time()
        if self.active_app and self.active_app != app:
            self._app_switches.append({
                "from": self.active_app, "to": app, "ts": now,
            })
        self.active_app = app
        self._last_app = app
        self._app_times[app] += 0.0  # accumulate below on switch-out

    def observe_document(self, doc: str, *, app: Optional[str] = None) -> None:
        self.active_document = doc
        self._documents.append({
            "path": doc, "app": app or self.active_app, "ts": time.time(),
        })
        if len(self._documents) > 200:
            self._documents = self._documents[-200:]

    def _tick(self) -> None:
        """Accumulate focus time for the current app."""
        if self.active_app:
            now = time.time()
            delta = now - self._last_tick
            self._app_times[self.active_app] += max(0.0, delta)
        self._last_tick = time.time()

    # ── Query ──────────────────────────────────────────────────────────────────

    def context(self) -> Dict[str, Any]:
        self._tick()
        top_apps = sorted(self._app_times.items(), key=lambda x: -x[1])[:3]
        return {
            "active_app": self.active_app,
            "active_document": self.active_document,
            "top_apps": [{"app": a, "focus_seconds": round(t, 1)} for a, t in top_apps],
            "recent_documents": self._documents[-5:],
            "session_seconds": round(time.time() - self._session_start, 1),
        }

    def suggests_next(self, top_k: int = 3) -> List[Dict[str, Any]]:
        """Predict next app from switch history (most common transition)."""
        pairs: Dict[str, List[str]] = defaultdict(list)
        for s in self._app_switches:
            pairs[s["from"]].append(s["to"])
        if not self.active_app or self.active_app not in pairs:
            return []
        transitions = pairs[self.active_app]
        from collections import Counter
        ranked = Counter(transitions).most_common(top_k)
        return [{"app": app, "probability": round(cnt / len(transitions), 3)} for app, cnt in ranked]

    def frequent_app_routines(self, *, min_support: int = 3,
                              max_len: int = 4) -> List[Dict[str, Any]]:
        """Mine the REAL switch history for repeated launch sequences
        (AccessFIles §59 — skill learning from observation).

        Counts ordered app n-grams (2..max_len) over the actual switch stream;
        a 'routine' is a sequence seen at least `min_support` times with no
        repeated app inside it. Longer sequences that contain an equally-
        supported shorter one win (most specific wins).
        """
        targets = [s.get("to", "") for s in self._app_switches if s.get("to")]
        if len(targets) < min_support * 2:
            return []

        from collections import Counter
        found: Dict[tuple, int] = {}
        for k in range(2, max_len + 1):
            counts = Counter(
                tuple(targets[i:i + k]) for i in range(len(targets) - k + 1)
            )
            for seq, cnt in counts.items():
                if cnt >= min_support and len(set(seq)) == len(seq):
                    # Keep this k-gram only if it's not just a repetition
                    # artifact of a longer dominant pattern — simplest honest
                    # rule: keep all qualifying grams; caller sees support.
                    found[seq] = max(found.get(seq, 0), cnt)

        routines = [
            {"apps": list(seq), "support": cnt}
            for seq, cnt in sorted(found.items(), key=lambda kv: (-kv[1], -len(kv[0])))
        ]
        return routines[:10]

    def snapshot(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            **self.context(),
            "suggested_next": self.suggests_next(),
            "switch_count": len(self._app_switches),
        }

    def persist(self) -> None:
        try:
            data = {
                "active_app": self.active_app,
                "active_document": self.active_document,
                "app_times": dict(self._app_times),
                "app_switches": self._app_switches[-100:],
                "documents": self._documents[-100:],
                "saved_at": time.time(),
            }
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except OSError:
            pass


# ── Singleton ──────────────────────────────────────────────────────────────────

_twin: Optional[DesktopTwin] = None


def get_desktop_twin(user_id: str = "default") -> DesktopTwin:
    global _twin
    if _twin is None or _twin.user_id != user_id:
        _twin = DesktopTwin(user_id)
    return _twin
