"""
runtime_telemetry.py
────────────────────
Writes Aariya's live system metrics into the runtime Obsidian vault on an
interval, so her "running details" accumulate as retrievable obsidian_runtime
context (the retrieval half is ObsidianIndexer.retrieve / the research
agent's _gather_vault_context).

Each tick appends a compact `## Telemetry` section to
<runtime_vault>/Logs/<YYYY-MM-DD>.md via ObsidianIndexer.append_runtime_note,
which also re-syncs the vault so the note is immediately retrievable.

Metrics collected (all best-effort — a failing collector never breaks the loop):
  - Server uptime   (this process's create time, via psutil)
  - System uptime   (boot time, via psutil)
  - Memory          (virtual_memory percent + server process RSS)
  - CPU             (cpu_percent since last tick)
  - Active agents   (AgentRegistry count + names)
  - Obsidian vaults (chunk counts per mem_type)

Interval: RUNTIME_TELEMETRY_INTERVAL_MIN (default 30 minutes); the first tick
fires ~30 s after boot, then every interval.
"""

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

START_GRACE_S = 30  # first tick shortly after boot, then every INTERVAL_MIN


def _interval_min() -> float:
    try:
        value = float(os.getenv("RUNTIME_TELEMETRY_INTERVAL_MIN", "30"))
        return value if value > 0 else 30.0
    except ValueError:
        return 30.0


INTERVAL_MIN = _interval_min()


def _fmt_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def collect_metrics() -> dict:
    """Gather live system + Aariya metrics. Best-effort: missing keys are omitted."""
    metrics: dict = {}

    try:
        import psutil
        proc = psutil.Process()
        metrics["server_uptime_s"] = time.time() - proc.create_time()
        metrics["system_uptime_s"] = time.time() - psutil.boot_time()
        vm = psutil.virtual_memory()
        metrics["memory_percent"] = round(vm.percent, 1)
        metrics["memory_used_gb"] = round(vm.used / (1024**3), 1)
        metrics["memory_total_gb"] = round(vm.total / (1024**3), 1)
        metrics["server_rss_mb"] = round(proc.memory_info().rss / (1024**2))
        # Tiny blocking interval so the very first sample is real, not psutil's
        # 0.0 "no previous sample" placeholder (ticks are minutes apart, so
        # 100 ms here is negligible).
        metrics["cpu_percent"] = round(psutil.cpu_percent(interval=0.1), 1)
    except Exception as exc:
        logger.warning("psutil metrics unavailable: %s", exc)

    try:
        from server.infrastructure.agent_registry import get_registry
        agents = get_registry().get_active_agents()
        metrics["active_agents"] = len(agents)
        names = ", ".join(a.get("name", "?") for a in agents[:12])
        if names:
            metrics["agent_names"] = names
    except Exception as exc:
        logger.warning("Agent registry metrics unavailable: %s", exc)

    try:
        from server.systems.rag.obsidian_indexer import get_obsidian_indexer
        idx = get_obsidian_indexer()
        metrics["vault_developer_chunks"] = idx.count("obsidian_developer")
        metrics["vault_runtime_chunks"] = idx.count("obsidian_runtime")
    except Exception as exc:
        logger.warning("Obsidian vault stats unavailable: %s", exc)

    return metrics


def format_note(metrics: dict) -> str:
    """Render a metrics dict as a compact markdown bullet list for the vault."""
    lines = []
    if "server_uptime_s" in metrics:
        lines.append(f"- Server uptime: {_fmt_duration(metrics['server_uptime_s'])}")
    if "system_uptime_s" in metrics:
        lines.append(f"- System uptime: {_fmt_duration(metrics['system_uptime_s'])}")
    if "memory_percent" in metrics:
        used = (
            f"{metrics.get('memory_used_gb', '?')} GB of "
            f"{metrics.get('memory_total_gb', '?')} GB"
        )
        lines.append(
            f"- Memory: {metrics['memory_percent']}% used ({used}), "
            f"server RSS {metrics.get('server_rss_mb', '?')} MB"
        )
    if "cpu_percent" in metrics:
        lines.append(f"- CPU: {metrics['cpu_percent']}%")
    if "active_agents" in metrics:
        suffix = f" ({metrics['agent_names']})" if metrics.get("agent_names") else ""
        lines.append(f"- Active agents: {metrics['active_agents']}{suffix}")
    if "vault_developer_chunks" in metrics:
        lines.append(
            f"- Obsidian vaults: {metrics['vault_developer_chunks']} developer / "
            f"{metrics.get('vault_runtime_chunks', 0)} runtime chunks"
        )
    return "\n".join(lines) if lines else "No telemetry available."


