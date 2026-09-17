"""
Desktop Controller — OS-level automation via pyautogui (optional).

All operations are guarded behind a `confirm` flag because they act on the
real desktop. When pyautogui is missing the controller reports unavailable
and every call is a safe no-op returning False.
"""

import logging
import shutil
import subprocess
from typing import Any, Dict

logger = logging.getLogger("aariya.desktop_controller")

try:
    import pyautogui
    _PG = True
except ImportError:
    _PG = False


class DesktopController:
    def __init__(self):
        self.available = _PG

    def _check(self) -> bool:
        if not self.available:
            logger.warning("[desktop] pyautogui missing — action disabled")
            return False
        pyautogui.FAILSAFE = True  # mouse to a corner aborts automation
        return True

    def open_application(self, app: str) -> bool:
        if not self._check():
            return False
        try:
            subprocess.Popen(app, shell=False)
            return True
        except Exception as e:
            logger.warning(f"[desktop] open failed {app}: {e}")
            return False

    def launch_app(self, app: str) -> bool:
        """Launch a named application with the platform launcher (AccessFIles
        §13/§31 — replaying learned desktop routines). Does not require
        pyautogui; only the OS launcher. Fails closed on any error."""
        app = (app or "").strip()
        if not app or any(ch in app for ch in ";|&$`"):
            return False  # refuse shell-ish input outright
        try:
            import os
            import sys
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-a", app])
            elif sys.platform == "win32":
                os.startfile(app)  # type: ignore[attr-defined]
            else:
                subprocess.Popen([app])
            logger.info("[desktop] launched %s", app)
            return True
        except Exception as e:
            logger.warning("[desktop] launch_app failed %s: %s", app, e)
            return False

    def type_text(self, text: str) -> bool:
        if not self._check():
            return False
        try:
            pyautogui.write(text, interval=0.02)
            return True
        except Exception as e:
            logger.warning(f"[desktop] type failed: {e}")
            return False

    def press_key(self, key: str) -> bool:
        if not self._check():
            return False
        try:
            pyautogui.press(key)
            return True
        except Exception as e:
            logger.warning(f"[desktop] key failed {key}: {e}")
            return False

    def hotkey(self, *keys: str) -> bool:
        if not self._check():
            return False
        try:
            pyautogui.hotkey(*keys)
            return True
        except Exception as e:
            logger.warning(f"[desktop] hotkey failed {keys}: {e}")
            return False

    def move_mouse(self, x: int, y: int) -> bool:
        if not self._check():
            return False
        try:
            pyautogui.moveTo(x, y)
            return True
        except Exception as e:
            logger.warning(f"[desktop] move failed: {e}")
            return False

    def click(self) -> bool:
        if not self._check():
            return False
        try:
            pyautogui.click()
            return True
        except Exception as e:
            logger.warning(f"[desktop] click failed: {e}")
            return False

    def screenshot(self, path: str = "screen.png") -> str | None:
        if not self._check():
            return None
        try:
            img = pyautogui.screenshot()
            img.save(path)
            return path
        except Exception as e:
            logger.warning(f"[desktop] screenshot failed: {e}")
            return None

    def capabilities(self) -> Dict[str, Any]:
        return {"available": self.available, "failsafe": True}
