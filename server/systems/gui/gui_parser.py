"""
GUI Parser — reads text off the screen and locates buttons by template.

Requires pyautogui + pytesseract. Optional: reports `available` so callers
can degrade. Template matching needs pre-saved button PNGs under `templates/`.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("aariya.gui_parser")

try:
    import pyautogui
    import pytesseract
    _PG = True
except ImportError:
    _PG = False


class GUIParser:
    def __init__(self, templates_dir: str = "templates"):
        self.available = _PG
        self.templates_dir = Path(templates_dir)

    def extract_text(self) -> str:
        if not self.available:
            return ""
        try:
            img = pyautogui.screenshot()
            return pytesseract.image_to_string(img)
        except Exception as e:
            logger.warning(f"[gui] text extract failed: {e}")
            return ""

    def find_button(self, label: str, confidence: float = 0.8):
        if not self.available:
            return None
        template = self.templates_dir / f"{label}.png"
        if not template.exists():
            logger.warning(f"[gui] template missing: {template}")
            return None
        try:
            return pyautogui.locateOnScreen(str(template), confidence=confidence)
        except Exception as e:
            logger.warning(f"[gui] find button failed {label}: {e}")
            return None
