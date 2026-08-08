#!/usr/bin/env bash
# scripts/backend.sh — control the persistent launchd-managed Aariya brain.
#
# The backend normally runs as a foreground child of `npm run dev` (dev.mjs)
# and dies with the terminal. For a persistent, always-on brain that survives
# reboots it runs under macOS launchd as the `com.aariya.backend` agent
# (plist: ~/Library/LaunchAgents/com.aariya.backend.plist).
#
# This script bootstraps ("start") and boots out ("stop") that agent, and
# recreates the plist if it has been removed. macOS only (launchd).
#
# Usage:
#   bash scripts/backend.sh [start|stop|restart|status|health]   (default: status)
#   AARIYA_PORT=8000 bash scripts/backend.sh start        (override port)
#
# `health` also checks the weekly dependency-scan agent (com.aariya.depscan,
# scripts/scan_deps.sh) — run it via `npm run health`.
#
# For the hot-reload dev loop use `npm run dev` or `npm run dev:brain` instead.

set -euo pipefail

# ── Paths / config ───────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LABEL="com.aariya.backend"
PORT="${AARIYA_PORT:-8000}"
PLIST="${AARIYA_PLIST:-$HOME/Library/LaunchAgents/$LABEL.plist}"
# The interpreter proven to run the server (server/.venv); override with AARIYA_PYTHON.
PYTHON="${AARIYA_PYTHON:-$ROOT/server/.venv/bin/python}"
LOG_OUT="/tmp/aariya_backend.log"
LOG_ERR="/tmp/aariya_backend.err.log"

GREEN='\033[32m'; YELLOW='\033[33m'; RED='\033[31m'; RESET='\033[0m'
ok()   { printf '%b%s%b\n' "$GREEN" "✅ $1" "$RESET"; }
warn() { printf '%b%s%b\n' "$YELLOW" "⚠️  $1" "$RESET"; }
fail() { printf '%b%s%b\n' "$RED" "❌ $1" "$RESET"; }

