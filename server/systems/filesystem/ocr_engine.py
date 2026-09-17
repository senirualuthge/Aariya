"""
OCR engine — image + PDF text extraction.

Layers pytesseract (image OCR) and pymupdf (PDF). PDF pages without a text
layer are rendered to a temp image and OCR'd. Both deps are optional; the
engine reports `available` so callers can degrade gracefully.
"""

import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger("aariya.ocr_engine")

try:
    import pytesseract
    import PIL.Image as PILImage
    _TESSERACT = True
except ImportError:
    _TESSERACT = False

try:
    import fitz  # PyMuPDF
    _PDF = True
except ImportError:
    _PDF = False


class OCREngine:
    def __init__(self):
        self.available = _TESSERACT and _PDF

    def image_to_text(self, path: str) -> str:
        if not _TESSERACT:
            return ""
        try:
            image = PILImage.open(path)
            return pytesseract.image_to_string(image)
        except Exception as e:
            logger.warning(f"[ocr] image failed {path}: {e}")
            return ""

    def pdf_to_text(self, path: str) -> str:
        if not _PDF:
            return ""
        try:
            doc = fitz.open(path)
            full_text = []
            for i, page in enumerate(doc):
                text = page.get_text()
                if not text.strip():
                    text = self._ocr_page(page, i)
                full_text.append(text)
            doc.close()
            return "\n".join(full_text)
        except Exception as e:
            logger.warning(f"[ocr] pdf failed {path}: {e}")
            return ""

    def _ocr_page(self, page, index: int) -> str:
        if not _TESSERACT:
            return ""
        try:
            pix = page.get_pixmap()
            fd, img_path = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            pix.save(img_path)
            try:
                return self.image_to_text(img_path)
            finally:
                try:
                    os.remove(img_path)
                except OSError:
                    pass
        except Exception as e:
            logger.warning(f"[ocr] page {index} failed: {e}")
            return ""
