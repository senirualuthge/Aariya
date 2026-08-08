#!/usr/bin/env bash
# scripts/scan_deps.sh — scheduled dependency security scan for the Aariya backend.
#
# Two layers:
#   1. pip-audit hard gate  — fails on any NEW vulnerability in server/.venv.
#      The known, unfixable chromadb risk (PYSEC-2026-311 / CVE-2026-45829,
#      pre-auth code injection in chroma's HTTP server API; not exploitable
#      here because chromadb runs embedded-only) is explicitly ignored so the
#      scan only signals on NEW findings.
#   2. Live CVE-agent test  — runs the real OSV.dev query (via pytest
#      test_cve_live_scan.py, RUN_LIVE_TESTS=1) and asserts fastapi reports
#      ZERO advisories, guarding the version-aware query from regressing.
#
# Schedule (choose one):
#   * launchd (recommended, macOS):  bash scripts/scan_deps.sh install
#       -> installs ~/Library/LaunchAgents/com.aariya.depscan.plist
#          and loads it. Runs every Monday 06:00 automatically.
#   * cron (any Unix):               0 6 * * 1  /bin/bash /path/to/scripts/scan_deps.sh run
#   * manual:                        bash scripts/scan_deps.sh run
#
# Usage:
#   bash scripts/scan_deps.sh [run|install|uninstall|status]   (default: run)

set -euo pipefail

# ── Paths / config ───────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LABEL="com.aariya.depscan"
PLIST="${AARIYA_DEPSCAN_PLIST:-$HOME/Library/LaunchAgents/$LABEL.plist}"
PYTHON="${AARIYA_PYTHON:-$ROOT/server/.venv/bin/python}"
# pip-audit is a venv CLI entry point (declared in server/requirements.txt).
AUDIT="${AARIYA_AUDIT:-$ROOT/server/.venv/bin/pip-audit}"
# The documented, accepted-risk advisory (unfixable, embedded-only usage).
IGNORED_VULN="${AARIYA_IGNORED_VULN:-PYSEC-2026-311}"
LOG_OUT="/tmp/aariya_depscan.log"
LOG_ERR="/tmp/aariya_depscan.err.log"
BOOT_ERR="/tmp/depscan_boot.err"

GREEN='\033[32m'; YELLOW='\033[33m'; RED='\033[31m'; RESET='\033[0m'
ok()   { printf '%b%s%b\n' "$GREEN" "✅ $1" "$RESET"; }
warn() { printf '%b%s%b\n' "$YELLOW" "⚠️  $1" "$RESET"; }
fail() { printf '%b%s%b\n' "$RED" "❌ $1" "$RESET"; }

UID_NUM="$(id -u)"
is_loaded() { launchctl print "gui/$UID_NUM/$LABEL" >/dev/null 2>&1; }

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
    <string>/bin/bash</string>
    <string>$SCRIPT_DIR/scan_deps.sh</string>
    <string>run</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$ROOT</string>
  <key>RunAtLoad</key><false/>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key><integer>1</integer>
    <key>Hour</key><integer>6</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key><string>$LOG_OUT</string>
  <key>StandardErrorPath</key><string>$LOG_ERR</string>
</dict>
</plist>
EOF
}

# ── Commands ─────────────────────────────────────────────────────────────────
run() {
  cd "$ROOT"
  local rc=0
  {
    echo "== Dependency scan — $(date -u +%FT%TZ) =="
  } >> "$LOG_OUT"

  # 1) pip-audit hard gate (only NEW findings fail — the chromadb risk is
  #    explicitly ignored; see header note). Tooling failures are reported
  #    separately so a missing/erroring scanner isn't mistaken for findings.
  if [ ! -x "$AUDIT" ]; then
    fail "pip-audit not found at $AUDIT — install server/requirements.txt."
    rc=1
  elif "$AUDIT" -l --ignore-vuln "$IGNORED_VULN" >> "$LOG_OUT" 2>&1; then
    ok "pip-audit CLEAN — no new findings (ignored: $IGNORED_VULN)."
  else
    fail "pip-audit reported findings or a scan error (see $LOG_OUT)."
    rc=1
  fi

  # 2) Live CVE-agent regression guard (fastapi must report zero advisories).
  if RUN_LIVE_TESTS=1 "$PYTHON" -m pytest server/tests/test_cve_live_scan.py -q \
      >> "$LOG_OUT" 2>&1; then
    ok "CVE agent live scan PASS."
  else
    fail "CVE agent live scan FAILED (see $LOG_OUT)."
    rc=1
  fi

  if [ "$rc" -eq 0 ]; then
    ok "Dependency scan healthy."
  else
    warn "Dependency scan reported problems — review $LOG_OUT."
  fi
  return "$rc"
}

install() {
  write_plist
  if is_loaded; then
    warn "agent $LABEL already loaded."
    return 0
  fi
  if launchctl bootstrap "gui/$UID_NUM" "$PLIST" 2>"$BOOT_ERR"; then
    ok "installed + loaded $LABEL — weekly scan every Monday 06:00."
  else
    launchctl load -w "$PLIST" 2>/dev/null && ok "installed + loaded (legacy path)."
    fail "bootstrap failed — $(tail -1 "$BOOT_ERR")"
    return 1
  fi
}

uninstall() {
  launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
  launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  ok "removed $LABEL (plist deleted)."
}

status() {
  if is_loaded; then
    ok "SCHEDULED — $LABEL loaded (weekly Monday 06:00)."
  else
    warn "NOT SCHEDULED — install with: bash scripts/scan_deps.sh install"
  fi
}

case "${1:-run}" in
  run)       run ;;
  install)   install ;;
  uninstall) uninstall ;;
  status)    status ;;
  *)
    echo "Usage: bash scripts/scan_deps.sh [run|install|uninstall|status]   (default: run)" >&2
    exit 2
    ;;
esac