# ── Helpers ──────────────────────────────────────────────────────────────────
UID_NUM="$(id -u)"
# Authoritative state check: `launchctl print` is exact, whereas grepping the
# `launchctl list` table has proved flaky in some environments.
is_loaded() { launchctl print "gui/$UID_NUM/$LABEL" >/dev/null 2>&1; }
# The weekly dependency-scan agent (scripts/scan_deps.sh) — separate service.
depscan_scheduled() {
  launchctl print "gui/$UID_NUM/com.aariya.depscan" >/dev/null 2>&1
}
# Non-fatal reminder shown after start/restart when the dep scan isn't scheduled.
warn_depscan_if_unscheduled() {
  if ! depscan_scheduled; then
    warn "dependency scan (com.aariya.depscan) NOT scheduled — install: bash scripts/scan_deps.sh install"
  fi
}
# Any HTTP response counts as "up" (the brain answers 404 on "/" — never
# use curl -f here, it would treat that as failure).
is_up()     { curl -sS -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/"; }
agent_pid() {
  # Anchored to the exact field so `ppid =` / `process type =` lines can't
  # hijack the match.
  launchctl print "gui/$UID_NUM/$LABEL" 2>/dev/null |
    awk -F' = ' '$1 ~ /pid$/ {print $2; exit}'
}

# (Re)create the plist from the current paths — the agent is self-describing
# so the script stays the single source of truth even if the plist is deleted.
write_plist() {
  mkdir -p "$(dirname "$PLIST")"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>-m</string>
    <string>uvicorn</string>
    <string>server.main:app</string>
    <string>--host</string>
    <string>0.0.0.0</string>
    <string>--port</string>
    <string>$PORT</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$ROOT</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG_OUT</string>
  <key>StandardErrorPath</key><string>$LOG_ERR</string>
</dict>
</plist>
EOF
}

# Bootstrap into the GUI launchd domain, tolerating "already loaded". The
# bootstrap error is kept for the caller to surface when startup fails.
bootstrap_agent() {
  if is_loaded; then return 0; fi
  # A booted-out instance may still be de-registering — bootstrapping the
  # same label too early can succeed without actually starting anything.
  local waited=0
  while is_loaded && [ "$waited" -lt 30 ]; do
    sleep 1
    waited=$((waited + 1))
  done
  if launchctl bootstrap "gui/$UID_NUM" "$PLIST" 2>/tmp/backend_boot.err; then
    return 0
  fi
  # Teardown races are transient — retry once before falling back.
  sleep 2
  launchctl bootstrap "gui/$UID_NUM" "$PLIST" 2>>/tmp/backend_boot.err && return 0
  # macOS predates bootstrap/bootout — legacy load path.
  launchctl load -w "$PLIST" 2>/dev/null
}

# Boot the agent out of the domain; best-effort legacy unload fallback.
# Returns immediately; `stop` separately waits for the port to free up.
bootout_agent() {
  launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
  launchctl unload "$PLIST" 2>/dev/null || true
}

# ── Commands ─────────────────────────────────────────────────────────────────
start() {
  if is_up; then
    if is_loaded; then
      ok "Aariya brain already answering on :$PORT — nothing to do."
      warn_depscan_if_unscheduled
    else
      # Something else holds the port (e.g. a dev-mode uvicorn) — the
      # launchd agent is NOT managed by this script right now.
      warn ":$PORT is answering but the launchd agent is not loaded — use: npm run dev -- --clean"
    fi
    return 0
  fi
  if [ ! -f "$PLIST" ]; then
    warn "plist missing — recreating at $PLIST"
    write_plist
  fi
  # A just-stopped instance drains gracefully and can leave the socket bound
  # (refusing connections) for a while. Let it go before bootstrapping, or
  # the fresh process crash-loops on "address already in use".
  local drain=0
  while lsof -nP -i ":$PORT" -sTCP:LISTEN >/dev/null 2>&1 && [ "$drain" -lt 60 ]; do
    sleep 1
    drain=$((drain + 1))
  done
  if ! bootstrap_agent; then
    fail "could not load launchd agent $LABEL — $(tail -1 /tmp/backend_boot.err 2>/dev/null)"
    return 1
  fi
  # The brain boots in ~10s; 120s also absorbs a slow port release right
  # after `stop` (uvicorn drains gracefully and launchd throttles restarts
  # while the old socket lingers), without false failure.
  local waited=0
  until is_up || [ "$waited" -ge 120 ]; do sleep 1; waited=$((waited + 1)); done
  if is_up; then
    ok "Aariya brain is UP on :$PORT (launchd $LABEL)."
    warn_depscan_if_unscheduled
  else
    fail "brain did not answer on :$PORT within 120s — check $LOG_ERR"
    return 1
  fi
}

stop() {
  if ! is_loaded && ! is_up; then
    warn "agent $LABEL is not loaded — nothing to stop."
    return 0
  fi
  bootout_agent
  # launchd de-registers the booted-out service asynchronously and uvicorn
  # drains its socket gracefully. Wait for BOTH before returning — re-
  # bootstrapping the same label while the old registration lingers can
  # silently no-op.
  local waited=0
  until { ! is_loaded && ! is_up; } || [ "$waited" -ge 60 ]; do
    sleep 1
    waited=$((waited + 1))
  done
  if is_loaded || is_up; then
    warn "agent still present after bootout — a stray process may hold :$PORT (use: npm run dev -- --clean)."
  else
    ok "Aariya brain stopped (agent $LABEL booted out)."
  fi
}

status() {
  if is_loaded; then
    local pid
    pid="$(agent_pid)"
    if is_up; then
      ok "RUNNING — $LABEL (pid ${pid:-?}) answering on :$PORT."
    else
      warn "LOADED but not answering on :$PORT (pid ${pid:-?}) — check $LOG_ERR."
    fi
  else
    warn "NOT LOADED — brain is not running. Start it with: bash scripts/backend.sh start"
  fi
}

restart() { stop; start; }

# launchd only exists on macOS. health() stays truthful (and CI-friendly)
# on other hosts: report n/a and pass — the real CI gates are the backend
# suite, pip-audit and the live CVE scan, not local macOS services.
# Set AARIYA_NO_LAUNCHD=1 to force the n/a branch (used by the CI workflow).
launchd_available() {
  [ "${AARIYA_NO_LAUNCHD:-0}" = "1" ] && return 1
  command -v launchctl >/dev/null 2>&1
}

# Combined health check: the brain AND the weekly dependency-scan agent.
# Non-zero exit if either is down / not scheduled — CI- and cron-friendly.
health() {
  local rc=0
  echo "── Aariya services ──"
  if ! launchd_available; then
    warn "brain    — n/a (no launchd on this host — macOS only)."
    warn "depscan  — n/a (no launchd on this host — macOS only)."
    echo "  (health is a macOS local-ops check — CI gates: backend suite + pip-audit + live CVE scan)"
    return 0
  fi
  if is_loaded; then
    local pid
    pid="$(agent_pid)"
    if is_up; then
      ok "brain    — RUNNING (pid ${pid:-?}) answering on :$PORT."
    else
      warn "brain    — LOADED but not answering on :$PORT."
      rc=1
    fi
  else
    warn "brain    — NOT LOADED. Start: bash scripts/backend.sh start"
    rc=1
  fi
  if launchctl print "gui/$UID_NUM/com.aariya.depscan" >/dev/null 2>&1; then
    ok "depscan  — SCHEDULED (weekly Monday 06:00)."
  else
    warn "depscan  — NOT SCHEDULED. Install: bash scripts/scan_deps.sh install"
    rc=1
  fi
  # Last scan outcome (log written by scripts/scan_deps.sh run). The grep
  # pipelines may legitimately find nothing — the || true guards keep them
  # from aborting under set -e.
  local last_run last_health
  last_run="$(grep '== Dependency scan' /tmp/aariya_depscan.log 2>/dev/null | tail -1 \
    | sed 's/== Dependency scan — //; s/ ==//' || true)"
  last_health="$(grep -E 'Dependency scan (healthy|reported)' /tmp/aariya_depscan.log 2>/dev/null | tail -1 || true)"
  if [ -n "$last_run" ]; then
    echo "  last depscan: $last_run  —  ${last_health:-see log for details}"
  else
    echo "  last depscan: none yet (first run Monday 06:00, or: bash scripts/scan_deps.sh run)"
  fi
  return "$rc"
}

case "${1:-status}" in
  start)   start ;;
  stop)    stop ;;
  restart) restart ;;
  status)  status ;;
  health)  health ;;
  *)
    echo "Usage: bash scripts/backend.sh [start|stop|restart|status|health]   (default: status)" >&2
    exit 2
    ;;
esac
