"""
Filesystem background service — boot wiring for the watcher/indexer/desktop twin.

Started once from the AutonomyDaemon.start() so the filesystem layer comes
alive alongside the 24/7 proactive brain:

  * AutoIndexer.background_scan over the allowed roots (cold-boot bulk index,
    capped, so a huge folder never blocks the request loop).
  * LiveWatcher (watchdog, optional) so edited/new docs land in semantic
    memory within ~1s instead of waiting for the next bulk scan.
  * Feeds the DesktopTwin real "active document" observations from watcher
    events, so the brain's model of the user's environment stays current.

Every subsystem degrades gracefully: when watchdog/chromadb/sentence-
transformers are absent the service still boots, just with those features
disabled (matching the no-op fallbacks in the individual modules).
"""

import logging
import os
import threading
from typing import Any, Dict, List, Optional

from server.safety.filesystem_guard import allowed_roots, validate_path
from server.systems.filesystem.file_memory_indexer import FileMemoryIndexer
from server.systems.filesystem.indexing_daemon import AdvancedIndexer, AutoIndexer
from server.systems.filesystem.live_watcher import LiveWatcher

logger = logging.getLogger("aariya.filesystem.background")


class _TwinNotifyingIndexer:
    """Proxy over FileMemoryIndexer that also feeds the DesktopTwin whenever a
    real file is indexed (watcher event or bulk scan), so the brain's model of
    the user's active environment stays in sync with actual activity."""

    def __init__(self, indexer: FileMemoryIndexer, notifier):
        self._indexer = indexer
        self._notifier = notifier

    def extract_text(self, path: str) -> str:
        from server.systems.filesystem.indexing_daemon import INDEXABLE
        ext = os.path.splitext(path)[1].lower()
        if ext in INDEXABLE:
            try:
                return open(path, encoding="utf-8", errors="ignore").read()
            except OSError:
                return ""
        return ""

    def index_file(self, path: str, text: str | None = None) -> bool:
        ok = self._indexer.index_file(path, text)
        if ok:
            self._service_note_indexed()
            if self._notifier is not None:
                try:
                    self._notifier(path)
                except Exception:
                    pass
        return ok

    def _service_note_indexed(self) -> None:
        # Real throughput metric for status(); kept off the hot path.
        try:
            svc = get_filesystem_service()
            svc.indexed_count += 1
        except Exception:
            pass


