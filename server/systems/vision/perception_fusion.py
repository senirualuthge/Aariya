"""
True Multimodal Perception (*AccessFIles.txt* §68).

Camera, microphone, screen, documents and desktop state exist as separate
probes today; this module fuses whatever is REALLY available right now into
one perception snapshot and pushes it into the WorldModel, so cognition sees
a single stream instead of scattered channels.

Channels are opt-in where they are expensive:
  * screen  — DesktopVision frame (pyautogui+cv2); honestly unavailable when
              those aren't installed or no display can be captured
  * gui     — GUIParser OCR of the screen (tesseract)
  * desktop — the desktop twin's real observation context
  * meeting — live audio/VAD ambience from MeetingMode
  * environment — §88 aggregated machine/hardware/time context

Every channel reports either real data or a truthful unavailability reason.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("aariya.perception_fusion")


class PerceptionFusion:
    def __init__(self):
        self._lock = threading.Lock()
        self._last: Dict[str, Any] = {}

    def fuse(self, *, include_screen: bool = False,
             include_gui_text: bool = False,
             user_id: str = "default",
             push_to_world_model: bool = True,
             world_model: Optional[Any] = None) -> Dict[str, Any]:
        channels: Dict[str, Any] = {}
        text_parts: list = []

        # ── screen frame ────────────────────────────────────────────────
        if include_screen:
            try:
                from server.systems.vision.desktop_vision import DesktopVision
                frame = DesktopVision().capture_screen()
                shape = getattr(frame, "shape", None)
                channels["screen"] = {
                    "available": shape is not None,
                    "frame_shape": list(shape) if shape is not None else None,
                    "reason": None if shape is not None else "capture returned no frame",
                }
            except Exception as exc:
                channels["screen"] = {"available": False, "reason": f"unavailable: {exc}"}

        # ── OCR'd on-screen text ────────────────────────────────────────
        if include_gui_text:
            try:
                from server.systems.gui.gui_parser import GUIParser
                text = str(GUIParser().extract_text() or "").strip()
                channels["gui_text"] = {"available": bool(text),
                                        "chars": len(text),
                                        "text": text or None,
                                        "reason": None if text else "OCR produced no text"}
                if text:
                    text_parts.append(f"onscreen: {text[:400]}")
            except Exception as exc:
                channels["gui_text"] = {"available": False, "reason": f"unavailable: {exc}"}

        # ── desktop focus context ───────────────────────────────────────
        try:
            from server.systems.desktop_twin import get_desktop_twin
            ctx = get_desktop_twin(user_id).context()
            channels["desktop"] = {"available": True, "context": ctx}
            if ctx.get("active_app"):
                text_parts.append(f"active app: {ctx['active_app']}")
            if ctx.get("active_document"):
                text_parts.append(f"active document: {ctx['active_document']}")
        except Exception as exc:
            channels["desktop"] = {"available": False, "reason": f"unavailable: {exc}"}

        # ── audio / conversation ambience ───────────────────────────────
        try:
            from server.systems.meeting_mode import get_meeting_mode
            status = get_meeting_mode().get_status()
            channels["meeting"] = {"available": True, "status": status}
        except Exception as exc:
            channels["meeting"] = {"available": False, "reason": f"unavailable: {exc}"}

        # ── broader environment (§88) ───────────────────────────────────
        try:
            from server.systems.cognition.environment_context import get_environment_context
            env = get_environment_context().snapshot()
            channels["environment"] = {"available": True, "snapshot": env}
            tod = ((env.get("time") or {}).get("part_of_day"))
            if tod:
                text_parts.append(f"time of day: {tod}")
        except Exception as exc:
            channels["environment"] = {"available": False, "reason": f"unavailable: {exc}"}

        fused_text = " | ".join(text_parts)
        available = sorted(k for k, v in channels.items()
                           if isinstance(v, dict) and v.get("available"))
        result = {
            "ts": time.time(),
            "channels": channels,
            "available_channels": available,
            "fused_text": fused_text,
        }

        if push_to_world_model:
            try:
                if world_model is None:   # default: the live kernel's model
                    from server.systems.cognition.cognitive_kernel import get_cognitive_kernel
                    world_model = get_cognitive_kernel().world_model
                perception = {
                    "ts": result["ts"], "available_channels": available,
                    "fused_text": fused_text}
                env_state = world_model.get("environment")
                # WorldModel has fixed slots — merge into `environment`.
                world_model.update("environment",
                                   {**env_state, "perception": perception}
                                   if isinstance(env_state, dict) else {"perception": perception})
                world_model.record_event({"type": "perception_fusion",
                                          "channels": available})
            except Exception as exc:
                logger.debug("[PerceptionFusion] world model push failed: %s", exc)

        with self._lock:
            self._last = result
        return result

    def status(self) -> Dict[str, Any]:
        with self._lock:
            last = self._last
            return {
                "last_ts": last.get("ts"),
                "last_available_channels": last.get("available_channels", []),
            }


_inst: Optional[PerceptionFusion] = None


def get_perception_fusion() -> PerceptionFusion:
    global _inst
    if _inst is None:
        _inst = PerceptionFusion()
    return _inst
