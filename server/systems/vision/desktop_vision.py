"""
Desktop Vision — screen capture for the vision/GUI pipeline.

Uses pyautogui for capture and OpenCV (numpy) for frame conversion. Optional
deps: every method returns None/empty when unavailable.
"""

import logging
from typing import Optional

logger = logging.getLogger("aariya.desktop_vision")

try:
    import pyautogui
    import numpy as np
    _PG = True
except ImportError:
    _PG = False


class DesktopVision:
    def __init__(self):
        self.available = _PG

    def capture_screen(self):
        """Return an RGB numpy frame (H, W, 3) or None."""
        if not self.available:
            return None
        try:
            return np.array(pyautogui.screenshot())
        except Exception as e:
            logger.warning(f"[vision] capture failed: {e}")
            return None

    def capture_region(self, x: int, y: int, w: int, h: int):
        if not self.available:
            return None
        try:
            return np.array(pyautogui.screenshot(region=(x, y, w, h)))
        except Exception as e:
            logger.warning(f"[vision] region capture failed: {e}")
            return None
