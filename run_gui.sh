#!/bin/bash
# AI Girl — Full System Launcher (DEV or PROD)
#
# Usage:
#   ./run_gui.sh           Start in development mode (vite dev server, auto-reload brain)
#   ./run_gui.sh --prod    Build the UI and run in production mode (vite preview,
#                          brain without auto-reload) — same as `npm run dev -- --prod`
#
# The dev launcher (scripts/dev.mjs) owns BOTH servers — brain (:8000) and UI
# (:5173) — so they always start and stop together: no orphaned processes and
# no "address already in use" collisions (uvicorn must NOT also be started
# directly here, or the launcher's own brain would crash on the busy port).
# `--clean` makes the launcher kill any stale listeners on those ports first,
# so a crashed previous session can't break this launch.
#
# Note: bash defers traps while `npm run gui` runs in the foreground, so a bare
# `kill <script>` while Electron is open waits until Electron exits. Closing the
# terminal or pressing Ctrl+C still stops everything immediately — SIGHUP/SIGINT
# reach the whole process group and dev.mjs handles them itself.

cd "$(dirname "$0")"

PROD=0
if [ "$1" = "--prod" ] || [ "$1" = "-p" ]; then
    PROD=1
fi

echo "========================================"
echo "  AI Girl - Full System Launcher"
echo "========================================"
if [ "$PROD" = "1" ]; then
    echo "  Mode: PRODUCTION - build + preview"
else
    echo "  Mode: DEVELOPMENT - dev server"
fi
echo "========================================"
echo ""

# Check Python
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "ERROR: Python not found. Please install Python 3.10+"
    exit 1
fi

# Check Node
if ! command -v npm &> /dev/null; then
    echo "ERROR: Node.js/npm not found. Please install Node.js"
    exit 1
fi

# Source virtual environment if exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

LAUNCHER_PID=""
cleanup() {
    # Preserve the exit status (so a launcher-failure path exits non-zero).
    local code=$?
    if [ -n "$LAUNCHER_PID" ]; then
        echo ""
        echo "Closing application... stopping servers"
        kill "$LAUNCHER_PID" 2>/dev/null || true
    fi
    exit "$code"
}
trap cleanup SIGINT SIGTERM EXIT

echo "[1/3] Starting servers..."
if [ "$PROD" = "1" ]; then
    echo "  Building UI for production (first run may take a minute)..."
    npm run dev -- --clean --prod &
else
    npm run dev -- --clean &
fi
LAUNCHER_PID=$!

echo "[2/3] Waiting for servers to be ready..."
# Poll until both ports answer (up to ~2 min — the prod build alone takes
# ~30s). A server is "up" as soon as it answers on TCP; the brain root returns
# HTTP 404, which curl still counts as a successful connection. If the launcher
# dies (e.g. the build failed), abort quickly instead of waiting it out.
READY=0
for i in $(seq 1 120); do
    if ! kill -0 "$LAUNCHER_PID" 2>/dev/null; then
        echo ""
        echo "ERROR: dev launcher exited - check the output above."
        exit 1
    fi
    if curl -s -o /dev/null --max-time 1 http://localhost:5173/ 2>/dev/null \
       && curl -s -o /dev/null --max-time 1 http://localhost:8000/ 2>/dev/null; then
        READY=1
        break
    fi
    sleep 1
done
if [ "$READY" = "1" ]; then
    echo "  Servers are ready."
else
    echo "  WARNING: servers did not respond within 2 minutes - launching anyway."
fi

echo ""
echo "[3/3] Launching Electron GUI..."
echo ""
npm run gui

echo ""
echo "========================================"
echo "  AI Girl has been closed"
echo "========================================"
