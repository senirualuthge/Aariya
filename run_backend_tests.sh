#!/bin/bash
# run_backend_tests.sh — run the Python backend test suite with pytest.
#
# The suite in server/tests/ is pytest-based (see conftest.py + pytest.ini);
# pytest is a declared venv dependency (server/requirements.txt).
#
# Only `server/tests/test_*.py` files are treated as tests — one-off dev
# scripts like `verify_dashboard_fix.py` are intentionally skipped.
#
# Usage:
#   ./run_backend_tests.sh                     run all tests
#   RUN_LIVE_TESTS=1 ./run_backend_tests.sh    include live-LLM tests
#   ./run_backend_tests.sh test_autonomy.py    run specific test(s) by name

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# ── Resolve the project venv python (root-level venv/ is the convention) ───
if [ -x "venv/bin/python" ]; then
    PY="venv/bin/python"
elif [ -x "venv/Scripts/python.exe" ]; then
    PY="venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
    PY="python3"
elif command -v python >/dev/null 2>&1; then
    PY="python"
else
    echo "ERROR: no Python interpreter found (looked in venv/, python3, python)" >&2
    exit 1
fi
echo "Using: $("$PY" --version 2>&1) ($PY)"

# ── pytest is required (declared in server/requirements.txt) ────────────────
if ! "$PY" -c "import pytest" >/dev/null 2>&1; then
    echo "ERROR: pytest is required to run the backend tests but is not in this venv." >&2
    echo "       Install it with:  $PY -m pip install pytest" >&2
    exit 1
fi

if [ "$#" -gt 0 ]; then
    ARGS=()
    for name in "$@"; do
        # Accept "test_autonomy.py" or "server/tests/test_autonomy.py"
        ARGS+=("server/tests/${name#server/tests/}")
    done
    exec "$PY" -m pytest "${ARGS[@]}"
fi

exec "$PY" -m pytest
