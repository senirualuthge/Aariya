"""
Self-Modeling (doc *AccessFIles §9) — Aariya's model of her own capabilities,
limitations, tools, and confidence. Used for safer autonomy, planning, and
reliability: she knows what she can (and cannot) do before committing to it.

`get_self_model()` is the singleton entry point. `register_capability` lets
other systems (agents, controllers) declare their capabilities at startup so
the model reflects the live runtime rather than a hardcoded guess.
"""

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("aariya.self_model")

_LOCK = threading.Lock()


class SelfModel:
    def __init__(self):
        self.capabilities: Dict[str, Dict[str, Any]] = {}
        self._verifiers: Dict[str, Callable[[], Any]] = {}

    def register_capability(
        self,
        name: str,
        available: bool,
        confidence: float = 1.0,
        verifier: Optional[Callable[[], Any]] = None,
    ) -> None:
        """Declare (or update) a capability with a confidence estimate."""
        with _LOCK:
            self.capabilities[name] = {
                "available": bool(available),
                "confidence": max(0.0, min(1.0, float(confidence))),
            }
            if verifier is not None:
                self._verifiers[name] = verifier

    def _live_check(self, name: str) -> bool:
        verifier = self._verifiers.get(name)
        if verifier is None:
            return self.capabilities.get(name, {}).get("available", False)
        try:
            return bool(verifier())
        except Exception as exc:
            logger.debug(f"[SelfModel] verifier for {name!r} failed: {exc}")
            return False

    def can(self, name: str) -> bool:
        """Live availability of a capability (verifier-aware)."""
        return self._live_check(name)

    def confidence(self, name: str) -> float:
        return self.capabilities.get(name, {}).get("confidence", 0.0)

    def summary(self) -> Dict[str, Any]:
        """Full self-model dict (doc §9 shape: can_*, confidence)."""
        result: Dict[str, Any] = {}
        for name, cap in self.capabilities.items():
            result[f"can_{name}"] = self._live_check(name)
        result["confidence"] = round(self._average_confidence(), 3)
        result["capabilities"] = {
            name: cap.get("confidence", 0.0) for name, cap in self.capabilities.items()
        }
        return result

    def _average_confidence(self) -> float:
        confs = [c.get("confidence", 0.0) for c in self.capabilities.values()]
        return sum(confs) / len(confs) if confs else 0.0


_self_model: Optional[SelfModel] = None


def get_self_model() -> SelfModel:
    global _self_model
    if _self_model is None:
        _self_model = SelfModel()
    return _self_model


def register_default_capabilities() -> SelfModel:
    """Seed the model with the capabilities we actually ship."""
    model = get_self_model()
    model.register_capability("access_files", True, 0.9)
    model.register_capability("control_browser", True, 0.5)
    model.register_capability("search_local_knowledge", True, 0.85)
    model.register_capability("voice_control", True, 0.7)
    return model