class FilesystemBackgroundService:
    """Owns the shared indexer + background threads, fed to the DesktopTwin."""

    def __init__(self, user_id: str = "user_default"):
        self.user_id = user_id
        self._indexer: Optional[FileMemoryIndexer] = None
        self._autoindexer: Optional[AutoIndexer] = None
        self._watcher: Optional[LiveWatcher] = None
        self._twin: Any = None
        self._lock = threading.Lock()
        self._started = False
        self._scan_threads: List[threading.Thread] = []
        self.indexed_count = 0
        self.root_count = 0
        # Drive hotplug (AccessFIles §3): poll real partitions so drives that
        # mount AFTER boot get watched + bulk-scanned too.
        self._drive_poll_stop = threading.Event()
        self._drive_poll_thread: Optional[threading.Thread] = None
        self.known_mounts: List[str] = []

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self, roots: Optional[List[str]] = None, *, max_files_per_root: int = 800) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True

        try:
            from server.systems.desktop_twin import get_desktop_twin
            self._twin = get_desktop_twin(self.user_id)
        except Exception as exc:
            logger.warning("[fs-bg] desktop twin unavailable: %s", exc)
            self._twin = None

        try:
            self._indexer = FileMemoryIndexer()
        except Exception as exc:
            logger.warning("[fs-bg] indexer init failed: %s", exc)
            self._indexer = None

        # Watcher requires an indexer object exposing both extract_text and
        # index_file — the proxy wraps FileMemoryIndexer and feeds the twin.
        if self._indexer is not None:
            try:
                proxy = _TwinNotifyingIndexer(
                    self._indexer,
                    notifier=(lambda p: self.observe_document(p)) if self._twin else None,
                )
                self._autoindexer = AutoIndexer(self._indexer)
                self._watcher = LiveWatcher(proxy)
            except Exception as exc:
                logger.warning("[fs-bg] watcher/autoindex init failed: %s", exc)

        scan_roots = roots if roots is not None else allowed_roots()
        # Cull roots to those that exist to avoid noise from cold dirs.
        scan_roots = [r for r in scan_roots if os.path.isdir(r)][:4]
        self.known_mounts = list(scan_roots)

        # Live watcher over the (small) real roots so new/changed docs are
        # indexed immediately without a full re-scan.
        if self._watcher is not None:
            try:
                for r in scan_roots:
                    self._watcher.watch(r, recursive=True)
                self._watcher.start()
            except Exception as exc:
                logger.warning("[fs-bg] watcher start failed: %s", exc)

        # Bulk cold-boot scan on background threads (non-blocking).
        if self._autoindexer is not None:
            for r in scan_roots:
                try:
                    thread = self._autoindexer.background_scan(
                        r, max_files=max_files_per_root
                    )
                    self._scan_threads.append(thread)
                    self.root_count += 1
                except Exception as exc:
                    logger.warning("[fs-bg] scan %s failed: %s", r, exc)

        logger.info(
            "[fs-bg] started: %d roots watched, %d bulk scans, twin=%s",
            len(scan_roots), len(self._scan_threads), self._twin is not None,
        )

        # Drive hotplug polling (AccessFIles §3): new removable mounts are
        # registered as roots and indexed within one poll interval.
        poll_seconds = max(15, int(os.getenv("AARIYA_DRIVE_POLL_SECONDS", "120")))
        self._drive_poll_stop.clear()
        self._drive_poll_thread = threading.Thread(
            target=self._drive_poll_loop,
            args=(poll_seconds,),
            daemon=True,
            name="fs-drive-poll",
        )
        self._drive_poll_thread.start()

    # ── Drive hotplug ────────────────────────────────────────────────────────

    def _new_mounts(self, partitions: List[Any]) -> List[str]:
        """Pure-ish diff: which partition mountpoints are new + indexable.
        Read-only filesystems (iso images etc.) and pseudo-fs are skipped."""
        skip_fstypes = {"squashfs", "iso9660", "tmpfs", "devtmpfs", "proc", "sysfs"}
        fresh = []
        for part in partitions:
            mount = getattr(part, "mountpoint", None)
            fstype = (getattr(part, "fstype", "") or "").lower()
            if not mount or not os.path.isdir(mount):
                continue
            if fstype in skip_fstypes or "ro" in (getattr(part, "opts", "") or "").split(","):
                continue
            if any(mount == m or mount.startswith(m.rstrip(os.sep) + os.sep)
                   for m in self.known_mounts):
                continue
            fresh.append(mount)
        return fresh

    def _drive_poll_loop(self, poll_seconds: int) -> None:
        try:
            import psutil
        except ImportError:
            logger.info("[fs-bg] psutil missing — drive hotplug disabled")
            return
        from server.safety.filesystem_guard import register_root
        while not self._drive_poll_stop.wait(poll_seconds):
            try:
                for mount in self._new_mounts(psutil.disk_partitions(all=False)):
                    if not register_root(mount):
                        continue
                    self.known_mounts.append(mount)
                    logger.info("[fs-bg] external drive mounted: %s — indexing", mount)
                    with self._lock:
                        watcher = self._watcher
                        autoindexer = self._autoindexer
                    if watcher is not None:
                        try:
                            watcher.watch(mount, recursive=True)
                        except Exception as exc:
                            logger.debug("[fs-bg] watch %s failed: %s", mount, exc)
                    if autoindexer is not None:
                        try:
                            thread = autoindexer.background_scan(mount, max_files=800)
                            self._scan_threads.append(thread)
                        except Exception as exc:
                            logger.debug("[fs-bg] scan %s failed: %s", mount, exc)
                    self.root_count += 1
            except Exception as exc:
                logger.debug("[fs-bg] drive poll error: %s", exc)

    def shutdown(self) -> None:
        with self._lock:
            self._started = False
        self._drive_poll_stop.set()
        if self._autoindexer is not None:
            self._autoindexer.shutdown()
        if self._watcher is not None:
            try:
                self._watcher.stop()
            except Exception:
                pass

    # ── Desktop twin feed ────────────────────────────────────────────────────

    def observe_document(self, path: str) -> None:
        """Feed a real filesystem event into the DesktopTwin."""
        if self._twin is not None:
            try:
                self._twin.observe_document(path, app="filesystem")
            except Exception as exc:
                logger.debug("[fs-bg] twin observe failed: %s", exc)

    def status(self) -> Dict[str, Any]:
        return {
            "started": self._started,
            "roots": self.root_count,
            "known_mounts": list(self.known_mounts),
            "bulk_scans": len(self._scan_threads),
            "indexed": self.indexed_count,
            "twin_active": self._twin is not None,
            "watcher_active": self._watcher is not None,
            "drive_poll_active": bool(self._drive_poll_thread and self._drive_poll_thread.is_alive()),
        }


# ── Singleton ────────────────────────────────────────────────────────────────

_service: Optional[FilesystemBackgroundService] = None


def get_filesystem_service(user_id: str = "user_default") -> FilesystemBackgroundService:
    global _service
    if _service is None:
        _service = FilesystemBackgroundService(user_id)
    return _service
