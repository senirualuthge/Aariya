"""
Automatic indexing daemon — background bulk-scan of allowed directories.

Runs a full `rglob` scan on a background thread so a cold boot over a large
folder never blocks the request loop. Honors the filesystem guard (only walks
allowed roots) and the OCR engine for rich formats.
"""

import logging
import threading
import time
from pathlib import Path

from server.safety.filesystem_guard import validate_path
from server.systems.filesystem.ocr_engine import OCREngine

logger = logging.getLogger("aariya.indexing_daemon")

INDEXABLE = {".txt", ".md", ".py", ".json", ".csv", ".yaml", ".yml", ".log"}


class AdvancedIndexer:
    """Extracts text from plain + rich formats, feeding a FileMemoryIndexer."""

    def __init__(self, indexer, ocr: OCREngine | None = None):
        self.indexer = indexer
        self.ocr = ocr or OCREngine()

    def extract_text(self, path: str) -> str:
        ext = Path(path).suffix.lower()
        if ext in INDEXABLE:
            try:
                return Path(path).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                return ""
        if ext == ".pdf" and self.ocr.available:
            return self.ocr.pdf_to_text(path)
        if ext in {".png", ".jpg", ".jpeg"} and self.ocr.available:
            return self.ocr.image_to_text(path)
        return ""


class AutoIndexer:
    def __init__(self, indexer):
        self.indexer = indexer
        self.advanced = AdvancedIndexer(indexer)
        self._stop = threading.Event()

    def scan_directory(self, root: str, *, max_files: int = 2000):
        resolved = validate_path(root, require_exists=True)
        if resolved is None:
            logger.warning(f"[autoindex] root not allowed: {root}")
            return 0
        count = 0
        for path in Path(resolved).rglob("*"):
            if self._stop.is_set():
                break
            if path.is_file():
                ext = path.suffix.lower()
                if ext in INDEXABLE or ext in {".pdf", ".png", ".jpg", ".jpeg"}:
                    text = self.advanced.extract_text(str(path))
                    if text and self.indexer.index_file(str(path), text):
                        count += 1
                    if count >= max_files:
                        break
        logger.info(f"[autoindex] scanned {root}: {count} files indexed")
        return count

    def background_scan(self, root: str, *, max_files: int = 2000):
        thread = threading.Thread(
            target=self.scan_directory,
            args=(root,),
            kwargs={"max_files": max_files},
            daemon=True,
            name=f"autoindex-{Path(root).name}",
        )
        thread.start()
        return thread

    def shutdown(self):
        self._stop.set()
