"""
Live filesystem watcher — auto-indexes documents as they change.

Uses watchdog (optional). When absent, the daemon falls back to periodic
scanning. The handler reuses the advanced indexer's extract_text so .md/.txt/
.pdf/.docx/images all land in semantic memory.
"""

import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger("aariya.live_watcher")

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    _WATCHDOG = True
except ImportError:
    _WATCHDOG = False


class LiveFileHandler(FileSystemEventHandler):
    def __init__(self, indexer):
        self.indexer = indexer
        self._debounce: dict[str, float] = {}
        self._lock = threading.Lock()

    def on_created(self, event):
        if not event.is_directory:
            self.process(str(event.src_path))

    def on_modified(self, event):
        if not event.is_directory:
            self.process(str(event.src_path))

    def process(self, path: str):
        ext = Path(path).suffix.lower()
        if ext not in {".txt", ".md", ".py", ".json", ".csv", ".pdf", ".docx", ".png", ".jpg", ".jpeg"}:
            return
        # Debounce: writers touch a file many times per second.
        now = time.monotonic()
        with self._lock:
            if self._debounce.get(path, 0) + 1.0 > now:
                return
            self._debounce[path] = now
        try:
            text = self.indexer.extract_text(path)
            if text:
                self.indexer.index_file(path, text)
                logger.info(f"[watcher] indexed {path}")
        except Exception as e:
            logger.warning(f"[watcher] failed {path}: {e}")


class LiveWatcher:
    def __init__(self, indexer):
        self.indexer = indexer
        self.observer = Observer() if _WATCHDOG else None
        self._watching = []

    def watch(self, path: str, *, recursive: bool = True) -> bool:
        if self.observer is None:
            logger.warning("[watcher] watchdog missing — watching disabled")
            return False
        handler = LiveFileHandler(self.indexer)
        self.observer.schedule(handler, path, recursive=recursive)
        self._watching.append(path)
        logger.info(f"[watcher] watching {path}")
        return True

    def start(self):
        if self.observer:
            self.observer.start()

    def stop(self):
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=3)