def seed_runtime_vault() -> dict:
    """
    Ensure the runtime vault has a starter log template and today's log file,
    so future entries are formatted consistently. Idempotent — safe to call on
    every startup; existing files are left untouched.

    Returns {"actions": [...], "template": path|None, "today_log": path|None}.
    Never raises.
    """
    result: dict = {"actions": [], "template": None, "today_log": None}
    try:
        from server.systems.rag.obsidian_indexer import get_obsidian_indexer
        indexer = get_obsidian_indexer()
        if not indexer.runtime_vault:
            result["actions"].append("no runtime vault configured — skipped")
            return result

        from datetime import datetime
        from pathlib import Path
        log_dir = Path(indexer.runtime_vault) / "Logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        # 1. Starter template (only if missing).
        template_path = log_dir / "_TEMPLATE.md"
        if not template_path.exists():
            template_src = Path(__file__).resolve().parent / "runtime_log_template.md"
            if template_src.exists():
                template_path.write_text(
                    template_src.read_text(encoding="utf-8"), encoding="utf-8"
                )
                result["template"] = str(template_path)
                result["actions"].append(f"wrote template {template_path.name}")
            else:
                result["actions"].append("template source missing — skipped")
        else:
            result["actions"].append("template already present")

        # 2. Today's daily log (only if missing).
        day = datetime.now().strftime("%Y-%m-%d")
        today = log_dir / f"{day}.md"
        if not today.exists():
            today.write_text(
                f"# Aariya Runtime Log — {day}\n\n"
                "Running details logged by Aariya. Format: see [[_TEMPLATE]].\n",
                encoding="utf-8",
            )
            result["today_log"] = str(today)
            result["actions"].append(f"created daily log {today.name}")
        else:
            result["actions"].append("daily log already present")
    except Exception as exc:
        logger.warning("Runtime vault seed failed: %s", exc)
        result["actions"].append(f"error: {exc}")

    logger.info("Runtime vault seed: %s", "; ".join(result["actions"]) or "no actions")
    return result


def log_telemetry_tick() -> bool:
    """Collect metrics and append them to the runtime vault. True on success."""
    try:
        from server.systems.rag.obsidian_indexer import get_obsidian_indexer
        path = get_obsidian_indexer().append_runtime_note(
            format_note(collect_metrics()), title="Telemetry"
        )
        return bool(path)
    except Exception as exc:
        logger.warning("Runtime telemetry tick failed: %s", exc)
        return False


def cleanup_runtime_logs() -> dict:
    """
    Daily-rotation cleanup for the runtime vault Logs/ dir (best-effort).

    Retention-deletes dated logs older than RUNTIME_LOG_RETENTION_DAYS (30)
    and rotates an oversized today-file (> RUNTIME_LOG_MAX_KB, 512) into
    Logs/Archive/, purging the affected Chroma chunks so retrieval never
    surfaces deleted or rotated notes. Never raises.
    """
    try:
        from server.systems.rag.obsidian_indexer import get_obsidian_indexer
        return get_obsidian_indexer().cleanup_runtime_logs()
    except Exception as exc:
        logger.warning("Runtime log cleanup failed: %s", exc)
        return {"deleted_files": 0, "rotated_files": 0, "purged_chunks": 0}


def _fingerprint(note: str) -> str:
    """Metric-only fingerprint — uptime always changes, so strip uptime lines
    before comparing; otherwise every idle tick would look 'changed'."""
    return "\n".join(
        line for line in note.splitlines() if "uptime" not in line.lower()
    )


def _loop() -> None:
    time.sleep(START_GRACE_S)
    last_note = ""
    while True:
        # Daily-rotation cleanup — keeps Logs/ bounded (retention + rotation).
        # Runs every tick (cheap: a glob + a few file ops, idempotent) so
        # growth is trimmed even between telemetry writes.
        try:
            cleanup_runtime_logs()
        except Exception as exc:
            logger.warning("Runtime log cleanup error: %s", exc)

        try:
            metrics = collect_metrics()
            note = format_note(metrics)
            # Change-detection: skip when only uptime moved (idle system would
            # otherwise append a near-identical telemetry chunk every tick,
            # crowding runtime-vault retrieval with duplicates).
            if _fingerprint(note) != _fingerprint(last_note):
                from server.systems.rag.obsidian_indexer import get_obsidian_indexer
                if get_obsidian_indexer().append_runtime_note(note, title="Telemetry"):
                    last_note = note
                else:
                    logger.warning("Telemetry tick: vault append failed — keeping last note.")
            else:
                logger.info("Telemetry tick skipped — metrics unchanged since last write.")
        except Exception as exc:  # never let the loop die
            logger.warning("Runtime telemetry tick error: %s", exc)
        time.sleep(INTERVAL_MIN * 60)


_loop_started = False
_lock = threading.Lock()


def start_runtime_telemetry() -> bool:
    """Start the daemon telemetry loop once (idempotent). True if running."""
    global _loop_started
    with _lock:
        if _loop_started:
            return True
        _loop_started = True
        # Trim any stale runtime logs from previous boots right away, before
        # the first tick (30 s after boot) catches up.
        try:
            cleanup_runtime_logs()
        except Exception as exc:
            logger.warning("Startup runtime log cleanup failed: %s", exc)
        threading.Thread(target=_loop, daemon=True, name="runtime-telemetry").start()
        logger.info("Runtime telemetry logger started (every %s min).", INTERVAL_MIN)
        return True
